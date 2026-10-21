import html
import json
import re
import unittest
from unittest.mock import patch
import test_scheduler as fixtures
from app import connect_db
from schedule import read_snapshot
from help_shortages import write_reference


class RebalanceRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def fields(self):
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        return {key:html.unescape(re.search('name="'+key+'" value="([^"]*)"',page)[1])
                for key in ("csrf_token","fingerprint","result_token","seed_token")}

    def seed(self):
        self.assertEqual(self.client.post("/schedule?month=2026-02",
            data=fixtures.ScheduleRouteTest.fields(self)).status_code,302)
        db=connect_db()
        snapshot,fp,raw=read_snapshot(db,"2026-02")
        value=json.loads(raw)
        value.update(history=[],updated="manual",source="仮名の調整表")
        value["grid"][1][0]="RR"
        encoded=json.dumps(value)
        db.execute("CREATE TABLE manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO manual_schedules VALUES ('2026-02',?)",(encoded,))
        write_reference(db,snapshot,fp,[],source_kind="manual",source_raw=encoded)
        db.commit();db.close()
        return encoded

    def stored(self,table):
        db=connect_db()
        try:return db.execute("SELECT data FROM "+table+" WHERE month='2026-02'").fetchone()[0]
        finally:db.close()

    def test_fixed_help_fails_but_explicit_rebalance_succeeds_without_overwriting_manual(self):
        manual=self.seed()
        old_result=self.stored("generated_schedules")
        response=self.client.post("/schedule?month=2026-02",data=dict(self.fields(),mode="help",replace="yes"))
        self.assertIn("現在の条件では作成できません",response.get_data(as_text=True))
        self.assertEqual(self.stored("generated_schedules"),old_result)
        response=self.client.post("/schedule?month=2026-02",data=dict(self.fields(),mode="rebalance",replace="yes"))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        value=json.loads(self.stored("generated_schedules"))
        self.assertTrue(value["rebalanced"])
        self.assertEqual(value["grid"][1][0],"DD")
        self.assertEqual(self.stored("manual_schedules"),manual)
        page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("自院全体も調整した月間勤務表",page)
        # Applying the result still requires the existing change preview.
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        fields={key:html.unescape(re.search('name="'+key+'"[^>]*value="([^"]*)"',page)[1])
                for key in ("csrf_token","fingerprint","revision")}
        preview=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="import",source="generated")).get_data(as_text=True)
        self.assertIn("まだ保存していません",preview)
        self.assertEqual(self.stored("manual_schedules"),manual)
        changes=html.unescape(re.search('name="patch" value="([^"]*)"',preview)[1])
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=changes,confirm="yes"))
        self.assertEqual(response.status_code,303)
        applied=json.loads(self.stored("manual_schedules"))
        self.assertEqual(applied["grid"],value["grid"])
        self.assertEqual(applied["history"][-1]["grid"],json.loads(manual)["grid"])

    def test_old_source_and_source_changed_during_search_are_rejected(self):
        manual=self.seed()
        before=self.stored("generated_schedules")
        fields=self.fields()
        response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="rebalance",replace="yes",seed_token="old"))
        self.assertIn("自院の仮表が変更",response.get_data(as_text=True))
        self.assertEqual(self.stored("generated_schedules"),before)
        from scheduler_engine import generate as real
        def changed(snapshot,use_help,seconds):
            result=real(snapshot,use_help,seconds)
            db=connect_db()
            value=json.loads(manual);value["updated"]="newer"
            db.execute("UPDATE manual_schedules SET data=?",(json.dumps(value),));db.commit();db.close()
            return result
        with patch("schedule.generate",side_effect=changed):
            response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="rebalance",replace="yes"))
        self.assertIn("作成中に入力または結果",response.get_data(as_text=True))
        self.assertEqual(self.stored("generated_schedules"),before)

    def test_infeasible_rebalance_does_not_save_a_draft_as_a_completed_result(self):
        manual=self.seed()
        before=self.stored("generated_schedules")
        db=connect_db()
        data=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        for person in ("1","2"):
            data["targets"][person]="28";data["wishes"][person+"_2026-02-02"]="full"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(data),));db.commit();db.close()
        response=self.client.post("/schedule?month=2026-02",data=dict(self.fields(),mode="rebalance",replace="yes"))
        self.assertIn("現在の条件では作成できません",response.get_data(as_text=True))
        self.assertEqual(self.stored("generated_schedules"),before)
        self.assertEqual(self.stored("manual_schedules"),manual)
