import copy
import unittest
from test_scheduler import sample, ScheduleRouteTest
from scheduler_engine import generate_draft, verify, draft_shortages


class DraftEngineTest(unittest.TestCase):
    def test_shortage_keeps_wishes_and_rest_targets(self):
        data = sample(regular_count=2)
        data["monthly_settings"]["wishes"]["1_2026-02-02"] = "full"
        data["monthly_settings"]["targets"]["1"] = "28"
        outcome = generate_draft(data, seconds=2)
        self.assertEqual(outcome["status"], "draft", outcome["messages"])
        self.assertEqual(outcome["grid"][1][0], "RR")
        self.assertTrue(outcome["shortages"])
        self.assertEqual(verify(outcome["problem"], outcome["grid"], allow_shortages=True), [])
        self.assertTrue(verify(outcome["problem"], outcome["grid"]))
        expected = [r for d, rows in enumerate(outcome["grid"]) for r in draft_shortages(outcome["problem"], d, rows)]
        self.assertEqual(outcome["shortages"], expected)

    def test_impossible_rest_target_is_explained(self):
        data = sample()
        data["monthly_settings"]["targets"]["1"] = "0"
        outcome = generate_draft(data, seconds=1)
        self.assertEqual(outcome["status"], "input_error")
        self.assertTrue(any("可能な休日日数" in m and "指定は0.0日" in m for m in outcome["messages"]))

    def test_unknown_inputs_are_not_filled(self):
        data = sample()
        data["monthly_settings"]["targets"] = {}
        self.assertEqual(generate_draft(data, seconds=1)["status"], "input_error")

    def test_technician_absence_is_reported_not_approved(self):
        data = sample()
        key = str(data["staff"][-1]["id"])
        data["monthly_settings"]["targets"][key] = "28"
        data["monthly_settings"]["wishes"][key + "_2026-02-02"] = "full"
        outcome = generate_draft(data, seconds=2)
        self.assertEqual(outcome["status"], "draft", outcome["messages"])
        self.assertTrue(any("他院の検査技師" in row["area"] for row in outcome["shortages"]))
        self.assertEqual(outcome["problem"]["technician_exceptions"], set())

    def test_draft_verification_still_rejects_personal_rule_violation(self):
        outcome = generate_draft(sample(), seconds=2)
        self.assertEqual(outcome["status"], "draft")
        bad = copy.deepcopy(outcome["grid"])
        bad[0] = tuple("AA" for _ in bad[0])
        self.assertTrue(verify(outcome["problem"], bad, allow_shortages=True))


