import html,json,re,unittest
from unittest.mock import patch
import test_scheduler as fixtures
import test_help_shortages as help_fixtures
from app import connect_db


class HelpAutoUpdateTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def prepare(self):
        help_fixtures.HelpShortagesTest.helper(self)
        help_fixtures.HelpShortagesTest.shortage(self)
        self.client.post("/schedule?month=2026-02",data=dict(fixtures.ScheduleRouteTest.fields(self),mode="draft"))

    def register(self,changes):
        page=self.client.get("/help?month=2026-02").get_data(as_text=True)
        self.assertIn('form="help-calendar-form" name="continue" value="build"',page)
        self.assertNotIn('href="/schedule?month=2026-02&amp;phase=build"',page)
        fp=re.search('name="fingerprint" value="([^"]*)"',page)[1]
        with self.client.session_transaction() as state:csrf=state["csrf_token"]
        return self.client.post("/help?month=2026-02",data=dict(csrf_token=csrf,fingerprint=fp,
            changes=json.dumps(changes),**{"continue":"build"}))

    def manual(self):
        db=connect_db()
        try:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedules'").fetchone():return None
            row=db.execute("SELECT data FROM manual_schedules WHERE month='2026-02'").fetchone()
            return row[0] if row else None
        finally:db.close()

    def test_save_visits_goes_straight_to_updated_review_then_confirmed_save(self):
        self.prepare()
        response=self.register({"9_2026-02-02":"full"})
        self.assertEqual(response.status_code,302)
        self.assertIn("update_token=",response.location)
        self.assertIsNone(self.manual())
        page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("保存前の変更確認",page)
        self.assertIn('name="input_priority" value="yes"',page)
        self.assertIsNone(self.manual())
        # 再読込しても勤務表を勝手に保存しない。
        again=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("保存前の変更確認",again)
        self.assertIsNone(self.manual())
        fields={k:html.unescape(re.search('name="'+k+'" value="([^"]*)"',again)[1])
                for k in ("csrf_token","fingerprint","revision","patch","input_priority")}
        result=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="save",confirm="yes"))
        self.assertEqual(result.status_code,303)
        saved=json.loads(self.manual())
        i=next(i for i,p in enumerate(saved["people"]) if p["id"]==9)
        self.assertEqual(saved["grid"][1][i],"DD")
        from help_shortages import shortages_from_source
        from schedule import read_snapshot
        db=connect_db()
        try:
            snapshot,_,_=read_snapshot(db,"2026-02")
            self.assertEqual(shortages_from_source(snapshot,json.dumps(saved)),[])
        finally:db.close()

    def test_already_registered_visits_can_be_reflected_without_new_changes(self):
        self.prepare()
        self.register({"9_2026-02-02":"full"})
        response=self.register({})
        page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("保存前の変更確認",page)
        self.assertIsNone(self.manual())

    def test_failed_update_keeps_saved_visits(self):
        self.prepare()
        response=self.register({"9_2026-02-02":"full"})
        with patch("roster_update.update_patch",side_effect=ValueError("入力を確認してください")):
            page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("来院予定は保存済みです",page)
        self.assertIsNone(self.manual())
        db=connect_db()
        try:self.assertEqual(json.loads(db.execute("SELECT data FROM help_availability").fetchone()[0]),{"9_2026-02-02":"full"})
        finally:db.close()

    def test_changed_input_after_registration_is_not_silently_used(self):
        self.prepare()
        response=self.register({"9_2026-02-02":"full"})
        db=connect_db()
        db.execute("UPDATE staff SET name=? WHERE id=1",("変更後仮名",))
        db.commit();db.close()
        with patch("roster_update.update_patch") as calculate:
            page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("登録後に入力または勤務表が変更",page)
        calculate.assert_not_called()

    def test_unrequested_and_non_ascii_tokens_never_start_an_update(self):
        self.prepare()
        for token in ("invalid","不正"):
            with patch("roster_update.update_patch") as calculate:
                response=self.client.get("/schedule/manual",query_string=dict(month="2026-02",update_token=token))
            self.assertEqual(response.status_code,200)
            self.assertIn("更新の確認画面を開き直して",response.get_data(as_text=True))
            calculate.assert_not_called()
