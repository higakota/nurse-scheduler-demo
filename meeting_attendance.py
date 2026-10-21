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


def attendance_plan(data, preview, staff_id, day, selected):
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
        if meeting["date"] == day:
            check_meeting_overlap(updated["meetings"], meeting, exclude=meeting["id"])
    return updated
