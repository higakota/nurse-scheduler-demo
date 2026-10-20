import re
import unittest
from app import connect_db
from test_scheduler import ScheduleRouteTest


class SchedulePrintTest(unittest.TestCase):
    setUp = ScheduleRouteTest.setUp
    tearDown = ScheduleRouteTest.tearDown

    def post_trial(self):
        page = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields = {name: re.search('name="' + name + '" value="([^"]*)"', page)[1]
                  for name in ("csrf_token", "fingerprint", "result_token")}
        return self.client.post("/schedule?month=2026-02", data=dict(fields, mode="draft_six")).get_data(as_text=True)

    def test_trial_print_packet_contains_warning_periods_shortages_and_checklist(self):
        text = self.post_trial()
        packet = text.split('id="draft-print"', 1)[1]
        self.assertIn('data-print-packet="draft-print"', text)
        for label in ("7連勤以上は禁止", "ヘルプ相談用・不足の詳しい一覧",
                      "お母さんへの確認メモ", "6連勤になるスタッフ・期間", "金曜午後の通常業務",
                      "公休日数・非常勤の週上限"):
            self.assertIn(label, packet)
        self.assertNotIn('name="mode"', packet)
        db = connect_db()
        try:
            if db.execute("SELECT name FROM sqlite_master WHERE name='generated_schedules'").fetchone():
                self.assertIsNone(db.execute("SELECT data FROM generated_schedules WHERE month='2026-02'").fetchone())
        finally:
            db.close()

    def test_no_print_button_when_no_result_exists(self):
        text = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('data-print-packet=', text)
        self.assertNotIn('id="draft-print"', text)
