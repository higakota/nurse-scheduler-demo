"""有給の登録と、初回導入時の前月末勤務入力。勤務表は自動作成しない。"""
import calendar
import hashlib
import json
import re
import secrets
from datetime import date, timedelta

from flask import abort, redirect, render_template, request, session, url_for

PERIODS = {"full": "全日有給", "am": "午前有給", "pm": "午後有給"}
HISTORY = {"": "未入力", "full": "全日勤務（会議含む）", "am": "午前のみ勤務",
           "pm": "午後のみ勤務", "rest": "全日休み", "paid": "全日有給",
           "am_paid": "午前有給・午後勤務", "pm_paid": "午前勤務・午後有給"}


def trailing_full_days(values):
    count = 0
    for value in reversed(values):
        if value == "full":
            count += 1
        elif value in HISTORY and value:
            return count
        else:
            return None
    return count


def absence_warnings(leaves, monthly, names):
    messages = []
    for key, period in leaves.items():
        staff_id, day = key.split("_", 1)
        label = day + " " + names.get(staff_id, "未登録スタッフ")
        wish = monthly.get("wishes", {}).get(key)
        if wish:
            if period == "full" or wish == "full" or wish == period:
                messages.append(label + "：通常の希望休と有給が重なっています。どちらも維持しています。区分を見直してください。")
            else:
                messages.append(label + "：半日有給と半日通常休みの組合せは、指定休日日数に1日として数えます。")
        if date.fromisoformat(day).weekday() == 6 or day in monthly.get("closures", {}):
            messages.append(label + "：休診日と有給が重なっています。休日日数の扱いを確認してください。")
        if period in ("full", "pm"):
            for meeting in monthly.get("meetings", []):
                if meeting["date"] == day and staff_id in meeting["participants"]:
                    messages.append(label + "：有給と午後の会議参加が重なっています。入力の見直しが必要です。")
    return messages


