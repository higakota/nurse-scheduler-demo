import json
import re
import unittest
import test_staff as helpers
from app import connect_db
from help_availability import available_help


class HelpAvailabilityTest(unittest.TestCase):
    setUp = helpers.StaffSettingsTest.setUp
    tearDown = helpers.StaffSettingsTest.tearDown
    save_staff = helpers.StaffSettingsTest.save

    def load(self):
        text = self.client.get("/help?month=2026-10").get_data(as_text=True)
        return re.search(r'name="fingerprint" value="([^"]+)"', text)[1]

    def post(self, changes, fingerprint=None, **extra):
        return self.client.post("/help?month=2026-10", data=dict(csrf_token=self.token,
            fingerprint=fingerprint or self.load(), changes=json.dumps(changes), **extra))

    def stored(self):
        db = connect_db()
        try:
            row = db.execute("SELECT data FROM help_availability WHERE month='2026-10'").fetchone()
            return json.loads(row[0]) if row else {}
        finally:
            db.close()

    def test_registration_alone_has_no_available_days(self):
        self.save_staff(is_help="1", allowed_areas=["A","C"])
        db = connect_db()
        try:
            self.assertEqual(available_help(db, "2026-10", "2026-10-20", "am", "A"), [])
        finally:
            db.close()
        self.assertEqual(self.stored(), {})

    def test_save_limits_dates_halves_and_areas(self):
        self.save_staff(is_help="1", allowed_areas=["A","C"])
        self.assertEqual(self.post({"1_2026-10-20":"am", "1_2026-10-21":"full"}, staff="1").status_code,302)
        db = connect_db()
        try:
            self.assertEqual(len(available_help(db, "2026-10", "2026-10-20", "am", "A")),1)
            self.assertEqual(available_help(db, "2026-10", "2026-10-20", "pm", "A"),[])
            self.assertEqual(len(available_help(db, "2026-10", "2026-10-20", "am", "B")),1)
            self.assertEqual(available_help(db, "2026-10", "2026-10-22", "am", "A"),[])
        finally:
            db.close()
        self.post({"1_2026-10-20":""})
        self.assertEqual(self.stored(), {"1_2026-10-21":"full"})

    def test_invalid_patch_rolls_back_all_changes(self):
        self.save_staff(is_help="1", allowed_areas=["A"])
        self.post({"1_2026-10-20":"am"})
        before = self.stored()
        for key, value in [("1_2026-11-01","full"),("1_2026-10-18","am"),("99_2026-10-20","pm"),("1_2026-10-21","bad")]:
            response = self.post({"1_2026-10-20":"pm", key:value})
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.stored(),before)
        self.assertEqual(self.client.post("/help?month=2026-10",data={}).status_code,400)

    def test_nonhelp_cannot_be_registered_as_help_visit(self):
        self.save_staff()
        self.client.get("/help?month=2026-10")
        db = connect_db()
        try:
            from help_availability import load_help
            _,_,_,fingerprint = load_help(db,"2026-10")
        finally:
            db.close()
        response = self.post({"1_2026-10-20":"full"},fingerprint)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.stored(),{})

    def test_stale_form_and_closure_changes(self):
        self.save_staff(is_help="1",allowed_areas=["A"])
        fingerprint = self.load()
        self.post({"1_2026-10-20":"full"})
        self.assertIn("別の画面",self.post({"1_2026-10-21":"am"},fingerprint).get_data(as_text=True))
        db=connect_db()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS monthly_settings(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            payload={"targets":{"1":"9"},"wishes":{},"closures":{"2026-10-20":"holiday"},"meetings":[]}
            db.execute("INSERT INTO monthly_settings VALUES (?,?)",("2026-10",json.dumps(payload)))
            db.commit()
            self.assertEqual(available_help(db,"2026-10","2026-10-20","am","A"),[])
        finally:
            db.close()
        self.assertIn("元の予定は維持",self.client.get("/help?month=2026-10").get_data(as_text=True))
        self.post({"1_2026-10-20":""})
        self.assertEqual(self.stored(),{})

    def test_calendar_month_lengths_and_multiple_helpers(self):
        self.save_staff(is_help="1",allowed_areas=["A"])
        self.save_staff(name="看護 次郎",is_help="1",allowed_areas=["B"])
        self.assertEqual(self.post({"1_2026-10-20":"am","2_2026-10-21":"pm"}).status_code,302)
        self.assertEqual(len(self.stored()),2)
        for month, days in [("2026-10",31),("2028-02",29)]:
            text=self.client.get("/help?month="+month).get_data(as_text=True)
            self.assertEqual(text.count('data-help-day="'),days)
        self.assertEqual(self.client.get("/help?month=2026-13").status_code,400)

    def test_friday_pm_excluded_from_clinical_candidates(self):
        self.save_staff(is_help="1",allowed_areas=["A"])
        self.post({"1_2026-10-23":"full"})
        db=connect_db()
        try:
            self.assertEqual(available_help(db,"2026-10","2026-10-23","pm","A"),[])
            self.assertEqual(len(available_help(db,"2026-10","2026-10-23","am","A")),1)
        finally:
            db.close()
