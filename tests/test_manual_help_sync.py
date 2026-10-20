import json
import re
import unittest
import test_scheduler as fixtures
import test_negotiated_leave as agreed_fixtures
from app import connect_db
from manual_schedule import synchronize_help_inputs
from leave_candidates import leave_candidates
from schedule import read_snapshot


class ManualHelpSyncTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown
    setup_roster=agreed_fixtures.NegotiatedLeaveTest.setup_roster

    def fields(self):
        text=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        return {key:re.search('name="'+key+'"[^>]*value="([^"]*)"',text)[1] for key in ("csrf_token","fingerprint","revision")}

    def test_paid_and_helper_edits_allow_candidates_and_direct_creation(self):
        self.setup_roster()
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'検査ヘルプ仮名','technician','',0,1,'C')")
        db.commit()
        fields=self.fields()
        patch=json.dumps({"1_5":"CC","2_0":"PP"})
        before=list(db.iterdump())
        preview=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="preview",patch=patch)).get_data(as_text=True)
        self.assertIn('name="help_consent"',preview)
        self.assertIn("来院OKを確認",preview)
        self.assertEqual(before,list(db.iterdump()))
        denied=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=patch,confirm="yes")).get_data(as_text=True)
        self.assertIn("ヘルプの来院OKを確認",denied)
        self.assertEqual(before,list(db.iterdump()))
        saved=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=patch,confirm="yes",help_consent="yes"))
        self.assertEqual(saved.status_code,303)
        snapshot,fp,_=read_snapshot(db,"2026-02")
        self.assertEqual(snapshot["help_availability"]["9_2026-02-02"],"full")
        self.assertEqual(snapshot["leave_history"]["leaves"]["1_2026-02-03"],"full")
        manual=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        candidates=leave_candidates(snapshot,manual,fp)
        self.assertEqual(candidates["message"],"")
        self.assertTrue(candidates["days"])
        # 自院だけの仮作成を挟まず、編集後の表を元に作成できる。
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields={key:re.search('name="'+key+'" value="([^"]*)"',text)[1] for key in ("csrf_token","fingerprint","result_token","seed_token")}
        result=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="help"))
        self.assertEqual(result.status_code,302,result.get_data(as_text=True)[:100])
        generated=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        ids={p["id"]:i for i,p in enumerate(generated["people"])}
        self.assertEqual(generated["grid"][1][ids[9]],"CC")
        self.assertEqual(generated["grid"][2][ids[1]],"PP")
        for d,row in enumerate(manual["grid"]):
            for i,p in enumerate(manual["people"]):
                if not p["is_help"]:
                    self.assertEqual(row[i],generated["grid"][d][ids[p["id"]]])
        db.close()

    def test_helper_reconciliation_preserves_approved_visit_and_does_not_assume_cancel(self):
        snapshot=dict(help_availability={"9_2026-02-02":"full","9_2026-02-03":"full"})
        base=dict(days=["2026-02-02","2026-02-03","2026-02-04"],
                  people=[dict(id=9,name="ヘルプ仮名",is_help=1)],grid=[["DR"],["RR"],["RD"]])
        updated,changes=synchronize_help_inputs(snapshot,base,base["grid"])
        self.assertEqual(updated["help_availability"],{"9_2026-02-02":"full","9_2026-02-03":"full","9_2026-02-04":"pm"})
        self.assertEqual(len(changes),1)
        self.assertNotIn("9_2026-02-04",snapshot["help_availability"])

    def test_candidate_block_explains_missing_helper_visit(self):
        data=fixtures.sample()
        data["staff"].append(dict(id=9,name="ヘルプ仮名",role="nurse",employment="full",veteran=0,is_help=1,allowed_areas="ABC"))
        days=[f"2026-02-{d:02}" for d in range(1,29)]
        grid=[["RR"]*6 for _ in days]
        grid[1]=["DD"]*4+["CC","DD"]
        source=dict(days=days,people=data["staff"],grid=grid,input_hash="current")
        result=leave_candidates(data,source,"current")
        self.assertTrue(any("来院予定に入っていません" in reason for reason in result["reasons"]))
        self.assertEqual(result["groups"],[])
