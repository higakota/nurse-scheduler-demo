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
        self.assertIn("来院予定 1件",controls)
        self.assertIn("登録済みのヘルプは使いません",controls)
        self.assertEqual(before,list(db.iterdump()))
        db.close()

    def test_without_visits_explains_how_to_enable_help_action(self):
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('name="mode" value="help"',text)
        self.assertIn("来院予定を保存",text)
        self.assertIn("スタッフ登録だけでは勤務に含めません",text)
