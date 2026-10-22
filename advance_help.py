"""事前に配置してよい勤務可能日を使う、相談前の仮作成。"""
from scheduler_engine import prefer_five


def generate_advance_draft(snapshot, seconds=10):
    people=[p for p in snapshot["staff"] if not p["is_help"] or p.get("advance_help")]
    helper_ids={str(p["id"]) for p in people if p["is_help"]}
    visits={key:value for key,value in snapshot.get("help_availability",{}).items()
            if key.partition("_")[0] in helper_ids}
    inputs=dict(snapshot,staff=people,help_availability=visits)
    result=prefer_five(inputs,use_help=bool(helper_ids),seconds=seconds,partial=True)
    result["advance_help"]=True
    result["messages"].append("事前に配置してよいヘルプの登録済み勤務可能日を使いました。ほかのヘルプは含めていません。")
    return result
