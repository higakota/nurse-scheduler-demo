"""最新の入力を表示中の表へまとめて反映する、保存前の変更案。"""
import json
import time
from input_reflection import reflection_patch
from help_shortages import conditions_hash
from scheduler_engine import prepare, verify, preference_metrics
from fixed_help import generate_fixed_help


def update_patch(snapshot, base, seconds=10):
    reflected = [list(row) for row in base["grid"]]
    for key, pair in json.loads(reflection_patch(snapshot, base)).items():
        d, i = map(int, key.split("_"))
        reflected[d][i] = pair
    problem = prepare(snapshot, use_help=True)
    indexes = {str(p["id"]): i for i, p in enumerate(problem["people"])}
    commitments = {}
    for d, day in enumerate(base["days"]):
        for i, person in enumerate(base["people"]):
            if not person["is_help"] or person.get("advance_help"):
                continue
            old = base["grid"][d][i]
            abstract = "".join("W" if c in "ABCD" else c for c in old)
            if old != "RR" and abstract in problem["options"][d][indexes[str(person["id"])]]:
                commitments[str(person["id"]) + "_" + day] = old
    planning = dict(snapshot, fixed_help_commitments=commitments)
    source = dict(base, grid=reflected, conditions_hash=conditions_hash(planning))
    started = time.monotonic()
    result = generate_fixed_help(planning, json.dumps(source), seconds=seconds * .3,
                                 source_name="表示中の勤務表", partial=False)
    from scheduler_engine import prefer_five
    if result.get("grid") is None:
        result = prefer_five(planning, use_help=True, partial=False, seconds=seconds * .4)
    if result.get("grid") is None:
        remaining = max(.1, seconds - (time.monotonic() - started))
        result = prefer_five(planning, use_help=True, partial=True, seconds=remaining)
    # 同じ不足数の別配置を返すだけの再更新では、不足日を動かさない。
    if result.get("status") != "success":
        base_positions={str(p["id"]):i for i,p in enumerate(base["people"])}
        current=[[row[base_positions[str(p["id"])]] for p in problem["people"]] for row in reflected]
        for d,row in enumerate(current):
            for i,p in enumerate(problem["people"]):
                abstract="".join("W" if c in "ABCD" else c for c in row[i])
                if p["is_help"] and abstract not in problem["options"][d][i] and "RR" in problem["options"][d][i]:
                    row[i]="RR"
        if not verify(problem,current,allow_shortages=True,max_full_days=6):
            retained=dict(status="draft",problem=problem,grid=current)
            def quality(value):
                metrics=preference_metrics(value)
                return metrics[0],metrics[2]
            if result.get("grid") is None or quality(retained)<=quality(result):
                result=retained
    if result.get("grid") is None:
        raise ValueError("更新できませんでした。" + " ".join(result.get("messages", [])))
    positions = {str(p["id"]): i for i, p in enumerate(result["problem"]["people"])}
    return json.dumps({f"{d}_{i}": row[positions[str(p["id"])]]
                       for d, row in enumerate(result["grid"])
                       for i, p in enumerate(base["people"])})
