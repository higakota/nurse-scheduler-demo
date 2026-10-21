import copy
import json
import re
import sqlite3
import unittest
import test_scheduler as fixtures
from advance_help import generate_advance_draft
from scheduler_engine import generate_draft, verify
from help_limits import helper_demand_roles, planned_helper_roles
from app import connect_db
from data_backup import validated_backup
from staff_schema import SCHEMA


class AdvanceHelpEngineTest(unittest.TestCase):
    def example(self,absent=2):
        data=fixtures.sample()
        for i in range(1,absent+1):
            data["monthly_settings"]["targets"][str(i)]="28"
            data["monthly_settings"]["wishes"][str(i)+"_2026-02-02"]="full"
        for i,advance in ((9,1),(10,0)):
            data["staff"].append(dict(id=i,name="仮名ヘルプ"+str(i),role="nurse",employment="full",
                veteran=1,is_help=1,allowed_areas="ABC",advance_help=advance))
            data["help_availability"][str(i)+"_2026-02-02"]="full"
        return data

    def test_advance_only_registered_days_and_no_other_helpers(self):
        data=self.example();before=copy.deepcopy(data)
        result=generate_advance_draft(data,seconds=2)
        self.assertEqual(result["status"],"draft",result["messages"])
        self.assertEqual([p["id"] for p in result["problem"]["people"] if p["is_help"]],[9])
        i=next(i for i,p in enumerate(result["problem"]["people"]) if p["id"]==9)
        self.assertEqual(result["grid"][1][i],"DD")
        self.assertTrue(all(row[i]=="RR" for d,row in enumerate(result["grid"]) if d!=1))
        self.assertEqual(verify(result["problem"],result["grid"],allow_shortages=True),[])
        self.assertFalse(result["shortages"])
        from help_shortages import shortages_from_source, included_helper_visits
        source=dict(days=result["problem"]["days"],people=result["problem"]["people"],grid=result["grid"])
        self.assertFalse(shortages_from_source(data,json.dumps(source)))
        reflected=included_helper_visits(source["people"],source["days"],source["grid"])
        self.assertEqual(reflected,{"9_2026-02-02":"full"})
        self.assertNotIn("10_2026-02-02",reflected)
        self.assertEqual(data,before)
        own=generate_draft(data,seconds=2)
        self.assertTrue(own["shortages"])
        self.assertFalse(any(p["is_help"] for p in own["problem"]["people"]))

    def test_available_helper_not_used_when_own_staff_are_enough(self):
        result=generate_advance_draft(self.example(absent=0),seconds=2)
        self.assertEqual(result["status"],"draft")
        i=next(i for i,p in enumerate(result["problem"]["people"]) if p["id"]==9)
        self.assertTrue(all(row[i]=="RR" for row in result["grid"]))

    def test_pair_preference_counts_advance_nurse_and_remaining_nurse_need(self):
        result=generate_advance_draft(self.example(absent=3),seconds=2)
        self.assertEqual(result["status"],"draft")
        problem=result["problem"];row=result["grid"][1]
        self.assertEqual(helper_demand_roles(problem,1,row)[0],1)
        self.assertEqual(planned_helper_roles(problem,1,row)[0],2)


class AdvanceHelpRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_staff_flag_and_backup_roundtrip_and_draft_action(self):
        self.client.get("/staff")
        with self.client.session_transaction() as state:token=state["csrf_token"]
        response=self.client.post("/staff",data=dict(csrf_token=token,name="事前ヘルプ仮名",role="nurse",
            employment="full",is_help="1",advance_help="1",veteran="1"))
        self.assertEqual(response.status_code,302)
        db=connect_db()
        person=db.execute("SELECT * FROM staff WHERE name='事前ヘルプ仮名'").fetchone()
        self.assertEqual(person["advance_help"],1)
        payload=db.serialize();clean,_=validated_backup(payload)
        restored=sqlite3.connect(":memory:");restored.deserialize(clean)
        self.assertEqual(restored.execute("SELECT advance_help FROM staff WHERE id=?",(person["id"],)).fetchone()[0],1)
        restored.close();db.close()
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertIn('value="advance_draft"',page)
        fields={key:re.search('name="'+key+'" value="([^"]*)"',page)[1] for key in ("csrf_token","fingerprint","result_token","seed_token")}
        response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="advance_draft"))
        self.assertIn("事前に配置してよいヘルプ",response.get_data(as_text=True))

    def test_monthly_available_days_share_help_storage(self):
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas,advance_help) VALUES (9,'事前ヘルプ仮名','nurse','full',1,1,'ABC',1)")
        db.commit();db.close()
        page=self.client.get("/monthly?month=2026-02").get_data(as_text=True)
        self.assertIn('data-month-tab="availability"',page)
        self.assertIn('data-advance-key="9_2026-02-02"',page)
        fp=re.search('name="fingerprint" value="([^"]*)"',page)[1]
        with self.client.session_transaction() as state:token=state["csrf_token"]
        response=self.client.post("/help?month=2026-02",data=dict(csrf_token=token,fingerprint=fp,return_monthly="1",changes=json.dumps({"9_2026-02-02":"full"})))
        help_page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        self.assertIn("追加で依頼するヘルプは未登録",help_page)
        self.assertNotIn("事前ヘルプ仮名",help_page)
        self.assertIn("#availability",help_page)
        self.assertIn("/monthly?",response.location)
        self.assertTrue(response.location.endswith("#availability"))
        db=connect_db()
        self.assertEqual(json.loads(db.execute("SELECT data FROM help_availability WHERE month='2026-02'").fetchone()[0]),{"9_2026-02-02":"full"})
        db.close()
        stale=self.client.post("/help?month=2026-02",data=dict(csrf_token=token,fingerprint=fp,return_monthly="1",changes=json.dumps({"9_2026-02-02":"am"})))
        self.assertIn("別の画面",stale.get_data(as_text=True))

    def test_old_backup_without_flag_still_restores(self):
        db=sqlite3.connect(":memory:")
        old=SCHEMA.replace("    advance_help INTEGER NOT NULL DEFAULT 0 CHECK(advance_help IN (0,1)),\n","")
        db.execute("CREATE TABLE staff "+old)
        db.execute("INSERT INTO staff(id,name,role,employment,veteran) VALUES (1,'仮名','nurse','full',0)")
        db.commit()
        clean,_=validated_backup(db.serialize());db.close()
        restored=sqlite3.connect(":memory:");restored.deserialize(clean)
        self.assertEqual(restored.execute("SELECT advance_help FROM staff").fetchone()[0],0)
        restored.close()
