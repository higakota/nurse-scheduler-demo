import unittest
import test_scheduler as fixtures
from scheduler_engine import generate, prepare, verify, draft_shortages


class ClinicalCapabilitiesTest(unittest.TestCase):
    def snapshot(self, can_c):
        data = fixtures.sample(regular_count=4)
        # C番2人=検査技師1人と看護師1人。看護師の合計4人。
        for value in data["coverage_settings"].values():
            value["c"] = 2
        for person in data["staff"]:
            if person["role"] == "nurse":
                person["allowed_areas"] = "ABC" if person["id"] in can_c else "AB"
        return data

    def test_one_eligible_nurse_is_enough_but_ab_nurse_cannot_replace_them(self):
        data = self.snapshot({1})
        result = generate(data, seconds=2)
        self.assertEqual(result["status"], "success", result["messages"])
        self.assertEqual(verify(result["problem"], result["grid"]), [])
        changed = [list(row) for row in result["grid"]]
        changed[1][0] = "RR"
        self.assertTrue(any("検査室を担当できる" in e for e in verify(result["problem"], changed)))
        deficits = draft_shortages(result["problem"], 1, changed[1])
        self.assertTrue(any(r["area"] == "検査室を担当できる看護師" for r in deficits))

    def test_total_headcount_does_not_hide_c_eligibility_shortage(self):
        result = generate(self.snapshot(set()), seconds=2)
        self.assertEqual(result["status"], "infeasible")
        self.assertTrue(any(r["area"] == "検査室を担当できる看護師" for r in result["shortages"]))

    def test_explicit_c_assignment_to_ineligible_nurse_is_rejected(self):
        result = generate(self.snapshot({1}), seconds=2)
        changed = [list(row) for row in result["grid"]]
        changed[1][1] = "CC"
        self.assertTrue(any("検査室を指定" in e for e in verify(result["problem"], changed)))
