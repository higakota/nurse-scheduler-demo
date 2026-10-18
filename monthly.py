"""月別の入力と保存。勤務表の自動作成は行わない。"""
import calendar
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import abort, redirect, render_template, request, session, url_for
import secrets


def register_monthly(app, connect_db):
    @app.route("/monthly", methods=["GET", "POST"])
    def monthly_settings():
        month = request.args.get("month", date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400, description="対象月が正しくありません。")
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400, description="対象月が正しくありません。")
        days = [date(year, number, day) for day in range(1, calendar.monthrange(year, number)[1] + 1)]
        session.setdefault("csrf_token", secrets.token_hex(32))
        error = None
        db = connect_db()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS monthly_settings (month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            staff = db.execute("SELECT * FROM staff ORDER BY id").fetchall()
            ids = {str(person["id"]) for person in staff}
            row = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone()
            data = json.loads(row["data"]) if row else {"targets": {}, "wishes": {}, "closures": {}, "meetings": []}
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400, description="画面を開き直してから保存してください。")
                action = request.form.get("action")
                if action == "settings":
                    targets, wishes, closures = {}, {}, {}
                    for person_id in sorted(ids):
                        raw = request.form.get("target_" + person_id, "").strip()
                        if raw:
                            try:
                                value = Decimal(raw)
                                if not value.is_finite() or value < 0 or value > len(days) or value * 2 != (value * 2).to_integral_value():
                                    raise ValueError
                                targets[person_id] = str(value)
                            except (InvalidOperation, ValueError):
                                error = "休日日数は0～月の日数まで、0.5日単位で入力してください。"
                        for day in days:
                            key = person_id + "_" + day.isoformat()
                            wish = request.form.get("wish_" + key, "")
                            if wish not in ("", "full", "am", "pm"):
                                error = "希望休の区分が正しくありません。"
                            elif wish:
                                wishes[key] = wish
                    for day in days:
                        kind = request.form.get("closure_" + day.isoformat(), "")
                        if kind not in ("", "holiday", "year_end"):
                            error = "休診日の区分が正しくありません。"
                        elif kind:
                            closures[day.isoformat()] = kind
                    candidate = dict(data, targets=targets, wishes=wishes, closures=closures)
                    if error is None:
                        data = candidate
                    else:
                        # 入力エラー時も有効な入力を画面に残す。DBには一切保存しない。
                        data = candidate
                elif action == "meeting_add":
                    meeting_date = request.form.get("meeting_date", "")
                    title = request.form.get("title", "").strip()
                    participants = list(dict.fromkeys(request.form.getlist("participants")))
                    if meeting_date not in {day.isoformat() for day in days}:
                        error = "会議日は対象月の日付を選択してください。"
                    elif date.fromisoformat(meeting_date).weekday() == 6 or meeting_date in data["closures"]:
                        error = "日曜・祝日・年末年始の休診日には会議を登録できません。"
                    elif not title or len(title) > 80:
                        error = "会議名は1～80文字で入力してください。"
                    elif not participants or not set(participants) <= ids:
                        error = "会議の参加者を選択してください。"
                    else:
                        data["meetings"].append({"id": secrets.token_hex(8), "date": meeting_date, "title": title, "participants": participants})
                elif action == "meeting_delete":
                    meeting_id = request.form.get("meeting_id", "")
                    if not any(meeting["id"] == meeting_id for meeting in data["meetings"]):
                        abort(404)
                    data["meetings"] = [meeting for meeting in data["meetings"] if meeting["id"] != meeting_id]
                else:
                    abort(400)
                if error is None:
                    db.execute("INSERT INTO monthly_settings(month, data) VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                               (month, json.dumps(data, ensure_ascii=False)))
                    db.commit()
                    return redirect(url_for("monthly_settings", month=month, saved="1"))
            warnings = []
            names = {str(person["id"]): person["name"] for person in staff}
            for meeting in data["meetings"]:
                if meeting["date"] in data["closures"]:
                    warnings.append(meeting["date"] + "：休診日に会議があります。入力の見直しが必要です。")
                for person_id in meeting["participants"]:
                    if data["wishes"].get(person_id + "_" + meeting["date"]) in ("full", "pm"):
                        warnings.append(meeting["date"] + " " + names.get(person_id, "未登録スタッフ") + "：希望休と会議が重なっています。希望休を維持しています。入力の見直しが必要です。")
            if len({meeting["date"] for meeting in data["meetings"]}) < len(data["meetings"]):
                warnings.append("同日に複数の会議があります。重複の扱いは未確認のため、自動で参加可否を判定していません。")
        finally:
            db.close()
        return render_template("monthly.html", month=month, days=days, staff=staff, data=data, names=names,
                               error=error, warnings=warnings, saved=request.args.get("saved") == "1",
                               weekdays="月火水木金土日")
