"""直近の仮表を、再作成・保存せずに表示する。"""
import json
from scheduler_engine import prepare,verify,draft_shortages,six_day_runs


def restore_draft(snapshot,fingerprint,raw):
    if not raw:
        return None
    source=json.loads(raw)
    if source.get("input_hash")!=fingerprint:
        return None
    problem=prepare(snapshot,use_help=True)
    if problem["errors"] or source["days"]!=problem["days"]:
        return None
    indexes={str(p["id"]):i for i,p in enumerate(source["people"])}
    if any(str(p["id"]) not in indexes for p in problem["people"] if not p["is_help"]):
        return None
    grid=[[row[indexes[str(p["id"])]] if str(p["id"]) in indexes else "RR" for p in problem["people"]]
          for row in source["grid"]]
    if verify(problem,grid,allow_shortages=True,max_full_days=6):
        return None
    return dict(status="draft",problem=problem,grid=grid,
                shortages=[r for d,row in enumerate(grid) for r in draft_shortages(problem,d,row)],
                messages=source.get("notes",[]),included_help=source.get("included_help",False),
                advance_help=source.get("advance_help",False),rebalanced=source.get("rebalanced",False),
                experimental=False,max_full_days=6,six_day_runs=six_day_runs(problem,grid),resumed=True)
