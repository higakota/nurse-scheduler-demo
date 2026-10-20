import unittest
from test_scheduler import sample
from scheduler_engine import prepare, allocate, verify, consolidate_rest_days, split_rest, generate


class FullDayRestPreferenceTest(unittest.TestCase):
    def half_day_grid(self, forced=False):
        data = sample(open_days=(2,3), regular_count=5)
        data["monthly_settings"]["targets"]["1"] = "27"
        if forced:
            data["monthly_settings"]["wishes"].update({"1_2026-02-02":"pm","1_2026-02-03":"pm"})
        problem = prepare(data)
        grid = []
        for d, options in enumerate(problem["options"]):
            pairs = ["WW" if "WW" in choices else choices[0] for choices in options]
            if d in (1,2):
                pairs[0] = "WR"
            grid.append(allocate(problem,d,pairs))
        self.assertEqual(verify(problem,grid),[])
        return problem,grid

    def test_two_half_rests_are_combined_without_changing_targets_or_coverage(self):
        problem,grid = self.half_day_grid()
        self.assertEqual(sum(split_rest(day[0]) for day in grid),2)
        result = consolidate_rest_days(problem,grid,seconds=2)
        self.assertEqual(sum(split_rest(day[0]) for day in result),0)
        self.assertEqual(sum(day[0]=="RR" for day in result),27)
        self.assertEqual(verify(problem,result),[])
        self.assertEqual(grid[1][0],"DR")

    def test_requested_half_rests_are_preserved(self):
        problem,grid = self.half_day_grid(forced=True)
        result = consolidate_rest_days(problem,grid,seconds=2)
        self.assertEqual(result[1][0],"DR")
        self.assertEqual(result[2][0],"DR")
        self.assertEqual(verify(problem,result),[])

    def test_odd_half_day_target_still_supported(self):
        data = sample()
        data["monthly_settings"]["targets"]["1"] = "27.5"
        result = generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertTrue(split_rest(result["grid"][1][0]))
        self.assertEqual(verify(result["problem"],result["grid"]),[])

    def test_single_requested_half_rest_is_not_converted_to_full_rest(self):
        data = sample(open_days=(2,3), regular_count=5)
        data["monthly_settings"]["targets"]["1"] = "27"
        data["monthly_settings"]["wishes"]["1_2026-02-02"] = "pm"
        problem = prepare(data)
        grid = []
        for d, options in enumerate(problem["options"]):
            pairs = ["WW" if "WW" in choices else choices[0] for choices in options]
            if d in (1,2):
                pairs[0] = "WR"
            grid.append(allocate(problem,d,pairs))
        self.assertEqual(verify(problem,grid),[])
        result=consolidate_rest_days(problem,grid,seconds=2)
        self.assertEqual(result[1][0],"DR")
        self.assertEqual(result[2][0],"DR")
        self.assertEqual(verify(problem,result),[])

    def test_generated_non_requested_half_rests_do_not_require_extra_help(self):
        data=sample(open_days=(2,3),regular_count=5)
        data["monthly_settings"]["targets"]["1"]="27"
        data["staff"].append(dict(id=9,name="看護ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        data["help_availability"]={"9_2026-02-02":"full","9_2026-02-03":"full"}
        result=generate(data,use_help=True,seconds=3)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertFalse(any(p["is_help"] for p in result["problem"]["people"]))
        self.assertEqual(sum(split_rest(row[0]) for row in result["grid"]),0)
        self.assertEqual(verify(result["problem"],result["grid"]),[])

    def helper_for_whole_day(self):
        data=sample(open_days=(2,3),regular_count=4)
        data["monthly_settings"]["targets"]["1"]="27"
        data["monthly_settings"]["targets"]["2"]="27"
        data["monthly_settings"]["wishes"].update({"2_2026-02-02":"am","2_2026-02-03":"am"})
        data["staff"].append(dict(id=9,name="看護ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        data["help_availability"]={"9_2026-02-02":"am"}
        return data

    def test_helper_can_replace_two_automatic_halves_with_one_whole_rest(self):
        from scheduler_engine import automatic_half_rest,rest_plan_key
        data=self.helper_for_whole_day()
        own=generate(data,seconds=3)
        self.assertEqual(own["status"],"success",own["messages"])
        self.assertEqual(rest_plan_key(own)[1],2)
        helped=generate(data,use_help=True,seconds=5)
        self.assertEqual(helped["status"],"success",helped["messages"])
        self.assertEqual(rest_plan_key(helped)[1],0)
        self.assertGreater(rest_plan_key(helped)[2],0)
        index=next(i for i,p in enumerate(helped["problem"]["people"]) if p["id"]==1)
        self.assertEqual(sum(row[index]=="RR" for row in helped["grid"]),27)
        # 本人が希望した午前休みは変えない。
        index2=next(i for i,p in enumerate(helped["problem"]["people"]) if p["id"]==2)
        self.assertEqual(helped["grid"][1][index2],"RD")
        self.assertEqual(helped["grid"][2][index2],"RD")
        self.assertEqual(verify(helped["problem"],helped["grid"],max_full_days=helped["max_full_days"]),[])
        helper=next(i for i,p in enumerate(helped["problem"]["people"]) if p["id"]==9)
        self.assertEqual(helped["grid"][1][helper],"DR")
        self.assertTrue(all(row[helper]=="RR" for d,row in enumerate(helped["grid"]) if d!=1))

    def test_draft_shows_help_need_instead_of_spreading_unwanted_half_rests(self):
        from scheduler_engine import generate_draft,rest_plan_key
        result=generate_draft(self.helper_for_whole_day(),seconds=3)
        self.assertEqual(result["status"],"draft",result["messages"])
        self.assertEqual(rest_plan_key(result)[1],0)
        self.assertTrue(result["shortages"])
        self.assertEqual(verify(result["problem"],result["grid"],allow_shortages=True,max_full_days=result["max_full_days"]),[])

    def test_optional_helper_timeout_keeps_successful_own_plan(self):
        from unittest.mock import patch
        from scheduler_engine import _generate,rest_plan_key
        data=self.helper_for_whole_day()
        own=generate(data,seconds=3)
        def attempt(snapshot,use_help,seconds,**kwargs):
            if not use_help:
                return dict(own,messages=list(own["messages"]))
            return {"status":"unknown","problem":prepare(snapshot,True),"grid":None,"messages":["探索上限"],"shortages":[]}
        with patch("scheduler_engine._generate",side_effect=attempt):
            result=generate(data,use_help=True,seconds=3)
        self.assertEqual(result["status"],"success")
        self.assertEqual(result["grid"],own["grid"])
        self.assertEqual(rest_plan_key(result)[1],2)

    def test_unqualified_helper_does_not_replace_required_veteran(self):
        from scheduler_engine import rest_plan_key
        data=self.helper_for_whole_day()
        data["staff"][-1]["veteran"]=0
        result=generate(data,use_help=True,seconds=3)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(rest_plan_key(result)[1],2)
        self.assertEqual(rest_plan_key(result)[2],0)
        self.assertEqual(verify(result["problem"],result["grid"],max_full_days=result["max_full_days"]),[])
