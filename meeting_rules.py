"""会議時間の検証。時刻不明の既存会議から参加可能とは推測しない。"""
import re


def checked_times(start, end):
    if not start and not end:
        return "", ""
    if not all(re.fullmatch(r"(?:1[2-9]|2[0-3]):[0-5][0-9]", value or "") for value in (start, end)) or start >= end:
        raise ValueError("会議の開始・終了は午後の時刻で、開始より終了を後にしてください。")
    return start, end


def check_meeting_overlap(meetings, proposed, exclude=None):
    start, end = checked_times(proposed.get("start", ""), proposed.get("end", ""))
    for old in meetings:
        if old.get("id") == exclude or old["date"] != proposed["date"] or not set(old["participants"]) & set(proposed["participants"]):
            continue
        old_start, old_end = old.get("start", ""), old.get("end", "")
        if not all((start, end, old_start, old_end)):
            raise ValueError("同じ参加者の会議があります。時間の重複を確認できないため、この午後への追加・変更は保留しています。会議の予定と参加者を確認してください。")
        if start < old_end and old_start < end:
            raise ValueError("同じ参加者の会議時間が重なっています。時間か参加者を見直してください。")
