import json
import unittest
import test_manual_schedule as manual
from manual_schedule import align_helper_rows


class OperationOrderTest(unittest.TestCase):
    setUp = manual.ManualScheduleTest.setUp
    tearDown = manual.ManualScheduleTest.tearDown
    fields = manual.ManualScheduleTest.fields
    post = manual.ManualScheduleTest.post

    def test_staff_edit_after_draft_refreshes_metadata_without_changing_grid(self):
        fields = self.fields()
        self.post(fields, "preview", {"1_0": "DD"})
        self.assertEqual(self.post(fields, "save", {"1_0": "DD"}).status_code, 303)
        before = json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.db.execute("UPDATE staff SET name='仮名更新',allowed_areas='AB',veteran=0 WHERE id=1")
        self.db.commit()
        page = self.client.get("/schedule/manual?month=2026-11").get_data(as_text=True)
        self.assertIn("仮名更新", page)
        self.assertNotIn('"allowed_areas": "ABC"', page)
        fields = self.fields()
        self.post(fields, "preview", {})
        self.assertEqual(self.post(fields, "save", {}).status_code, 303)
        saved = json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(saved["people"][0]["allowed_areas"], "AB")
        self.assertEqual(saved["people"][0]["veteran"], 0)
        self.assertEqual(saved["grid"], before["grid"])
        self.assertEqual(saved["history"], before["history"])

    def test_repeated_paid_edit_save_reload_and_duplicate_submission(self):
        for pair, expected in (("PP", "full"), ("PD", "am"), ("DP", "pm"), ("DD", None)):
            fields = self.fields()
            patch = {"1_0": pair}
            self.post(fields, "preview", patch)
            self.assertEqual(self.post(fields, "save", patch).status_code, 303)
            before = list(self.db.iterdump())
            self.post(fields, "save", patch)
            self.assertEqual(before, list(self.db.iterdump()))
            data = json.loads(self.db.execute("SELECT data FROM leave_history").fetchone()[0])
            self.assertEqual(data["leaves"].get("1_2026-11-02"), expected)
            for _ in range(2):
                fields = self.fields()
                self.post(fields, "preview", {})
                self.assertEqual(self.post(fields, "save", {}).status_code, 303)
            self.assertEqual(before, list(self.db.iterdump()))

    def test_aligned_metadata_does_not_mutate_source(self):
        old = dict(id=1, name="仮名旧", is_help=0, allowed_areas="ABC")
        new = dict(old, name="仮名新", allowed_areas="AB")
        base = dict(people=[old], grid=[["DD"]], history=[])
        aligned = align_helper_rows(dict(staff=[new]), base)
        self.assertEqual(aligned["people"], [new])
        self.assertEqual(base["people"], [old])
        self.assertEqual(aligned["grid"], base["grid"])


import html
import re
import test_scheduler as scheduler
from app import connect_db


class RepeatedCreationTest(unittest.TestCase):
    setUp = scheduler.ScheduleRouteTest.setUp
    tearDown = scheduler.ScheduleRouteTest.tearDown
    fields = scheduler.ScheduleRouteTest.fields

    def test_recreation_and_reimport_preserve_manual_until_confirmation(self):
        url = "/schedule?month=2026-02"
        edit = "/schedule/manual?month=2026-02"
        self.assertEqual(self.client.post(url, data=self.fields()).status_code, 302)
        def tokens():
            page = self.client.get(edit).get_data(as_text=True)
            return {key:html.unescape(re.search('name="'+key+'"[^>]*value="([^"]*)"',page)[1])
                    for key in ("csrf_token","fingerprint","revision")}
        fields = tokens()
        patch = json.dumps({"1_0":"DR"})
        self.client.post(edit,data=dict(fields,action="preview",patch=patch))
        self.assertEqual(self.client.post(edit,data=dict(fields,action="save",patch=patch,confirm="yes")).status_code,303)
        db = connect_db()
        for _ in range(3):
            before = db.execute("SELECT data FROM manual_schedules").fetchone()[0]
            stale_fields = tokens()
            self.client.post(edit,data=dict(stale_fields,action="preview",patch="{}"))
            self.assertEqual(self.client.post(url,data=self.fields()).status_code,302)
            # A previously opened confirmation must not overwrite a newer generation.
            self.client.post(edit,data=dict(stale_fields,action="save",patch="{}",confirm="yes"))
            self.assertEqual(db.execute("SELECT data FROM manual_schedules").fetchone()[0],before)
            fields = tokens()
            response = self.client.post(edit,data=dict(fields,action="import",source="generated"))
            page = response.get_data(as_text=True)
            patch = html.unescape(re.search('name="patch" value="([^"]*)"',page)[1])
            self.assertEqual(db.execute("SELECT data FROM manual_schedules").fetchone()[0],before)
            self.assertEqual(self.client.post(edit,data=dict(fields,action="save",patch=patch,confirm="yes")).status_code,303)
            saved = json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
            result = json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
            self.assertEqual(saved["grid"],result["grid"])
        db.close()
