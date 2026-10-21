import json
import re
import unittest
from unittest.mock import patch
from app import connect_db
import test_scheduler as fixtures
from help_shortages import load_reference, publish_reference
from schedule import read_snapshot


class HelpShortagesTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def shortage(self):
        db=connect_db()
        monthly=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        for i in ("1","2"):
            monthly["wishes"][i+"_2026-02-02"]="full"
            monthly["targets"][i]="28"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(monthly),))
        db.commit()
        db.close()

    def helper(self):
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','nurse','full',1,1,'ABC')")
        db.commit()
        db.close()

    def draft(self):
        fields=fixtures.ScheduleRouteTest.fields(self)
        return self.client.post("/schedule?month=2026-02",data=dict(fields,mode="draft"))

    def reference(self):
        db=connect_db()
        try:return load_reference(db,"2026-02")
        finally:db.close()

    def test_draft_shortages_visible_without_any_helper_and_veteran_is_subset(self):
        self.shortage()
        self.assertEqual(self.draft().status_code,200)
        data=self.reference()
        self.assertEqual(data["state"],"current")
        self.assertEqual(data["days"]["2026-02-02"][0]["label"],"看護師1人（うちベテラン1人）")
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        self.assertIn("看護師1人（うちベテラン1人）",page)
        self.assertIn('data-shortage-day="2026-02-02"',page)
        self.assertIn("ヘルプスタッフは未登録",page)

    def test_input_change_hides_old_numbers(self):
        self.shortage()
        self.draft()
        db=connect_db()
        db.execute("UPDATE staff SET veteran=0 WHERE id=1")
        db.commit()
        db.close()
        self.assertEqual(self.reference()["state"],"outdated")
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        self.assertIn("古い不足人数は表示していません",page)
        self.assertNotIn("看護師1人（うちベテラン1人）",page)

    def test_visit_save_keeps_baseline_and_does_not_claim_shortage_resolved(self):
        self.helper()
        self.shortage()
        self.draft()
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        fp=re.search('name="fingerprint" value="([^"]*)"',page)[1]
        with self.client.session_transaction() as session:token=session["csrf_token"]
        response=self.client.post("/help?month=2026-02",data=dict(csrf_token=token,fingerprint=fp,changes=json.dumps({"9_2026-02-02":"full"})))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.reference()["state"],"reference")
        page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("再作成前の仮表での不足（参考）",page)
        self.assertIn("看護師1人（うちベテラン1人）",page)
        self.assertNotIn("検証済み勤務表では、不足はありません",page)

    def test_verified_result_clears_previous_shortage_reference(self):
        self.helper()
        self.draft()
        response=self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.reference()["kind"],"verified")
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        self.assertIn("検証済み勤務表では、不足はありません",page)
        db=connect_db()
        db.execute("CREATE TABLE IF NOT EXISTS help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO help_availability VALUES (?,?)",("2026-02",json.dumps({"9_2026-02-02":"am"})))
        db.commit()
        db.close()
        self.assertEqual(self.reference()["state"],"outdated")

    def test_explicit_refresh_requires_csrf_and_does_not_save_final_schedule(self):
        self.shortage()
        self.assertEqual(self.client.post("/help/shortages?month=2026-02").status_code,400)
        with patch("scheduler_engine.generate_draft") as calculate:
            self.client.get("/help?month=2026-02")
            calculate.assert_not_called()
        with self.client.session_transaction() as session:token=session["csrf_token"]
        response=self.client.post("/help/shortages?month=2026-02",data=dict(csrf_token=token))
        self.assertEqual(response.status_code,303)
        self.assertTrue(self.reference()["days"])
        db=connect_db()
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='generated_schedules'").fetchone())
        db.close()

    def test_publish_rejects_input_changed_during_calculation(self):
        self.shortage()
        self.draft()
        db=connect_db()
        snapshot,fp,_=read_snapshot(db,"2026-02")
        original=db.execute("SELECT data FROM help_shortage_previews").fetchone()[0]
        db.execute("UPDATE staff SET veteran=0 WHERE id=1")
        db.commit()
        db.close()
        self.assertFalse(publish_reference(connect_db,snapshot,fp,[]))
        db=connect_db()
        self.assertEqual(db.execute("SELECT data FROM help_shortage_previews").fetchone()[0],original)
        db.close()

    def test_refresh_preserves_saved_manual_and_invalidates_after_edit(self):
        self.shortage()
        self.draft()
        db=connect_db()
        raw=db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0]
        value=json.loads(raw)
        value["updated"]="2099-01-01T00:00:00"
        raw=json.dumps(value)
        db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO manual_schedules VALUES (?,?)",("2026-02",raw))
        db.commit()
        db.close()
        with self.client.session_transaction() as session:token=session["csrf_token"]
        with patch("scheduler_engine.generate_draft") as calculate:
            response=self.client.post("/help/shortages?month=2026-02",data=dict(csrf_token=token))
            calculate.assert_not_called()
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.reference()["kind"],"manual")
        db=connect_db()
        self.assertEqual(db.execute("SELECT data FROM manual_schedules").fetchone()[0],raw)
        snapshot,fp,_=read_snapshot(db,"2026-02")
        value["updated"]="2099-01-02T00:00:00"
        db.execute("UPDATE manual_schedules SET data=?",(json.dumps(value),))
        db.commit()
        db.close()
        self.assertEqual(self.reference()["state"],"outdated")
        self.assertFalse(publish_reference(connect_db,snapshot,fp,[],expected_source=("manual",raw)))


class TechnicianAlternativeCalendarTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown
    shortage=HelpShortagesTest.shortage
    draft=HelpShortagesTest.draft

    def test_saved_reference_updates_help_calendar_without_recreating_or_writing(self):
        self.shortage()
        db=connect_db()
        coverage=json.loads(db.execute("SELECT data FROM coverage_settings").fetchone()[0])
        for half in ("am","pm"):coverage["2026-02-02_"+half]["c"]=2
        db.execute("UPDATE coverage_settings SET data=?",(json.dumps(coverage),))
        db.commit();db.close()
        self.draft()
        db=connect_db()
        reference=json.loads(db.execute("SELECT data FROM help_shortage_previews").fetchone()[0])
        # 修正前に保存した不足表示と同じ形にする。
        for row in reference["rows"]:
            row.pop("alternative_technicians",None)
        db.execute("UPDATE help_shortage_previews SET data=?",(json.dumps(reference),))
        db.commit()
        self.client.get("/help?month=2026-02")
        before=list(db.iterdump())
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        self.assertIn("看護師2人",page)
        self.assertIn("うち1人は検査技師でも可",page)
        self.assertEqual(before,list(db.iterdump()))
        db.close()
