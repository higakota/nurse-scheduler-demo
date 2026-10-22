import json
import re
import unittest
from scheduler_engine import prepare, generate, allocate, verify, six_day_runs
from test_scheduler import sample
from test_weekly_work import month_sample
import test_scheduler as fixtures
from app import connect_db


def helper():
    return dict(id=9,name="ヘルプ仮名",role="nurse",employment="part",veteran=1,
                is_help=1,allowed_areas="ABC",weekly_limit_units=0)


class HelperManagementScopeTest(unittest.TestCase):
    def test_no_helper_history_weekly_or_monthly_target_is_required(self):
        data=month_sample("2026-04",[1])
        data["staff"].append(helper())
        data["help_availability"]={"9_2026-04-01":"full"}
        for staff_id in ("1","2"):
            data["monthly_settings"]["wishes"][staff_id+"_2026-04-01"]="full"
            data["monthly_settings"]["targets"][staff_id]="30"
        problem=prepare(data,use_help=True)
        self.assertEqual(problem["errors"],[])
        i=next(i for i,p in enumerate(problem["people"]) if p["is_help"])
        self.assertNotIn(i,problem["regular"])
        self.assertNotIn(i,problem["weekly"]["parts"])
        self.assertEqual(problem["tails"][i],0)
        result=generate(data,use_help=True,seconds=3)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertTrue(any(p["is_help"] for p in result["problem"]["people"]))
        self.assertEqual(verify(result["problem"],result["grid"],max_full_days=5),[])

    def test_helper_run_is_excluded_but_visits_and_own_runs_are_checked(self):
        data=sample(open_days=(2,3,4,5,6,7))
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="28"
        data["staff"].append(helper())
        data["help_availability"]={f"9_2026-02-{d:02d}":"full" for d in (2,3,4,5,6,7)}
        data["monthly_settings"]["meetings"]=[dict(id="h",date="2026-02-06",title="会議仮名",participants=["9"],start="",end="")]
        problem=prepare(data,use_help=True)
        self.assertEqual(problem["errors"],[])
        grid=[]
        for d,day in enumerate(problem["days"]):
            pair="WM" if day=="2026-02-06" else ("WW" if 2<=d+1<=7 else "RR")
            grid.append(allocate(problem,d,["RR"]*5+[pair],partial=True))
        self.assertEqual(verify(problem,grid,allow_shortages=True,max_full_days=5),[])
        self.assertEqual(six_day_runs(problem,grid),[])
        bad=list(grid)
        bad[0]=tuple(["RR"]*5+["DD"])
        self.assertTrue(any("来院予定" in e for e in verify(problem,bad,allow_shortages=True,max_full_days=5)))
        bad=list(grid)
        for d in range(1,7):
            row=list(bad[d])
            row[0]="DO" if d==5 else "DD"
            bad[d]=tuple(row)
        self.assertTrue(any("5連勤" in e for e in verify(problem,bad,allow_shortages=True,max_full_days=5)))


class HelperHistoryRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_helper_history_is_hidden_and_existing_data_preserved(self):
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','nurse','full',1,1,'ABC')")
        old=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])
        old["history"]["9_2026-01-31"]="full"
        db.execute("UPDATE leave_history SET data=?",(json.dumps(old),))
        db.commit()
        db.close()
        page=self.client.get("/leave-history?month=2026-02").get_data(as_text=True)
        self.assertNotIn('id="history_9_',page)
        fields={key:re.search('name="'+key+'" value="([^"]*)"',page)[1] for key in ("csrf_token","fingerprint")}
        response=self.client.post("/leave-history?month=2026-02",data=dict(fields,action="history_save"))
        self.assertEqual(response.status_code,302)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])
        db.close()
        self.assertEqual(saved["history"]["9_2026-01-31"],"full")