def register_leave_and_history(app, connect_db):
    @app.route("/leave-history", methods=["GET", "POST"])
    def leave_history():
        month = request.args.get("month", date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400)
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400)
        first = date(year, number, 1)
        last = date(year, number, calendar.monthrange(year, number)[1])
        history_days = [first - timedelta(days=offset) for offset in range(6, 0, -1)]
        previous_month = history_days[-1].strftime("%Y-%m")
        session.setdefault("csrf_token", secrets.token_hex(32))
        error = None
        values = {"staff": request.args.get("staff", ""), "day": request.args.get("day", ""), "period": "full"}
        db = connect_db()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS leave_history(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS monthly_settings(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.commit()
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400, description="画面を開き直してください。")
                db.execute("BEGIN IMMEDIATE")
            staff = db.execute("SELECT * FROM staff ORDER BY id").fetchall()
            people = {str(person["id"]): dict(person) for person in staff}
            names = {key: value["name"] for key, value in people.items()}
            row = db.execute("SELECT data FROM leave_history WHERE month=?", (month,)).fetchone()
            raw = row["data"] if row else ""
            data = json.loads(raw) if raw else {"leaves": {}, "history": {}}
            monthly_row = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone()
            monthly = json.loads(monthly_row["data"]) if monthly_row else {}
            previous = db.execute("SELECT data FROM monthly_settings WHERE month=?", (previous_month,)).fetchone()
            previous_closures = json.loads(previous["data"]).get("closures", {}) if previous else {}
            fingerprint = hashlib.sha256(json.dumps(
                [raw, people, monthly, previous_closures], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            fixed_days = {day.isoformat() for day in history_days if day.weekday() == 6 or day.isoformat() in previous_closures}
            if values["staff"] not in people:
                values["staff"] = next(iter(people), "")
            if values["staff"] + "_" + values["day"] in data["leaves"]:
                values["period"] = data["leaves"][values["staff"] + "_" + values["day"]]
            if request.method == "POST":
                try:
                    if not secrets.compare_digest(fingerprint, request.form.get("fingerprint", "")):
                        raise ValueError("別の画面で入力が変更されました。最新の内容を確認してやり直してください。")
                    action = request.form.get("action")
                    if action == "leave_bulk_save":
                        values["staff"] = request.form.get("staff", values["staff"])
                        if values["staff"] not in people:
                            raise ValueError("スタッフを選択してください。")
                        try:
                            patch = json.loads(request.form.get("leave_changes", ""))
                        except (ValueError, TypeError):
                            raise ValueError("カレンダーの選択内容を読み取れません。画面を開き直してください。")
                        if not isinstance(patch, dict) or len(patch) > len(people) * last.day:
                            raise ValueError("有給の入力内容が正しくありません。")
                        candidate = dict(data["leaves"])
                        for key, period in patch.items():
                            pieces = key.split("_", 1)
                            if len(pieces) != 2 or pieces[0] not in people or period not in ("", "full", "am", "pm"):
                                raise ValueError("有給のスタッフまたは区分が正しくありません。")
                            try:
                                leave_day = date.fromisoformat(pieces[1])
                            except ValueError:
                                raise ValueError("有給の日付が正しくありません。")
                            if not first <= leave_day <= last or leave_day.isoformat() != pieces[1]:
                                raise ValueError("有給の日付は対象月の日付を指定してください。")
                            if period:
                                candidate[key] = period
                            else:
                                candidate.pop(key, None)
                        data["leaves"] = candidate
                    elif action == "leave_save":
                        values = {key: request.form.get(key, "") for key in ("staff", "day", "period")}
                        if values["staff"] not in people or values["period"] not in PERIODS:
                            raise ValueError("スタッフと有給の区分を選択してください。")
                        try:
                            leave_day = date.fromisoformat(values["day"])
                        except ValueError:
                            raise ValueError("有給の日付を選択してください。")
                        values["day"] = leave_day.isoformat()
                        if not first <= leave_day <= last:
                            raise ValueError("有給の日付は対象月の日付を指定してください。")
                        data["leaves"][values["staff"] + "_" + values["day"]] = values["period"]
                    elif action == "leave_delete":
                        key = request.form.get("key", "")
                        if key not in data["leaves"]:
                            abort(404)
                        del data["leaves"][key]
                    elif action == "history_save":
                        candidate = dict(data["history"])
                        for staff_id, person in people.items():
                            if person["is_help"]:
                                continue
                            for day in history_days:
                                key = staff_id + "_" + day.isoformat()
                                value = request.form.get("history_" + key, "")
                                if value not in HISTORY:
                                    raise ValueError("前月末勤務の区分が正しくありません。")
                                if day.isoformat() in fixed_days:
                                    if value not in ("", "rest"):
                                        raise ValueError(day.isoformat() + "：休診日は全日休みで入力してください。")
                                    value = "rest"
                                if person["role"] == "technician" and value in ("pm", "am_paid"):
                                    raise ValueError(person["name"] + "：検査技師の午後のみ勤務は登録できません。")
                                candidate[key] = value
                        data["history"] = candidate
                    else:
                        abort(400)
                    db.execute("INSERT INTO leave_history VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                               (month, json.dumps(data, ensure_ascii=False)))
                    db.commit()
                    selected_staff, selected_day = "", ""
                    if action in ("leave_save", "leave_bulk_save"):
                        selected_staff, selected_day = values["staff"], values["day"]
                    elif action == "leave_delete":
                        selected_staff, selected_day = key.split("_", 1)
                    return redirect(url_for("leave_history", month=month, saved="1",
                                            staff=selected_staff, day=selected_day))
                except ValueError as exc:
                    db.rollback()
                    error = str(exc)
            warnings = absence_warnings(data["leaves"], monthly, names)
            for key, value in data["history"].items():
                staff_id, history_day = key.split("_", 1)
                if staff_id in people and people[staff_id]["is_help"]:
                    continue
                if history_day in fixed_days and value not in ("", "rest"):
                    warnings.append(history_day + " " + names.get(staff_id, "未登録スタッフ") + "：登録済みの前月末勤務と休診指定が重なっています。入力の見直しが必要です。")
            history_rows = []
            for person in staff:
                if person["is_help"]:
                    continue
                slots = []
                for day in history_days:
                    key = str(person["id"]) + "_" + day.isoformat()
                    value = "rest" if day.isoformat() in fixed_days else data["history"].get(key, "")
                    slots.append({"key": key, "day": day.isoformat(), "value": value, "fixed": day.isoformat() in fixed_days})
                history_rows.append({"person": person, "slots": slots, "tail": trailing_full_days([slot["value"] for slot in slots])})
        finally:
            db.close()
        return render_template("leave_history.html", month=month, staff=staff,
                               fingerprint=fingerprint, error=error, warnings=warnings,
                               history_options=HISTORY, history_rows=history_rows,
                               saved=request.args.get("saved") == "1")
