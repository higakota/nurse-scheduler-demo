"""既存の勤務を複数スタッフで交換する。入力条件・未承諾ヘルプは変更しない。"""
import itertools
import time
from help_limits import helper_demand, helper_demand_roles, planned_helper_roles, PREFERRED_DAILY_HELPERS


def improve_jointly(problem, grid, allow_shortages=False, max_full_days=6, seconds=1):
    from scheduler_engine import (allocate, automatic_half_rest, draft_shortages,
                                  rest_units, verify, six_day_runs)
    from weekly_rules import work_units
    result = list(grid)
    deadline = time.monotonic() + max(0, seconds)
    people = problem["people"]
    own = [i for i,p in enumerate(people) if not p["is_help"]]
    days = range(len(grid))
    weekly_parts = [i for i in own if people[i]["role"]=="nurse" and people[i]["employment"]=="part"] if allow_shortages else []

    def abstract(rows):
        return ["".join("W" if c in "ABCD" else c for c in pair) for pair in rows]

    def deficits(d, rows):
        totals = [0,0,0]
        for row in draft_shortages(problem,d,rows):
            category = 1 if "検査技師" in row["area"] else (2 if "ベテラン" in row["area"] else 0)
            totals[category] += row["missing"]
        totals[0] = helper_demand_roles(problem,d,rows)[0]
        return totals

    def half_score(d, rows):
        return sum(automatic_half_rest(problem,d,i,pair) for i,pair in enumerate(rows))

    def alternatives(d,e,i,a,b):
        wanted_rest = rest_units(a)+rest_units(b)
        wanted_work = work_units(a)+work_units(b)
        pairs = []
        for left,right in itertools.product(problem["options"][d][i],problem["options"][e][i]):
            if (left,right)==(a,b) or rest_units(left)+rest_units(right)!=wanted_rest:
                continue
            if work_units(left)+work_units(right)!=wanted_work:
                continue
            # 通常の休みの集約では、本人希望の半日勤務を維持する。
            if not allow_shortages and any((day,i) in problem.get("requested_half_rests",set()) and automatic_requested(old)
                   and new!=old for day,old,new in ((d,a,left),(e,b,right))):
                continue
            pairs.append((left,right))
        return pairs

    def automatic_requested(pair):
        return pair.count("R")==1 and any(c in "WMO" for c in pair)

    # 不足がある日・自動半休がある日から、別の日への休み移動を探す。
    while time.monotonic()<deadline:
        improved=False
        scores={d:deficits(d,rows) for d,rows in enumerate(result)}
        halves={d:half_score(d,rows) for d,rows in enumerate(result)}
        demand_roles={d:planned_helper_roles(problem,d,rows) for d,rows in enumerate(result)}
        nurse_needs={d:helper_demand_roles(problem,d,rows)[0] for d,rows in enumerate(result)}
        priority=sorted(days,key=lambda d:(-nurse_needs[d],-max(0,demand_roles[d][0]-1),-sum(scores[d]),-halves[d],d))
        original_runs=len(six_day_runs(problem,result))
        # 非常勤に週上限の余地がある場合、他日の勤務を減らさず不足を補う。
        # 公休指定の常勤や本人希望は変更せず、希望外の半休も増やさない。
        for d in priority:
            if not nurse_needs[d]:
                continue
            for i in weekly_parts:
                for pair in sorted(problem["options"][d][i],key=lambda p:-work_units(p)):
                    if time.monotonic()>=deadline:
                        return result
                    if work_units(pair)<=work_units(result[d][i]):
                        continue
                    rows=abstract(result[d]);rows[i]=pair
                    allocated=allocate(problem,d,rows,partial=True)
                    if allocated is None or half_score(d,allocated)>halves[d]:
                        continue
                    if helper_demand_roles(problem,d,allocated)[0]>=nurse_needs[d]:
                        continue
                    candidate=list(result);candidate[d]=allocated
                    if len(six_day_runs(problem,candidate))>original_runs:
                        continue
                    if verify(problem,candidate,allow_shortages=True,max_full_days=max_full_days):
                        continue
                    result=candidate;improved=True
                    break
                if improved:break
            if improved:break
        if improved:
            continue
        for position,d in enumerate(priority):
            for e in priority[position+1:]:
                if time.monotonic()>=deadline:
                    return result
                left,right=abstract(result[d]),abstract(result[e])
                old_def=[a+b for a,b in zip(scores[d],scores[e])]
                old_half=halves[d]+halves[e]
                old_roles=[demand_roles[day] for day in (d,e)]
                old_demand=[sum(role) for role in old_roles]
                old_cap=(sum(max(0,nurses-1) for nurses,tech in old_roles),
                         sum(max(0,n-PREFERRED_DAILY_HELPERS) for n in old_demand),max(old_demand))
                variations={i:alternatives(d,e,i,left[i],right[i]) for i in own}
                # 1人の休み移動と、2人の交換を両方調べる。
                groups=[(i,) for i in own if variations[i]]
                groups += [(i,j) for i,j in itertools.combinations(own,2) if variations[i] and variations[j]]
                for group in groups:
                    for changes in itertools.product(*(variations[i] for i in group)):
                        if time.monotonic()>=deadline:
                            return result
                        a,b=list(left),list(right)
                        for i,(x,y) in zip(group,changes):
                            a[i],b[i]=x,y
                        new_left=allocate(problem,d,a,partial=allow_shortages)
                        new_right=allocate(problem,e,b,partial=allow_shortages)
                        if new_left is None or new_right is None:
                            continue
                        new_def=[x+y for x,y in zip(deficits(d,new_left),deficits(e,new_right))]
                        new_half=half_score(d,new_left)+half_score(e,new_right)
                        # 看護師不足を減らせるなら、検査技師への追加依頼が増える案も比較する。
                        if (new_def[0]>old_def[0] or new_def[2]>old_def[2]
                            or (new_def[0]==old_def[0] and new_def[1]>old_def[1])
                            or new_half>old_half):
                            continue
                        new_roles=[planned_helper_roles(problem,day,rows) for day,rows in ((d,new_left),(e,new_right))]
                        new_demand=[sum(role) for role in new_roles]
                        new_cap=(sum(max(0,nurses-1) for nurses,tech in new_roles),
                                 sum(max(0,n-PREFERRED_DAILY_HELPERS) for n in new_demand),max(new_demand))
                        reduced_nurses = new_def[0] < old_def[0]
                        moved_requested_work = any(
                            (day,i) in problem.get("requested_half_rests",set()) and automatic_requested(old) and old != new
                            for i,(x,y) in zip(group,changes)
                            for day,old,new in ((d,left[i],x),(e,right[i],y)))
                        # 希望した休みはoptionsで必ず守る。反対側の勤務の移動は、
                        # 自院の不足を補い、必要なヘルプが減る場合だけ採用する。
                        if moved_requested_work and (not allow_shortages or (not reduced_nurses and sum(new_demand) >= sum(old_demand))):
                            continue
                        if allow_shortages and new_cap > old_cap and not reduced_nurses:
                            continue
                        if new_def==old_def and new_half==old_half and (not allow_shortages or new_cap>=old_cap):
                            continue
                        candidate=list(result)
                        candidate[d],candidate[e]=new_left,new_right
                        new_runs=len(six_day_runs(problem,candidate))
                        if new_runs>original_runs:
                            continue
                        if verify(problem,candidate,allow_shortages=allow_shortages,max_full_days=max_full_days):
                            continue
                        result=candidate
                        improved=True
                        break
                    if improved:break
                if improved:break
            if improved:break
        if not improved:break
    return result
