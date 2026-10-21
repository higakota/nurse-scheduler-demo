import copy
import unittest
import test_scheduler as fixtures
from app import app
from flask import render_template
from scheduler_engine import generate
from leave_candidates import leave_candidates
from schedule_display import monthly_display


class SimplerScheduleTest(unittest.TestCase):
    def test_helper_absence_is_blank_and_half_visit_is_explicit(self):
        people=[dict(id=1,name="ヘルプ仮名",is_help=1,employment="",role="nurse")]
        grid=[["RR"],["DR"],["RD"],["DD"]]
        before=copy.deepcopy(grid)
        result=monthly_display(["2026-02-02","2026-02-03","2026-02-04","2026-02-05"],people,grid)
        cells=result["rows"][0]["cells"]
        self.assertEqual([c["label"] for c in cells],["","午前","午後","日"])
        self.assertEqual(cells[0]["detail"],"")
        self.assertEqual(cells[0]["hint"],"来院なし")
        self.assertNotIn("R",cells[1]["detail"])
        self.assertEqual(grid,before)

    def creation(self,outcome=None):
        with app.test_request_context("/schedule?month=2026-02"):
            return render_template("_schedule_creation.html",month="2026-02",help_count=0,
                                   fingerprint="fp",result_token="r",seed_token="s",outcome=outcome)

    def test_six_day_option_only_shown_for_remaining_shortages(self):
        self.assertNotIn("6連勤を含めて組み直す",self.creation())
        text=self.creation(dict(status="infeasible",shortages=[{"missing":1}]))
        self.assertEqual(text.count('value="draft_six"'),1)
        self.assertNotIn('value="six"',text)
        self.assertNotIn("6連勤を含めて組み直す",self.creation(dict(status="draft",shortages=[])))

    def source(self,data):
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        return dict(days=result["problem"]["days"],people=result["problem"]["people"],
                    grid=result["grid"],input_hash="current")

    def test_morning_leave_is_suggested_when_afternoon_is_full(self):
        import json
        data=fixtures.sample(regular_count=4)
        data["doctor_plans"]["2026-02-02"]["pm"]=["医師仮名1","医師仮名2"]
        data["coverage_settings"]["2026-02-02_pm"]={"c":1,"doctors":["医師仮名1","医師仮名2"]}
        data["doctor_raw"]=json.dumps(data["doctor_plans"],ensure_ascii=False)
        data["doctor_plan_reviews"]["data"]=data["doctor_raw"]
        source=self.source(data)
        before=copy.deepcopy((data,source))
        result=leave_candidates(data,source,"current")
        groups={g["period"]:g["days"] for g in result["groups"]}
        self.assertTrue(groups["am"])
        self.assertEqual(groups["pm"],[])
        self.assertEqual(groups["full"],[])
        self.assertEqual((data,source),before)

    def test_technician_morning_paid_does_not_create_afternoon_only_work(self):
        data=fixtures.sample(regular_count=5)
        result=leave_candidates(data,self.source(data),"current")
        ids={g["period"]:{p["id"] for day in g["days"] for p in day["people"]} for g in result["groups"]}
        self.assertNotIn(6,ids["am"])
        self.assertNotIn(6,ids["full"])
        self.assertNotIn(6,ids["pm"])

    def test_meeting_days_excluded_from_all_leave_periods(self):
        data=fixtures.sample(regular_count=5)
        data["monthly_settings"]["meetings"]=[dict(id="meeting",date="2026-02-02",title="仮名会議",participants=["2"])]
        result=leave_candidates(data,self.source(data),"current")
        self.assertTrue(all(not group["days"] for group in result["groups"]))
