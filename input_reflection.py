"""今月の入力を既存表へ反映する差分。条件に合う既存勤務を維持する。"""
import json
from scheduler_engine import prepare,rest_units
from weekly_rules import work_units

def reflection_patch(snapshot,base):
    problem=prepare(snapshot,use_help=True)
    if problem["errors"]:raise ValueError(problem["errors"][0])
    indexes={str(p["id"]):i for i,p in enumerate(problem["people"])}
    if set(indexes)!={str(p["id"]) for p in base["people"]} or problem["days"]!=base["days"]:
        raise ValueError("スタッフや日付が変わっています。新規作成が必要です。")
    patch={}
    for d,day in enumerate(base["days"]):
        for i,p in enumerate(base["people"]):
            if p["is_help"]:continue
            old=base["grid"][d][i]
            abstract="".join("W" if c in "ABCD" else c for c in old)
            options=problem["options"][d][indexes[str(p["id"])]]
            if abstract in options:continue
            choice=min(options,key=lambda pair:(sum(a!=b for a,b in zip(pair,abstract)),abs(rest_units(pair)-rest_units(old)),-work_units(pair),pair))
            pair="".join(("C" if p["role"]=="technician" else "D") if c=="W" else c for c in choice)
            if old!=pair:patch[f"{d}_{i}"]=pair
    return json.dumps(patch)
