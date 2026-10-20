import json
import re
import unittest
from app import connect_db
from test_scheduler import ScheduleRouteTest


class ScheduleComparisonTest(unittest.TestCase):
    setUp = ScheduleRouteTest.setUp
    tearDown = ScheduleRouteTest.tearDown

    def submit(self, mode):
        page = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields = {key: re.search('name="' + key + '" value="([^"]*)"', page)[1]
                  for key in ("csrf_token", "fingerprint", "result_token")}
        return self.client.post("/schedule?month=2026-02", data=dict(fields, mode=mode))

    def test_draft_and_print_have_same_comparison_scope(self):
        text = self.submit("draft").get_data(as_text=True)
        self.assertEqual(text.count('data-comparison-scope="draft"'), 2)
        self.assertIn('data-compare-schedule="draft"', text)
        self.assertIn("paper-request-row comparison-only", text)

    def test_completed_result_preserves_original_wishes_after_input_changes(self):
        response = self.submit("self")
        self.assertEqual(response.status_code, 302)
        db = connect_db()
        row = db.execute("SELECT data FROM generated_schedules WHERE month='2026-02'").fetchone()
        saved = json.loads(row[0])
        self.assertEqual(saved["comparison_inputs"], {"wishes": {}, "leaves": {}})
        self.assertTrue(saved["doctor_plans"])
        self.assertIn("meetings", saved["monthly_context"])
        monthly = json.loads(db.execute("SELECT data FROM monthly_settings WHERE month='2026-02'").fetchone()[0])
        monthly["wishes"]["1_2026-02-02"] = "full"
        db.execute("UPDATE monthly_settings SET data=? WHERE month='2026-02'", (json.dumps(monthly),))
        db.commit()
        db.close()
        text = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('data-compare-schedule="saved"', text)
        self.assertNotIn('class="paper-request-wish"', text)

    def test_legacy_stale_result_does_not_compare_against_current_wishes(self):
        self.submit("self")
        db = connect_db()
        saved = json.loads(db.execute("SELECT data FROM generated_schedules WHERE month='2026-02'").fetchone()[0])
        saved.pop("comparison_inputs")
        saved.pop("doctor_plans")
        saved.pop("monthly_context")
        saved["input_hash"] = "old"
        db.execute("UPDATE generated_schedules SET data=? WHERE month='2026-02'", (json.dumps(saved),))
        db.commit()
        db.close()
        text = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn("自動で作った月間勤務表", text)
        self.assertNotIn('data-compare-schedule="saved"', text)
        self.assertNotIn('id="saved-print"', text)
