import json
import re
import unittest
import test_scheduler as fixtures
import test_negotiated_leave as agreed_fixtures
from app import connect_db
from schedule import read_snapshot
from manual_schedule import synchronize_paid_inputs
from fixed_help import load_manual_source,consulted_help_source


class ManualPaidSyncTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown
    setup_roster=agreed_fixtures.NegotiatedLeaveTest.setup_roster

    def fields(self):
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        return {key:re.search('name="'+key+'"[^>]*value="([^"]*)"',page)[1] for key in ("csrf_token","fingerprint","revision")}

    def test_paid_edit_is_registered_and_used_in_creation(self):
        self.setup_roster()
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'検査ヘルプ仮名','technician','',0,1,'C')")
        db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO help_availability VALUES (?,?)",("2026-02",json.dumps({"9_2026-02-02":"full"})))
        db.commit()
        fields=self.fields()
        patch=json.dumps({"2_0":"PP"})
        before=list(db.iterdump())
        preview=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="preview",patch=patch)).get_data(as_text=True)
        self.assertIn("表の有給を登録にも反映します",preview)
        self.assertEqual(before,list(db.iterdump()))
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=patch,confirm="yes"))
        self.assertEqual(response.status_code,303)
        snapshot,fp,_=read_snapshot(db,"2026-02")
        self.assertEqual(snapshot["leave_history"]["leaves"]["1_2026-02-03"],"full")
        raw=load_manual_source(db,"2026-02")
        self.assertEqual(json.loads(raw)["input_hash"],fp)
        self.assertEqual(consulted_help_source(db,"2026-02",raw),("manual",True))
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields={key:re.search('name="'+key+'" value="([^"]*)"',page)[1] for key in ("csrf_token","fingerprint","result_token","seed_token")}
        created=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="help"))
        self.assertEqual(created.status_code,302,created.get_data(as_text=True)[:100])
        generated=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        self.assertEqual(generated["grid"][2][0],"PP")
        # 表で取り消した有給は登録からも取り消す。
        fields=self.fields()
        patch=json.dumps({"2_0":"DD"})
        self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="preview",patch=patch))
        self.assertEqual(self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=patch,confirm="yes")).status_code,303)
        leaves=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])["leaves"]
        self.assertNotIn("1_2026-02-03",leaves)
        db.close()

    def test_existing_manual_paid_is_reconciled_but_unrelated_input_not_removed(self):
        snapshot=dict(month="2026-02",leave_history=dict(leaves={"2_2026-02-02":"full"},history={"keep":"rest"}))
        base=dict(days=["2026-02-02"],people=[dict(id=1,name="仮名1",is_help=0),dict(id=2,name="仮名2",is_help=0)],grid=[["PP","RR"]])
        updated,changes=synchronize_paid_inputs(snapshot,base,base["grid"])
        self.assertEqual(updated["leave_history"]["leaves"],{"1_2026-02-02":"full","2_2026-02-02":"full"})
        self.assertEqual(updated["leave_history"]["history"],{"keep":"rest"})
        self.assertEqual(len(changes),1)
        self.assertNotIn("1_2026-02-02",snapshot["leave_history"]["leaves"])
