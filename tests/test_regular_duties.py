import unittest
from test_scheduler import sample
from scheduler_engine import prepare, generate, verify, rest_units
from weekly_rules import work_units


class RegularDutiesTest(unittest.TestCase):
    def data(self):
        data = sample(open_days=(6,))
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key] = "27"
        return data

    def test_friday_afternoon_duty_counts_as_work_not_clinical(self):
        result = generate(self.data(), seconds=2)
        self.assertEqual(result["status"], "success", result["messages"])
        self.assertTrue(all(pair[1] == "O" for pair in result["grid"][5]))
        self.assertEqual(verify(result["problem"], result["grid"]), [])
        self.assertEqual(rest_units("AO"), 0)
        self.assertEqual(work_units("AO"), 2)
        self.assertEqual(work_units("RO"), 1)

    def test_wishes_paid_closures_and_technician_restriction(self):
        data = self.data()
        data["monthly_settings"]["wishes"]["1_2026-02-06"] = "pm"
        data["leave_history"]["leaves"]["2_2026-02-06"] = "pm"
        problem = prepare(data)
        self.assertTrue(all(pair[1] == "R" for pair in problem["options"][5][0]))
        self.assertTrue(all(pair[1] == "P" for pair in problem["options"][5][1]))
        self.assertTrue(all(pair == "RR" for pair in problem["options"][12][0]))
        self.assertNotIn("RO", problem["options"][5][-1])
        self.assertIn("WO", problem["options"][5][-1])

    def test_duty_cannot_escape_full_day_consecutive_limit(self):
        result = generate(self.data(), seconds=2)
        grid = list(result["grid"])
        grid[:7] = [tuple("AO" for _ in result["problem"]["people"])] * 7
        errors = verify(result["problem"], grid, allow_shortages=True)
        self.assertTrue(any("連勤を超えています" in e for e in errors))
