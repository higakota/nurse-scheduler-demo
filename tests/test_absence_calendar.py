import json
import re
import test_monthly as helpers
import unittest
from app import connect_db


class AbsenceCalendarTest(unittest.TestCase):
    setUp = helpers.MonthlyTest.setUp
    tearDown = helpers.MonthlyTest.tearDown
    post = helpers.MonthlyTest.post

    def snapshot(self):
        db = connect_db()
        try:
            result = []
            for table in ("monthly_settings", "leave_history"):
                row = db.execute("SELECT data FROM " + table + " WHERE month='2026-10'").fetchone()
                result.append(json.loads(row[0]) if row else None)
            return result
        finally:
            db.close()

    def page_token(self):
        text = self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        return re.search(r'name="absence_fingerprint" value="([^"]+)"', text)[1]

    def save(self, changes, token=None):
        return self.post(action="absence_save", absence_changes=json.dumps(changes),
                         absence_fingerprint=token or self.page_token())

    def test_combined_save_and_preservation(self):
        self.post(action="settings", target_1="9", **{"closure_2026-10-12":"holiday", "wish_1_2026-10-21":"am"})
        db = connect_db()
        db.execute("INSERT INTO leave_history VALUES (?,?)", ("2026-10", json.dumps({"leaves":{"1_2026-10-22":"full"}, "history":{"1_2026-09-30":"full"}})))
        db.commit()
        db.close()
        response = self.save({"wishes":{"1_2026-10-19":"pm"}, "leaves":{"1_2026-10-20":"am"}})
        self.assertEqual(response.status_code, 302)
        monthly, leave = self.snapshot()
        self.assertEqual(monthly["wishes"], {"1_2026-10-21":"am", "1_2026-10-19":"pm"})
        self.assertEqual(monthly["targets"], {"1":"9"})
        self.assertEqual(monthly["closures"], {"2026-10-12":"holiday"})
        self.assertEqual(leave["leaves"], {"1_2026-10-22":"full", "1_2026-10-20":"am"})
        self.assertEqual(leave["history"], {"1_2026-09-30":"full"})

    def test_overlap_keeps_both_and_warns(self):
        self.save({"wishes":{"1_2026-10-20":"am"}, "leaves":{"1_2026-10-20":"am"}})
        monthly, leave = self.snapshot()
        self.assertEqual(monthly["wishes"]["1_2026-10-20"], "am")
        self.assertEqual(leave["leaves"]["1_2026-10-20"], "am")
        text = self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        self.assertIn("通常の希望休と有給が重なっています", text)
        self.save({"wishes":{}, "leaves":{"1_2026-10-20":""}})
        self.assertIn("1_2026-10-20", self.snapshot()[0]["wishes"])
        self.assertEqual(self.snapshot()[1]["leaves"], {})

    def test_invalid_paid_patch_rolls_back_wishes(self):
        before = self.snapshot()
        for key, period in [("1_2026-11-01","full"), ("99_2026-10-20","am"), ("1_2026-10-20","bad")]:
            response = self.save({"wishes":{"1_2026-10-19":"full"}, "leaves":{key:period}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.snapshot(), before)

    def test_stale_form_is_rejected(self):
        token = self.page_token()
        self.save({"wishes":{"1_2026-10-19":"full"}, "leaves":{}})
        before = self.snapshot()
        response = self.save({"wishes":{}, "leaves":{"1_2026-10-20":"am"}}, token)
        self.assertIn("別の画面で入力が変更", response.get_data(as_text=True))
        self.assertEqual(self.snapshot(), before)

    def test_settings_does_not_remove_calendar_wishes(self):
        self.save({"wishes":{"1_2026-10-19":"pm"}, "leaves":{}})
        self.post(action="settings", preserve_wishes="yes", target_1="10")
        self.assertEqual(self.snapshot()[0]["wishes"], {"1_2026-10-19":"pm"})

    def test_calendar_month_lengths_and_single_editor(self):
        for month, length in [("2026-10",31),("2028-02",29),("2026-02",28)]:
            text = self.client.get("/monthly?month=" + month).get_data(as_text=True)
            self.assertEqual(text.count('data-absence-day="'), length)
            self.assertIn("希望休・有給をまとめて保存", text)
        text = self.client.get("/leave-history?month=2026-10").get_data(as_text=True)
        self.assertNotIn('class="leave-entry', text)
        self.assertIn("/monthly?month=2026-10", text)

    def test_multiple_staff_and_staff_selection_survive_save(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name, role, employment, veteran) VALUES ('看護 太郎', 'nurse', 'part', 0)")
        db.commit()
        db.close()
        response = self.post(action="absence_save", absence_staff="2", absence_fingerprint=self.page_token(),
                             absence_changes=json.dumps({"wishes":{"1_2026-10-19":"am", "2_2026-10-20":"full"}, "leaves":{"2_2026-10-21":"pm"}}))
        self.assertEqual(response.status_code, 302)
        text = self.client.get(response.location).get_data(as_text=True)
        self.assertIn('value="2" selected', text)
        self.assertEqual(self.snapshot()[1]["leaves"]["2_2026-10-21"], "pm")
        self.assertEqual(self.snapshot()[0]["wishes"]["1_2026-10-19"], "am")
