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
from schedule_display import monthly_display, grouped_shortages, concise_shortages


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def read_snapshot(db, month):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    snapshot = {"rules_version": 19, "month": month, "staff": [dict(row) for row in db.execute("SELECT * FROM staff ORDER BY id")]}
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
            from fixed_help import load_seed, load_manual_source, consulted_help_source
            seed_raw = load_seed(db, month)
            manual_raw = load_manual_source(db, month)
            help_source, source_checked = consulted_help_source(db, month, manual_raw)
        finally:
            db.close()
        source_raw = manual_raw if help_source == "manual" else seed_raw
        source_name = "不足を確認した自院の表"
        source_token = digest(json.dumps([seed_raw, manual_raw]))
        outcome = None
        if request.method == "POST":
            if not secrets.compare_digest(session["csrf_token"].encode(), request.form.get("csrf_token","").encode()):
                abort(400)
            if request.form.get("mode") not in ("self","help","help_draft","rebalance","six","draft","advance_draft","draft_six"):
                abort(400)
            if not secrets.compare_digest(fingerprint.encode(), request.form.get("fingerprint","").encode()) or not secrets.compare_digest(digest(original).encode(), request.form.get("result_token","").encode()):
                outcome = {"status":"input_error","messages":["別の画面で入力または作成結果が変更されました。最新の内容を確認して作成してください。"],"shortages":[]}
            elif request.form.get("mode") in ("help","help_draft","rebalance") and (seed_raw or manual_raw) and request.form.get("seed_token", "") != source_token:
                outcome = {"status":"input_error","messages":["別の画面で自院の仮表が変更されました。画面を開き直してください。"],"shortages":[]}
            elif original and request.form.get("mode") not in ("draft","advance_draft","help_draft","draft_six") and request.form.get("replace") != "yes":
                outcome = {"status":"input_error","messages":["保存済み結果を置き換えることを確認してください。"],"shortages":[]}
            else:
                use_help = request.form.get("mode") in ("help","help_draft","rebalance","six")
                if request.form.get("mode") == "advance_draft":
                    from advance_help import generate_advance_draft
                    outcome=generate_advance_draft(snapshot,seconds=app.config.get("SCHEDULER_SECONDS",10))
                elif request.form.get("mode") in ("help","help_draft") and not source_checked:
                    outcome = {"status":"input_error", "messages":["自院の勤務を変更した後の不足が未確認です。ヘルプ画面で「不足を表示・更新」を押してから作成してください。"], "shortages":[]}
                elif request.form.get("mode") in ("help","help_draft") and source_raw:
                    from fixed_help import generate_fixed_help
                    outcome = generate_fixed_help(snapshot, source_raw, seconds=app.config.get("SCHEDULER_SECONDS",10), source_name=source_name, partial=request.form.get("mode")=="help_draft")
                elif request.form.get("mode")=="help_draft":
                    from scheduler_engine import prefer_five
                    outcome=prefer_five(snapshot,use_help=True,partial=True,seconds=app.config.get("SCHEDULER_SECONDS",10))
                    outcome["included_help"]=True
                else:
                    outcome = (generate_draft(snapshot, seconds=app.config.get("SCHEDULER_SECONDS",10), allow_six=request.form.get("mode") == "draft_six")
                           if request.form.get("mode") in ("draft","draft_six") else
                           (generate(snapshot, use_help, seconds=app.config.get("SCHEDULER_SECONDS",10), allow_six=True)
                            if request.form.get("mode")=="six" else generate(snapshot, use_help, seconds=app.config.get("SCHEDULER_SECONDS",10))))
                if request.form.get("mode") == "rebalance":
                    outcome["messages"].append("了承出勤・希望休・有給・会議・来院OKの時間帯を守り、自院全体の勤務を組み直しました。" if outcome["status"]=="success" else "自院全体も調整して探索しました。自院だけの仮作成を繰り返しても、不足が解消するとは限りません。")
                if outcome["status"] == "success":
                    validation = verify(outcome["problem"], outcome["grid"], max_full_days=outcome.get("max_full_days",5))
                    if validation:
                        outcome.update(status="unknown", messages=validation)
                    else:
                        problem = outcome["problem"]
                        saved = dict(rebalanced=request.form.get("mode")=="rebalance", max_full_days=outcome.get("max_full_days",5), six_day_runs=outcome.get("six_day_runs", []), doctor_plans=snapshot.get("doctor_plans", {}), monthly_context=snapshot.get("monthly_settings", {}), comparison_inputs={"wishes": snapshot.get("monthly_settings", {}).get("wishes", {}), "leaves": snapshot.get("leave_history", {}).get("leaves", {})}, weekly_summary=weekly_summary(problem,outcome["grid"]), input_hash=fingerprint, mode="help" if use_help else "self", days=problem["days"],
                                     people=problem["people"], grid=outcome["grid"], notes=outcome["messages"],
                                     created=datetime.now(timezone.utc).isoformat(), targets={str(problem["people"][i]["id"]):problem["targets"][k]/2 for k,i in enumerate(problem["regular"])})
                        db = connect_db()
                        try:
                            db.execute("BEGIN IMMEDIATE")
                            _, latest, latest_result = read_snapshot(db,month)
                            if latest != fingerprint or latest_result != original or (request.form.get("mode") in ("help","help_draft","rebalance") and (load_seed(db, month) != seed_raw or load_manual_source(db, month) != manual_raw)):
                                db.rollback()
                                outcome.update(status="input_error",messages=["作成中に入力または結果が変更されたため、保存しませんでした。再作成してください。"])
                            else:
                                db.execute("CREATE TABLE IF NOT EXISTS generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
                                db.execute("INSERT INTO generated_schedules VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                                           (month,json.dumps(saved,ensure_ascii=False)))
                                from help_shortages import write_reference
                                write_reference(db,snapshot,fingerprint,[],kind="verified")
                                db.commit()
                                return redirect(url_for("schedule",month=month,saved="1",_anchor="saved-result"))
                        finally:
                            db.close()
        saved = json.loads(original) if original else None
        stale = bool(saved and saved["input_hash"] != fingerprint)
        shortage_rows = outcome.get("shortages", []) if outcome else []
        if outcome and outcome.get("status") == "draft":
            shortage_rows = grouped_shortages(outcome["shortages"], outcome["problem"], outcome["grid"])
            from help_limits import helper_demand, PREFERRED_DAILY_HELPERS
            outcome["help_preference_days"] = [day for d,day in enumerate(outcome["problem"]["days"])
                if helper_demand(outcome["problem"],d,outcome["grid"][d]) > PREFERRED_DAILY_HELPERS]
            from help_shortages import publish_reference
            if not publish_reference(connect_db,snapshot,fingerprint,shortage_rows,kind="draft_six" if request.form.get("mode")=="draft_six" else "draft",outcome=outcome,expected_source=(help_source,source_raw) if request.form.get("mode")=="help_draft" and source_raw else None):
                outcome["messages"].append("仮作成中に入力が変わったため、来院予定画面の不足表示は更新していません。再作成してください。")
            else:
                # この画面から続けてヘルプ込み作成する際も、新しい仮表を参照する。
                db = connect_db()
                try:
                    seed_raw = load_seed(db, month)
                    manual_raw = load_manual_source(db, month)
                finally:
                    db.close()
                help_source = "draft"
                source_checked = True
                source_raw = seed_raw
                source_token = digest(json.dumps([seed_raw, manual_raw]))

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
        from manual_schedule import load_manual
        db=connect_db()
        try:
            _, edit_revision=load_manual(db, month, snapshot, fingerprint, original)
        finally:
            db.close()
        from leave_candidates import leave_candidates
        paid_candidates = leave_candidates(snapshot, saved, fingerprint)
        from itsdangerous import URLSafeSerializer
        shortage_scope = URLSafeSerializer(app.secret_key, salt="agreed-shortage-days").dumps(
            dict(month=month,fingerprint=fingerprint,days=concise_shortages(shortage_rows),
                 source_kind=help_source,source_hash=digest(source_raw) if source_raw else "",include_help=request.form.get("mode") in ("help","help_draft","rebalance","six","advance_draft"))) if shortage_rows else ""
        return render_template("schedule.html", advance_help_count=sum(1 for p in snapshot["staff"] if p["is_help"] and p.get("advance_help")), shortage_scope=shortage_scope, paid_candidates=paid_candidates, edit_revision=edit_revision, seed_token=source_token, fixed_help_base=bool(source_raw), help_source=help_source, has_seed=bool(seed_raw), has_manual=bool(manual_raw), source_name=source_name, month=month, fingerprint=fingerprint, result_token=digest(original),
                               outcome=outcome, result=saved, stale=stale, draft_display=draft_display, saved_display=saved_display, shortage_rows=shortage_rows, shortage_summary=concise_shortages(shortage_rows),
                               help_count=help_count)
