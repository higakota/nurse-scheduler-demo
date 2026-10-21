"""画面共通の案内と、保存状況を表示するホーム。勤務条件は判定しない。"""
import calendar
import json
import re
from datetime import date
from flask import abort, render_template, request, session
from doctor_import import IMPORT_VERSION

STEPS = [
    ("doctor_import", "医師予定", "Excelから担当医を取り込む"),
    ("monthly_settings", "希望休・会議", "希望休・有給、休日日数、休診日と会議"),
    ("leave_history", "前月末勤務", "月をまたぐ連勤を確認"),
    ("coverage_settings", "必要人数", "診療に必要な最低人数を確認"),
]
INPUT_TABS = [("doctor_import","医師予定"),("monthly_settings","希望休・会議"),("coverage_settings","必要人数"),
              ("leave_history","前月末勤務"),("weekly_settings","月をまたぐ週"),("input_review","入力一覧")]
SCHEDULE_TABS = [("schedule","自動作成"),("manual_schedule","編集・印刷")]
PAGE_ALIASES = {"agreed_record_edit":"manual_schedule", "agreed_wish_change":"manual_schedule", "doctor_edit":"doctor_import", "staff_delete":"staff_settings",
                "preview_restore":"data_backup", "restore_backup":"data_backup"}

PAGES = {
    "manual_schedule": ("勤務表の編集・印刷", "下書きを修正して確認・保存します。"),
    "input_review": ("入力内容の確認", "今月の保存済みの入力をまとめて確認します。"),
    "data_backup": ("データのバックアップ", "入力した全月のデータをPCに保存します。"),
    "help_requests": ("ヘルプ相談リスト", "不足から相談状況を管理し、来院が決まった人を反映します。"),
    "index": ("ホーム", "今月の勤務表をつくりましょう。"),
    "help_availability": ("ヘルプの来院予定", "不足時に相談し、来院が決まった日だけ追加します。"),
    "schedule": ("勤務表の自動作成", "自院スタッフで作成し、不足時にヘルプを追加して再作成します。"),
    "staff_delete": ("スタッフの削除", "削除の対象を確認します。"),
    "weekly_settings": ("非常勤の週勤務", "月曜〜日曜の上限と、月をまたぐ週の実績・決定済み勤務を確認します。"),
    "staff_settings": ("スタッフ設定", "職種やベテランなど、毎月共通の設定です。"),
    "doctor_import": ("医師予定", "Excelを取り込み、午前・午後の担当医を確認します。"),
    "doctor_edit": ("医師予定の編集", "変更前後の担当医と人数を確認して保存します。"),
    "monthly_settings": ("希望休・会議", "下のタブから、入力したい項目を選んでください。"),
    "leave_history": ("前月末勤務", "前月末の勤務を入力します。希望休・有給は同じカレンダーで入力できます。"),
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
        active = PAGE_ALIASES.get(endpoint, endpoint)
        input_endpoints = {item[0] for item in INPUT_TABS}
        group = "inputs" if active in input_endpoints else ("schedules" if active in ("schedule","manual_schedule") else active)
        tabs = INPUT_TABS if group=="inputs" else (SCHEDULE_TABS if group=="schedules" else [])
        year, number = map(int, month.split("-"))
        month_index = year * 12 + number - 1
        def adjacent(offset):
            y, m = divmod(month_index + offset, 12)
            return f"{y:04}-{m+1:02}" if 1900 <= y <= 9998 else None
        return dict(ui_previous_month=adjacent(-1), ui_next_month=adjacent(1),
                    ui_month=month, ui_month_label=f"{year}年{number}月",
                    ui_active=active, ui_group=group, ui_tabs=tabs, ui_month_endpoint=active,
                    ui_title=PAGES.get(active, PAGES["index"])[0],
                    ui_description=PAGES.get(active, PAGES["index"])[1])



def render_home(connect_db):
    month = selected_month()
    db = connect_db()
    try:
        db.execute("BEGIN")
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
        manual_row = db.execute("SELECT data FROM manual_schedules WHERE month=?", (month,)).fetchone() if "manual_schedules" in tables else None
        manual_saved = bool(manual_row)
        from schedule import read_snapshot
        snapshot,current_hash,generated_raw=read_snapshot(db,month)
        generated=json.loads(generated_raw) if generated_raw else {}
        manual=json.loads(manual_row[0]) if manual_row else {}
        manual_stale=bool(manual and manual.get("input_hash")!=current_hash)
        generated_stale=bool(generated and generated.get("input_hash")!=current_hash)
        help_visits=sum(1 for key,value in snapshot.get("help_availability",{}).items() if value in ("full","am","pm") and key.partition("_")[0] in {str(p["id"]) for p in staff if p["is_help"]})
        verified = bool(doctors and review and review["version"] == IMPORT_VERSION and review["data"] == snapshots["doctor_plans"])
        states = [
            dict(saved=bool(doctors), attention=bool(doctors and not verified),
                 detail=f"{len(doctors)}日分の医師予定" if doctors else "いつものExcelを用意してください"),
            dict(saved=bool(snapshots["monthly_settings"]), attention=False,
                 detail=f"休日日数 {len(monthly.get('targets', {}))}人分 · 有給 {len(leave.get('leaves', {}))}件 · 会議 {len(monthly.get('meetings', []))}件"),
            dict(saved=bool(leave.get("history")), attention=False,
                 detail="前月末勤務の入力"),
            dict(saved=bool(snapshots["coverage_settings"]), attention=False,
                 detail="A・B番は自動表示、C番は1人／2人を指定"),
        ]
    finally:
        db.close()
    cards = [dict(endpoint=step[0], title=step[1], description=step[2], **state)
             for step, state in zip(STEPS, states)]
    next_card = next((card for card in cards if not card["saved"] or card["attention"]), dict(endpoint="input_review",title="入力一覧"))
    year, number = map(int, month.split("-"))
    return render_template("home.html", cards=cards, staff_count=len(staff), manual_saved=manual_saved,
                           next_card=next_card, month=month, generated_saved=bool(generated), generated_stale=generated_stale, manual_stale=manual_stale, help_visits=help_visits,
                           saved_count=sum(card["saved"] for card in cards),
                           month_days=calendar.monthrange(year, number)[1])
