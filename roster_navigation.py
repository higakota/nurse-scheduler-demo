"""表の版と遷移元を明示し、別の表を黙って開かない。"""
import json
from datetime import datetime,timezone

def stamp(value):
    try:
        result=datetime.fromisoformat(value.get("updated") or value.get("created") or "")
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError,TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)

def newer(left,right):
    return stamp(left)>stamp(right)

def import_patch(base,source,staff):
    if source.get("days")!=base["days"]:
        raise ValueError("指定した表の日付が一致しません。元の画面を開き直してください。")
    if {str(p["id"]) for p in base["people"]}!={str(p["id"]) for p in staff}:
        raise ValueError("スタッフが変わっています。現在の勤務表を確認してください。")
    positions={str(p["id"]):i for i,p in enumerate(source["people"])}
    return json.dumps({f"{d}_{i}":row[positions[str(p["id"])]] if str(p["id"]) in positions else "RR"
                      for d,row in enumerate(source["grid"]) for i,p in enumerate(base["people"])})

def pending_source(base,sources,fingerprint):
    current=[(kind,source) for kind,source in sources.items()
             if source.get("input_hash")==fingerprint and newer(source,base)
             and (source["grid"]!=base["grid"] or source["people"]!=base["people"])]
    return max(current,key=lambda item:stamp(item[1])) if current else (None,None)