class DraftRouteTest(unittest.TestCase):
    setUp = ScheduleRouteTest.setUp
    tearDown = ScheduleRouteTest.tearDown

    def test_preview_does_not_save_completed_result(self):
        import re
        from app import connect_db
        page = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields = {name: re.search('name="' + name + '" value="([^"]*)"', page)[1]
                  for name in ("csrf_token", "fingerprint", "result_token")}
        response = self.client.post("/schedule?month=2026-02", data=dict(fields, mode="draft"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("自院スタッフの仮配置", response.get_data(as_text=True))
        db = connect_db()
        try:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='generated_schedules'").fetchone()
            if exists:
                self.assertIsNone(db.execute("SELECT data FROM generated_schedules WHERE month='2026-02'").fetchone())
        finally:
            db.close()


class DraftMonthlySearchTest(unittest.TestCase):
    def test_monthly_draft_does_not_enumerate_every_staff_combination(self):
        from test_weekly_work import month_sample
        from datetime import date
        data = month_sample("2026-11", [d for d in range(1,31) if date(2026,11,d).weekday()!=6])
        for person in data["staff"]:
            data["monthly_settings"]["targets"][str(person["id"])] = "9"
        result = generate_draft(data, seconds=2)
        self.assertEqual(result["status"], "draft", result["messages"])
        self.assertEqual(verify(result["problem"], result["grid"], allow_shortages=True), [])

    def test_exact_rest_target_forces_six_full_days_with_specific_dates(self):
        from test_weekly_work import month_sample
        from datetime import date
        data = month_sample("2026-11", [d for d in range(1,31) if date(2026,11,d).weekday()!=6])
        data["monthly_settings"]["closures"].update({"2026-11-03": "holiday", "2026-11-23": "holiday"})
        for person in data["staff"]:
            data["monthly_settings"]["targets"][str(person["id"])] = "9"
        data["monthly_settings"]["wishes"].update({"1_2026-11-02": "full", "1_2026-11-05": "full"})
        data["leave_history"]["leaves"].update({"1_2026-11-06": "full", "1_2026-11-18": "full"})
        result = generate_draft(data, seconds=2)
        self.assertEqual(result["status"], "draft", result["messages"])
        result=generate_draft(data,seconds=2,allow_six=True)
        self.assertEqual(result["status"],"draft")
        self.assertTrue(any(run["start"] == "2026-11-09" and run["end"] == "2026-11-14" for run in result["six_day_runs"]))

class ExperimentalSixTest(unittest.TestCase):
    def sample_six(self):
        from test_weekly_work import month_sample
        from datetime import date
        data = month_sample("2026-11", [d for d in range(1,31) if date(2026,11,d).weekday()!=6])
        data["monthly_settings"]["closures"].update({"2026-11-03": "holiday", "2026-11-23": "holiday"})
        for person in data["staff"]:
            data["monthly_settings"]["targets"][str(person["id"])] = "9"
        data["monthly_settings"]["wishes"].update({"1_2026-11-02": "full", "1_2026-11-05": "full"})
        data["leave_history"]["leaves"].update({"1_2026-11-06": "full", "1_2026-11-18": "full"})
        return data

    def test_explicit_six_only_in_draft_and_reports_period(self):
        data = self.sample_six()
        self.assertEqual(generate_draft(data, seconds=2)["status"], "draft")
        result = generate_draft(data, seconds=2, experimental_six=True)
        self.assertEqual(result["status"], "draft", result["messages"])
        self.assertFalse(result["experimental"])
        self.assertIn({"name": data["staff"][0]["name"], "start": "2026-11-09", "end": "2026-11-14"}, result["six_day_runs"])
        self.assertEqual(verify(result["problem"], result["grid"], allow_shortages=True, max_full_days=6), [])
        self.assertTrue(any("5連勤" in e for e in verify(result["problem"], result["grid"], allow_shortages=True, max_full_days=5)))
        bad = list(result["grid"])
        for d in range(7):
            bad[d] = tuple("AA" for _ in result["problem"]["people"])
        self.assertTrue(any("6連勤" in e for e in verify(result["problem"], bad, allow_shortages=True, max_full_days=6)))

    def test_six_does_not_override_unknown_targets(self):
        data = self.sample_six()
        data["monthly_settings"]["targets"] = {}
        self.assertEqual(generate_draft(data, experimental_six=True)["status"], "input_error")


class ExperimentalSixRouteTest(unittest.TestCase):
    setUp = ScheduleRouteTest.setUp
    tearDown = ScheduleRouteTest.tearDown

    def test_explicit_trial_has_warning_and_is_not_saved(self):
        import re
        from app import connect_db
        page = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields = {name: re.search('name="' + name + '" value="([^"]*)"', page)[1]
                  for name in ("csrf_token", "fingerprint", "result_token")}
        response = self.client.post("/schedule?month=2026-02", data=dict(fields, mode="draft_six"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("未確認ルールを使用した仮検討", response.get_data(as_text=True))
        self.assertIn("7連勤以上は禁止", response.get_data(as_text=True))
        db = connect_db()
        try:
            if db.execute("SELECT name FROM sqlite_master WHERE name='generated_schedules'").fetchone():
                self.assertIsNone(db.execute("SELECT data FROM generated_schedules WHERE month='2026-02'").fetchone())
        finally:
            db.close()
