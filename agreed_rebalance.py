"""了承出勤後の6連勤を、依頼済みヘルプを固定した全体調整で解消する。"""
import copy
import json
from collections import Counter
from scheduler_engine import prepare,generate,six_day_runs,verify
from help_commitments import lock_requested_help


def rebalance_agreement(snapshot,base,grid,person_id,day,period):
    problem=prepare(snapshot,use_help=True)
    if problem["errors"] or [str(p["id"]) for p in problem["people"]]!=[str(p["id"]) for p in base["people"]]:
        return grid,False
    name=next(p["name"] for p in problem["people"] if str(p["id"])==person_id)
    before=Counter(r["name"] for r in six_day_runs(problem,grid))
    if not before[name]:
        return grid,False
    settings=copy.deepcopy(snapshot["monthly_settings"])
    settings.setdefault("agreed_wish_changes",[]).append(dict(staff_id=person_id,date=day,work_period=period))
    planning=dict(snapshot,monthly_settings=settings)
    locked=lock_requested_help(planning,json.dumps(dict(base,grid=grid)))
    result=generate(locked,use_help=True,seconds=5)
    if result["status"]!="success":
        return grid,False
    after=Counter(r["name"] for r in result.get("six_day_runs",[]))
    if after[name]>=before[name] or any(after[n]>before[n] for n in after if n!=name):
        return grid,False
    if verify(result["problem"],result["grid"],max_full_days=result.get("max_full_days",5)):
        return grid,False
    positions={str(p["id"]):i for i,p in enumerate(result["problem"]["people"])}
    remapped=[[row[positions[str(p["id"])]] if str(p["id"]) in positions else "RR" for p in base["people"]]
              for row in result["grid"]]
    return remapped,True
