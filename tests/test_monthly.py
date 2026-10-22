import json
import re
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
        self.assertIn("希望休を優先し", self.client.get("/monthly?month=2026-10").get_data(as_text=True))
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

    def weekly_setup(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name,role,employment,veteran,weekly_limit_units) VALUES ('非常勤 看護', 'nurse', 'part', 0, 6)")
        db.execute("INSERT INTO staff(name,role,employment,veteran,weekly_limit_units) VALUES ('非常勤 検査', 'technician', 'part', 0, 4)")
        db.commit()
        db.close()
        page = self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        return re.search(r'name="settings_fingerprint" value="([^"]+)"', page)[1]

    def weekly_limits(self):
        db = connect_db()
        try:
            return [row[0] for row in db.execute("SELECT weekly_limit_units FROM staff WHERE employment='part' ORDER BY id")]
        finally:
            db.close()

    def test_weekly_limits_save_with_targets_and_visible_in_other_month(self):
        fingerprint = self.weekly_setup()
        response = self.post(action="settings", target_1="10", weekly_limit_2="3.5", weekly_limit_3="2.5", settings_fingerprint=fingerprint, settings_tab="targets")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("#targets"))
        self.assertEqual(self.weekly_limits(), [7, 5])
        self.assertEqual(self.stored()["targets"], {"1": "10"})
        page = self.client.get("/monthly?month=2026-11").get_data(as_text=True)
        self.assertRegex(page, r'name="weekly_limit_2" value="3.5"')
        self.assertIn("全月共通", page)

    def test_weekly_invalid_or_stale_save_is_atomic(self):
        fingerprint = self.weekly_setup()
        for raw in ("7.5", "-1", "0.3", "NaN", "Infinity"):
            response = self.post(action="settings", target_1="10", weekly_limit_2=raw, weekly_limit_3="3", settings_fingerprint=fingerprint)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.weekly_limits(), [6, 4])
            self.assertIsNone(self.stored())
        self.post(action="settings", target_1="bad", weekly_limit_2="4", settings_fingerprint=fingerprint)
        self.assertEqual(self.weekly_limits(), [6, 4])
        db = connect_db()
        db.execute("UPDATE staff SET weekly_limit_units=8 WHERE id=2")
        db.commit()
        db.close()
        response = self.post(action="settings", target_1="10", weekly_limit_2="3", settings_fingerprint=fingerprint)
        self.assertIn("別の画面で変更", response.get_data(as_text=True))
        self.assertEqual(self.weekly_limits(), [8, 4])
        self.assertIsNone(self.stored())

    def test_weekly_blank_and_omitted_fields(self):
        fingerprint = self.weekly_setup()
        self.post(action="settings", weekly_limit_2="", settings_fingerprint=fingerprint)
        self.assertEqual(self.weekly_limits(), [None, 4])
        self.post(action="settings", target_1="10")
        self.assertEqual(self.weekly_limits(), [None, 4])

    def test_weekly_update_requires_fingerprint_and_eligible_staff(self):
        fingerprint = self.weekly_setup()
        self.post(action="settings", weekly_limit_2="4")
        self.assertEqual(self.weekly_limits(), [6, 4])
        self.post(action="settings", weekly_limit_1="4", weekly_limit_2="4", settings_fingerprint=fingerprint)
        self.assertEqual(self.weekly_limits(), [6, 4])
        self.assertIsNone(self.stored())

    def meeting_fingerprint(self):
        page = self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        return re.search(r'name="settings_fingerprint" value="([^"]+)"', page)[1]

    def test_edit_imported_meeting_preserves_source_and_other_data(self):
        self.post(action="settings", target_1="10", **{"wish_1_2026-10-22": "full"})
        self.post(action="meeting_add", meeting_date="2026-10-20", title="元の会議", participants="1", start="14:00", end="15:00")
        data = self.stored()
        meeting = data["meetings"][0]
        meeting["import_source"] = "excel-example"
        db = connect_db()
        db.execute("UPDATE monthly_settings SET data=? WHERE month='2026-10'", (json.dumps(data),))
        db.commit()
        db.close()
        response = self.post(action="meeting_edit", meeting_id=meeting["id"], settings_fingerprint=self.meeting_fingerprint(),
                             meeting_date="2026-10-21", title="変更した会議", participants="1", start="15:00", end="16:00")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("#meetings"))
        saved = self.stored()
        edited = saved["meetings"][0]
        self.assertEqual((edited["date"], edited["title"], edited["start"], edited["end"]), ("2026-10-21", "変更した会議", "15:00", "16:00"))
        self.assertEqual((edited["id"], edited["import_source"]), (meeting["id"], "excel-example"))
        self.assertEqual(saved["targets"], data["targets"])
        self.assertEqual(saved["wishes"], data["wishes"])
        page = self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        self.assertIn('class="meeting-editor-dialog"',page)
        self.assertIn('data-meeting-edit=',page)

    def test_edit_meeting_rejects_invalid_date_participants_overlap_and_stale(self):
        self.post(action="meeting_add", meeting_date="2026-10-20", title="会議1", participants="1", start="14:00", end="15:00")
        self.post(action="meeting_add", meeting_date="2026-10-21", title="会議2", participants="1", start="14:00", end="15:00")
        original = self.stored()
        meeting = original["meetings"][0]
        fields = dict(action="meeting_edit", meeting_id=meeting["id"], settings_fingerprint=self.meeting_fingerprint(),
                      meeting_date="2026-10-20", title="変更", participants="1", start="14:00", end="15:00")
        for changes in ({"meeting_date": "2026-11-01"}, {"meeting_date": "2026-10-18"},
                        {"participants": "999"}, {"participants": ""}, {"title": ""},
                        {"start": "16:00"}, {"meeting_date": "2026-10-21"}):
            response = self.post(**dict(fields, **changes))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.stored(), original)
        self.post(action="meeting_add", meeting_date="2026-10-22", title="別画面", participants="1")
        latest = self.stored()
        response = self.post(**fields)
        self.assertIn("別の画面で変更", response.get_data(as_text=True))
        self.assertEqual(self.stored(), latest)

    def test_edit_meeting_can_change_participants(self):
        db = connect_db()
        db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('看護 次郎','nurse','full',0)")
        db.commit()
        db.close()
        self.post(action="meeting_add", meeting_date="2026-10-20", title="会議", participants="1")
        meeting = self.stored()["meetings"][0]
        self.post(action="meeting_edit", meeting_id=meeting["id"], settings_fingerprint=self.meeting_fingerprint(),
                  meeting_date="2026-10-20", title="会議", participants="2")
        self.assertEqual(self.stored()["meetings"][0]["participants"], ["2"])

    def test_failed_meeting_after_previous_save_never_shows_success(self):
        response = self.client.post("/monthly?month=2026-10&saved=1", data={
            "csrf_token": self.token, "action": "meeting_add",
            "settings_fingerprint": self.meeting_fingerprint(),
            "meeting_date": "2026-10-20", "title": "参加者未選択", "start": "14:00", "end": "15:00"})
        text = response.get_data(as_text=True)
        self.assertNotIn("保存しました。", text)
        self.assertIn("会議は保存できませんでした", text)
        self.assertIn("会議の参加者を選択", text)
        self.assertIsNone(self.stored())

    def test_added_meeting_visible_after_following_redirect(self):
        response = self.post(action="meeting_add", settings_fingerprint=self.meeting_fingerprint(),
                             meeting_date="2026-10-20", title="確認用会議", participants="1", start="14:00", end="15:00")
        self.assertEqual(response.status_code, 302)
        text = self.client.get(response.location).get_data(as_text=True)
        self.assertNotIn("登録済みの会議（1件）", text)
        self.assertIn('data-meeting-edit=',text)
        self.assertIn("確認用会議を編集", text)
        self.assertNotIn('<article class="meeting"',text)
        self.assertIn("保存しました。登録済みの会議は1件", text)
        self.assertIn('action="/monthly?month=2026-10#meetings"', text)

    def test_renaming_meeting_repeatedly_keeps_same_id_and_one_record(self):
        self.post(action="meeting_add", meeting_date="2026-10-20", title="上半期総括", participants="1",
                  start="14:00", end="15:00", settings_fingerprint=self.meeting_fingerprint())
        meeting_id = self.stored()["meetings"][0]["id"]
        for title in ("職場会議", "会議・ミーティング（午後）", '会議 "A" & <確認>', "上半期総括"):
            response = self.post(action="meeting_edit", meeting_id=meeting_id,
                                 settings_fingerprint=self.meeting_fingerprint(), meeting_date="2026-10-20",
                                 title=title, participants="1", start="14:00", end="15:00")
            self.assertEqual(response.status_code, 302)
            meetings = self.stored()["meetings"]
            self.assertEqual(len(meetings), 1)
            self.assertEqual((meetings[0]["id"], meetings[0]["title"]), (meeting_id, title))
            self.assertIn('name="action" value="meeting_edit"', self.client.get(response.location).get_data(as_text=True))

    def test_meeting_ui_has_no_time_fields_and_can_register_afternoon_only(self):
        page = self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        self.assertNotIn('type="time"', page)
        response = self.post(action="meeting_add", meeting_date="2026-10-20", title="午後会議",
                             participants="1", settings_fingerprint=self.meeting_fingerprint())
        self.assertEqual(response.status_code, 302)
        meeting = self.stored()["meetings"][0]
        self.assertEqual((meeting["start"], meeting["end"]), ("", ""))
        response = self.post(action="meeting_edit", meeting_id=meeting["id"], meeting_date="2026-10-20",
                             title="変更した午後会議", participants="1", settings_fingerprint=self.meeting_fingerprint())
        self.assertEqual(response.status_code, 302)

    def test_meeting_edit_without_time_fields_preserves_existing_times(self):
        self.post(action="meeting_add", meeting_date="2026-10-20", title="既存会議", participants="1", start="14:00", end="15:00")
        meeting = self.stored()["meetings"][0]
        response = self.post(action="meeting_edit", meeting_id=meeting["id"], meeting_date="2026-10-20",
                             title="名称変更", participants="1", settings_fingerprint=self.meeting_fingerprint())
        self.assertEqual(response.status_code, 302)
        saved = self.stored()["meetings"][0]
        self.assertEqual((saved["start"], saved["end"]), ("14:00", "15:00"))
