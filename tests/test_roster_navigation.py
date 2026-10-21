import copy,html,json,re,unittest
from datetime import datetime,timedelta,timezone
import test_scheduler as fixtures
from app import connect_db
from schedule import digest

class RosterNavigationTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def generate(self):
        fields=fixtures.ScheduleRouteTest.fields(self)
        response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="self"))
        self.assertEqual(response.status_code,302)
        db=connect_db()
        value=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        db.close()
        return value

    def store(self,table,value):
        db=connect_db()
        db.execute("CREATE TABLE IF NOT EXISTS "+table+"(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO "+table+" VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",("2026-02",json.dumps(value)))
        db.commit();db.close()

    def dump(self):
        db=connect_db()
        try:return list(db.iterdump())
        finally:db.close()

    def test_return_to_creation_shows_saved_edits_instead_of_old_generated_grid(self):
        source=self.generate()
        manual=copy.deepcopy(source)
        manual.update(updated=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
        manual["grid"][1][0]="DR"
        self.store("manual_schedules",manual)
        before=self.dump()
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertIn('id="working-result"',page)
        self.assertNotIn('id="saved-result"',page)
        self.assertIn("編集・保存した勤務表",page)
        self.assertEqual(before,self.dump())

    def test_resume_draft_never_opens_other_completed_result(self):
        source=self.generate()
        draft=copy.deepcopy(source)
        draft.update(created="2020-01-01T00:00:00+00:00")
        self.store("manual_schedule_seeds",draft)
        before=self.dump()
        page=self.client.get("/schedule?month=2026-02&resume=1").get_data(as_text=True)
        self.assertIn("前回作成した仮表を表示",page)
        self.assertNotIn('id="saved-result"',page)
        self.assertEqual(before,self.dump())

    def test_creation_step_five_opens_exact_result_as_read_only_review(self):
        source=self.generate()
        old=copy.deepcopy(source);old["updated"]="2020-01-01T00:00:00+00:00";old["grid"][1][0]="RR"
        self.store("manual_schedules",old)
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        nav=page.split('class="journey-nav"',1)[1].split("</nav>",1)[0]
        link=html.unescape(re.search('href="([^"]+view_source=generated[^"]+)"',nav)[1])
        before=self.dump()
        review=self.client.get(link).get_data(as_text=True)
        self.assertIn("保存前の変更確認",review)
        self.assertIn("反映前の確認",review)
        self.assertIn("→",review)
        self.assertEqual(before,self.dump())
        # 間に再作成されたときは、代わりの表を勝手に開かない。
        source["notes"]=["再作成"]
        self.store("generated_schedules",source)
        blocked=self.client.get(link).get_data(as_text=True)
        self.assertIn("指定した勤務表は更新",blocked)
        self.assertNotIn('class="paper-grid"',blocked)
        self.assertNotIn('id="manual-form"',blocked)

    def test_new_generated_result_is_visible_as_pending_in_manual(self):
        source=self.generate()
        old=copy.deepcopy(source);old["updated"]="2020-01-01T00:00:00+00:00";old["grid"][1][0]="RR"
        self.store("manual_schedules",old)
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        self.assertIn("新しく作った表は、まだ反映していません",page)
        self.assertIn("view_source=generated",page)

    def test_failed_creation_does_not_show_previous_table_as_new_result(self):
        self.generate()
        fields=fixtures.ScheduleRouteTest.fields(self)
        page=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="self",fingerprint="old")).get_data(as_text=True)
        self.assertIn("別の画面で入力",page)
        self.assertNotIn('id="saved-result"',page)
        self.assertNotIn('id="saved-print"',page)

    def test_exact_source_review_save_and_return_preserve_the_selected_grid(self):
        source=self.generate()
        old=copy.deepcopy(source);old["updated"]="2020-01-01T00:00:00+00:00";old["grid"][1][0]="RR"
        self.store("manual_schedules",old)
        value=digest(json.dumps(source,sort_keys=True,ensure_ascii=False))
        page=self.client.get("/schedule/manual?month=2026-02&view_source=generated&view_token="+value).get_data(as_text=True)
        fields={key:html.unescape(re.search('name="'+key+'"[^>]*value="([^"]*)"',page)[1]) for key in ("csrf_token","fingerprint","revision","patch")}
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",confirm="yes"))
        self.assertEqual(response.status_code,303)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(saved["grid"],source["grid"])
        self.assertEqual(saved["history"][-1]["grid"],old["grid"])
        db.close()
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertIn('id="working-result"',page)
        self.assertNotIn('id="saved-result"',page)
