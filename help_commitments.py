"""全体調整でも、依頼済みヘルプの元の勤務を保持する。"""
import json


def lock_requested_help(snapshot, source_raw):
    helpers=[p for p in snapshot["staff"] if p["is_help"] and not p.get("advance_help")]
    if not helpers:
        return snapshot
    if not source_raw:
        raise ValueError("依頼済みヘルプの元の勤務表がありません。先にヘルプ込みの仮表を確認してください。")
    source=json.loads(source_raw)
    indexes={str(p["id"]):i for i,p in enumerate(source["people"])}
    fixed={}
    for d,day in enumerate(source["days"]):
        for person in helpers:
            pid=str(person["id"])
            fixed[pid+"_"+day]=source["grid"][d][indexes[pid]] if pid in indexes else "RR"
    return dict(snapshot,fixed_help_commitments=fixed)
