import json
import re
import unittest
import test_monthly as fixtures
from app import connect_db


class MeetingAttendanceTest(unittest.TestCase):
    setUp=fixtures.MonthlyTest.setUp
    tearDown=fixtures.MonthlyTest.tearDown
    post=fixtures.MonthlyTest.post

    def settings(self):
        db=connect_db()
        row=db.execute("SELECT data FROM monthly_settings WHERE month='2026-10'").fetchone()
        result=json.loads(row[0]) if row else None
        db.close()
        return result

    def save(self,selected,day="2026-10-02",person="1",fingerprint=None):
        page=self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        fp=fingerprint or re.search('name="settings_fingerprint" value="([^"]+)"',page)[1]
        return self.post(action="meeting_attendance",settings_fingerprint=fp,
            attendance_day=day,attendance_staff=person,attendance=selected)

    def seed(self):
        self.post(action="meeting_add",meeting_date="2026-10-02",title="仮名会議",participants="1")
        return self.settings()["meetings"][0]["id"]

    def test_cell_add_remove_and_repeat_preserve_other_participants(self):
        key="saved:"+self.seed()
        db=connect_db()
        db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('仮名次郎','nurse','full',0)")
        db.commit();db.close()
        self.assertEqual(self.save([key],person="2").status_code,302)
        self.assertEqual(self.settings()["meetings"][0]["participants"],["1","2"])
        self.assertEqual(self.save([key],person="2").status_code,302)
        self.assertEqual(self.settings()["meetings"][0]["participants"],["1","2"])
        self.assertEqual(self.save([],person="2").status_code,302)
        self.assertEqual(self.settings()["meetings"][0]["participants"],["1"])

    def test_candidate_registers_only_selected_meeting_and_person(self):
        self.client.get("/monthly?month=2026-10")
        db=connect_db()
        db.execute("INSERT INTO excel_event_drafts VALUES ('test','2026-10',?)",(json.dumps(dict(extras=dict(closures=[],meetings=[dict(id="new",date="2026-10-02",title="仮名研修",source="test")]))),))
        db.commit();db.close()
        self.assertEqual(self.save(["excel:new"]).status_code,302)
        value=self.settings()["meetings"]
        self.assertEqual(len(value),1)
        self.assertEqual(value[0]["participants"],["1"])
        self.assertEqual(value[0]["import_source"],"new")
        self.assertEqual(value[0]["title"],"仮名研修")

    def test_stale_or_wrong_day_cannot_overwrite(self):
        key="saved:"+self.seed()
        page=self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        fp=re.search('name="settings_fingerprint" value="([^"]+)"',page)[1]
        self.save([])
        before=self.settings()
        self.assertIn("別の画面",self.save([key],fingerprint=fp).get_data(as_text=True))
        self.assertEqual(self.settings(),before)
        self.save([key],day="2026-10-03")
        self.assertEqual(self.settings(),before)

    def test_overlap_is_rejected_without_partial_changes(self):
        first=self.seed()
        db=connect_db()
        data=self.settings()
        data["meetings"].append(dict(id="other",date="2026-10-02",title="別会議",participants=[],start="",end=""))
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(data),));db.commit();db.close()
        before=self.settings()
        self.save(["saved:"+first,"saved:other"])
        self.assertEqual(self.settings(),before)

    def test_grid_uses_editable_empty_cells_and_full_meeting_names(self):
        self.seed()
        page=self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        self.assertIn('data-attendance-person="1"',page)
        self.assertIn('id="meeting-attendance-dialog"',page)
        self.assertIn('class="input-day-meeting-title"',page)
        self.assertIn("仮名会議",page)
        self.assertNotIn('class="input-meeting-agenda"',page)
        self.assertIn('--input-sheet-days:31',page)
