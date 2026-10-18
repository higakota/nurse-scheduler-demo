"""画面共通の案内と、保存状況を表示するホーム。勤務条件は判定しない。"""
import calendar
import json
import re
from datetime import date
from flask import abort, render_template, request, session
from doctor_import import IMPORT_VERSION

STEPS = [
    ("doctor_import", "医師予定", "Excelから担当医を取り込む"),
    ("monthly_settings", "希望休・会議", "希望休、休日日数、休診日と会議"),
    ("leave_history", "有給・前月末", "有給と月をまたぐ勤務を入力"),
    ("coverage_settings", "必要人数", "診療に必要な最低人数を確認"),
]
PAGES = {
    "index": ("ホーム", "今月の勤務表をつくりましょう。"),
    "staff_settings": ("スタッフ設定", "職種やベテランなど、毎月共通の設定です。"),
    "doctor_import": ("医師予定", "Excelを取り込み、午前・午後の担当医を確認します。"),
    "doctor_edit": ("医師予定の編集", "変更前後の担当医と人数を確認して保存します。"),
    "monthly_settings": ("希望休・会議", "下のタブから、入力したい項目を選んでください。"),
    "leave_history": ("有給・前月末", "有給はカレンダーから。前月末勤務は画面の下で入力できます。"),
    "coverage_settings": ("必要人数", "未設定をまとめて1人にして、増員が必要なところだけ変更できます。"),
}


def selected_month():
    month = request.args.get("month") or session.get("ui_month") or date.today().strftime("%Y-%m")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        abort(400)
    year, number = map(int, month.split("-"))
    if not 1900 <= year <= 9998 or not 1 <= number <= 12:
        abort(400)
    return month


def register_ui(app):
    @app.context_processor
    def common_ui():
        month = selected_month()
        session["ui_month"] = month
        endpoint = request.endpoint or "index"
        active = "doctor_import" if endpoint == "doctor_edit" else endpoint
        current = next((i for i, step in enumerate(STEPS) if step[0] == active), None)
        year, number = map(int, month.split("-"))
        return dict(ui_month=month, ui_month_label=f"{year}年{number}月", ui_steps=STEPS,
                    ui_active=active, ui_title=PAGES.get(endpoint, PAGES["index"])[0],
                    ui_description=PAGES.get(endpoint, PAGES["index"])[1],
                    ui_previous=STEPS[current - 1] if current is not None and current > 0 else None,
                    ui_next=STEPS[current + 1] if current is not None and current + 1 < len(STEPS) else None)


def render_home(connect_db):
    month = selected_month()
    db = connect_db()
    try:
        staff = db.execute("SELECT * FROM staff ORDER BY id").fetchall()
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        snapshots = {}
        for table in ("doctor_plans", "monthly_settings", "leave_history", "coverage_settings"):
            row = db.execute(f"SELECT data FROM {table} WHERE month=?", (month,)).fetchone() if table in tables else None
            snapshots[table] = row["data"] if row else ""
        doctors = json.loads(snapshots["doctor_plans"]) if snapshots["doctor_plans"] else {}
        monthly = json.loads(snapshots["monthly_settings"]) if snapshots["monthly_settings"] else {}
        leave = json.loads(snapshots["leave_history"]) if snapshots["leave_history"] else {}
        review = db.execute("SELECT * FROM doctor_plan_reviews WHERE month=?", (month,)).fetchone() if "doctor_plan_reviews" in tables else None
        verified = bool(doctors and review and review["version"] == IMPORT_VERSION and review["data"] == snapshots["doctor_plans"])
        states = [
            dict(saved=bool(doctors), attention=bool(doctors and not verified),
                 detail=f"{len(doctors)}日分の医師予定" if doctors else "いつものExcelを用意してください"),
            dict(saved=bool(snapshots["monthly_settings"]), attention=False,
                 detail=f"休日日数 {len(monthly.get('targets', {}))}人分 · 会議 {len(monthly.get('meetings', []))}件"),
            dict(saved=bool(snapshots["leave_history"]), attention=False,
                 detail=f"有給 {len(leave.get('leaves', {}))}件 · 前月末勤務の入力"),
            dict(saved=bool(snapshots["coverage_settings"]), attention=False,
                 detail="A・B番は自動表示、C番は1人／2人を指定"),
        ]
    finally:
        db.close()
    cards = [dict(endpoint=step[0], title=step[1], description=step[2], **state)
             for step, state in zip(STEPS, states)]
    next_card = next((card for card in cards if not card["saved"] or card["attention"]), cards[0])
    year, number = map(int, month.split("-"))
    return render_template("home.html", cards=cards, staff_count=len(staff),
                           next_card=next_card, month=month,
                           saved_count=sum(card["saved"] for card in cards),
                           month_days=calendar.monthrange(year, number)[1])
