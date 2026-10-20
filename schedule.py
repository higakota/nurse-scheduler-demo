"""勤務表の作成と保存。入力と保存済み結果の変更を検出する。"""
import calendar
import hashlib
import json
import re
import secrets
from datetime import date, timedelta, datetime, timezone
from flask import abort, redirect, render_template, request, session, url_for
from scheduler_engine import generate, verify, generate_draft
from weekly_rules import weekly_summary
from schedule_display import monthly_display, grouped_shortages


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def read_snapshot(db, month):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    snapshot = {"rules_version": 14, "month": month, "staff": [dict(row) for row in db.execute("SELECT * FROM staff ORDER BY id")]}
    raw = {}
    for table in ("monthly_settings","doctor_plans","coverage_settings","leave_history","help_availability","technician_exceptions","weekly_work_boundaries"):
        row = db.execute(f"SELECT data FROM {table} WHERE month=?", (month,)).fetchone() if table in tables else None
        raw[table] = row["data"] if row else ""
        snapshot[table] = json.loads(raw[table]) if raw[table] else {}
    review = db.execute("SELECT data,version FROM doctor_plan_reviews WHERE month=?", (month,)).fetchone() if "doctor_plan_reviews" in tables else None
    snapshot["doctor_plan_reviews"] = dict(review) if review else {}
    snapshot["doctor_raw"] = raw["doctor_plans"]
    first = date.fromisoformat(month + "-01")
    previous_month = (first-timedelta(days=1)).strftime("%Y-%m")
    previous = db.execute("SELECT data FROM monthly_settings WHERE month=?", (previous_month,)).fetchone() if "monthly_settings" in tables else None
    snapshot["previous_closures"] = json.loads(previous["data"]).get("closures",{}) if previous else {}
    next_month = (first.replace(day=calendar.monthrange(first.year,first.month)[1])+timedelta(days=1)).strftime("%Y-%m")
    snapshot["weekly_neighbor_boundaries"] = {}
    for neighbor in (previous_month,next_month):
        row = db.execute("SELECT data FROM weekly_work_boundaries WHERE month=?",(neighbor,)).fetchone() if "weekly_work_boundaries" in tables else None
        if row:
            snapshot["weekly_neighbor_boundaries"][neighbor] = json.loads(row["data"])
    following = db.execute("SELECT data FROM monthly_settings WHERE month=?",(next_month,)).fetchone() if "monthly_settings" in tables else None
    snapshot["weekly_next_closures"] = json.loads(following["data"]).get("closures",{}) if following else {}
    fingerprint = digest(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    result = db.execute("SELECT data FROM generated_schedules WHERE month=?", (month,)).fetchone() if "generated_schedules" in tables else None
    return snapshot, fingerprint, result["data"] if result else ""


def register_schedule(app, connect_db):
    @app.route("/schedule", methods=["GET","POST"])
    def schedule():
        month = request.args.get("month", session.get("ui_month", date.today().strftime("%Y-%m")))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400)
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400)
        session.setdefault("csrf_token", secrets.token_hex(32))
        db = connect_db()
        try:
            snapshot, fingerprint, original = read_snapshot(db, month)
        finally:
            db.close()
        outcome = None
        if request.method == "POST":
            if not secrets.compare_digest(session["csrf_token"].encode(), request.form.get("csrf_token","").encode()):
                abort(400)
            if request.form.get("mode") not in ("self","help","six","draft","draft_six"):
                abort(400)
            if not secrets.compare_digest(fingerprint.encode(), request.form.get("fingerprint","").encode()) or not secrets.compare_digest(digest(original).encode(), request.form.get("result_token","").encode()):
                outcome = {"status":"input_error","messages":["別の画面で入力または作成結果が変更されました。最新の内容を確認して作成してください。"],"shortages":[]}
            elif original and request.form.get("mode") not in ("draft","draft_six") and request.form.get("replace") != "yes":
                outcome = {"status":"input_error","messages":["保存済み結果を置き換えることを確認してください。"],"shortages":[]}
            else:
                use_help = request.form.get("mode") in ("help","six")
                outcome = (generate_draft(snapshot, seconds=app.config.get("SCHEDULER_SECONDS",10), allow_six=request.form.get("mode") == "draft_six")
                           if request.form.get("mode") in ("draft","draft_six") else
                           (generate(snapshot, use_help, seconds=app.config.get("SCHEDULER_SECONDS",10), allow_six=True)
                            if request.form.get("mode")=="six" else generate(snapshot, use_help, seconds=app.config.get("SCHEDULER_SECONDS",10))))
                if outcome["status"] == "success":
                    validation = verify(outcome["problem"], outcome["grid"], max_full_days=outcome.get("max_full_days",5))
                    if validation:
                        outcome.update(status="unknown", messages=validation)
                    else:
                        problem = outcome["problem"]
                        saved = dict(max_full_days=outcome.get("max_full_days",5), six_day_runs=outcome.get("six_day_runs", []), doctor_plans=snapshot.get("doctor_plans", {}), monthly_context=snapshot.get("monthly_settings", {}), comparison_inputs={"wishes": snapshot.get("monthly_settings", {}).get("wishes", {}), "leaves": snapshot.get("leave_history", {}).get("leaves", {})}, weekly_summary=weekly_summary(problem,outcome["grid"]), input_hash=fingerprint, mode="help" if use_help else "self", days=problem["days"],
                                     people=problem["people"], grid=outcome["grid"], notes=outcome["messages"],
                                     created=datetime.now(timezone.utc).isoformat(), targets={str(problem["people"][i]["id"]):problem["targets"][k]/2 for k,i in enumerate(problem["regular"])})
                        db = connect_db()
                        try:
                            db.execute("BEGIN IMMEDIATE")
                            _, latest, latest_result = read_snapshot(db,month)
                            if latest != fingerprint or latest_result != original:
                                db.rollback()
                                outcome.update(status="input_error",messages=["作成中に入力または結果が変更されたため、保存しませんでした。再作成してください。"])
                            else:
                                db.execute("CREATE TABLE IF NOT EXISTS generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
                                db.execute("INSERT INTO generated_schedules VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                                           (month,json.dumps(saved,ensure_ascii=False)))
                                from help_shortages import write_reference
                                write_reference(db,snapshot,fingerprint,[],kind="verified")
                                db.commit()
                                return redirect(url_for("schedule",month=month,saved="1"))
                        finally:
                            db.close()
        saved = json.loads(original) if original else None
        stale = bool(saved and saved["input_hash"] != fingerprint)
        shortage_rows = outcome.get("shortages", []) if outcome else []
        if outcome and outcome.get("status") == "draft":
            shortage_rows = grouped_shortages(outcome["shortages"], outcome["problem"], outcome["grid"])
            from help_shortages import publish_reference
            if not publish_reference(connect_db,snapshot,fingerprint,shortage_rows,kind="draft_six" if request.form.get("mode")=="draft_six" else "draft"):
                outcome["messages"].append("仮作成中に入力が変わったため、来院予定画面の不足表示は更新していません。再作成してください。")
        if outcome and outcome.get("status") == "draft":
            from manual_schedule import seed_draft
            db = connect_db()
            try:
                db.execute("BEGIN IMMEDIATE")
                _, current_fp, _ = read_snapshot(db, month)
                if current_fp == fingerprint:
                    seed_draft(db, month, snapshot, fingerprint, outcome)
                    db.commit()
            finally:
                db.close()
        current_comparison = {"wishes": snapshot.get("monthly_settings", {}).get("wishes", {}),
                              "leaves": snapshot.get("leave_history", {}).get("leaves", {})}
        draft_display = None
        if outcome and outcome.get("status") == "draft":
            problem = outcome["problem"]
            draft_display = monthly_display(problem["days"], problem["people"], outcome["grid"],
                                            snapshot.get("monthly_settings"), dict(zip(
                                                (str(problem["people"][i]["id"]) for i in problem["regular"]),
                                                (value/2 for value in problem["targets"]))), shortage_rows, comparison_inputs=current_comparison, doctor_plans=snapshot.get("doctor_plans"))
        saved_display = monthly_display(saved["days"], saved["people"], saved["grid"],
                                        saved.get("monthly_context", snapshot.get("monthly_settings") if not stale else None),
                                        saved.get("targets"), comparison_inputs=saved.get("comparison_inputs", current_comparison if not stale else None), doctor_plans=saved.get("doctor_plans", snapshot.get("doctor_plans") if not stale else None)) if saved else None
        helper_ids={str(p["id"]) for p in snapshot["staff"] if p["is_help"]}
        help_count=sum(1 for key,period in snapshot.get("help_availability",{}).items()
                       if key.partition("_")[0] in helper_ids and period in ("full","am","pm"))
        return render_template("schedule.html", month=month, fingerprint=fingerprint, result_token=digest(original),
                               outcome=outcome, result=saved, stale=stale, draft_display=draft_display, saved_display=saved_display, shortage_rows=shortage_rows,
                               help_count=help_count)
