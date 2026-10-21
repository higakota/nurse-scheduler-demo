import json
import unittest
import test_scheduler as fixtures
from app import connect_db

class ScheduleActionsTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_help_action_is_visible_without_expanding_details(self):
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help) VALUES (9,'看護ヘルプ仮名','nurse','full',1,1)")
        db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY,data TEXT)")
        db.execute("INSERT INTO help_availability VALUES ('2026-02',?)",(json.dumps({"9_2026-02-02":"am","999_2026-02-02":"full"}),))
        db.commit()
        before=list(db.iterdump())
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        controls=text.split('class="panel creation-controls"',1)[1].split("<details",1)[0]
        self.assertIn('name="mode" value="help"',controls)
        self.assertIn("ヘルプ込みで勤務表を作成",controls)
        self.assertIn("依頼済み 1件",controls)
        self.assertNotIn("登録済みのヘルプは使いません",controls)
        self.assertIn("調整用の仮表",controls)
        self.assertEqual(before,list(db.iterdump()))
        db.close()

    def test_without_visits_explains_how_to_enable_help_action(self):
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('name="mode" value="help"',text)
        self.assertIn("来院予定を登録",text)
        self.assertIn("スタッフ登録だけでは勤務に含めません",text)

    def test_creation_does_not_require_storage_checkbox(self):
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('type="checkbox" name="replace"',text)
        self.assertIn('type="hidden" name="replace" value="yes"',text)
        self.assertNotIn("保存済みの自動作成結果を置き換えます",text)

    def test_current_result_comes_before_closed_recreation_controls(self):
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertLess(text.index('id="saved-result"'),text.index('id="schedule-recreate"'))
        self.assertIn('<details class="compact-help recreate-controls" id="schedule-recreate">',text)
        self.assertNotIn("どの表にヘルプを加える？",text)
        self.assertIn('name="mode" value="draft"',text)

    def test_changed_inputs_keep_creation_controls_visible(self):
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        db=connect_db()
        db.execute("UPDATE staff SET name='看護仮名変更' WHERE id=1")
        db.commit();db.close()
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('id="schedule-recreate"',text)
        self.assertIn('class="panel creation-controls"',text)

    def test_explicit_manual_help_action_keeps_creation_controls_visible(self):
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        text=self.client.get("/schedule?month=2026-02&help_source=manual").get_data(as_text=True)
        self.assertNotIn('id="schedule-recreate"',text)
        self.assertIn('class="panel creation-controls"',text)

    def test_help_result_also_hides_creation_panel_by_default(self):
        fields=dict(fixtures.ScheduleRouteTest.fields(self),mode="help")
        response=self.client.post("/schedule?month=2026-02",data=fields)
        self.assertEqual(response.status_code,302)
        text=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("ヘルプ反映済み",text)
        self.assertLess(text.index('id="saved-result"'),text.index('id="schedule-recreate"'))
        self.assertIn('<details class="compact-help recreate-controls" id="schedule-recreate">',text)
