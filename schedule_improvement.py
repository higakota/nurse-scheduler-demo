"""既存の勤務を複数スタッフで交換する。入力条件・未承諾ヘルプは変更しない。"""
import itertools
import time


def improve_jointly(problem, grid, allow_shortages=False, max_full_days=6, seconds=1):
    from scheduler_engine import (allocate, automatic_half_rest, draft_shortages,
                                  rest_units, verify, six_day_runs)
    from weekly_rules import work_units
    result = list(grid)
    deadline = time.monotonic() + max(0, seconds)
    people = problem["people"]
    own = [i for i,p in enumerate(people) if not p["is_help"]]
    days = range(len(grid))

    def abstract(rows):
        return ["".join("W" if c in "ABCD" else c for c in pair) for pair in rows]

    def deficits(d, rows):
        totals = [0,0,0]
        for row in draft_shortages(problem,d,rows):
            category = 1 if "検査技師" in row["area"] else (2 if "ベテラン" in row["area"] else 0)
            totals[category] += row["missing"]
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
            # 本人希望の半日勤務は、休みの集約を理由に全休へ変更しない。
            if any((day,i) in problem.get("requested_half_rests",set()) and automatic_requested(old)
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
        priority=sorted(days,key=lambda d:(-sum(scores[d]),-halves[d],d))
        original_runs=len(six_day_runs(problem,result))
        for d in priority:
            for e in priority:
                if e<=d:
                    continue
                if time.monotonic()>=deadline:
                    return result
                left,right=abstract(result[d]),abstract(result[e])
                old_def=[a+b for a,b in zip(scores[d],scores[e])]
                old_half=halves[d]+halves[e]
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
                        if any(x>y for x,y in zip(new_def,old_def)) or new_half>old_half:
                            continue
                        if new_def==old_def and new_half==old_half:
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
