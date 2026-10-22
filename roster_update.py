"""最新の入力を表示中の表へまとめて反映する、保存前の変更案。"""
import json
from input_reflection import reflection_patch
from help_shortages import conditions_hash
from scheduler_engine import prepare
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
    result = generate_fixed_help(planning, json.dumps(source), seconds=seconds,
                                 source_name="表示中の勤務表", partial=True)
    if result.get("grid") is None:
        from scheduler_engine import prefer_five
        result = prefer_five(planning, use_help=True, partial=True, seconds=seconds)
    if result.get("grid") is None:
        raise ValueError("更新できませんでした。" + " ".join(result.get("messages", [])))
    positions = {str(p["id"]): i for i, p in enumerate(result["problem"]["people"])}
    return json.dumps({f"{d}_{i}": row[positions[str(p["id"])]]
                       for d, row in enumerate(result["grid"])
                       for i, p in enumerate(base["people"])})
