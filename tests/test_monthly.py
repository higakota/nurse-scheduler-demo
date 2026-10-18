import json
import tempfile
import unittest
from pathlib import Path
from app import app, connect_db


class MonthlyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config["DATABASE"]
        app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "test.sqlite3"))
        self.client = app.test_client()
        self.client.get("/monthly?month=2026-10")
        with self.client.session_transaction() as s:
            self.token = s["csrf_token"]
        db = connect_db()
        db.execute("INSERT INTO staff(name, role, employment, veteran) VALUES ('看護 花子', 'nurse', 'full', 1)")
        db.commit()
        db.close()

    def tearDown(self):
        app.config["DATABASE"] = self.old
        self.temp.cleanup()

    def post(self, **data):
        return self.client.post("/monthly?month=2026-10", data=dict(csrf_token=self.token, **data))

    def stored(self):
        db = connect_db()
        try:
            row = db.execute("SELECT data FROM monthly_settings WHERE month='2026-10'").fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def test_save_reload_month_isolation(self):
        response = self.post(action="settings", target_1="9.5", **{"wish_1_2026-10-20": "pm", "closure_2026-10-12": "holiday"})
        self.assertEqual(response.status_code, 302)
        data = self.stored()
        self.assertEqual(data["targets"]["1"], "9.5")
        self.assertEqual(data["wishes"]["1_2026-10-20"], "pm")
        self.assertIn('value="9.5"', self.client.get("/monthly?month=2026-10").get_data(as_text=True))
        self.assertNotIn('value="9.5"', self.client.get("/monthly?month=2026-11").get_data(as_text=True))

    def test_meeting_preserves_wish_and_warns(self):
        self.post(action="settings", **{"wish_1_2026-10-20": "pm"})
        self.assertEqual(self.post(action="meeting_add", meeting_date="2026-10-20", title="院内会議", participants="1").status_code, 302)
        self.assertIn("入力の見直しが必要", self.client.get("/monthly?month=2026-10").get_data(as_text=True))
        self.assertEqual(self.stored()["wishes"]["1_2026-10-20"], "pm")
        meeting = self.stored()["meetings"][0]
        self.post(action="meeting_delete", meeting_id=meeting["id"])
        self.assertEqual(self.stored()["meetings"], [])

    def test_no_meeting_on_closed_days(self):
        self.post(action="settings", **{"closure_2026-10-12": "holiday", "closure_2026-10-30": "year_end"})
        for day in ("2026-10-04", "2026-10-12", "2026-10-30", "2026-11-01"):
            self.assertEqual(self.post(action="meeting_add", meeting_date=day, title="会議", participants="1").status_code, 200)
            self.assertEqual(self.stored()["meetings"], [])
        self.assertEqual(self.post(action="meeting_add", meeting_date="2026-10-09", title="金曜会議", participants="1").status_code, 302)

    def test_invalid_values_do_not_replace_saved_data(self):
        self.post(action="settings", target_1="10")
        for value in ("-1", "32", "0.3", "NaN", "Infinity"):
            self.post(action="settings", target_1=value)
            self.assertEqual(self.stored()["targets"]["1"], "10")
        self.assertEqual(self.client.post("/monthly?month=2026-10", data={"action": "settings"}).status_code, 400)
        for month in ("2026-13", "2026-00", "bad"):
            self.assertEqual(self.client.get("/monthly?month=" + month).status_code, 400)

    def test_closing_day_does_not_remove_existing_meeting(self):
        self.post(action="meeting_add", meeting_date="2026-10-20", title="会議", participants="1")
        self.post(action="settings", **{"closure_2026-10-20": "holiday"})
        self.assertEqual(len(self.stored()["meetings"]), 1)
        self.assertIn("休診日に会議があります", self.client.get("/monthly?month=2026-10").get_data(as_text=True))

    def test_leap_year(self):
        page = self.client.get("/monthly?month=2028-02").get_data(as_text=True)
        self.assertIn("2028-02-29", page)
        self.assertNotIn("2028-02-30", page)
