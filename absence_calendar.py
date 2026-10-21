"""希望休・有給の共通入力。保存先と区分を分けたまま一括更新する。"""
import calendar
import hashlib
import json
import secrets
from datetime import date


def load_absences(db, month):
    db.execute("CREATE TABLE IF NOT EXISTS leave_history(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
    monthly = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone()
    leave = db.execute("SELECT data FROM leave_history WHERE month=?", (month,)).fetchone()
    staff = [dict(row) for row in db.execute("SELECT * FROM staff ORDER BY id")]
    raw = [monthly["data"] if monthly else "", leave["data"] if leave else "", staff]
    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    settings = json.loads(raw[0]) if raw[0] else {"targets": {}, "wishes": {}, "closures": {}, "meetings": []}
    history = json.loads(raw[1]) if raw[1] else {"leaves": {}, "history": {}}
    return settings, history, fingerprint, staff


def save_absences(db, month, form):
    db.execute("BEGIN IMMEDIATE")
    monthly, history, fingerprint, staff = load_absences(db, month)
    if not secrets.compare_digest(fingerprint, form.get("absence_fingerprint", "")):
        raise ValueError("別の画面で入力が変更されました。最新の内容を確認してやり直してください。")
    try:
        changes = json.loads(form.get("absence_changes", ""))
    except (ValueError, TypeError):
        raise ValueError("カレンダーの選択内容を読み取れません。")
    if not isinstance(changes, dict) or not {"wishes", "leaves"} <= set(changes) or set(changes)-{"wishes","leaves","summer","support"}:
        raise ValueError("希望休・有給の入力内容が正しくありません。")
    ids = {str(person["id"]) for person in staff}
    year, number = map(int, month.split("-"))
    for kind, target in (("wishes", monthly["wishes"]), ("leaves", history["leaves"]), ("summer",monthly.setdefault("summer",{})), ("support",monthly.setdefault("support",{}))):
        patch = changes.get(kind,{})
        if not isinstance(patch, dict) or len(patch) > len(ids) * calendar.monthrange(year, number)[1]:
            raise ValueError("希望休・有給の入力件数が正しくありません。")
        for key, period in patch.items():
            if not isinstance(key, str) or not isinstance(period, str) or period not in ("", "full", "am", "pm"):
                raise ValueError("希望休・有給の区分が正しくありません。")
            pieces = key.split("_", 1)
            if len(pieces) != 2 or pieces[0] not in ids:
                raise ValueError("スタッフが正しくありません。")
            try:
                day = date.fromisoformat(pieces[1])
            except ValueError:
                raise ValueError("日付が正しくありません。")
            if day.strftime("%Y-%m") != month or day.isoformat() != pieces[1]:
                raise ValueError("日付は対象月の日付を選択してください。")
            if period:
                target[key] = period
            else:
                target.pop(key, None)
    for table, data in (("monthly_settings", monthly), ("leave_history", history)):
        db.execute(f"INSERT INTO {table} VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                   (month, json.dumps(data, ensure_ascii=False)))
    db.commit()
