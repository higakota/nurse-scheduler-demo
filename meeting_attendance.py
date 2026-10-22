"""Calendar attendance editing, preserving all unrelated monthly input."""
from copy import deepcopy
import secrets
from meeting_rules import check_meeting_overlap


def attendance_choices(data, preview):
    result = {}
    imported = {m.get("import_source") for m in data["meetings"]}
    for index, meeting in enumerate(data["meetings"]):
        result.setdefault(meeting["date"], []).append(dict(
            key="saved:"+meeting.get("id","legacy-"+str(index)), title=meeting.get("title","??"),
            participants=meeting["participants"], candidate=False))
    for item in (preview or {}).get("extras", {}).get("meetings", []):
        if item.get("date") and item["id"] not in imported:
            result.setdefault(item["date"], []).append(dict(
                key="excel:"+item["id"], title=item["title"], participants=[], candidate=True))
    return result


def attendance_plan(data, preview, staff_id, day, selected, validate=True):
    choices = attendance_choices(data, preview).get(day, [])
    allowed = {item["key"] for item in choices}
    if not set(selected) <= allowed:
        raise ValueError("この日の会議を選択してください。")
    updated = deepcopy(data)
    for index, meeting in enumerate(updated["meetings"]):
        if meeting["date"] != day:
            continue
        key = "saved:"+meeting.get("id","legacy-"+str(index))
        meeting.setdefault("id",secrets.token_hex(8))
        members = [str(value) for value in meeting["participants"] if str(value) != staff_id]
        if key in selected:
            members.append(staff_id)
        meeting["participants"] = members
    candidates = {item["id"]: item for item in (preview or {}).get("extras", {}).get("meetings", [])}
    for key in selected:
        if key.startswith("excel:"):
            item = candidates[key[6:]]
            updated["meetings"].append(dict(id=secrets.token_hex(8), date=day,
                title=item["title"], participants=[staff_id], start="", end="", import_source=item["id"]))
    for meeting in updated["meetings"]:
        if validate and meeting["date"] == day:
            check_meeting_overlap(updated["meetings"], meeting, exclude=meeting["id"])
    return updated

def attendance_batch_plan(data,preview,changes,staff_ids,days):
    """全セルの変更をまとめて検証する。途中までの保存はしない。"""
    from datetime import date
    if not isinstance(changes,dict) or len(changes)>len(staff_ids)*len(days):
        raise ValueError("会議参加の変更内容が正しくありません。")
    updated=deepcopy(data)
    touched=set()
    for key,selected in changes.items():
        if not isinstance(key,str) or "_" not in key:
            raise ValueError("会議参加のスタッフ・日付が正しくありません。")
        pid,day=key.split("_",1)
        if pid not in staff_ids or day not in days or date.fromisoformat(day).weekday()==6 or day in data["closures"]:
            raise ValueError("会議参加のスタッフ・日付を確認してください。")
        if not isinstance(selected,list) or any(not isinstance(v,str) for v in selected) or len(selected)!=len(set(selected)):
            raise ValueError("参加する会議を選び直してください。")
        touched.add(day)
        # 同じExcel候補を別の人が選んでも、一つの会議としてまとめる。
        imported={"excel:"+m["import_source"]:"saved:"+m["id"] for m in updated["meetings"] if m.get("import_source")}
        selected=[imported.get(v,v) for v in selected]
        updated=attendance_plan(updated,preview,pid,day,selected,validate=False)
    for meeting in updated["meetings"]:
        if meeting["date"] not in touched:continue
        check_meeting_overlap(updated["meetings"],meeting,exclude=meeting.get("id"))
    return updated
