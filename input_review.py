"""保存済みの月別入力を読み取って表示する。勤務表の生成・条件変更はしない。"""
import calendar
import json
from datetime import date
from flask import render_template
from ui import selected_month
from doctor_import import IMPORT_VERSION

PERIODS = {"full": "全日", "am": "午前", "pm": "午後"}


def register_input_review(app, connect_db):
    @app.get("/inputs")
    def input_review():
        month = selected_month()
        year, number = map(int, month.split("-"))
        db = connect_db()
        try:
            db.execute("BEGIN")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            staff = [dict(r) for r in db.execute("SELECT * FROM staff ORDER BY id")]
            def load(table):
                row = db.execute("SELECT data FROM " + table + " WHERE month=?", (month,)).fetchone() if table in tables else None
                return (json.loads(row["data"]) if row else {}), (row["data"] if row else "")
            monthly, _ = load("monthly_settings")
            leave, _ = load("leave_history")
            doctors, raw_doctors = load("doctor_plans")
            helpers, _ = load("help_availability")
            coverage, _ = load("coverage_settings")
            review = db.execute("SELECT * FROM doctor_plan_reviews WHERE month=?", (month,)).fetchone() if "doctor_plan_reviews" in tables else None
            reviewed = bool(raw_doctors and review and review["version"] == IMPORT_VERSION and review["data"] == raw_doctors)
        finally:
            db.close()
        names = {str(p["id"]): p["name"] for p in staff}
        day_rows = []
        for n in range(1, calendar.monthrange(year, number)[1] + 1):
            day = date(year, number, n)
            iso = day.isoformat()
            closure = monthly.get("closures", {}).get(iso)
            closed = "日曜・休診" if day.weekday() == 6 else {"holiday":"祝日・休診", "year_end":"年末年始・休診"}.get(closure, "")
            meetings = [dict(title=m.get("title", "名称未設定"),
                             participants=[names.get(str(i), "未登録スタッフ（ID " + str(i) + "）") for i in m.get("participants", [])])
                        for m in monthly.get("meetings", []) if m.get("date") == iso]
            visits = []
            for key, period in helpers.items():
                person_id, _, visit_day = key.partition("_")
                if visit_day == iso:
                    visits.append(dict(name=names.get(person_id, "未登録スタッフ（ID " + person_id + "）"),
                                       period=PERIODS.get(period, "未確認の区分")))
            day_rows.append(dict(iso=iso, label=f"{n}日（{'月火水木金土日'[day.weekday()]}）",
                                 closed=closed, friday=day.weekday()==4,
                                 doctors=doctors.get(iso, {}), meetings=meetings, visits=visits))
        issues=[]
        missing_doctors=[]
        missing_c=[]
        for row in day_rows:
            if row["closed"]:
                continue
            for half,label in (("am","午前"),("pm","午後")):
                if row["friday"] and half=="pm":
                    continue
                doctors_here=row["doctors"].get(half)
                if not isinstance(doctors_here,list) or not doctors_here:
                    missing_doctors.append(row["label"]+" "+label)
                elif len(doctors_here)<3:
                    saved=coverage.get(row["iso"]+"_"+half,{})
                    if saved.get("c") not in (1,2) or sorted(saved.get("doctors",[]))!=sorted(doctors_here):
                        missing_c.append(row["label"]+" "+label)
        if missing_doctors:
            issues.append(dict(title="医師予定が未登録、または0人の診療時間帯",details=missing_doctors,endpoint="doctor_import",anchor=""))
        if raw_doctors and not reviewed:
            issues.append(dict(title="医師予定の確認・保存が必要です",details=["現在の保存内容と確認記録が一致していません。"],endpoint="doctor_import",anchor=""))
        if missing_c:
            issues.append(dict(title="検査室の必要人数が未設定、または医師予定の変更後に未確認",details=missing_c,endpoint="coverage_settings",anchor=""))
        missing_limits=[]
        missing_targets=[]
        for person in staff:
            if person["is_help"]:
                continue
            if person["employment"]=="part":
                if person.get("weekly_limit_units") is None:
                    missing_limits.append(person["name"])
            elif monthly.get("targets",{}).get(str(person["id"])) in (None,""):
                missing_targets.append(person["name"])
        if missing_targets:
            issues.append(dict(title="公休日数が未設定のスタッフ",details=missing_targets,endpoint="monthly_settings",anchor="targets"))
        if missing_limits:
            issues.append(dict(title="週の勤務上限が未設定の非常勤スタッフ",details=missing_limits,endpoint="monthly_settings",anchor="targets"))
        invalid_meetings=[m.get("date","")+" "+m.get("title","名称未設定") for m in monthly.get("meetings",[]) if not m.get("participants") or any(str(i) not in names for i in m.get("participants",[]))]
        if invalid_meetings:
            issues.append(dict(title="参加者の確認が必要な会議",details=invalid_meetings,endpoint="monthly_settings",anchor="meetings"))
        people = []
        for p in staff:
            if p["is_help"]:
                continue
            person_id = str(p["id"])
            entries = []
            for row in day_rows:
                key = person_id + "_" + row["iso"]
                wish = monthly.get("wishes", {}).get(key)
                paid = leave.get("leaves", {}).get(key)
                if wish or paid:
                    entries.append(dict(label=row["label"],
                        wish=PERIODS.get(wish, "未確認の区分") if wish else "",
                        paid=PERIODS.get(paid, "未確認の区分") if paid else ""))
            target = monthly.get("targets", {}).get(person_id)
            limit = p.get("weekly_limit_units")
            setting = ("週上限 " + str(limit/2) + "日" if limit is not None else "週上限 未設定") if p["employment"]=="part" else ("公休 " + str(target) + "日" if target is not None else "公休日数 未設定")
            people.append(dict(id=person_id, name=p["name"], role="検査技師" if p["role"]=="technician" else "看護師",
                               employment="非常勤" if p["employment"]=="part" else ("常勤" if p["employment"]=="full" else "勤務区分 未設定"),
                               setting=setting, entries=entries))
        return render_template("input_review.html", month=month, days=day_rows, people=people,
                               reviewed=reviewed, has_doctors=bool(raw_doctors), issues=issues)
