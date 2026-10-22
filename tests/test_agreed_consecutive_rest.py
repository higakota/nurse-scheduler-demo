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


    def test_joint_adjustment_runs_during_agreement_and_can_be_fully_cancelled(self):
        snapshot=sample(open_days=(2,3,4,5,6,7,9),regular_count=5)
        days=[f"2026-02-{d:02}" for d in range(1,29)]
        grid=[["RR"]*6 for _ in days]
        for d,active in zip(range(1,7),((1,2),(3,4),(1,3),(2,4),(1,4),(2,3))):
            grid[d][0]="RR" if d==3 else "DO" if d==5 else "DD"
            for i in active:
                grid[d][i]="DO" if d==5 else "DD"
            grid[d][5]="CO" if d==5 else "CC"
        grid[8]=["DD"]*5+["CC"]
        snapshot["staff"].append(dict(id=9,name="依頼済みヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,advance_help=0,allowed_areas="ABC"))
        snapshot["help_availability"]["9_2026-02-09"]="full"
        for d,row in enumerate(grid):
            row.append("DD" if d==8 else "RR")
        snapshot["monthly_settings"]["targets"]={str(p["id"]):str(sum(pair[i].count("R") for pair in grid)/2)
                                                for i,p in enumerate(snapshot["staff"])}
        snapshot["monthly_settings"]["wishes"]["1_2026-02-04"]="full"
        base=dict(days=days,people=snapshot["staff"],grid=grid)
        updated,adjusted,changes,audit=change_plan(snapshot,base,"1","2026-02-04","full","","")
        self.assertTrue(audit["global_adjustment"])
        self.assertTrue(all(new[-1]==old[-1] for new,old in zip(adjusted,grid)))
        self.assertFalse(any(r["name"]==snapshot["staff"][0]["name"] for r in six_day_runs(prepare(updated,True),adjusted)))
        self.assertTrue(any(c.get("staff_id") for c in changes))
        self.assertEqual(adjusted[3][0],"DD")
        self.assertEqual(verify(prepare(updated,True),adjusted,max_full_days=6),[])
        restored,restored_grid,_,_=cancellation_plan(updated,dict(base,grid=adjusted),0)
        self.assertEqual(restored_grid,grid)
        self.assertEqual(restored["monthly_settings"]["wishes"],snapshot["monthly_settings"]["wishes"])
        changed=next(c for c in changes if c.get("staff_id"))
        j=next(i for i,p in enumerate(base["people"]) if str(p["id"])==changed["staff_id"])
        tampered=copy.deepcopy(adjusted)
        tampered[days.index(changed["day"])][j]=changed["before"]
        with self.assertRaises(ValueError):
            cancellation_plan(updated,dict(base,grid=tampered),0)
