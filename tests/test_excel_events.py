import io
import json
import unittest
import zipfile
from werkzeug.datastructures import MultiDict
from app import connect_db
from doctor_import import parse_schedule
from excel_events import extract_events, apply_events, monthly_snapshot
import test_doctor_import as helpers
workbook = helpers.workbook


def event_book():
    original = workbook()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            text = source.read(name)
            if name.endswith("sheet1.xml"):
                text = text.decode().replace("<sheetData>", '<sheetData>').replace("</worksheet>", '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="draw"/></worksheet>').encode()
            target.writestr(name, text)
        target.writestr("xl/worksheets/_rels/sheet1.xml.rels", '<Relationships><Relationship Id="draw" Target="../drawings/drawing1.xml"/></Relationships>')
        target.writestr("xl/drawings/drawing1.xml", '<x:wsDr xmlns:x="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><x:oneCellAnchor><x:from><x:col>3</x:col><x:row>5</x:row></x:from><x:sp><a:p><a:r><a:t>職場会議</a:t></a:r></a:p><a:p><a:r><a:t>感染委員会</a:t></a:r></a:p></x:sp></x:oneCellAnchor></x:wsDr>')
    return out.getvalue()


class ExcelEventsTest(unittest.TestCase):
    setUp = helpers.DoctorImportTest.setUp
    tearDown = helpers.DoctorImportTest.tearDown
    post = helpers.DoctorImportTest.post
    plan = helpers.DoctorImportTest.plan
    save_fields = helpers.DoctorImportTest.save_fields

    def load(self):
        self.post(action="upload", workbook=(io.BytesIO(event_book()), "sample.xlsx"))
        response = self.post(action="read", sheet="12月")
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as state:
            owner = state["import_owner"]
        db = connect_db()
        preview = json.loads(db.execute("SELECT preview FROM doctor_import_draft WHERE owner=?", (owner,)).fetchone()[0])
        db.close()
        return preview

    def test_paragraphs_separate_and_dates_not_guessed(self):
        raw = event_book()
        extra = extract_events(raw, "12月", parse_schedule(raw, "12月", "2026-12"))
        self.assertEqual([m["title"] for m in extra["meetings"]], ["職場会議", "感染委員会"])
        self.assertTrue(all(not m["date"] for m in extra["meetings"]))

    def test_unselected_does_not_modify_monthly(self):
        self.load()
        self.assertEqual(self.post(**self.save_fields()).status_code, 302)
        db = connect_db()
        self.assertIsNone(monthly_snapshot(db, "2026-12"))
        db.close()

    def test_bad_meeting_rolls_back_doctors(self):
        preview = self.load()
        fields = self.save_fields()
        fields["meeting_pick_" + preview["extras"]["meetings"][0]["id"]] = "yes"
        fields["action"] = "excel_events"
        response = self.client.post("/monthly?month=2026-12", data=dict(fields, csrf_token=self.token))
        self.assertIn("会議の日付を指定", response.get_data(as_text=True))
        self.assertIsNone(self.plan())

    def test_closure_conflict_and_stale_snapshot(self):
        db = connect_db()
        original = json.dumps({"targets":{"1":"9"}, "wishes":{}, "closures":{}, "meetings":[{"date":"2026-12-01"}]})
        monthly_snapshot(db, "2026-12")
        db.execute("INSERT INTO monthly_settings VALUES (?,?)", ("2026-12", original))
        db.commit()
        preview = {"monthly_original":original,"extras":{"closures":[{"id":"C","date":"2026-12-01"}]}}
        form = MultiDict({"closure_pick_C":"yes", "closure_kind_C":"holiday"})
        with self.assertRaisesRegex(ValueError, "会議が登録済み"):
            apply_events(db, "2026-12", preview, form)
        preview["monthly_original"] = None
        with self.assertRaisesRegex(ValueError, "会議が登録済み"):
            apply_events(db, "2026-12", preview, form)
        db.close()

    def test_selected_meeting_preserves_data_and_is_idempotent(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name, role, employment, veteran) VALUES ('仮名', 'nurse', 'full', 0)")
        person = str(db.execute("SELECT id FROM staff").fetchone()[0])
        original = monthly_snapshot(db, "2026-12")
        preview = {"monthly_original":original, "extras":{"meetings":[{"id":"example"}]}}
        form = MultiDict({"meeting_pick_example":"yes", "meeting_example_date":"2026-12-01", "meeting_example_title":"職場会議", "meeting_example_participants":person})
        apply_events(db, "2026-12", preview, form)
        db.commit()
        preview["monthly_original"] = monthly_snapshot(db, "2026-12")
        apply_events(db, "2026-12", preview, form)
        db.commit()
        self.assertEqual(len(json.loads(monthly_snapshot(db, "2026-12"))["meetings"]), 1)
        db.close()

    def test_candidates_available_in_monthly_after_doctor_save(self):
        self.load()
        self.assertEqual(self.post(**self.save_fields()).status_code, 302)
        response = self.client.get("/monthly?month=2026-12")
        text = response.get_data(as_text=True)
        self.assertIn("職場会議", text)
        self.assertIn("選んだ会議を反映・保存", text)
        self.assertIn('name="action" value="excel_events"', text)

    def test_monthly_reflection_updates_normal_controls(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name, role, employment, veteran) VALUES ('テスト看護師', 'nurse', 'full', 0)")
        person = str(db.execute("SELECT id FROM staff").fetchone()[0])
        db.commit()
        db.close()
        preview = self.load()
        key = preview["extras"]["meetings"][0]["id"]
        fields = {"csrf_token":self.token, "action":"excel_events", "event_tab":"meetings",
                  "meeting_pick_" + key:"yes", "meeting_" + key + "_date":"2026-12-01",
                  "meeting_" + key + "_title":"職場会議", "meeting_" + key + "_participants":person}
        response = self.client.post("/monthly?month=2026-12", data=fields)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("#meetings"))
        db = connect_db()
        data = json.loads(monthly_snapshot(db, "2026-12"))
        self.assertEqual(data["meetings"][0]["participants"], [person])
        self.assertIsNone(self.plan())
        db.close()
        text = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("職場会議を編集", text)
        self.assertIn('data-meeting-edit=',text)

    def test_previous_import_candidates_visible_after_session_change(self):
        self.load()
        from app import app
        other = app.test_client()
        page = other.get("/monthly?month=2026-12").get_data(as_text=True)
        self.assertIn("職場会議", page)
        self.assertIn("候補（未反映）", page)
        self.assertNotIn('<article class="meeting"',page)


    def test_renamed_excel_candidate_is_saved_with_edited_title(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name, role, employment, veteran) VALUES ('仮名 看護', 'nurse', 'full', 0)")
        person = str(db.execute("SELECT id FROM staff").fetchone()[0])
        db.commit()
        db.close()
        preview = self.load()
        key = preview["extras"]["meetings"][0]["id"]
        fields = {"csrf_token": self.token, "action": "excel_events", "event_tab": "meetings",
                  "meeting_pick_" + key: "yes", "meeting_" + key + "_date": "2026-12-01",
                  "meeting_" + key + "_title": "変更した会議名", "meeting_" + key + "_participants": person}
        response = self.client.post("/monthly?month=2026-12", data=fields)
        self.assertEqual(response.status_code, 302)
        db = connect_db()
        meetings = json.loads(monthly_snapshot(db, "2026-12"))["meetings"]
        db.close()
        self.assertEqual(meetings[0]["title"], "変更した会議名")
        self.assertEqual(meetings[0]["import_source"], key)

    def test_no_selection_shows_error_and_preserves_renamed_candidate(self):
        preview = self.load()
        key = preview["extras"]["meetings"][0]["id"]
        db = connect_db()
        original = monthly_snapshot(db, "2026-12")
        db.close()
        response = self.client.post("/monthly?month=2026-12&saved=1", data={
            "csrf_token": self.token, "action": "excel_events", "event_tab": "meetings",
            "meeting_" + key + "_title": "変更した会議名"})
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("取り込む候補が選択されていません", text)
        self.assertIn('value="変更した会議名"', text)
        self.assertIn("excel-event-error", text)
        self.assertNotIn("保存しました。", text)
        db = connect_db()
        self.assertEqual(monthly_snapshot(db, "2026-12"), original)
        db.close()

    def test_old_candidate_merges_into_latest_month_without_overwriting(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('仮名','nurse','full',0)")
        person = str(db.execute("SELECT id FROM staff").fetchone()[0])
        monthly_snapshot(db, "2026-12")
        latest = {"targets": {person: "10"}, "wishes": {person + "_2026-12-02": "full"},
                  "closures": {"2026-12-03": "holiday"}, "meetings": []}
        db.execute("INSERT INTO monthly_settings VALUES (?,?)", ("2026-12", json.dumps(latest)))
        db.commit()
        preview = {"monthly_original": None, "extras": {"meetings": [{"id": "old"}]}}
        form = MultiDict({"meeting_pick_old": "yes", "meeting_old_date": "2026-12-01",
                          "meeting_old_title": "候補から追加", "meeting_old_participants": person})
        apply_events(db, "2026-12", preview, form)
        db.commit()
        saved = json.loads(monthly_snapshot(db, "2026-12"))
        for key in ("targets", "wishes", "closures"):
            self.assertEqual(saved[key], latest[key])
        self.assertEqual(saved["meetings"][0]["title"], "候補から追加")
        db.close()

    def test_candidate_date_choices_are_only_target_month(self):
        self.load()
        text = self.client.get("/monthly?month=2026-12").get_data(as_text=True)
        import re
        fields = re.findall(r'<select name="meeting_[^"]+_date">(.*?)</select>', text, re.S)
        self.assertTrue(fields)
        for field in fields:
            dates = re.findall(r'value="(2026-[0-9-]+)"', field)
            self.assertEqual(len(dates), 31)
            self.assertTrue(all(day.startswith("2026-12-") for day in dates))
