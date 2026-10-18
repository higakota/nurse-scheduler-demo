"""診療必要人数の確認と検査室人数の指定。勤務の割当は行わない。"""
import calendar
import hashlib
import json
import re
import secrets
from datetime import date

from flask import abort, redirect, render_template, request, session, url_for
from doctor_import import IMPORT_VERSION


def requirements_for(day, half, names, closed):
    if closed:
        return {"closed": True, "doctor_count": 0, "a": 0, "b": 0, "automatic_c": 0}
    if names is None or not names:
        return {"closed": False, "doctor_count": None if names is None else 0,
                "a": None, "b": None, "automatic_c": None}
    count = len(names)
    return {"closed": False, "doctor_count": count, "a": 2, "b": count,
            "automatic_c": 2 if count >= 3 else None}


def register_coverage(app, connect_db):
    @app.route("/coverage", methods=["GET", "POST"])
    def coverage_settings():
        month = request.args.get("month", date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400)
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400)
        days = [date(year, number, day) for day in range(1, calendar.monthrange(year, number)[1] + 1)]
        session.setdefault("csrf_token", secrets.token_hex(32))
        error = None
        db = connect_db()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS doctor_plans(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS doctor_plan_reviews(month TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS monthly_settings(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS coverage_settings(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.commit()
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400, description="画面を開き直してください。")
                db.execute("BEGIN IMMEDIATE")
            doctor_row = db.execute("SELECT data FROM doctor_plans WHERE month=?", (month,)).fetchone()
            monthly_row = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone()
            stored_row = db.execute("SELECT data FROM coverage_settings WHERE month=?", (month,)).fetchone()
            review = db.execute("SELECT data, version FROM doctor_plan_reviews WHERE month=?", (month,)).fetchone()
            doctor_raw = doctor_row["data"] if doctor_row else ""
            stored_raw = stored_row["data"] if stored_row else ""
            doctors = json.loads(doctor_raw) if doctor_raw else {}
            monthly = json.loads(monthly_row["data"]) if monthly_row else {}
            closures = monthly.get("closures", {})
            stored = json.loads(stored_raw) if stored_raw else {}
            trusted = bool(doctor_raw and review and review["version"] == IMPORT_VERSION and review["data"] == doctor_raw)
            fingerprint = hashlib.sha256(json.dumps(
                [doctor_raw, closures, stored_raw], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            rows = []
            selectable = []
            for day in days:
                slots = []
                for half, label in (("am", "午前"), ("pm", "午後")):
                    key = day.isoformat() + "_" + half
                    names = doctors.get(day.isoformat(), {}).get(half)
                    closed = day.weekday() == 6 or day.isoformat() in closures or (day.weekday() == 4 and half == "pm")
                    slot = requirements_for(day, half, names, closed)
                    slot.update(key=key, label=label, names=names or [], selection="", changed=False)
                    if closed:
                        slot["reason"] = "日曜休診" if day.weekday() == 6 else (
                            "金曜午後・診療なし" if day.weekday() == 4 and half == "pm" and day.isoformat() not in closures else
                            ("祝日" if closures.get(day.isoformat()) == "holiday" else "年末年始休診"))
                    else:
                        slot["reason"] = ""
                    if slot["a"] is not None and not closed and slot["automatic_c"] is None:
                        previous = stored.get(key)
                        same_doctors = previous and sorted(previous.get("doctors", [])) == sorted(names)
                        if same_doctors and previous.get("c") in (1, 2):
                            slot["selection"] = str(previous["c"])
                        slot["changed"] = bool(previous and not same_doctors)
                        selectable.append(slot)
                    slot["c"] = slot["automatic_c"] if slot["automatic_c"] is not None else (
                        int(slot["selection"]) if slot["selection"] else None)
                    slots.append(slot)
                rows.append({"day": day.isoformat(), "slots": slots})
            if request.method == "POST":
                if not trusted:
                    error = "先に医師予定を取り込み、最新の内容を確認して保存してください。"
                elif not secrets.compare_digest(fingerprint, request.form.get("fingerprint", "")):
                    error = "医師予定・休診日・必要人数が別の画面で変更されました。最新の内容を確認して、もう一度指定してください。"
                else:
                    candidate = dict(stored)
                    for slot in selectable:
                        value = request.form.get("c_" + slot["key"], "")
                        if value not in ("1", "2"):
                            error = "診療のある各時間帯の検査室を1人または2人で指定してください。"
                            slot["selection"] = ""
                            slot["c"] = None
                        else:
                            slot["selection"] = value
                            slot["c"] = int(value)
                            candidate[slot["key"]] = {"c": int(value), "doctors": slot["names"]}
                    # 自動・休診の欄はリクエスト値を使わず、必須ルールを常に優先する。
                    if error is None:
                        db.execute("INSERT INTO coverage_settings VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                                   (month, json.dumps(candidate, ensure_ascii=False)))
                        db.commit()
                        return redirect(url_for("coverage_settings", month=month, saved="1"))
                db.rollback()
        finally:
            db.close()
        return render_template("coverage.html", month=month, rows=rows, trusted=trusted, error=error,
                               fingerprint=fingerprint, saved=request.args.get("saved") == "1")
