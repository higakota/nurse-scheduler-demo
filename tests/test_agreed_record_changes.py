import json
import re
import unittest
import test_scheduler as fixtures
import test_negotiated_leave as agreed_fixtures
import test_agreed_calendar as calendar_fixtures
from app import connect_db
from scheduler_engine import prepare
from schedule import read_snapshot
from fixed_help import consulted_help_source,load_manual_source


class AgreedRecordChangesTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown
    setup_roster=agreed_fixtures.NegotiatedLeaveTest.setup_roster
    fields=agreed_fixtures.NegotiatedLeaveTest.fields
    post=agreed_fixtures.NegotiatedLeaveTest.post

    def create_record(self):
        self.setup_roster()
        fields=self.fields()
        self.post(fields,"preview")
        response=self.post(fields,"save","yes")
        self.assertEqual(response.status_code,303)
        return response

    def record_fields(self,index=0):
        text=self.client.get(f"/schedule/agreed-change/record/{index}?month=2026-02").get_data(as_text=True)
        return {key:re.search('name="'+key+'"[^>]*value="([^"]*)"',text)[1] for key in ("csrf_token","fingerprint","revision")}

    def record_post(self,fields,action,index=0,operation="delete",**extra):
        return self.client.post(f"/schedule/agreed-change/record/{index}?month=2026-02",data=dict(
            fields,action=action,operation=operation,period="full",swap="",**extra))

    def dump(self):
        db=connect_db()
        result=list(db.iterdump());db.close()
        return result

    def test_record_stays_in_calendar_after_shortage_is_resolved(self):
        response=self.create_record()
        self.assertIn("/schedule/manual?",response.location)
        reflected=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("了承済みの変更を勤務表に反映しました",reflected)
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        cell=re.search(r'<td data-agreed-date="2026-02-02".*?</td>',text,re.S)[0]
        self.assertIn("了承出勤（全日）",cell)
        self.assertIn("/schedule/agreed-change/record/0",cell)
        self.assertIn("変更・取り消し",cell)

    def test_cancellation_preview_and_apply_restore_wishes_and_grid(self):
        self.create_record()
        before=self.dump()
        fields=self.record_fields()
        self.assertEqual(self.dump(),before)
        text=self.record_post(fields,"preview").get_data(as_text=True)
        self.assertIn("元の希望休と勤務へ戻します",text)
        self.assertEqual(self.dump(),before)
        self.record_post(fields,"save")
        self.assertEqual(self.dump(),before)
        response=self.record_post(fields,"save",consent="yes")
        self.assertEqual(response.status_code,303)
        db=connect_db()
        snapshot,_,_=read_snapshot(db,"2026-02")
        manual=json.loads(load_manual_source(db,"2026-02"))
        self.assertEqual(snapshot["monthly_settings"]["wishes"]["5_2026-02-02"],"full")
        self.assertNotIn("5_2026-02-03",snapshot["monthly_settings"]["wishes"])
        self.assertEqual(manual["grid"][1][4],"RR")
        self.assertEqual(manual["grid"][2][4],"CC")
        self.assertTrue(snapshot["monthly_settings"]["agreed_wish_changes"][0]["cancelled"])
        self.assertIn("RR",prepare(snapshot,True)["options"][1][4])
        self.assertEqual(consulted_help_source(db,"2026-02",load_manual_source(db,"2026-02")),("manual",True))
        db.close()

    def test_edit_time_then_delete_keeps_history_and_restores_original(self):
        self.create_record()
        fields=self.record_fields()
        data=dict(fields,action="preview",operation="edit",period="am",swap="2026-02-03")
        self.client.post("/schedule/agreed-change/record/0?month=2026-02",data=data)
        data.update(action="save",consent="yes")
        self.assertEqual(self.client.post("/schedule/agreed-change/record/0?month=2026-02",data=data).status_code,303)
        db=connect_db()
        snapshot,_,_=read_snapshot(db,"2026-02")
        records=snapshot["monthly_settings"]["agreed_wish_changes"]
        self.assertTrue(records[0]["cancelled"])
        self.assertFalse(records[1].get("cancelled",False))
        self.assertEqual(records[1]["work_period"],"am")
        self.assertEqual(snapshot["monthly_settings"]["wishes"]["5_2026-02-02"],"pm")
        self.assertEqual(json.loads(load_manual_source(db,"2026-02"))["grid"][1][4],"CR")
        db.close()
        fields=self.record_fields(1)
        self.record_post(fields,"preview",index=1)
        self.assertEqual(self.record_post(fields,"save",index=1,consent="yes").status_code,303)
        db=connect_db()
        restored=json.loads(load_manual_source(db,"2026-02"))
        self.assertEqual(restored["grid"][1][4],"RR")
        self.assertEqual(restored["grid"][2][4],"CC")
        db.close()

    def test_later_manual_edit_is_not_overwritten(self):
        self.create_record()
        db=connect_db()
        value=json.loads(load_manual_source(db,"2026-02"))
        value["grid"][1][4]="PP"
        db.execute("UPDATE manual_schedules SET data=?",(json.dumps(value),));db.commit();db.close()
        fields=self.record_fields()
        before=self.dump()
        text=self.record_post(fields,"preview").get_data(as_text=True)
        self.assertIn("後から編集されています",text)
        self.assertEqual(self.dump(),before)

    def test_stale_and_tampered_requests_do_not_apply(self):
        self.create_record()
        fields=self.record_fields()
        before=self.dump()
        data=dict(fields,csrf_token="bad")
        self.assertEqual(self.record_post(data,"preview").status_code,400)
        self.assertEqual(self.dump(),before)
        self.record_post(fields,"preview")
        data=dict(fields,revision="changed")
        self.assertIn("入力や勤務表が変更",self.record_post(data,"save",consent="yes").get_data(as_text=True))
        self.assertEqual(self.dump(),before)

    def test_month_boundary_can_be_edited_then_cancelled(self):
        calendar_fixtures.AgreedCalendarTest.test_month_boundary_is_updated_only_after_confirmed_consent(self)
        fields=self.record_fields()
        data=dict(fields,operation="edit",period="am",swap="",action="preview")
        self.client.post("/schedule/agreed-change/record/0?month=2026-02",data=data)
        data.update(action="save",consent="yes")
        self.assertEqual(self.client.post("/schedule/agreed-change/record/0?month=2026-02",data=data).status_code,303)
        db=connect_db()
        values=json.loads(db.execute("SELECT data FROM weekly_work_boundaries WHERE month='2026-03'").fetchone()[0])
        self.assertEqual(values["5_2026-02-28"],0.5)
        db.close()
        fields=self.record_fields(1)
        self.record_post(fields,"preview",index=1)
        self.assertEqual(self.record_post(fields,"save",index=1,consent="yes").status_code,303)
        db=connect_db()
        values=json.loads(db.execute("SELECT data FROM weekly_work_boundaries WHERE month='2026-03'").fetchone()[0])
        self.assertEqual(values,{"5_2026-02-28":0,"other":"keep"})
        db.close()

    def test_overlapping_later_agreement_must_be_removed_first(self):
        self.setup_roster()
        fields=self.fields()
        fields.update(period="am")
        self.post(fields,"preview")
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        settings["wishes"].pop("5_2026-02-02",None)
        settings["agreed_wish_changes"].append(dict(staff_id="5",date="2026-02-02",
            work_period="pm",original_wish="pm",remaining_wish="",changes=[
                dict(day="2026-02-02",before="CR",after="CC")],created="later",reason=""))
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(settings),))
        value=json.loads(load_manual_source(db,"2026-02"));value["grid"][1][4]="CC"
        db.execute("UPDATE manual_schedules SET data=?",(json.dumps(value),))
        db.commit();db.close()
        fields=self.record_fields(0)
        before=self.dump()
        text=self.record_post(fields,"preview").get_data(as_text=True)
        self.assertIn("後の変更から先に取り消してください",text)
        self.assertEqual(before,self.dump())
