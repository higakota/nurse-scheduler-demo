"""他院ヘルプは明示的に登録した来院予定だけを利用する。自動配置は行わない。"""
import calendar
import hashlib
import json
import re
import secrets
from datetime import date
from flask import abort, flash, redirect, render_template, request, session, url_for

PERIODS = {"": "来院予定なし", "full": "全日", "am": "午前のみ", "pm": "午後のみ"}


def load_technician_exceptions(db, month):
    db.execute("CREATE TABLE IF NOT EXISTS technician_exceptions(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
    row = db.execute("SELECT data FROM technician_exceptions WHERE month=?", (month,)).fetchone()
    return json.loads(row["data"]) if row else {}


def load_help(db, month):
    db.execute("CREATE TABLE IF NOT EXISTS help_availability(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
    row = db.execute("SELECT data FROM help_availability WHERE month=?", (month,)).fetchone()
    raw = row["data"] if row else ""
    staff = [dict(person) for person in db.execute("SELECT * FROM staff WHERE is_help=1 ORDER BY id")]
    exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monthly_settings'").fetchone()
    monthly = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone() if exists else None
    closures = json.loads(monthly["data"]).get("closures", {}) if monthly else {}
    fingerprint = hashlib.sha256(json.dumps([raw, staff, closures, load_technician_exceptions(db, month)], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return json.loads(raw) if raw else {}, staff, closures, fingerprint


def available_help(db, month, day_text, half, area):
    """将来の自動作成用。来院予定なしのヘルプは候補に含めない。"""
    if half not in ("am", "pm") or area not in ("A", "B", "C"):
        raise ValueError("配置条件が正しくありません。")
    day = date.fromisoformat(day_text)
    if day.strftime("%Y-%m") != month:
        raise ValueError("対象月が一致しません。")
    data, staff, closures, _ = load_help(db, month)
    if day.weekday() == 6 or day_text in closures or (day.weekday() == 4 and half == "pm"):
        return []
    result = []
    for person in staff:
        period = data.get(str(person["id"]) + "_" + day_text)
        if period not in ("full", half) or area not in person["allowed_areas"]:
            continue
        if person["role"] == "technician" and (area != "C" or period == "pm"):
            continue
        result.append(person)
    return result


def register_help_availability(app, connect_db):
    @app.route("/help", methods=["GET", "POST"])
    def help_availability():
        month = request.args.get("month", session.get("ui_month", date.today().strftime("%Y-%m")))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400)
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400)
        session.setdefault("csrf_token", secrets.token_hex(32))
        error = None
        db = connect_db()
        try:
            data, staff, closures, fingerprint = load_help(db, month)
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400)
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                data, staff, closures, fingerprint = load_help(db, month)
                try:
                    if not secrets.compare_digest(fingerprint, request.form.get("fingerprint", "")):
                        raise ValueError("別の画面で来院予定・スタッフ・休診日が変更されました。最新の内容を確認してください。")
                    action = request.form.get("action", "visits")
                    if action == "exceptions":
                        selected_days = list(dict.fromkeys(request.form.getlist("exception_dates")))
                        exceptions = load_technician_exceptions(db, month)
                        # 既存の休診日の例外は、利用者がこの画面で保存した場合に限り取消できる。
                        candidate = {}
                        for text in selected_days:
                            try:
                                day = date.fromisoformat(text)
                            except ValueError:
                                raise ValueError("看護師のみ対応の日付が正しくありません。")
                            if day.strftime("%Y-%m") != month or day.isoformat() != text:
                                raise ValueError("看護師のみ対応は対象月の日付を選択してください。")
                            if day.weekday() == 6 or text in closures:
                                if exceptions.get(text) is not True:
                                    raise ValueError("休診日には看護師のみ対応の例外は不要です。")
                            candidate[text] = True
                        db.execute("INSERT INTO technician_exceptions VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                                   (month, json.dumps(candidate, ensure_ascii=False)))
                        db.commit()
                        return redirect(url_for("help_availability", month=month, saved="1", _anchor="technician-exceptions"))
                    if action != "visits":
                        abort(400)
                    try:
                        patch = json.loads(request.form.get("changes", ""))
                    except (ValueError, TypeError):
                        raise ValueError("来院予定を読み取れません。")
                    people = {str(p["id"]): p for p in staff}
                    if not isinstance(patch, dict) or len(patch) > len(people) * calendar.monthrange(year, number)[1]:
                        raise ValueError("来院予定の件数が正しくありません。")
                    candidate = dict(data)
                    for key, period in patch.items():
                        if not isinstance(key, str) or not isinstance(period, str) or period not in PERIODS:
                            raise ValueError("来院予定の区分が正しくありません。")
                        parts = key.split("_", 1)
                        if len(parts) != 2 or parts[0] not in people:
                            raise ValueError("登録済みのヘルプを選択してください。")
                        try:
                            day = date.fromisoformat(parts[1])
                        except ValueError:
                            raise ValueError("来院日が正しくありません。")
                        if day.strftime("%Y-%m") != month or day.isoformat() != parts[1]:
                            raise ValueError("来院日は対象月の日付を指定してください。")
                        if period and (day.weekday() == 6 or parts[1] in closures):
                            raise ValueError("休診日には来院予定を登録できません。")
                        if period == "pm" and people[parts[0]]["role"] == "technician":
                            raise ValueError("検査技師は午後のみの勤務を登録できません。")
                        if period:
                            candidate[key] = period
                        else:
                            candidate.pop(key, None)
                    db.execute("INSERT INTO help_availability VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                               (month, json.dumps(candidate, ensure_ascii=False)))
                    db.commit()
                    return redirect(url_for("help_availability", month=month, staff=request.form.get("staff", ""), saved="1"))
                except ValueError as exc:
                    db.rollback()
                    error = str(exc)
            people = {str(p["id"]): p for p in staff}
            warnings = []
            for key, period in data.items():
                person, day_text = key.split("_", 1)
                if person not in people or date.fromisoformat(day_text).weekday() == 6 or day_text in closures:
                    warnings.append(day_text + "：登録済み来院予定とスタッフ設定・休診日を見直してください。元の予定は維持しています。")
            exceptions = load_technician_exceptions(db, month)
            for day_text in exceptions:
                if date.fromisoformat(day_text).weekday() == 6 or day_text in closures:
                    warnings.append(day_text + "：看護師のみ対応の例外が登録されていますが、現在は休診日です。必要なら取消してください。")
            from help_shortages import load_reference
            shortages = load_reference(db,month)
            selected = request.form.get("staff", request.args.get("staff", ""))
            if selected not in people:
                selected = next(iter(people), "")
        finally:
            db.close()
        weeks = [[day if day.month == number else None for day in week] for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, number)]
        return render_template("help_availability.html", shortages=shortages, month=month, data=data, staff=staff, closures=closures,
                               exceptions=exceptions, fingerprint=fingerprint, error=error, warnings=warnings, selected=selected,
                               weeks=weeks, periods=PERIODS)


    @app.route("/help/shortages", methods=["POST"])
    def refresh_help_shortages():
        month=request.args.get("month",session.get("ui_month",date.today().strftime("%Y-%m")))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}",month):
            abort(400)
        year,number=map(int,month.split("-"))
        if not 1900<=year<=9998 or not 1<=number<=12:
            abort(400)
        if not session.get("csrf_token") or not secrets.compare_digest(session["csrf_token"],request.form.get("csrf_token","")):
            abort(400)
        from schedule import read_snapshot
        from scheduler_engine import generate_draft
        from schedule_display import grouped_shortages
        from help_shortages import publish_reference, shortages_from_source
        from fixed_help import load_seed, load_manual_source, preferred_help_source
        db=connect_db()
        try:
            snapshot,fp,_=read_snapshot(db,month)
            draft_raw, manual_raw = load_seed(db,month), load_manual_source(db,month)
            source_kind = preferred_help_source(snapshot,draft_raw,manual_raw)
            source_raw = manual_raw if source_kind == "manual" else draft_raw
        finally:
            db.close()
        if source_raw:
            try:
                rows = shortages_from_source(snapshot, source_raw)
                if publish_reference(connect_db,snapshot,fp,rows,kind=source_kind,expected_source=(source_kind,source_raw)):
                    return redirect(url_for("help_availability",month=month,shortages_updated="1"),code=303)
                flash("計算中に元の勤務表が変わりました。もう一度更新してください。","help-shortage-error")
            except ValueError as exc:
                flash(str(exc),"help-shortage-error")
            return redirect(url_for("help_availability",month=month),code=303)
        if any(p["is_help"] and p.get("advance_help") for p in snapshot["staff"]):
            from advance_help import generate_advance_draft
            outcome=generate_advance_draft(snapshot,seconds=app.config.get("SCHEDULER_SECONDS",10))
        else:
            outcome=generate_draft(snapshot,seconds=app.config.get("SCHEDULER_SECONDS",10))
        if outcome["status"]=="draft":
            rows=grouped_shortages(outcome["shortages"],outcome["problem"],outcome["grid"])
            if publish_reference(connect_db,snapshot,fp,rows,outcome=outcome):
                return redirect(url_for("help_availability",month=month,shortages_updated="1"),code=303)
            flash("計算中に入力が変わったため不足表示を更新していません。再確認してください。","help-shortage-error")
        else:
            for message in outcome["messages"][:3]:
                flash(message,"help-shortage-error")
        return redirect(url_for("help_availability",month=month),code=303)
