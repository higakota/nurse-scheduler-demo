import json
import tempfile
import unittest
from pathlib import Path

from app import app, connect_db
from doctor_import import IMPORT_VERSION


class HomeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config["DATABASE"]
        app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "db.sqlite3"))
        self.client = app.test_client()

    def tearDown(self):
        app.config["DATABASE"] = self.old
        self.temp.cleanup()

    def test_home_links_to_generation_without_creating_input_data(self):
        page = self.client.get("/?month=2026-10")
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn("2026年10月の勤務表", text)
        self.assertIn("0/4項目に保存あり", text)
        self.assertIn("スタッフを登録する", text)
        self.assertIn("確定機能は未実装", text)
        self.assertIn("/schedule?month=2026-10", text)
        db = connect_db()
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        db.close()
        self.assertEqual(tables, ["staff"])

    def test_saved_doctors_need_current_review_before_showing_normal_status(self):
        self.client.get("/")
        db = connect_db()
        db.execute("CREATE TABLE doctor_plans(month TEXT PRIMARY KEY,data TEXT)")
        db.execute("CREATE TABLE doctor_plan_reviews(month TEXT PRIMARY KEY,data TEXT,version INTEGER)")
        raw = json.dumps({"2026-10-01": {"am": ["医師 花子"], "pm": []}})
        db.execute("INSERT INTO doctor_plans VALUES ('2026-10',?)", (raw,))
        db.commit()
        page = self.client.get("/?month=2026-10").get_data(as_text=True)
        self.assertIn("再確認が必要", page)
        self.assertIn("1日分の医師予定", page)
        db.execute("INSERT INTO doctor_plan_reviews VALUES ('2026-10',?,?)", (raw, IMPORT_VERSION))
        db.commit()
        db.close()
        page = self.client.get("/?month=2026-10").get_data(as_text=True)
        self.assertNotIn("再確認が必要", page)
        self.assertIn("1/4項目に保存あり", page)

    def test_paid_leave_record_does_not_claim_history_was_entered(self):
        self.client.get("/")
        db=connect_db()
        db.execute("CREATE TABLE leave_history(month TEXT PRIMARY KEY,data TEXT)")
        db.execute("INSERT INTO leave_history VALUES ('2026-11',?)",(json.dumps({"leaves":{"1_2026-11-02":"full"},"history":{}}),))
        db.commit()
        before=list(db.iterdump())
        text=self.client.get("/?month=2026-11").get_data(as_text=True)
        self.assertIn("0/4項目に保存あり",text)
        self.assertIn("自動作成結果",text)
        self.assertIn("手動下書き",text)
        self.assertEqual(before,list(db.iterdump()))
        db.close()

    def test_navigation_keeps_selected_month_and_invalid_month_is_rejected(self):
        self.client.get("/?month=2027-02")
        page = self.client.get("/staff").get_data(as_text=True)
        self.assertIn('value="2027-02"', page)
        self.assertIn("/monthly?month=2027-02", page)
        self.assertEqual(self.client.get("/?month=2026-13").status_code, 400)

class NavigationTest(unittest.TestCase):
    setUp=HomeTest.setUp
    tearDown=HomeTest.tearDown
    def test_menu_groups_inputs_and_editing_and_keeps_month(self):
        page=self.client.get("/inputs?month=2026-11").get_data(as_text=True)
        sidebar=page.split('<nav class="side-nav">',1)[1].split("</nav>",1)[0]
        self.assertEqual(sidebar.count("<a "),5)
        self.assertIn("今月の入力",sidebar)
        self.assertNotIn("勤務表の手動修正",sidebar)
        self.assertIn('/doctors?month=2026-11',page)
        self.assertIn('月をまたぐ週',page)
        self.assertIn('入力一覧',page)
        edit=self.client.get("/schedule/manual?month=2026-11").get_data(as_text=True)
        self.assertIn('編集・印刷',edit)
        self.assertIn('/schedule?month=2026-11',edit)
        self.assertNotIn('準備の前後へ',edit)
