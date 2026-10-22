import unittest
import test_scheduler as fixtures
from scheduler_engine import generate
from leave_candidates import leave_candidates


class LeaveCandidatesTest(unittest.TestCase):
    def source(self, data):
        result = generate(data, seconds=2)
        self.assertEqual(result["status"], "success")
        return dict(days=result["problem"]["days"], people=result["problem"]["people"],
                    grid=result["grid"], input_hash="current")

    def test_spare_nurse_can_take_leave_without_writes(self):
        import copy
        data = fixtures.sample(regular_count=5)
        source = self.source(data)
        before = copy.deepcopy((data, source))
        candidates = leave_candidates(data, source, "current")
        self.assertTrue(candidates["days"])
        self.assertEqual((data, source), before)
        # 検査技師不在時の未承認の看護師のみ対応は提案しない。
        self.assertNotIn(6, [p["id"] for day in candidates["days"] for p in day["people"]])

    def test_minimum_staffing_or_stale_result_is_not_suggested(self):
        data = fixtures.sample(regular_count=3)
        source = self.source(data)
        self.assertEqual(leave_candidates(data, source, "current")["days"], [])
        self.assertTrue(leave_candidates(data, source, "changed")["message"])

    def test_sole_veteran_and_meeting_participant_are_not_candidates(self):
        data = fixtures.sample(regular_count=5)
        for person in data["staff"]:
            person["veteran"] = int(person["id"] == 1)
        data["monthly_settings"]["meetings"] = [
            {"id": "test", "date": "2026-02-02", "title": "仮名会議", "participants": ["2"]}
        ]
        source = self.source(data)
        candidates = leave_candidates(data, source, "current")
        ids = [p["id"] for day in candidates["days"] for p in day["people"]]
        self.assertNotIn(1, ids)
        self.assertNotIn(2, ids)

    def test_meeting_day_excludes_nonparticipants_but_other_days_remain(self):
        data=fixtures.sample(open_days=(2,3),regular_count=6)
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="26"
        data["monthly_settings"]["meetings"]=[
            {"id":"meeting","date":"2026-02-02","title":"仮名会議","participants":["2"]}
        ]
        source=self.source(data)
        candidates=leave_candidates(data,source,"current")
        dates=[row["date"] for row in candidates["days"]]
        self.assertNotIn("2026-02-02",dates)
        self.assertIn("2026-02-03",dates)
