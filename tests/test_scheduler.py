import copy
import calendar
import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from app import app, connect_db
from doctor_import import IMPORT_VERSION
from scheduler_engine import generate, prepare, verify


def sample(open_days=(2,), regular_count=4):
    month="2026-02"
    people=[dict(id=i+1,name="看護"+str(i+1),role="nurse",employment="full",veteran=int(i<2),is_help=0,allowed_areas="ABC") for i in range(regular_count)]
    people.append(dict(id=regular_count+1,name="検査仮名",role="technician",employment="",veteran=0,is_help=0,allowed_areas="C"))
    doctors={}
    coverage={}
    closures={}
    for d in range(1,29):
        day=date(2026,2,d)
        text=day.isoformat()
        if d not in open_days and day.weekday()!=6:
            closures[text]="year_end"
        doctors[text]={"am":["医師仮名"],"pm":[] if day.weekday()==4 else ["医師仮名"]}
        for half in ("am","pm"):
            coverage[text+"_"+half]={"c":1,"doctors":["医師仮名"]}
    raw=json.dumps(doctors,ensure_ascii=False)
    targets={str(p["id"]):str(28-len(open_days)) for p in people}
    return dict(month=month,staff=people,doctor_plans=doctors,doctor_raw=raw,
                doctor_plan_reviews={"data":raw,"version":IMPORT_VERSION},
                coverage_settings=coverage,monthly_settings={"targets":targets,"wishes":{},"closures":closures,"meetings":[]},
                leave_history={"leaves":{},"history":{}},help_availability={},previous_closures={})


