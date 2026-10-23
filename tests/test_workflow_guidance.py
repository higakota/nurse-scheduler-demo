import html
import json
import re
import unittest
import test_scheduler as fixtures
from app import connect_db


class WorkflowGuidanceTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_monthly_entries_start_with_doctors_and_follow_input_order(self):
        from ui import STEPS, INPUT_TABS
        self.assertEqual([item[0] for item in STEPS], [item[0] for item in INPUT_TABS[:4]])
        for url in ("/?month=2026-02", "/monthly?month=2026-02"):
            page=self.client.get(url).get_data(as_text=True)
            links=re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',page,re.S)
            entries=[href for href,label in links if re.sub(r"<[^>]+>", "", label).strip().endswith("今月の入力")]
            self.assertTrue(entries)
            self.assertTrue(all("/doctors?month=2026-02" == html.unescape(href) for href in entries))

    def prepare_helpers(self):
        db=connect_db()
        for pid,advance in ((9,1),(10,0)):
            db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas,advance_help) VALUES (?,?, 'nurse','full',1,1,'ABC',?)",
                       (pid,"事前仮名" if advance else "依頼仮名",advance))
        db.execute("CREATE TABLE IF NOT EXISTS help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO help_availability VALUES (?,?)",("2026-02",json.dumps({"9_2026-02-02":"full"})))
        monthly=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        for pid in ("1","2","3"):
            monthly["targets"][pid]="28"
            monthly["wishes"][pid+"_2026-02-02"]="full"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(monthly),))
        db.commit();db.close()

    def fields(self):
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        return {key:html.unescape(re.search('name="'+key+'" value="([^"]*)"',page)[1])
                for key in ("csrf_token","fingerprint","result_token","seed_token")}

    def draft(self):
        return self.client.post("/schedule?month=2026-02",data=dict(self.fields(),mode="advance_draft"))

    def dump(self):
        db=connect_db()
        try:return list(db.iterdump())
        finally:db.close()

    def test_advance_days_are_not_counted_as_requested_visits(self):
        self.prepare_helpers()
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertIn("まず、不足を確認する",page)
        self.assertIn('value="advance_draft"',page)
        self.assertNotIn('value="help"',page)
        home=self.client.get("/?month=2026-02").get_data(as_text=True)
        self.assertNotIn("依頼したヘルプを勤務表に反映する",home)
        self.assertIn("/monthly?month=2026-02#availability",home)

    def test_draft_register_and_build_follow_the_same_workflow(self):
        self.prepare_helpers()
        response=self.draft()
        self.assertIn("不足を見て、ヘルプを相談する",response.get_data(as_text=True))
        self.assertIn('class="compact-help recreate-controls"',response.get_data(as_text=True))
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        fp=re.search('name="fingerprint" value="([^"]*)"',page)[1]
        with self.client.session_transaction() as state:token=state["csrf_token"]
        response=self.client.post("/help?month=2026-02",data=dict(csrf_token=token,fingerprint=fp,
            changes=json.dumps({"10_2026-02-02":"full"}),**{"continue":"build"}))
        self.assertIn("/schedule/manual?",response.location)
        self.assertIn("update_token=",response.location)
        page=self.client.get(response.location,follow_redirects=True).get_data(as_text=True)
        self.assertIn("保存前の変更確認",page)
        home=self.client.get("/?month=2026-02").get_data(as_text=True)
        self.assertIn("依頼したヘルプを勤務表に反映する",home)
        response=self.client.post("/schedule?month=2026-02",data=dict(self.fields(),mode="help",replace="yes"))
        self.assertEqual(response.status_code,302)
        page=self.client.get(response.location,follow_redirects=True).get_data(as_text=True)
        self.assertIn("保存前の変更確認",page)

    def test_resume_draft_is_read_only_and_skips_outdated_input(self):
        self.prepare_helpers()
        self.draft()
        before=self.dump()
        page=self.client.get("/schedule?month=2026-02&resume=1").get_data(as_text=True)
        self.assertIn("前回作成した仮表を表示",page)
        self.assertEqual(self.dump(),before)
        new=self.client.get("/schedule?month=2026-02&phase=plan").get_data(as_text=True)
        self.assertNotIn("前回作成した仮表を表示",new)
        db=connect_db()
        db.execute("UPDATE help_availability SET data=?",(json.dumps({"9_2026-02-02":"full","10_2026-02-02":"full"}),))
        db.commit();db.close()
        page=self.client.get("/schedule?month=2026-02&resume=1").get_data(as_text=True)
        self.assertNotIn("前回作成した仮表を表示",page)
        self.assertIn("登録したヘルプを反映する",page)
