import copy
import json
import unittest
from test_scheduler import sample
from scheduler_engine import prepare, WORK, verify, six_day_runs
from negotiated_leave import change_plan
from agreed_record_changes import cancellation_plan


class AgreedConsecutiveRestTest(unittest.TestCase):
    def roster(self,part=False):
        snapshot=sample(open_days=(2,3,4,5,6,7,9),regular_count=5)
        if part:
            snapshot["staff"][0].update(employment="part",weekly_limit_units=12)
            snapshot["monthly_settings"]["targets"].pop("1")
            snapshot["weekly_work_boundaries"]={f"1_2026-01-{d:02}":"0.0" for d in range(26,32)}
        else:
            snapshot["monthly_settings"]["targets"]["1"]="22"
        snapshot["monthly_settings"]["wishes"]["1_2026-02-04"]="pm" if part else "full"
        problem=prepare(snapshot,True)
        self.assertEqual(problem["errors"],[])
        grid=[]
        for d,day in enumerate(problem["days"]):
            row=[]
            for i,person in enumerate(problem["people"]):
                options=problem["options"][d][i]
                pair=max(options,key=lambda pair:sum(c in "WMO" for c in pair))
                row.append("".join(("C" if person["role"]=="technician" else "D") if c=="W" else c for c in pair))
            grid.append(row)
        if part:
            grid[8][0]="RR"
        return snapshot,dict(days=problem["days"],people=problem["people"],grid=grid)

    def test_part_time_agreed_half_day_does_not_leave_avoidable_six_run(self):
        snapshot,base=self.roster(True)
        before=copy.deepcopy(base)
        updated,grid,changes,audit=change_plan(snapshot,base,"1","2026-02-04","full","","")
        self.assertEqual(grid[3][0],"DD")
        self.assertFalse(any(r["name"]==snapshot["staff"][0]["name"] for r in six_day_runs(prepare(updated,True),grid)))
        self.assertTrue(audit["automatic_rest_dates"])
        self.assertEqual(base,before)
        self.assertTrue(all(new[1:]==old[1:] for new,old in zip(grid,base["grid"])))
        self.assertFalse(verify(prepare(updated,True),grid,allow_shortages=True,max_full_days=6))
        self.assertEqual(len({c["day"] for c in changes}),len(changes))
        from fixed_help import generate_fixed_help
        completed=generate_fixed_help(updated,json.dumps(dict(base,grid=grid)),seconds=2)
        self.assertEqual(completed["status"],"success",completed["messages"])
        self.assertEqual([list(row) for row in completed["grid"]],grid)
        restored,restored_grid,_,_=cancellation_plan(updated,dict(base,grid=grid),0)
        self.assertEqual(restored_grid,base["grid"])
        self.assertEqual(restored["monthly_settings"]["wishes"],snapshot["monthly_settings"]["wishes"])

    def test_full_time_rest_is_selected_to_break_run_and_keep_target(self):
        snapshot,base=self.roster()
        updated,grid,_,audit=change_plan(snapshot,base,"1","2026-02-04","full","","")
        self.assertFalse(any(r["name"]==snapshot["staff"][0]["name"] for r in six_day_runs(prepare(updated,True),grid)))
        self.assertEqual(audit["rest_after"],22)
        self.assertFalse(verify(prepare(updated,True),grid,allow_shortages=True,max_full_days=6))
