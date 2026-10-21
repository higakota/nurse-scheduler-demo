"""月別の入力と保存。勤務表の自動作成は行わない。"""
import calendar
import hashlib
from leave_and_history import absence_warnings
from meeting_rules import checked_times, check_meeting_overlap
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
        from absence_calendar import load_absences, save_absences
        db = connect_db()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS monthly_settings (month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            if request.method == "POST" and request.form.get("action") in ("settings", "excel_events", "meeting_attendance", "meeting_add", "meeting_edit", "meeting_time", "meeting_delete"):
                db.execute("BEGIN IMMEDIATE")
            staff = db.execute("SELECT * FROM staff ORDER BY id").fetchall()
            ids = {str(person["id"]) for person in staff}
            row = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone()
            data = json.loads(row["data"]) if row else {"targets": {}, "wishes": {}, "closures": {}, "meetings": []}
            settings_fingerprint = hashlib.sha256(json.dumps(
                {"staff": [dict(person) for person in staff], "monthly": data},
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            weekly_updates = {}
            event_preview = None
            db.execute("CREATE TABLE IF NOT EXISTS excel_event_drafts(owner TEXT, month TEXT, data TEXT NOT NULL, PRIMARY KEY(owner, month))")
            event_row = db.execute("SELECT data FROM excel_event_drafts WHERE owner=? AND month=?", (session.get("import_owner", ""), month)).fetchone()
            if event_row is None:
                # 自宅PCの単独利用。再起動等でセッションが変わっても保存済み候補を確認できる。
                previous_draft = db.execute("SELECT owner, data FROM excel_event_drafts WHERE month=? ORDER BY rowid DESC LIMIT 1", (month,)).fetchone()
                if previous_draft:
                    session["import_owner"] = previous_draft["owner"]
                    event_row = previous_draft
            if event_row:
                event_preview = json.loads(event_row["data"])
                # Older saved candidates can gain dates without changing saved meetings.
                if any(not item.get("date") for item in event_preview.get("extras",{}).get("meetings",[])):
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    source = db.execute("SELECT workbook FROM doctor_import_draft WHERE owner=?", (session.get("import_owner",""),)).fetchone() if "doctor_import_draft" in tables else None
                    if source:
                        from doctor_import import parse_schedule
                        from excel_events import extract_events
                        first = event_preview["extras"]["meetings"][0]
                        sheet = first.get("source","").split("・文字枠")[0]
                        try:
                            fresh = extract_events(source["workbook"], sheet, parse_schedule(source["workbook"],sheet,month))
                            dates = {item["id"]:item["date"] for item in fresh["meetings"]}
                            for item in event_preview["extras"]["meetings"]:
                                item["date"] = dates.get(item["id"],item.get("date",""))
                        except (ValueError,KeyError):
                            pass
            doctor_row = db.execute("SELECT data FROM doctor_plans WHERE month=?",(month,)).fetchone() if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doctor_plans'").fetchone() else None
            input_doctors = json.loads(doctor_row["data"]) if doctor_row else {}
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400, description="画面を開き直してから保存してください。")
                action = request.form.get("action")
                if action in ("meeting_attendance", "meeting_add", "meeting_edit", "meeting_time", "meeting_delete") and (
                        action in ("meeting_edit","meeting_attendance") or "settings_fingerprint" in request.form):
                    if not secrets.compare_digest(settings_fingerprint, request.form.get("settings_fingerprint", "")):
                        error = "会議またはスタッフ等の設定が別の画面で変更されています。画面を開き直してください。"
                        action = "meeting_conflict"
                if action == "meeting_conflict":
                    pass
                elif action == "meeting_attendance":
                    person_id = request.form.get("attendance_staff","")
                    meeting_day = request.form.get("attendance_day","")
                    if person_id not in ids or meeting_day not in {d.isoformat() for d in days}:
                        error = "スタッフと対象月の日付を選択してください。"
                    elif date.fromisoformat(meeting_day).weekday()==6 or meeting_day in data["closures"]:
                        error = "休診日には会議の参加を登録できません。"
                    else:
                        from meeting_attendance import attendance_plan
                        try:
                            data = attendance_plan(data,event_preview,person_id,meeting_day,request.form.getlist("attendance"))
                        except ValueError as exc:
                            error = str(exc)
                elif action == "absence_save":
                    try:
                        save_absences(db, month, request.form)
                        return redirect(url_for("monthly_settings", month=month, saved="1", staff=request.form.get("absence_staff", ""), _anchor="wishes"))
                    except ValueError as exc:
                        db.rollback()
                        error = str(exc)
                elif action == "excel_events":
                    from excel_events import apply_events, monthly_snapshot
                    try:
                        if not event_preview:
                            raise ValueError("先に医師予定の画面でExcelを読み取ってください。")
                        tab = request.form.get("event_tab") or ("meetings" if any(key.startswith("meeting_pick_") and value == "yes" for key, value in request.form.items()) else "closures")
                        if tab not in ("closures", "meetings"):
                            raise ValueError("反映する項目のタブを選択してください。")
                        kind, prefix = ("meetings", "meeting_pick_") if tab == "meetings" else ("closures", "closure_pick_")
                        if not any(request.form.get(prefix + item["id"]) == "yes" for item in event_preview.get("extras", {}).get(kind, [])):
                            raise ValueError("取り込む候補が選択されていません。「この会議を取り込む」などにチェックを入れてください。")
                        apply_events(db, month, event_preview, request.form)
                        event_preview["monthly_original"] = monthly_snapshot(db, month)
                        for kind, prefix in (("closures", "closure_pick_"), ("meetings", "meeting_pick_")):
                            event_preview["extras"][kind] = [item for item in event_preview["extras"][kind] if request.form.get(prefix + item["id"]) != "yes"]
                        db.execute("UPDATE excel_event_drafts SET data=? WHERE owner=? AND month=?", (json.dumps(event_preview, ensure_ascii=False), session.get("import_owner", ""), month))
                        db.commit()
                        tab = request.form.get("event_tab", "closures")
                        return redirect(url_for("monthly_settings", month=month, saved="1", _anchor="meetings" if tab == "meetings" else "closures"))
                    except ValueError as exc:
                        db.rollback()
                        error = str(exc)
                elif action == "settings":
                    weekly_fields = [key for key in request.form if key.startswith("weekly_limit_")]
                    if (weekly_fields or "settings_fingerprint" in request.form) and not secrets.compare_digest(
                            settings_fingerprint, request.form.get("settings_fingerprint", "")):
                        error = "設定が別の画面で変更されています。画面を開き直してから保存してください。"
                    eligible = {str(person["id"]) for person in staff if not person["is_help"] and person["employment"] == "part"}
                    for field in weekly_fields:
                        person_id = field.removeprefix("weekly_limit_")
                        if person_id not in eligible:
                            error = "週上限の対象スタッフが変更されています。画面を開き直してください。"
                            continue
                        raw = request.form[field].strip()
                        try:
                            value = Decimal(raw) if raw else None
                            if value is not None and (not value.is_finite() or value < 0 or value > 7 or value * 2 != (value * 2).to_integral_value()):
                                raise ValueError
                            weekly_updates[person_id] = int(value * 2) if value is not None else None
                        except (InvalidOperation, ValueError):
                            error = "週の勤務上限は0～7日まで、0.5日単位で入力してください。"
                    monthly_excluded_ids = {str(person["id"]) for person in staff if person["is_help"] or person["employment"] == "part"}
                    targets, wishes, closures = {key: value for key, value in data["targets"].items() if key in monthly_excluded_ids}, dict(data["wishes"]) if request.form.get("preserve_wishes") == "yes" else {}, {}
                    for person_id in sorted(ids):
                        raw = request.form.get("target_" + person_id, "").strip()
                        if raw and person_id not in monthly_excluded_ids:
                            try:
                                value = Decimal(raw)
                                if not value.is_finite() or value < 0 or value > len(days) or value * 2 != (value * 2).to_integral_value():
                                    raise ValueError
                                targets[person_id] = str(value)
                            except (InvalidOperation, ValueError):
                                error = "休日日数は0～月の日数まで、0.5日単位で入力してください。"
                        for day in days:
                            key = person_id + "_" + day.isoformat()
                            wish = data["wishes"].get(key, "") if request.form.get("preserve_wishes") == "yes" else request.form.get("wish_" + key, "")
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
                elif action in ("meeting_add", "meeting_edit"):
                    existing = None
                    if action == "meeting_edit":
                        existing = next((m for m in data["meetings"] if m["id"] == request.form.get("meeting_id")), None)
                        if existing is None:
                            abort(404)
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
                        try:
                            start, end = checked_times(request.form.get("start", (existing or {}).get("start", "")), request.form.get("end", (existing or {}).get("end", "")))
                            proposed = dict(existing or {}, id=existing["id"] if existing else secrets.token_hex(8),
                                            date=meeting_date, title=title, participants=participants, start=start, end=end)
                            check_meeting_overlap(data["meetings"], proposed, exclude=existing["id"] if existing else None)
                            if existing:
                                existing.update(proposed)
                            else:
                                data["meetings"].append(proposed)
                        except ValueError as exc:
                            error = str(exc)
                elif action == "meeting_time":
                    meeting = next((m for m in data["meetings"] if m["id"] == request.form.get("meeting_id")), None)
                    if not meeting:
                        abort(404)
                    try:
                        start, end = checked_times(request.form.get("start", ""), request.form.get("end", ""))
                        if not start:
                            raise ValueError("開催時間を指定してください。")
                        proposed = dict(meeting, start=start, end=end)
                        # 時刻不明の既存会議は順に補完できる。既知の重複だけ保存を拒否する。
                        known = [m for m in data["meetings"] if m.get("start") and m.get("end")]
                        check_meeting_overlap(known, proposed, exclude=meeting["id"])
                        meeting.update(start=start, end=end)
                    except ValueError as exc:
                        error = str(exc)
                elif action == "meeting_delete":
                    meeting_id = request.form.get("meeting_id", "")
                    if not any(meeting["id"] == meeting_id for meeting in data["meetings"]):
                        abort(404)
                    data["meetings"] = [meeting for meeting in data["meetings"] if meeting["id"] != meeting_id]
                else:
                    abort(400)
                if error is None and action not in ("excel_events", "absence_save"):
                    for person_id, units in weekly_updates.items():
                        db.execute("UPDATE staff SET weekly_limit_units=? WHERE id=?", (units, person_id))
                    db.execute("INSERT INTO monthly_settings(month, data) VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                               (month, json.dumps(data, ensure_ascii=False)))
                    db.commit()
                    return redirect(url_for("monthly_settings", month=month, saved="1", _anchor="meetings" if action.startswith("meeting_") else (request.form.get("settings_tab") if request.form.get("settings_tab") in ("targets", "closures") else None)))
            if error:
                db.rollback()
            _, absence_data, absence_fingerprint, _ = load_absences(db, month)
            warnings = []
            names = {str(person["id"]): person["name"] for person in staff}
            for meeting in data["meetings"]:
                if not meeting["participants"]:
                    warnings.append(meeting["date"] + " " + meeting["title"] + "：会議の参加者が未設定です。会議の編集で参加者を指定してください。")
                if meeting["date"] in data["closures"]:
                    warnings.append(meeting["date"] + "：休診日に会議があります。入力の見直しが必要です。")
                for person_id in meeting["participants"]:
                    if data["wishes"].get(person_id + "_" + meeting["date"]) in ("full", "pm"):
                        warnings.append(meeting["date"] + " " + names.get(person_id, "未登録スタッフ") + "：希望休と会議が重なっています。希望休を優先し、この時間帯は会議に出席しません。")
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leave_history'").fetchone():
                leave_row = db.execute("SELECT data FROM leave_history WHERE month=?", (month,)).fetchone()
                if leave_row:
                    warnings.extend(absence_warnings(json.loads(leave_row["data"])["leaves"], data, names))
            for index, meeting in enumerate(data["meetings"]):
                for other in data["meetings"][:index]:
                    try:
                        check_meeting_overlap([other], meeting)
                    except ValueError as exc:
                        warnings.append(meeting["date"] + "：" + str(exc))
            from help_availability import load_help
            advance_visits, help_people, _, help_fingerprint = load_help(db, month)
            advance_people = [p for p in help_people if p.get("advance_help")]
        finally:
            db.close()
        absence_weeks = [[day if day.month == number else None for day in week] for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, number)]
        from meeting_attendance import attendance_choices
        return render_template("monthly.html", advance_visits=advance_visits, advance_people=advance_people, help_fingerprint=help_fingerprint, attendance_days=attendance_choices(data,event_preview), input_doctors=input_doctors, settings_fingerprint=settings_fingerprint, absence_weeks=absence_weeks, absence_leaves=absence_data["leaves"], absence_fingerprint=absence_fingerprint, event_preview=event_preview, extra_staff=staff, month=month, days=days, staff=staff, data=data, names=names,
                               error=error, warnings=warnings, saved=request.method == "GET" and request.args.get("saved") == "1",
                               weekdays="月火水木金土日")
