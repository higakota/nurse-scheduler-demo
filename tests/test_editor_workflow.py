import html
import json
import re
import unittest
import test_scheduler as fixtures
from app import connect_db


class EditorWorkflowTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_generated_result_opens_preview_before_replacing_manual_draft(self):
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        db=connect_db()
        original=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        manual=dict(original,history=[],source="手動下書き",updated="old")
        manual["grid"]=[list(row) for row in original["grid"]]
        manual["grid"][1][0]="DR"
        db.execute("CREATE TABLE manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO manual_schedules VALUES ('2026-02',?)",(json.dumps(manual),))
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','nurse','full',0,1,'ABC')")
        db.commit();db.close()
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        toolbar=text.split('class="result-toolbar"',1)[1].split("</form>",1)[0]
        fields={key:html.unescape(re.search('name="'+key+'" value="([^"]*)"',toolbar)[1])
                for key in ("csrf_token","fingerprint","revision")}
        db=connect_db()
        before=list(db.iterdump())
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="import",source="generated"))
        preview=response.get_data(as_text=True)
        self.assertIn("まだ保存していません",preview)
        self.assertIn('id="manual-change-1-0"',preview)
        self.assertEqual(before,list(db.iterdump()))
        patch=html.unescape(re.search('name="patch" value="([^"]*)"',preview)[1])
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=patch,confirm="yes"))
        self.assertEqual(response.status_code,303)
        saved=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(len(saved["people"]),6)
        self.assertEqual(saved["grid"][1][0],"DD")
        self.assertEqual(saved["grid"][1][-1],"RR")
        self.assertEqual(saved["history"][-1]["grid"][1][0],"DR")
        db.close()

    def test_self_draft_does_not_show_previous_help_result_and_imports_correct_source(self):
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','nurse','full',1,1,'ABC')")
        db.commit();db.close()
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        db=connect_db()
        value=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        value["mode"]="help"
        value["people"].append(dict(id=9,name="ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        for rows in value["grid"]:rows.append("DD")
        raw=json.dumps(value)
        db.execute("UPDATE generated_schedules SET data=?",(raw,))
        db.commit();db.close()
        fields=fixtures.ScheduleRouteTest.fields(self)
        response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="draft"))
        text=response.get_data(as_text=True)
        self.assertIn("この仮表は自院スタッフのみです",text)
        self.assertNotIn('id="saved-result"',text)
        self.assertNotIn('id="saved-print"',text)
        self.assertIn('name="source" value="draft"',text)
        db=connect_db()
        seed=json.loads(db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0])
        self.assertFalse(any(person["is_help"] for person in seed["people"]))
        self.assertEqual(db.execute("SELECT data FROM generated_schedules").fetchone()[0],raw)
        db.close()

    def test_importing_self_draft_removes_help_only_after_preview_and_confirm(self):
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','nurse','full',1,1,'ABC')")
        db.commit();db.close()
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        manual=dict(saved,source="手動下書き",updated="old",history=[])
        manual["people"].append(dict(id=9,name="ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        for rows in manual["grid"]:rows.append("DD")
        db.execute("CREATE TABLE manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        raw=json.dumps(manual)
        db.execute("INSERT INTO manual_schedules VALUES ('2026-02',?)",(raw,))
        db.commit();db.close()
        response=self.client.post("/schedule?month=2026-02",data=dict(fixtures.ScheduleRouteTest.fields(self),mode="draft"))
        page=response.get_data(as_text=True)
        toolbar=page.split("この自院仮表を確認して編集へ",1)[0].rsplit("<form",1)[1]
        fields={key:html.unescape(re.search('name="'+key+'" value="([^"]*)"',toolbar)[1])
                for key in ("csrf_token","fingerprint","revision")}
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="import",source="draft"))
        preview=response.get_data(as_text=True)
        self.assertIn("まだ保存していません",preview)
        db=connect_db()
        self.assertEqual(db.execute("SELECT data FROM manual_schedules").fetchone()[0],raw)
        patch=html.unescape(re.search('name="patch" value="([^"]*)"',preview)[1])
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",patch=patch,confirm="yes"))
        self.assertEqual(response.status_code,303)
        current=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        helper=next(i for i,p in enumerate(current["people"]) if p["id"]==9)
        self.assertTrue(all(rows[helper]=="RR" for rows in current["grid"]))
        self.assertTrue(all(rows[helper]=="DD" for rows in current["history"][-1]["grid"]))
        db.close()

    def test_create_help_directly_from_new_draft_does_not_use_old_source_token(self):
        response=self.client.post("/schedule?month=2026-02",data=dict(fixtures.ScheduleRouteTest.fields(self),mode="draft"))
        for attempt in range(2):
            page=response.get_data(as_text=True)
            fields={key:html.unescape(re.search('name="'+key+'" value="([^"]*)"',page)[1])
                    for key in ("csrf_token","fingerprint","result_token","seed_token")}
            if attempt==0:
                response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="draft"))
            else:
                response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="help",help_source="draft"))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        self.assertIn("saved=1",response.location)
