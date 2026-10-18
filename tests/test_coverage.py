import json
import re
import tempfile
import unittest
from pathlib import Path

from app import app, connect_db
from doctor_import import IMPORT_VERSION


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config["DATABASE"]
        app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "db.sqlite3"))
        self.client = app.test_client()
        self.client.get("/coverage?month=2026-10")
        self.plans = {
            "2026-10-01": {"am": ["医師 花子", "医師 次郎"], "pm": ["医師 花子", "医師 次郎", "医師 三郎"]},
            "2026-10-02": {"am": ["医師 花子", "医師 次郎"], "pm": ["医師 花子"]},
            "2026-10-04": {"am": ["医師 花子"], "pm": ["医師 次郎"]},
            "2026-10-05": {"am": ["医師 花子"], "pm": ["医師 花子", "医師 次郎"]},
            "2026-10-12": {"am": ["医師 花子"], "pm": ["医師 花子"]},
            "2026-10-30": {"am": ["医師 花子"], "pm": []},
            "2026-10-31": {"am": [], "pm": []},
        }
        self.monthly = {"closures": {"2026-10-12": "holiday", "2026-10-30": "year_end"},
                        "targets": {"1": "9"}, "wishes": {"1_2026-10-05": "pm"}, "meetings": []}
        db = connect_db()
        encoded = json.dumps(self.plans, ensure_ascii=False)
        db.execute("INSERT INTO doctor_plans VALUES ('2026-10', ?)", (encoded,))
        db.execute("INSERT INTO doctor_plan_reviews VALUES ('2026-10', ?, ?)", (encoded, IMPORT_VERSION))
        db.execute("INSERT INTO monthly_settings VALUES ('2026-10', ?)", (json.dumps(self.monthly),))
        db.commit()
        db.close()
        with self.client.session_transaction() as state:
            self.token = state["csrf_token"]

    def tearDown(self):
        app.config["DATABASE"] = self.old
        self.temp.cleanup()

    def page(self):
        return self.client.get("/coverage?month=2026-10").get_data(as_text=True)

    def payload(self):
        page = self.page()
        values = {
            "csrf_token": self.token,
            "fingerprint": re.search(r'name="fingerprint" value="([^"]+)"', page)[1],
            "c_2026-10-01_am": "1",
            "c_2026-10-02_am": "2",
            "c_2026-10-05_am": "1",
            "c_2026-10-05_pm": "2",
        }
        return values

    def save(self, payload=None):
        return self.client.post("/coverage?month=2026-10", data=payload or self.payload())

    def stored(self):
        db = connect_db()
        try:
            row = db.execute("SELECT data FROM coverage_settings WHERE month='2026-10'").fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def test_rules_for_all_time_slots(self):
        response = self.client.get("/coverage?month=2026-10")
        rows = response.get_data(as_text=True)
        self.assertIn("2026-10-01（木）", rows)
        self.assertIn('name="c_2026-10-01_am"', rows)
        for key in ("2026-10-01_pm", "2026-10-02_pm", "2026-10-04_am", "2026-10-04_pm", "2026-10-12_am", "2026-10-30_am"):
            self.assertNotIn('name="c_' + key + '"', rows)
        self.assertIn("医師0人・診療の有無を確認", rows)
        self.assertIn("医師予定未登録", rows)

    def test_save_reload_and_month_isolation(self):
        self.assertEqual(self.save().status_code, 302)
        saved = self.stored()
        self.assertEqual(saved["2026-10-02_am"]["c"], 2)
        self.assertEqual(saved["2026-10-01_am"]["doctors"], self.plans["2026-10-01"]["am"])
        self.assertIn('value="2" checked', self.page())
        self.assertNotIn('value="2" checked', self.client.get("/coverage?month=2026-11").get_data(as_text=True))
        db = connect_db()
        self.assertEqual(json.loads(db.execute("SELECT data FROM monthly_settings WHERE month='2026-10'").fetchone()[0]), self.monthly)
        self.assertEqual(json.loads(db.execute("SELECT data FROM doctor_plans WHERE month='2026-10'").fetchone()[0]), self.plans)
        db.close()

    def test_invalid_or_missing_choices_never_partially_save(self):
        self.save()
        before = self.stored()
        payload = self.payload()
        payload["c_2026-10-01_am"] = "2"
        payload["c_2026-10-02_am"] = "0"
        self.assertEqual(self.save(payload).status_code, 200)
        self.assertEqual(self.stored(), before)
        payload["c_2026-10-02_am"] = ""
        self.save(payload)
        self.assertEqual(self.stored(), before)

    def test_automatic_and_closed_counts_cannot_be_overridden(self):
        payload = self.payload()
        payload.update({"c_2026-10-01_pm": "1", "c_2026-10-02_pm": "2", "c_2026-10-04_am": "2"})
        self.assertEqual(self.save(payload).status_code, 302)
        for key in ("2026-10-01_pm", "2026-10-02_pm", "2026-10-04_am"):
            self.assertNotIn(key, self.stored())

    def test_stale_page_and_unverified_doctors_rejected(self):
        payload = self.payload()
        db = connect_db()
        changed = dict(self.monthly, closures={})
        db.execute("UPDATE monthly_settings SET data=? WHERE month='2026-10'", (json.dumps(changed),))
        db.commit()
        db.close()
        self.assertIn("別の画面で変更", self.save(payload).get_data(as_text=True))
        self.assertIsNone(self.stored())
        db = connect_db()
        db.execute("DELETE FROM doctor_plan_reviews")
        db.commit()
        db.close()
        self.assertIn("最新の内容を確認", self.save().get_data(as_text=True))
        self.assertIsNone(self.stored())

    def test_changed_doctors_require_c_to_be_selected_again(self):
        self.save()
        db = connect_db()
        changed = dict(self.plans)
        changed["2026-10-01"] = {"am": ["医師 三郎"], "pm": self.plans["2026-10-01"]["pm"]}
        raw = json.dumps(changed, ensure_ascii=False)
        db.execute("UPDATE doctor_plans SET data=? WHERE month='2026-10'", (raw,))
        db.execute("UPDATE doctor_plan_reviews SET data=? WHERE month='2026-10'", (raw,))
        db.commit()
        db.close()
        self.assertIn("医師予定が変わったため、再指定", self.page())

    def test_csrf_and_invalid_month(self):
        self.assertEqual(self.client.post("/coverage?month=2026-10", data={}).status_code, 400)
        self.assertEqual(self.client.get("/coverage?month=2026-13").status_code, 400)
        self.assertEqual(self.client.get("/coverage?month=2028-02").status_code, 200)
