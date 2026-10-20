import json
import unittest
import test_staff as staff_helpers
import test_monthly as monthly_helpers
from app import connect_db
from meeting_rules import checked_times, check_meeting_overlap


class HelpStaffTest(unittest.TestCase):
    setUp = staff_helpers.StaffSettingsTest.setUp
    tearDown = staff_helpers.StaffSettingsTest.tearDown
    save = staff_helpers.StaffSettingsTest.save
    rows = staff_helpers.StaffSettingsTest.rows

    def test_help_areas_and_hours_persist(self):
        response = self.save(is_help="1", employment="", allowed_areas=["A","C"])
        self.assertEqual(response.status_code, 302)
        row = self.rows()[0]
        self.assertEqual((row["allowed_areas"], row["is_help"], row["employment"]), ("ABC",1,"full"))
        self.assertIn("他院ヘルプ", self.client.get("/staff").get_data(as_text=True))
        self.save(id=str(row["id"]), is_help="1", allowed_areas=["B"])
        self.assertEqual(self.rows()[0]["allowed_areas"], "ABC")

    def test_help_needs_no_area_selection_and_ignores_old_form_values(self):
        self.assertEqual(self.save(is_help="1").status_code, 302)
        self.assertEqual(self.save(is_help="1", allowed_areas=["Z"]).status_code, 302)
        self.assertTrue(all(row["allowed_areas"] == "ABC" for row in self.rows()))
        self.assertNotIn('id="help-areas"', self.client.get("/staff").get_data(as_text=True))

    def test_existing_help_restrictions_are_updated_without_losing_visits(self):
        self.save(is_help="1")
        db = connect_db()
        try:
            db.execute("UPDATE staff SET allowed_areas='AC' WHERE id=1")
            db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("INSERT INTO help_availability VALUES (?,?)", ("2026-10", '{"1_2026-10-20":"am"}'))
            db.commit()
        finally:
            db.close()
        self.assertEqual(self.rows()[0]["allowed_areas"], "ABC")
        db = connect_db()
        try:
            self.assertEqual(json.loads(db.execute("SELECT data FROM help_availability").fetchone()[0]), {"1_2026-10-20":"am"})
        finally:
            db.close()

    def test_regular_and_technician_keep_fixed_areas(self):
        self.save(allowed_areas=["A"])
        self.save(role="technician", is_help="1", allowed_areas=["A","B","C"], veteran="1")
        rows = self.rows()
        self.assertEqual(rows[0]["allowed_areas"], "ABC")
        self.assertEqual((rows[1]["allowed_areas"], rows[1]["veteran"]), ("C",0))


class MeetingTimeTest(unittest.TestCase):
    setUp = monthly_helpers.MonthlyTest.setUp
    tearDown = monthly_helpers.MonthlyTest.tearDown
    post = monthly_helpers.MonthlyTest.post
    stored = monthly_helpers.MonthlyTest.stored

    def add(self, start, end):
        return self.post(action="meeting_add", meeting_date="2026-10-20", title="会議", participants="1", start=start, end=end)

    def test_nonoverlap_allowed_overlap_rejected(self):
        self.assertEqual(self.add("13:30","14:30").status_code, 302)
        self.assertEqual(self.add("14:30","15:00").status_code, 302)
        response = self.add("14:00","15:30")
        self.assertIn("時間が重なっています", response.get_data(as_text=True))
        self.assertEqual(len(self.stored()["meetings"]), 2)

    def test_invalid_time_and_legacy_time_update(self):
        self.assertEqual(self.add("14:00","13:00").status_code, 200)
        self.assertEqual(self.add("09:00","10:00").status_code, 200)
        self.assertIsNone(self.stored())
        self.add("","")
        self.assertEqual(self.add("14:00","15:00").status_code, 200)
        meeting_id = self.stored()["meetings"][0]["id"]
        self.assertEqual(self.post(action="meeting_time", meeting_id=meeting_id, start="13:00", end="14:00").status_code,302)
        self.assertEqual(self.add("14:00","15:00").status_code, 302)

    def test_separate_people_can_overlap(self):
        old = {"id":"a", "date":"2026-10-20", "participants":["1"], "start":"13:00", "end":"15:00"}
        check_meeting_overlap([old], dict(old, id="b", participants=["2"]))
        with self.assertRaises(ValueError):
            checked_times("13:00","")
