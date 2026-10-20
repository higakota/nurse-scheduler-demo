"""月曜～日曜の非常勤勤務上限。整数の半日単位で数える。"""
import calendar
from datetime import date, timedelta

HISTORY_UNITS = {"full":2, "am":1, "pm":1, "rest":0, "paid":0, "am_paid":1, "pm_paid":1}


def work_units(pair):
    return sum(code in "ABCDMWO" for code in pair)


def boundary_dates(month):
    first=date.fromisoformat(month+"-01")
    last=first.replace(day=calendar.monthrange(first.year,first.month)[1])
    monday=first-timedelta(days=first.weekday())
    sunday=last+timedelta(days=6-last.weekday())
    return ([monday+timedelta(days=n) for n in range((first-monday).days)] +
            [last+timedelta(days=n) for n in range(1,(sunday-last).days+1)])


def parse_units(value):
    if str(value) not in ("0","0.0","0.5","1","1.0"):
        raise ValueError("勤務日数は0・0.5・1日のいずれかで指定してください。")
    return {"0":0,"0.0":0,"0.5":1,"1":2,"1.0":2}[str(value)]


def outside_sources(snapshot, person, day):
    key=str(person["id"])+"_"+day.isoformat()
    values=[]
    own=snapshot.get("weekly_work_boundaries") or {}
    if key in own:
        values.append(("この月の境界入力",parse_units(own[key])))
    for source, entries in (snapshot.get("weekly_neighbor_boundaries") or {}).items():
        if key in entries:
            values.append((source+"の境界入力",parse_units(entries[key])))
    if day < date.fromisoformat(snapshot["month"]+"-01"):
        code=(snapshot.get("leave_history") or {}).get("history",{}).get(key)
        if code in HISTORY_UNITS:
            values.append(("前月末勤務",HISTORY_UNITS[code]))
    closures=dict(snapshot.get("previous_closures") or {})
    closures.update(snapshot.get("weekly_next_closures") or {})
    if day.weekday()==6 or day.isoformat() in closures:
        values.append(("休診",0))
    return values


def build_weekly(snapshot, people, days):
    parts=[i for i,p in enumerate(people) if not p["is_help"] and p["employment"]=="part"]
    dates=[date.fromisoformat(day) for day in days]
    starts=list(dict.fromkeys((day-timedelta(days=day.weekday())).isoformat() for day in dates))
    weeks=[dict(start=start,end=(date.fromisoformat(start)+timedelta(days=6)).isoformat(),
                indices=[d for d,day in enumerate(dates) if (day-timedelta(days=day.weekday())).isoformat()==start]) for start in starts]
    week_for_day=[next(w for w,week in enumerate(weeks) if d in week["indices"]) for d in range(len(days))]
    limits=[]
    errors=[]
    external=[[0]*len(parts) for _ in weeks]
    pending=[[[] for _ in parts] for _ in weeks]
    fixed={}
    prefix={}
    for k,i in enumerate(parts):
        person=people[i]
        limit=person.get("weekly_limit_units")
        if not isinstance(limit,int) or isinstance(limit,bool) or not 0<=limit<=14:
            errors.append(person["name"]+"：スタッフ設定で週の勤務上限を指定してください。")
            limit=0
        limits.append(limit)
        for day in boundary_dates(snapshot["month"]):
            w=starts.index((day-timedelta(days=day.weekday())).isoformat())
            try:
                sources=outside_sources(snapshot,person,day)
            except ValueError as exc:
                errors.append(person["name"]+" "+day.isoformat()+"："+str(exc))
                continue
            values={value for _,value in sources}
            if len(values)>1:
                errors.append(person["name"]+" "+day.isoformat()+"：境界の勤務日数と前月末勤務・他月の指定が一致しません。")
            if values:
                count=next(iter(values))
                external[w][k]+=count
                if day<dates[0]:
                    prefix[str(person["id"])+"_"+day.isoformat()]=count
            elif day<dates[0]:
                errors.append(person["name"]+" "+day.isoformat()+"：週上限の判定に必要な前月の実績を「非常勤の週勤務」で入力してください。")
            else:
                pending[w][k].append(day.isoformat())
        for d,day in enumerate(dates):
            # 他月で決定済みとして入力した日を、この月で勝手に変更しない。
            key=str(person["id"])+"_"+day.isoformat()
            values=[]
            for source,entries in (snapshot.get("weekly_neighbor_boundaries") or {}).items():
                if key in entries:
                    try:
                        values.append(parse_units(entries[key]))
                    except ValueError as exc:
                        errors.append(person["name"]+" "+day.isoformat()+"："+str(exc))
            if len(set(values))>1:
                errors.append(person["name"]+" "+day.isoformat()+"：他月の境界入力が一致しません。")
            if values:
                fixed[(d,i)]=values[0]
        for w,week in enumerate(weeks):
            if external[w][k]>limit:
                errors.append(person["name"]+" "+week["start"]+"の週：前後月の決定済み勤務だけで週上限を超えています。")
    return dict(parts=parts,limits=limits,weeks=weeks,week_for_day=week_for_day,external=external,pending=pending,fixed=fixed,prefix=prefix,errors=errors)


def weekly_summary(problem, grid):
    model=problem["weekly"]
    summary=[]
    for w,week in enumerate(model["weeks"]):
        for k,i in enumerate(model["parts"]):
            inside=sum(work_units(grid[d][i]) for d in week["indices"])
            known=inside+model["external"][w][k]
            summary.append(dict(name=problem["people"][i]["name"],start=week["start"],end=week["end"],
                                current=inside/2, outside=model["external"][w][k]/2,
                                known=known/2,limit=model["limits"][k]/2,
                                remaining=(model["limits"][k]-known)/2,pending=model["pending"][w][k]))
    return summary
