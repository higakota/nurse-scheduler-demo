"""保存した勤務表から全日・半日有給の候補を個別に再検証する。"""
from copy import deepcopy
from scheduler_engine import prepare, verify, WORK


def leave_candidates(snapshot, source, fingerprint):
    blocked = {"days": [], "groups": [], "message": "現在の条件を満たす勤務表を保存・再作成してから確認してください。"}
    if not source or source.get("input_hash") != fingerprint:
        return blocked
    problem = prepare(snapshot, use_help=True)
    if problem["errors"] or problem["days"] != source.get("days"):
        return blocked
    indexes = {str(p["id"]): i for i, p in enumerate(source["people"])}
    if any(str(p["id"]) not in indexes for p in problem["people"] if not p["is_help"]):
        return blocked
    grid = [[row[indexes[str(p["id"])]] if str(p["id"]) in indexes else "RR"
             for p in problem["people"]] for row in source["grid"]]
    issues=verify(problem,grid,max_full_days=6)
    if issues:
        return dict(blocked,message="勤務表と入力の不一致を直すと、有給候補を確認できます。",reasons=issues[:3])
    groups = [{"period":period,"label":label,"days":[]} for period,label in
              (("full","全日"),("am","午前のみ"),("pm","午後のみ"))]
    meeting_days = {meeting["date"] for meeting in snapshot.get("monthly_settings", {}).get("meetings", [])}
    for d, day in enumerate(problem["days"]):
        if day in meeting_days:
            continue
        names = {group["period"]:[] for group in groups}
        for i, person in enumerate(problem["people"]):
            pair=grid[d][i]
            if person["is_help"] or "P" in pair or "M" in pair:
                continue
            for group in groups:
                period=group["period"]
                halves={"full":(0,1),"am":(0,),"pm":(1,)}[period]
                if not all(pair[h] in WORK for h in halves):
                    continue
                trial_snapshot = deepcopy(snapshot)
                trial_snapshot.setdefault("leave_history", {}).setdefault("leaves", {})[str(person["id"]) + "_" + day] = period
                trial_problem = prepare(trial_snapshot, use_help=True)
                trial = [list(row) for row in grid]
                changed=list(pair)
                for h in halves:
                    changed[h]="P"
                trial[d][i]="".join(changed)
                if not trial_problem["errors"] and not verify(trial_problem, trial, max_full_days=6):
                    names[period].append({"id": person["id"], "name": person["name"]})
        for group in groups:
            if names[group["period"]]:
                group["days"].append({"date": day, "people": names[group["period"]]})
    return {"days": groups[0]["days"], "groups":groups, "message": ""}
