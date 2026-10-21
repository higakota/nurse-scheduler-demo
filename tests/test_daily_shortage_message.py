import unittest
import test_scheduler as fixtures
from scheduler_engine import prepare,daily_shortages_from_options
from schedule_display import concise_shortages


class DailyShortageMessageTest(unittest.TestCase):
    def summary(self,problem):
        return concise_shortages(daily_shortages_from_options(problem,1))

    def test_afternoon_nurse_count(self):
        problem=prepare(fixtures.sample(),use_help=True)
        problem["options"][1]=[("WR",),("WW",),("WW",),("RR",),("WW",)]
        self.assertEqual(self.summary(problem),[dict(date="2026-02-02",items=["午後：看護師1人不足"])])

    def test_technician_count_does_not_duplicate_nurse_count(self):
        problem=prepare(fixtures.sample(),use_help=True)
        problem["options"][1]=[("WW",),("WW",),("WW",),("RR",),("RR",)]
        self.assertEqual(self.summary(problem),[dict(date="2026-02-02",items=["午前・午後：他院の検査技師1人不足"])])

    def test_veteran_requirement_is_a_replacement_when_headcount_is_enough(self):
        data=fixtures.sample()
        for person in data["staff"]:
            person["veteran"]=0
        problem=prepare(data,use_help=True)
        problem["options"][1]=[("WW",)]*5
        self.assertEqual(self.summary(problem),[dict(date="2026-02-02",items=["午前・午後：ベテラン看護師1人への交代が必要"])])
