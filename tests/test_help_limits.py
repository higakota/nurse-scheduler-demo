import json
import re
import unittest
import test_scheduler as fixtures
from app import connect_db
from scheduler_engine import prepare, allocate, verify, generate, consolidate_rest_days
from schedule_improvement import improve_jointly
from help_limits import helper_count, helper_demand, visit_counts


class PreferredDailyHelpTest(unittest.TestCase):
    def data(self):
        data=fixtures.sample(regular_count=3)
        for i,role in ((9,"nurse"),(10,"technician"),(11,"nurse")):
            data["staff"].append(dict(id=i,name="ヘルプ仮名"+str(i),role=role,employment="full",veteran=1,is_help=1,allowed_areas="C" if role=="technician" else "ABC"))
            data["help_availability"][str(i)+"_2026-02-02"]="full"
        return data

    def test_distinct_people_are_counted_across_morning_and_afternoon(self):
        people=[dict(is_help=1)]*3
        self.assertEqual(helper_count(people,["DR","RD","RR"]),2)
        self.assertEqual(helper_count(people,["DD","DD","DD"]),3)
        self.assertEqual(visit_counts({"9_2026-02-02":"am","10_2026-02-02":"pm","11_2026-02-02":"full"},{"9","10","11"})["2026-02-02"],3)

    def test_allocator_and_independent_verifier_allow_three_helpers_when_needed(self):
        problem=prepare(self.data(),use_help=True)
        pairs=["WW","WW","WW","WW","WW","WW","WW"]
        self.assertIsNotNone(allocate(problem,1,pairs))
        grid=[tuple("RR" for _ in problem["people"]) for _ in problem["days"]]
        grid[1]=("DD","DD","DD","CC","DD","CC","DD")
        self.assertEqual(verify(problem,grid),[])
        grid[1]=("DD","DD","DD","CC","DR","RC","RD")
        self.assertFalse(any("1日2人" in error for error in verify(problem,grid,allow_shortages=True)))

    def test_generator_can_use_three_helpers_if_own_staff_cannot_cover(self):
        data=self.data()
        data["staff"][5]["role"]="nurse"
        data["staff"][5]["allowed_areas"]="ABC"
        for i in (1,2,3):
            data["monthly_settings"]["targets"][str(i)]="28"
            data["monthly_settings"]["wishes"][str(i)+"_2026-02-02"]="full"
        result=generate(data,use_help=True,seconds=3)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(helper_count(result["problem"]["people"],result["grid"][1]),3)
        self.assertEqual(verify(result["problem"],result["grid"],max_full_days=result.get("max_full_days",5)),[])

    def test_draft_spreads_equal_total_shortages_to_stay_within_two_helpers(self):
        data=fixtures.sample(open_days=(2,24),regular_count=6)
        for i in range(1,8):
            data["monthly_settings"]["targets"][str(i)]="27" if i<=4 else "26"
        problem=prepare(data)
        for d in (1,23):problem["requirements"][d]=((3,3,1),(3,3,1))
        grid=[tuple(["RR"]*7) for _ in problem["days"]]
        grid[1]=allocate(problem,1,["WW"]*7,partial=True)
        grid[23]=allocate(problem,23,["RR"]*4+["WW"]*3,partial=True)
        self.assertEqual(helper_demand(problem,23,grid[23]),4)
        self.assertEqual(verify(problem,grid,allow_shortages=True,max_full_days=5),[])
        result=improve_jointly(problem,grid,allow_shortages=True,max_full_days=5,seconds=2)
        self.assertLessEqual(max(helper_demand(problem,d,result[d]) for d in (1,23)),2)
        self.assertEqual(verify(problem,result,allow_shortages=True,max_full_days=5),[])
        combined=consolidate_rest_days(problem,result,allow_shortages=True,prefer_whole_rest=True)
        self.assertLessEqual(max(helper_demand(problem,d,combined[d]) for d in (1,23)),2)
        self.assertEqual(grid[23][0],"RR")


class DailyHelpRegistrationTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_three_visitors_can_be_registered_and_reduced_to_two(self):
        db=connect_db()
        for i,role in ((9,"nurse"),(10,"technician"),(11,"nurse")):
            db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (?,?,?,'full',0,1,?)",
                       (i,"ヘルプ仮名"+str(i),role,"C" if role=="technician" else "ABC"))
        db.commit();db.close()
        text=self.client.get("/help?month=2026-02").get_data(as_text=True)
        fp=re.search('name="fingerprint" value="([^"]*)"',text)[1]
        with self.client.session_transaction() as state:token=state["csrf_token"]
        changes={"9_2026-02-02":"am","10_2026-02-02":"full","11_2026-02-02":"pm"}
        response=self.client.post("/help?month=2026-02",data=dict(csrf_token=token,fingerprint=fp,changes=json.dumps(changes)))
        self.assertEqual(response.status_code,302)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM help_availability WHERE month='2026-02'").fetchone()[0])
        db.close()
        self.assertEqual(saved,changes)
        text=self.client.get("/help?month=2026-02").get_data(as_text=True)
        fp=re.search('name="fingerprint" value="([^"]*)"',text)[1]
        response=self.client.post("/help?month=2026-02",data=dict(csrf_token=token,fingerprint=fp,changes=json.dumps({"11_2026-02-02":""})))
        self.assertEqual(response.status_code,302)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM help_availability WHERE month='2026-02'").fetchone()[0])
        db.close()
        changes.pop("11_2026-02-02")
        self.assertEqual(saved,changes)

    def test_draft_explains_three_helpers_are_allowed_without_changing_wishes(self):
        db=connect_db()
        monthly=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        for i in range(1,5):
            monthly["targets"][str(i)]="28"
            monthly["wishes"][str(i)+"_2026-02-02"]="full"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(monthly),))
        db.commit();db.close()
        response=self.client.post("/schedule?month=2026-02",data=dict(fixtures.ScheduleRouteTest.fields(self),mode="draft"))
        text=response.get_data(as_text=True)
        self.assertIn("必要な場合は3人以上でも作成できます",text)
        self.assertNotIn("1日2人まで",text)
        self.assertIn("2026-02-02",text)
        db=connect_db()
        source=json.loads(db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0])
        db.close()
        self.assertEqual(source["grid"][1][:4],["RR"]*4)
