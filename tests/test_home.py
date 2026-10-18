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

    def test_home_does_not_claim_generation_is_available(self):
        page = self.client.get("/?month=2026-10")
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn("2026年10月の勤務表", text)
        self.assertIn("0/4項目に保存あり", text)
        self.assertIn("スタッフを登録する", text)
        self.assertIn("自動作成・結果の確認・印刷は準備中", text)
        self.assertIn('button disabled aria-describedby="creation-note"', text)
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

    def test_navigation_keeps_selected_month_and_invalid_month_is_rejected(self):
        self.client.get("/?month=2027-02")
        page = self.client.get("/staff").get_data(as_text=True)
        self.assertIn('value="2027-02"', page)
        self.assertIn("/doctors?month=2027-02", page)
        self.assertEqual(self.client.get("/?month=2026-13").status_code, 400)