class SchedulerEngineTest(unittest.TestCase):
    def test_full_month_and_independent_validation(self):
        data=sample()
        outcome=generate(data,seconds=2)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertEqual(verify(outcome["problem"],outcome["grid"]),[])
        self.assertEqual(len(outcome["grid"]),28)
        bad=copy.deepcopy(outcome["grid"])
        bad[1]=tuple("RR" for _ in bad[1])
        self.assertTrue(verify(outcome["problem"],bad))

    def test_wish_and_paid_are_not_relaxed(self):
        data=sample()
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="am"
        data["leave_history"]["leaves"]["2_2026-02-02"]="full"
        outcome=generate(data,seconds=2)
        self.assertEqual(outcome["status"],"infeasible")
        self.assertTrue(outcome["shortages"])

    def test_half_paid_and_opposite_rest_count_one_day(self):
        data=sample()
        data["monthly_settings"]["targets"]["1"]="28"
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="pm"
        data["leave_history"]["leaves"]["1_2026-02-02"]="am"
        outcome=generate(data,seconds=2)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertEqual(outcome["grid"][1][0],"PR")
        self.assertEqual(verify(outcome["problem"],outcome["grid"]),[])

    def test_veteran_and_c_requirements(self):
        data=sample()
        for p in data["staff"]:
            p["veteran"]=0
        outcome=generate(data,seconds=1)
        self.assertEqual(outcome["status"],"infeasible")
        self.assertTrue(any("ベテラン" in row["area"] for row in outcome["shortages"]))

    def test_help_used_only_for_registered_half_and_no_target(self):
        data=sample(regular_count=3)
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="full"
        data["monthly_settings"]["targets"]["1"]="28"
        helper=dict(id=9,name="ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC")
        data["staff"].append(helper)
        self.assertEqual(generate(data,seconds=1)["status"],"infeasible")
        data["help_availability"]={"9_2026-02-02":"am"}
        self.assertEqual(generate(data,True,seconds=1)["status"],"infeasible")
        data["help_availability"]={"9_2026-02-02":"full"}
        outcome=generate(data,True,seconds=2)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertNotIn(4,outcome["problem"]["regular"])
        self.assertTrue(all(cell=="RR" for d,row in enumerate(outcome["grid"]) if d!=1 for cell in [row[-1]]))

    def test_missing_c_or_unreviewed_doctors_blocks(self):
        for key in ("coverage_settings","doctor_plan_reviews"):
            data=sample()
            data[key]={}
            self.assertEqual(generate(data,seconds=1)["status"],"input_error")

    def test_unknown_paid_closure_overlap_blocks(self):
        data=sample()
        data["leave_history"]["leaves"]["1_2026-02-03"]="full"
        self.assertEqual(generate(data,seconds=1)["status"],"input_error")

    def test_exact_target_failure_not_relabelled_as_specific_shortage(self):
        data=sample()
        data["monthly_settings"]["targets"]["1"]="0"
        outcome=generate(data,seconds=1)
        self.assertEqual(outcome["status"],"infeasible")
        self.assertEqual(outcome["shortages"],[])

    def test_search_limit_is_unknown_not_infeasible(self):
        data=sample()
        self.assertEqual(generate(data,seconds=0)["status"],"unknown")

    def test_meeting_forces_pm_exclusion_and_counts_as_work(self):
        data=sample(regular_count=5)
        data["monthly_settings"]["meetings"]=[{"id":"x","date":"2026-02-02","title":"会議","participants":["1"],"start":"13:15","end":"14:00"}]
        outcome=generate(data,seconds=2)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertEqual(outcome["grid"][1][0][1],"M")
        self.assertEqual(verify(outcome["problem"],outcome["grid"]),[])

    def test_strict_preference_can_reject_sixth(self):
        data=sample(open_days=(2,3,4,5,6,7))
        problem=prepare(data)
        grid=[tuple("RR" for _ in problem["people"]) for _ in problem["days"]]
        for d in range(1,7):
            grid[d]=tuple("AA" for _ in problem["people"])
        self.assertTrue(any("5連勤" in text for text in verify(problem,grid,max_full_days=5)))

    def test_realistic_month_with_fridays_and_meetings(self):
        opens=tuple(d for d in range(1,29) if date(2026,2,d).weekday()!=6)
        data=sample(open_days=opens)
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="8"
        data["monthly_settings"]["meetings"]=[{"id":"a","date":"2026-02-06","title":"会議","participants":["1"],"start":"13:15","end":"14:00"},
                                               {"id":"b","date":"2026-02-06","title":"会議2","participants":["1"],"start":"14:00","end":"15:00"}]
        outcome=generate(data,seconds=3)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertEqual(verify(outcome["problem"],outcome["grid"]),[])
        self.assertEqual(outcome["grid"][5][0][1],"M")
        for i in range(1,len(data["staff"])):
            self.assertIn(outcome["grid"][5][i][1],("R","O"))
        for index, day in enumerate(outcome["problem"]["days"]):
            if date.fromisoformat(day).weekday()==6:
                self.assertTrue(all(row=="RR" for row in outcome["grid"][index]))

    def test_half_work_and_paid_reset_full_consecutive_count(self):
        data=sample()
        problem=prepare(data)
        problem["tails"]=(6,)+problem["tails"][1:]
        grid=[tuple("RR" for _ in problem["people"]) for _ in problem["days"]]
        grid[0]=("AR",)+grid[0][1:]
        self.assertFalse(any("6連勤" in e for e in verify(problem,grid)))
        grid[0]=("AA",)+grid[0][1:]
        self.assertTrue(any("6連勤" in e for e in verify(problem,grid)))
        grid[0]=("AP",)+grid[0][1:]
        self.assertFalse(any("6連勤" in e for e in verify(problem,grid)))

    def test_previous_month_history_is_required_when_relevant(self):
        data=sample()
        # 3月は1日が日曜なので、月初が診療日の4月へ移して検証する。
        data["month"]="2026-04"
        data["doctor_plans"]={"2026-04-"+str(d).zfill(2):{"am":["医師"],"pm":["医師"]} for d in range(1,31)}
        data["doctor_raw"]=json.dumps(data["doctor_plans"])
        data["doctor_plan_reviews"]={"data":data["doctor_raw"],"version":IMPORT_VERSION}
        data["coverage_settings"]={day+"_"+half:{"c":1,"doctors":["医師"]} for day in data["doctor_plans"] for half in ("am","pm")}
        data["monthly_settings"]["closures"]={}
        outcome=generate(data,seconds=1)
        self.assertEqual(outcome["status"],"input_error")
        self.assertTrue(any("前月末勤務" in e for e in outcome["messages"]))

    def test_c_two_with_three_doctors_ignores_stored_c_one(self):
        data=sample(regular_count=6)
        data["doctor_plans"]["2026-02-02"]={"am":["医師1","医師2","医師3"],"pm":["医師1","医師2","医師3"]}
        data["doctor_raw"]=json.dumps(data["doctor_plans"],ensure_ascii=False)
        data["doctor_plan_reviews"]["data"]=data["doctor_raw"]
        outcome=generate(data,seconds=2)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        for half in (0,1):
            self.assertEqual(sum(row[half]=="D" for row in outcome["grid"][1]),6)
            self.assertEqual(sum(row[half]=="C" for row in outcome["grid"][1]),1)

    def test_technician_pm_only_and_meeting_collision_not_accepted(self):
        data=sample()
        data["monthly_settings"]["wishes"]["5_2026-02-02"]="am"
        problem=prepare(data)
        self.assertFalse(any(pair[1]=="W" for pair in problem["options"][1][4]))
        data["monthly_settings"]["meetings"]=[{"id":"a","date":"2026-02-02","title":"会議","participants":["1"],"start":"13:15","end":"14:00"},
                                               {"id":"b","date":"2026-02-02","title":"会議2","participants":["1"],"start":"13:30","end":"14:30"}]
        self.assertEqual(generate(data,seconds=1)["status"],"input_error")

    def test_month_boundary_six_full_days_is_hard_limit_end_to_end(self):
        from datetime import timedelta
        data=sample()
        data["month"]="2026-08"
        dates=[date(2026,8,d).isoformat() for d in range(1,32)]
        data["doctor_plans"]={day:{"am":["医師仮名"],"pm":["医師仮名"]} for day in dates}
        data["doctor_raw"]=json.dumps(data["doctor_plans"],ensure_ascii=False)
        data["doctor_plan_reviews"]={"data":data["doctor_raw"],"version":IMPORT_VERSION}
        data["monthly_settings"]["closures"]={day:"year_end" for day in dates[1:] if date.fromisoformat(day).weekday()!=6}
        data["monthly_settings"]["targets"]={str(p["id"]):"30" for p in data["staff"]}
        data["coverage_settings"]={day+"_"+half:{"c":1,"doctors":["医師仮名"]} for day in dates for half in ("am","pm")}
        first=date(2026,8,1)
        data["leave_history"]["history"]={str(p["id"])+"_"+(first-timedelta(days=offset)).isoformat():"full" for p in data["staff"] for offset in range(1,6)}
        outcome=generate(data,seconds=2,allow_six=True)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertTrue(outcome["six_day_runs"])
        for p in data["staff"]:
            data["leave_history"]["history"][str(p["id"])+"_2026-07-31"]="pm_paid"
        outcome=generate(data,seconds=2,allow_six=True)
        self.assertEqual(outcome["status"],"success",outcome["messages"])

    def test_meeting_outside_known_work_hours_is_not_assumed_allowed(self):
        data=sample()
        data["monthly_settings"]["meetings"]=[{"id":"a","date":"2026-02-02","title":"会議","participants":["1"],"start":"16:30","end":"18:00"}]
        outcome=generate(data,seconds=1)
        self.assertEqual(outcome["status"],"input_error")
        self.assertTrue(any("時間外勤務" in text for text in outcome["messages"]))

    def test_six_nurses_one_technician_two_doctors_and_friday_meetings(self):
        data=sample(open_days=tuple(d for d in range(1,29) if date(2026,2,d).weekday()!=6),regular_count=6)
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="10"
        for day in data["doctor_plans"]:
            for half in ("am","pm"):
                if data["doctor_plans"][day][half]:
                    data["doctor_plans"][day][half]=["医師仮名1","医師仮名2"]
                    data["coverage_settings"][day+"_"+half]={"c":1,"doctors":["医師仮名1","医師仮名2"]}
        data["doctor_raw"]=json.dumps(data["doctor_plans"],ensure_ascii=False)
        data["doctor_plan_reviews"]["data"]=data["doctor_raw"]
        data["monthly_settings"]["meetings"]=[{"id":str(d),"date":date(2026,2,d).isoformat(),"title":"会議","participants":[str(p["id"]) for p in data["staff"]],"start":"13:30","end":"14:30"} for d in range(1,29) if date(2026,2,d).weekday()==4]
        outcome=generate(data,seconds=3)
        self.assertEqual(outcome["status"],"success",outcome["messages"])
        self.assertEqual(verify(outcome["problem"],outcome["grid"]),[])

    def test_part_time_missing_weekly_limit_is_not_subject_to_monthly_rest(self):
        data=sample()
        data["staff"][0]["employment"]="part"
        data["monthly_settings"]["targets"].pop("1")
        before=copy.deepcopy(data)
        result=generate(data,seconds=1)
        self.assertEqual(result["status"],"input_error")
        self.assertTrue(any("週の勤務上限" in text for text in result["messages"]))
        self.assertNotIn(0,result["problem"]["regular"])
        self.assertFalse(any("看護1：月の休日日数" in text for text in result["messages"]))
        self.assertEqual(data,before)


class ScheduleRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=app.config["DATABASE"]
        app.config.update(TESTING=True,DATABASE=str(Path(self.temp.name)/"db.sqlite3"))
        self.client=app.test_client()
        data=sample()
        db=connect_db()
        for p in data["staff"]:
            db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (?,?,?,?,?,?,?)",
                       tuple(p[k] for k in ("id","name","role","employment","veteran","is_help","allowed_areas")))
        for table in ("monthly_settings","doctor_plans","coverage_settings","leave_history"):
            db.execute("CREATE TABLE "+table+"(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            raw=data["doctor_raw"] if table=="doctor_plans" else json.dumps(data[table],ensure_ascii=False)
            db.execute("INSERT INTO "+table+" VALUES (?,?)",(data["month"],raw))
        db.execute("CREATE TABLE doctor_plan_reviews(month TEXT PRIMARY KEY,data TEXT,version INTEGER)")
        db.execute("INSERT INTO doctor_plan_reviews VALUES (?,?,?)",(data["month"],data["doctor_raw"],IMPORT_VERSION))
        db.commit()
        db.close()

    def tearDown(self):
        app.config["DATABASE"]=self.old
        self.temp.cleanup()

    def fields(self):
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields={name:re.search('name="'+name+'" value="([^"]*)"',page)[1] for name in ("csrf_token","fingerprint","result_token")}
        return dict(fields,mode="self",replace="yes")

    def stored(self):
        db=connect_db()
        try:
            return db.execute("SELECT data FROM generated_schedules").fetchone()[0]
        finally:
            db.close()

    def test_save_and_input_change_warning_and_no_partial_overwrite(self):
        response=self.client.post("/schedule?month=2026-02",data=self.fields())
        self.assertEqual(response.status_code,302)
        before=self.stored()
        self.assertIn("自動で作った月間勤務表",self.client.get(response.location).get_data(as_text=True))
        stale=self.fields()
        db=connect_db()
        db.execute("UPDATE staff SET veteran=0")
        db.commit()
        db.close()
        response=self.client.post("/schedule?month=2026-02",data=stale)
        self.assertIn("別の画面",response.get_data(as_text=True))
        self.assertEqual(self.stored(),before)
        response=self.client.post("/schedule?month=2026-02",data=self.fields())
        self.assertIn("現在の条件では作成できません",response.get_data(as_text=True))
        self.assertEqual(self.stored(),before)
        self.assertNotIn("自動で作った月間勤務表", response.get_data(as_text=True))
        self.assertNotIn('id="saved-print"', response.get_data(as_text=True))

    def test_csrf_month_and_explicit_replacement(self):
        self.assertEqual(self.client.post("/schedule?month=2026-02",data={}).status_code,400)
        self.assertEqual(self.client.get("/schedule?month=2026-13").status_code,400)
        self.client.post("/schedule?month=2026-02",data=self.fields())
        before=self.stored()
        fields=self.fields()
        fields.pop("replace")
        response=self.client.post("/schedule?month=2026-02",data=fields)
        self.assertIn("置き換えることを確認",response.get_data(as_text=True))
        self.assertEqual(self.stored(),before)


    def test_inputs_changed_during_generation_do_not_overwrite_result(self):
        from unittest.mock import patch
        from scheduler_engine import generate as real_generate
        self.client.post("/schedule?month=2026-02",data=self.fields())
        before=self.stored()
        fields=self.fields()
        def changing_generate(snapshot, use_help, seconds):
            outcome=real_generate(snapshot,use_help,seconds)
            db=connect_db()
            try:
                db.execute("UPDATE staff SET name='変更後の仮名' WHERE id=1")
                db.commit()
            finally:
                db.close()
            return outcome
        with patch("schedule.generate",side_effect=changing_generate):
            response=self.client.post("/schedule?month=2026-02",data=fields)
        self.assertIn("作成中に入力",response.get_data(as_text=True))
        self.assertEqual(self.stored(),before)

class AggregateNurseStaffingTest(unittest.TestCase):
    def test_nurses_have_clinical_duty_without_abc_assignment(self):
        result = generate(sample(), seconds=2)
        self.assertEqual(result["status"], "success", result["messages"])
        for i, person in enumerate(result["problem"]["people"]):
            if person["role"] == "nurse":
                self.assertEqual(result["grid"][1][i], "DD")
        self.assertEqual(verify(result["problem"], result["grid"]), [])

    def test_missing_nurse_is_detected_with_technician_counted_for_c(self):
        data = sample()
        result = generate(data, seconds=2)
        altered = list(result["grid"])
        altered[1] = ("RR", "RR") + altered[1][2:]
        self.assertTrue(any("看護師の合計人数" in e for e in verify(result["problem"], altered)))

    def test_meetings_are_not_clinical_nurses(self):
        result = generate(sample(), seconds=2)
        changed = list(result["grid"])
        changed[1] = ("MM", "MM", "MM", "DD", "CC")
        self.assertTrue(any("看護師の合計人数" in e for e in verify(result["problem"], changed)))
