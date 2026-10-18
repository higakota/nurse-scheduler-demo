import json
import re
import tempfile
import unittest
from pathlib import Path

from app import app, connect_db
from leave_and_history import trailing_full_days


class LeaveHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config["DATABASE"]
        app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "db.sqlite3"))
        self.client = app.test_client()
        self.client.get("/leave-history?month=2026-10")
        db = connect_db()
        db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('看護 花子','nurse','full',1)")
        db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('検査 次郎','technician','',0)")
        monthly = {"targets": {"1": "9"}, "wishes": {"1_2026-10-20": "pm"},
                   "closures": {"2026-10-12": "holiday"},
                   "meetings": [{"date": "2026-10-20", "participants": ["1"], "title": "会議"}]}
        db.execute("INSERT INTO monthly_settings VALUES ('2026-10',?)", (json.dumps(monthly),))
        db.commit()
        db.close()
        self.monthly = monthly
        with self.client.session_transaction() as state:
            self.token = state["csrf_token"]

    def tearDown(self):
        app.config["DATABASE"] = self.old
        self.temp.cleanup()

    def payload(self, **values):
        page = self.client.get("/leave-history?month=2026-10").get_data(as_text=True)
        return dict(csrf_token=self.token, fingerprint=re.search(r'name="fingerprint" value="([^"]+)"', page)[1], **values)

    def post(self, **values):
        return self.client.post("/leave-history?month=2026-10", data=self.payload(**values))

    def stored(self):
        db = connect_db()
        try:
            row = db.execute("SELECT data FROM leave_history WHERE month='2026-10'").fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def test_paid_leave_save_edit_delete_and_totals(self):
        self.assertEqual(self.post(action="leave_save", staff="1", day="2026-10-20", period="full").status_code, 302)
        self.assertEqual(self.stored()["leaves"]["1_2026-10-20"], "full")
        self.post(action="leave_save", staff="1", day="2026-10-20", period="am")
        self.assertEqual(self.stored()["leaves"]["1_2026-10-20"], "am")
        page = self.client.get("/leave-history?month=2026-10").get_data(as_text=True)
        self.assertIn("看護 花子：0.5日", page)
        edit = self.client.get("/leave-history?month=2026-10&staff=1&day=2026-10-20").get_data(as_text=True)
        self.assertIn('data-period="am" aria-pressed="true"', edit)
        self.post(action="leave_delete", key="1_2026-10-20")
        self.assertEqual(self.stored()["leaves"], {})

    def test_wishes_preserved_and_conflicts_visible_on_both_pages(self):
        self.post(action="leave_save", staff="1", day="2026-10-20", period="pm")
        page = self.client.get("/leave-history?month=2026-10").get_data(as_text=True)
        self.assertIn("通常の希望休と有給が重なっています", page)
        self.assertIn("有給と午後の会議参加が重なっています", page)
        self.assertIn("有給と午後の会議参加が重なっています", self.client.get("/monthly?month=2026-10").get_data(as_text=True))
        db = connect_db()
        self.assertEqual(json.loads(db.execute("SELECT data FROM monthly_settings WHERE month='2026-10'").fetchone()[0]), self.monthly)
        db.close()

    def test_holiday_and_unconfirmed_combination_are_not_silently_aggregated(self):
        self.post(action="leave_save", staff="1", day="2026-10-12", period="full")
        self.post(action="leave_save", staff="1", day="2026-10-20", period="am")
        page = self.client.get("/leave-history?month=2026-10").get_data(as_text=True)
        self.assertIn("休診日と有給が重なっています", page)
        self.assertIn("半日有給と半日通常休み", page)

    def test_invalid_input_and_concurrent_changes_do_not_write(self):
        for fields in (dict(staff="999", day="2026-10-20", period="am"),
                       dict(staff="1", day="2026-11-01", period="full"),
                       dict(staff="1", day="2026-10-20", period="invalid")):
            self.post(action="leave_save", **fields)
            self.assertIsNone(self.stored())
        stale = self.payload(action="leave_save", staff="1", day="2026-10-20", period="am")
        self.post(action="leave_save", staff="1", day="2026-10-21", period="pm")
        response = self.client.post("/leave-history?month=2026-10", data=stale)
        self.assertIn("別の画面で入力が変更", response.get_data(as_text=True))
        self.assertNotIn("1_2026-10-20", self.stored()["leaves"])
        self.assertEqual(self.client.post("/leave-history?month=2026-10", data={}).status_code, 400)

    def test_history_save_unknown_is_not_rest_and_paid_resets_tail(self):
        fields = {"history_1_2026-09-28": "full", "history_1_2026-09-29": "full", "history_1_2026-09-30": "full"}
        self.assertEqual(self.post(action="history_save", **fields).status_code, 302)
        self.assertEqual(self.stored()["history"]["1_2026-09-26"], "")
        self.assertEqual(self.stored()["history"]["1_2026-09-27"], "rest")
        self.assertIn("3日", self.client.get("/leave-history?month=2026-10").get_data(as_text=True))
        for code in ("paid", "am_paid", "pm_paid"):
            fields["history_1_2026-09-30"] = code
            self.post(action="history_save", **fields)
            self.assertEqual(self.stored()["history"]["1_2026-09-30"], code)
            self.assertEqual(trailing_full_days(["full", "full", code]), 0)
        self.assertIsNone(trailing_full_days(["rest", "", "full"]))
        self.assertEqual(trailing_full_days(["", "", "rest", "full"]), 1)
        self.assertEqual(trailing_full_days(["full"] * 5), 5)

    def test_closed_history_and_technician_afternoon_are_rejected(self):
        self.post(action="history_save", **{"history_1_2026-09-27": "full"})
        self.assertIsNone(self.stored())
        self.post(action="history_save", **{"history_2_2026-09-30": "pm"})
        self.assertIsNone(self.stored())
        self.post(action="history_save", **{"history_2_2026-09-30": "am_paid"})
        self.assertIsNone(self.stored())
        db = connect_db()
        db.execute("INSERT INTO monthly_settings VALUES ('2026-09',?)", (json.dumps({"closures": {"2026-09-30": "holiday"}}),))
        db.commit()
        db.close()
        self.post(action="history_save", **{"history_1_2026-09-30": "full"})
        self.assertIsNone(self.stored())

    def test_month_boundary_and_month_isolation(self):
        self.post(action="leave_save", staff="1", day="2026-10-20", period="pm")
        page = self.client.get("/leave-history?month=2027-01").get_data(as_text=True)
        self.assertIn("2026-12-27", page)
        self.assertIn("2026-12-31", page)
        self.assertNotIn("2026-10-20（", page)
        page = self.client.get("/leave-history?month=2028-03").get_data(as_text=True)
        self.assertIn("2028-02-29", page)
        self.assertEqual(self.client.get("/leave-history?month=2026-13").status_code, 400)

    def test_later_closure_does_not_silently_erase_saved_history(self):
        self.post(action="history_save", **{"history_1_2026-09-30": "full"})
        db = connect_db()
        db.execute("INSERT INTO monthly_settings VALUES ('2026-09',?)", (json.dumps({"closures": {"2026-09-30": "holiday"}}),))
        db.commit()
        db.close()
        page = self.client.get("/leave-history?month=2026-10").get_data(as_text=True)
        self.assertIn("登録済みの前月末勤務と休診指定が重なっています", page)
        self.assertEqual(self.stored()["history"]["1_2026-09-30"], "full")

    def test_calendar_bulk_save_only_changes_selected_days(self):
        self.post(action="leave_save", staff="1", day="2026-10-19", period="am")
        self.post(action="history_save", **{"history_1_2026-09-30": "paid"})
        patch = {"1_2026-10-20": "full", "1_2026-10-21": "pm", "2_2026-10-22": "am"}
        response = self.post(action="leave_bulk_save", staff="1", leave_changes=json.dumps(patch))
        self.assertEqual(response.status_code, 302)
        data = self.stored()
        self.assertEqual(data["leaves"]["1_2026-10-19"], "am")
        for key, value in patch.items():
            self.assertEqual(data["leaves"][key], value)
        self.assertNotIn("1_2026-10-23", data["leaves"])
        self.assertEqual(data["history"]["1_2026-09-30"], "paid")
        self.post(action="leave_bulk_save", staff="1", leave_changes=json.dumps({"1_2026-10-20": ""}))
        self.assertNotIn("1_2026-10-20", self.stored()["leaves"])
        self.assertEqual(self.stored()["leaves"]["1_2026-10-21"], "pm")

    def test_invalid_bulk_patch_is_atomic(self):
        self.post(action="leave_save", staff="1", day="2026-10-19", period="am")
        before = self.stored()
        for patch in ({"1_2026-10-20": "full", "1_2026-11-01": "pm"},
                      {"999_2026-10-20": "full"}, {"1_2026-10-20": "invalid"},
                      {"1_2026-10-20": {"period": "full"}}, ["full"]):
            self.post(action="leave_bulk_save", staff="1", leave_changes=json.dumps(patch))
            self.assertEqual(self.stored(), before)
        self.post(action="leave_bulk_save", staff="1", leave_changes="not json")
        self.assertEqual(self.stored(), before)

    def test_bulk_save_rejects_stale_page(self):
        old = self.payload(action="leave_bulk_save", staff="1",
                           leave_changes=json.dumps({"1_2026-10-20": "full"}))
        self.post(action="leave_save", staff="2", day="2026-10-21", period="am")
        response = self.client.post("/leave-history?month=2026-10", data=old)
        self.assertIn("別の画面で入力が変更", response.get_data(as_text=True))
        self.assertNotIn("1_2026-10-20", self.stored()["leaves"])
