import json
import re
import unittest
import test_scheduler as fixtures
import test_negotiated_leave as agreed_fixtures
from app import connect_db
from scheduler_engine import generate, WORK
from fixed_help import consulted_help_source,load_manual_source


class AgreedGenerationTest(unittest.TestCase):
    def test_recreation_keeps_agreed_full_day(self):
        data=fixtures.sample(open_days=(2,3),regular_count=5)
        data["monthly_settings"]["targets"]["1"]="27"
        data["monthly_settings"]["agreed_wish_changes"]=[
            dict(staff_id="1",date="2026-02-02",work_period="full",original_wish="full")]
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertTrue(all(c in WORK for c in result["grid"][1][0]))
        self.assertEqual(result["grid"][2][0],"RR")

    def test_agreed_morning_preserves_afternoon_wish(self):
        data=fixtures.sample(regular_count=5)
        data["monthly_settings"]["targets"]["1"]="27.5"
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="pm"
        data["monthly_settings"]["agreed_wish_changes"]=[
            dict(staff_id="1",date="2026-02-02",work_period="am",original_wish="full")]
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertIn(result["grid"][1][0][0],WORK)
        self.assertEqual(result["grid"][1][0][1],"R")

    def test_later_explicit_replacement_supersedes_previous_agreed_day(self):
        data=fixtures.sample(open_days=(2,3),regular_count=5)
        data["monthly_settings"]["targets"]["1"]="27"
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="full"
        data["monthly_settings"]["agreed_wish_changes"]=[
            dict(staff_id="1",date="2026-02-02",work_period="full"),
            dict(staff_id="1",date="2026-02-03",work_period="full",replacement_date="2026-02-02")]
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"RR")
        self.assertTrue(all(c in WORK for c in result["grid"][2][0]))


class AgreedSourceRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown
    setup_roster=agreed_fixtures.NegotiatedLeaveTest.setup_roster
    fields=agreed_fixtures.NegotiatedLeaveTest.fields
    post=agreed_fixtures.NegotiatedLeaveTest.post

    def test_save_then_help_creation_uses_agreed_table_without_extra_refresh(self):
        self.setup_roster()
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'検査ヘルプ仮名','technician','',0,1,'C')")
        db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO help_availability VALUES (?,?)",("2026-02",json.dumps({"9_2026-02-03":"full"})))
        db.commit();db.close()
        fields=self.fields()
        self.post(fields,"preview")
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        self.assertEqual(consulted_help_source(db,"2026-02",load_manual_source(db,"2026-02")),("manual",True))
        db.close()
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields={key:re.search('name="'+key+'" value="([^"]*)"',page)[1] for key in
                ("csrf_token","fingerprint","result_token","seed_token")}
        response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="help"))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True)[:100])
        db=connect_db()
        result=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        ids={p["id"]:i for i,p in enumerate(result["people"])}
        self.assertEqual(result["grid"][1][ids[5]],"CC")
        self.assertEqual(result["grid"][2][ids[5]],"RR")
        self.assertEqual(result["grid"][2][ids[9]],"CC")
        db.close()
