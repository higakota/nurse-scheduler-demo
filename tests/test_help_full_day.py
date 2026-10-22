import json
import unittest
import test_scheduler as fixtures
from scheduler_engine import generate, verify
from fixed_help import generate_fixed_help


class FullDayHelpTest(unittest.TestCase):
    def data(self, day=2, period="full"):
        data=fixtures.sample(open_days=(day,),regular_count=3)
        text=f"2026-02-{day:02d}"
        data["monthly_settings"]["wishes"]["1_"+text]="pm" if day != 6 else "am"
        data["monthly_settings"]["targets"]["1"]="27.5"
        data["staff"].append(dict(id=9,name="看護ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        data["help_availability"]={"9_"+text:period}
        return data

    def helper_pair(self, result, day=2):
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(verify(result["problem"],result["grid"],max_full_days=result.get("max_full_days",5)),[])
        i=next(i for i,p in enumerate(result["problem"]["people"]) if p["id"]==9)
        return result["grid"][day-1][i]

    def test_full_day_approval_is_not_cut_to_afternoon_only(self):
        data=self.data()
        self.assertEqual(self.helper_pair(generate(data,use_help=True,seconds=3)),"DD")

    def test_afternoon_only_approval_is_not_extended(self):
        data=self.data(period="pm")
        self.assertEqual(self.helper_pair(generate(data,use_help=True,seconds=3)),"RD")

    def test_friday_full_approval_includes_afternoon_ordinary_work(self):
        data=self.data(day=6)
        self.assertEqual(self.helper_pair(generate(data,use_help=True,seconds=3),day=6),"DO")

    def test_fixed_own_roster_is_maintained_while_helper_works_full_day(self):
        data=self.data()
        people=[p for p in data["staff"] if not p["is_help"]]
        days=[f"2026-02-{d:02d}" for d in range(1,29)]
        grid=[["RR"]*len(people) for day in days]
        grid[1]=["DR","DD","DD","CC"]
        source=dict(days=days,people=people,grid=grid)
        result=generate_fixed_help(data,json.dumps(source),seconds=3)
        self.assertEqual(self.helper_pair(result),"DD")
        self.assertEqual(result["grid"][1][:4],tuple(grid[1]))
