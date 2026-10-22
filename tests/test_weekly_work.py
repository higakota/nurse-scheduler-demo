import copy
import json
import re
import sqlite3
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
import test_staff as staff_helpers
import test_scheduler as schedule_helpers
from app import app,connect_db
from doctor_import import IMPORT_VERSION
from scheduler_engine import generate,prepare,verify
from weekly_rules import boundary_dates,build_weekly,work_units,weekly_summary


def part_time(data,person=0,limit=2):
    p=data["staff"][person]
    p["employment"]="part"
    p["weekly_limit_units"]=limit
    data["monthly_settings"]["targets"].pop(str(p["id"]),None)
    data.setdefault("weekly_work_boundaries",{}).update({str(p["id"])+"_"+day.isoformat():"0.0" for day in boundary_dates(data["month"]) if day<date.fromisoformat(data["month"]+"-01")})
    return data


def month_sample(month,opens):
    data=schedule_helpers.sample()
    first=date.fromisoformat(month+"-01")
    import calendar
    dates=[first.replace(day=d).isoformat() for d in range(1,calendar.monthrange(first.year,first.month)[1]+1)]
    data["month"]=month
    data["doctor_plans"]={day:{"am":["医師"],"pm":[] if date.fromisoformat(day).weekday()==4 else ["医師"]} for day in dates}
    data["doctor_raw"]=json.dumps(data["doctor_plans"],ensure_ascii=False)
    data["doctor_plan_reviews"]={"data":data["doctor_raw"],"version":IMPORT_VERSION}
    data["coverage_settings"]={day+"_"+half:{"c":1,"doctors":["医師"]} for day in dates for half in ("am","pm")}
    data["monthly_settings"]["closures"]={day:"year_end" for day in dates if int(day[-2:]) not in opens and date.fromisoformat(day).weekday()!=6}
    data["monthly_settings"]["targets"]={str(p["id"]):str(len(dates)-len(opens)+0.5*sum(date(first.year,first.month,d).weekday()==4 for d in opens)) for p in data["staff"]}
    data["leave_history"]["history"]={str(p["id"])+"_"+(first-timedelta(days=n)).isoformat():"rest" for p in data["staff"] for n in range(1,6)}
    return data


class PartTimeEngineTest(unittest.TestCase):
    def test_week_limit_is_hard_and_resets_monday(self):
        data=part_time(schedule_helpers.sample(open_days=(2,3,9)),limit=2)
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        summary=weekly_summary(result["problem"],result["grid"])
        weeks={row["start"]:row for row in summary}
        self.assertEqual(weeks["2026-02-02"]["known"],1)
        self.assertEqual(weeks["2026-02-09"]["known"],1)
        self.assertEqual(verify(result["problem"],result["grid"]),[])
        bad=copy.deepcopy(result["grid"])
        bad[1]=("AA",)+bad[1][1:]
        bad[2]=("AA",)+bad[2][1:]
        self.assertTrue(any("週勤務上限" in e for e in verify(result["problem"],bad)))

    def test_half_paid_work_is_half_day_paid_itself_is_zero(self):
        data=part_time(schedule_helpers.sample(),limit=1)
        data["leave_history"]["leaves"]["1_2026-02-02"]="pm"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(work_units(result["grid"][1][0]),1)
        self.assertEqual(result["grid"][1][0][1],"P")
        data["leave_history"]["leaves"]["1_2026-02-02"]="full"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"PP")
        data["leave_history"]["leaves"]["1_2026-02-02"]="am"
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="pm"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(work_units(result["grid"][1][0]),0)

    def test_full_time_rest_target_not_sacrificed_to_part_time_preference(self):
        data=part_time(schedule_helpers.sample(),limit=1)
        data["monthly_settings"]["targets"]["2"]="28"
        self.assertEqual(generate(data,seconds=2)["status"],"infeasible")
        data["staff"][0]["weekly_limit_units"]=2
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][1],"RR")

    def test_part_time_technician_morning_work_requires_afternoon_technician(self):
        data=part_time(schedule_helpers.sample(),person=4,limit=1)
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"infeasible")
        data["technician_exceptions"]={"2026-02-02":True}
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertLessEqual(work_units(result["grid"][1][4]),1)
        self.assertEqual(verify(result["problem"],result["grid"]),[])

    def test_monthly_target_for_part_time_is_ignored_and_exact_week_not_required(self):
        data=part_time(schedule_helpers.sample(),limit=6)
        data["monthly_settings"]["targets"]["1"]="0"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertNotIn(0,result["problem"]["regular"])
        self.assertTrue(any(row["remaining"]>0 for row in weekly_summary(result["problem"],result["grid"])))

    def test_missing_previous_actual_is_not_assumed_rest(self):
        data=part_time(schedule_helpers.sample())
        data["weekly_work_boundaries"]={}
        result=generate(data,seconds=1)
        self.assertEqual(result["status"],"input_error")
        self.assertTrue(any("前月の実績" in e for e in result["messages"]))

    def test_decided_future_reserved_pending_future_reported(self):
        data=part_time(month_sample("2026-06",(29,30)),limit=4)
        data["weekly_work_boundaries"]["1_2026-07-01"]="1.0"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        last=weekly_summary(result["problem"],result["grid"])[-1]
        self.assertEqual(last["outside"],1)
        self.assertLessEqual(last["known"],2)
        self.assertIn("2026-07-02",last["pending"])
        self.assertNotIn("2026-07-01",last["pending"])
        self.assertNotIn("1_2026-07-02",data["weekly_work_boundaries"])

    def test_next_month_honors_decided_day_and_previous_actual(self):
        data=part_time(month_sample("2026-07",(1,2,3,4)),limit=4)
        data["weekly_work_boundaries"]["1_2026-06-29"]="1.0"
        data["weekly_work_boundaries"]["1_2026-06-30"]="0.0"
        data["leave_history"]["history"]["1_2026-06-29"]="full"
        data["weekly_neighbor_boundaries"]={"2026-06":{"1_2026-07-01":"1.0"}}
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(work_units(result["grid"][0][0]),2)
        self.assertEqual(sum(work_units(result["grid"][d][0]) for d in range(4)),2)
        self.assertEqual(weekly_summary(result["problem"],result["grid"])[0]["known"],2)

    def test_conflicting_actuals_and_known_external_over_cap_block(self):
        data=part_time(month_sample("2026-04",(1,2)),limit=2)
        data["weekly_work_boundaries"]["1_2026-03-30"]="1.0"
        self.assertEqual(generate(data,seconds=1)["status"],"input_error")
        data["leave_history"]["history"]["1_2026-03-30"]="full"
        data["weekly_work_boundaries"]["1_2026-03-31"]="1.0"
        data["leave_history"]["history"]["1_2026-03-31"]="full"
        result=generate(data,seconds=1)
        self.assertEqual(result["status"],"input_error")
        self.assertTrue(any("決定済み勤務だけで" in e for e in result["messages"]))

    def test_realistic_full_and_part_time_nurses_with_part_time_technician(self):
        opens=tuple(d for d in range(1,29) if date(2026,2,d).weekday()!=6)
        data=schedule_helpers.sample(open_days=opens,regular_count=6)
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="10"
        for index in (4,5):
            part_time(data,person=index,limit=6)
        part_time(data,person=6,limit=8)
        data["technician_exceptions"]={date(2026,2,d).isoformat():True for d in opens}
        data["monthly_settings"]["meetings"]=[{"id":str(d),"date":date(2026,2,d).isoformat(),"title":"会議","participants":[str(p["id"]) for p in data["staff"]],"start":"13:30","end":"14:30"} for d in range(1,29) if date(2026,2,d).weekday()==4]
        result=generate(data,seconds=4)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(verify(result["problem"],result["grid"]),[])
        self.assertTrue(all(row["known"]<=row["limit"] for row in weekly_summary(result["problem"],result["grid"])))


class PartTimeStaffTest(unittest.TestCase):
    setUp=staff_helpers.StaffSettingsTest.setUp
    tearDown=staff_helpers.StaffSettingsTest.tearDown
    save=staff_helpers.StaffSettingsTest.save
    rows=staff_helpers.StaffSettingsTest.rows

    def test_part_time_nurse_and_technician_register_without_limit(self):
        self.assertEqual(self.save(employment="part").status_code,302)
        self.assertIsNone(self.rows()[0]["weekly_limit_units"])
        self.assertEqual(self.save(role="technician",employment="part",veteran="1").status_code,302)
        row=self.rows()[1]
        self.assertEqual((row["employment"],row["weekly_limit_units"],row["veteran"],row["allowed_areas"]),("part",None,0,"C"))
        text=self.client.get("/staff").get_data(as_text=True)
        self.assertNotIn('name="weekly_limit"',text)
        self.assertIn("休日日数・週上限",text)

    def test_staff_edit_preserves_limit_and_ignores_old_form_field(self):
        self.save(employment="part")
        row=self.rows()[0]
        db=connect_db()
        db.execute("UPDATE staff SET weekly_limit_units=7 WHERE id=?",(row["id"],))
        db.commit()
        db.close()
        self.assertEqual(self.save(id=str(row["id"]),employment="part",name="仮名 変更",weekly_limit="1").status_code,302)
        self.assertEqual(self.rows()[0]["weekly_limit_units"],7)
        self.assertEqual(self.rows()[0]["name"],"仮名 変更")
        self.assertEqual(self.save(is_help="1",employment="part").status_code,302)
        self.assertIsNone(self.rows()[1]["weekly_limit_units"])


class WeeklyBoundaryRouteTest(unittest.TestCase):
    setUp=schedule_helpers.ScheduleRouteTest.setUp
    tearDown=schedule_helpers.ScheduleRouteTest.tearDown

    def configure_part(self):
        db=connect_db()
        try:
            db.execute("UPDATE staff SET employment='part',weekly_limit_units=6 WHERE id=1")
            db.commit()
        finally:
            db.close()

    def fields(self):
        text=self.client.get("/weekly?month=2026-02").get_data(as_text=True)
        result={name:re.search('name="'+name+'" value="([^"]+)"',text)[1] for name in ("csrf_token","fingerprint")}
        for day in boundary_dates("2026-02"):
            result["boundary_1_"+day.isoformat()]="0.0" if day<date(2026,2,1) else ""
        return result

    def saved(self):
        db=connect_db()
        try:
            exists=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='weekly_work_boundaries'").fetchone()
            row=db.execute("SELECT data FROM weekly_work_boundaries WHERE month='2026-02'").fetchone() if exists else None
            return json.loads(row[0]) if row else {}
        finally:
            db.close()

    def test_save_boundary_then_generate_with_weekly_summary(self):
        self.configure_part()
        response=self.client.post("/weekly?month=2026-02",data=self.fields())
        self.assertEqual(response.status_code,302)
        self.assertEqual(len(self.saved()),6)
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        fields={name:re.search('name="'+name+'" value="([^"]*)"',text)[1] for name in ("csrf_token","fingerprint","result_token")}
        response=self.client.post("/schedule?month=2026-02",data=dict(fields,mode="self"))
        self.assertEqual(response.status_code,302)
        text=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("非常勤の週ごとの確認",text)
        self.assertIn("週3.0日まで",text)

    def test_stale_invalid_csrf_and_partial_input(self):
        self.configure_part()
        fields=self.fields()
        invalid=dict(fields)
        invalid["boundary_1_2026-01-26"]="0.3"
        self.assertEqual(self.client.post("/weekly?month=2026-02",data=invalid).status_code,200)
        self.assertEqual(self.saved(),{})
        self.assertEqual(self.client.post("/weekly?month=2026-02",data={}).status_code,400)
        self.assertEqual(self.client.post("/weekly?month=2026-02",data=fields).status_code,302)
        stale=dict(fields)
        changed=self.fields()
        changed["boundary_1_2026-01-26"]="0.5"
        self.client.post("/weekly?month=2026-02",data=changed)
        response=self.client.post("/weekly?month=2026-02",data=stale)
        self.assertIn("別の画面",response.get_data(as_text=True))
        self.assertEqual(self.saved()["1_2026-01-26"],"0.5")


class StaffSchemaMigrationTest(unittest.TestCase):
    def test_old_schema_preserves_ids_and_related_data_and_allows_part_time_technician(self):
        from staff_schema import ensure_staff_schema
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"old.sqlite3"
            db=sqlite3.connect(path)
            db.row_factory=sqlite3.Row
            try:
                db.execute("CREATE TABLE staff(id INTEGER PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('nurse','technician')),employment TEXT NOT NULL CHECK(employment IN ('full','part','')),veteran INTEGER NOT NULL CHECK(veteran IN (0,1)),is_help INTEGER NOT NULL DEFAULT 0,allowed_areas TEXT NOT NULL DEFAULT 'ABC',CHECK((role='nurse' AND employment IN ('full','part')) OR (role='technician' AND employment='' AND veteran=0)))")
                db.execute("INSERT INTO staff VALUES (7,'仮名看護','nurse','part',1,0,'ABC')")
                db.execute("INSERT INTO staff VALUES (42,'仮名検査','technician','',0,0,'C')")
                db.execute("CREATE INDEX staff_name_index ON staff(name)")
                db.execute("CREATE TABLE monthly_settings(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
                payload='{"targets":{"7":"9","42":"10"}}'
                db.execute("INSERT INTO monthly_settings VALUES ('2026-02',?)",(payload,))
                db.commit()
                before=[tuple(row) for row in db.execute("SELECT * FROM staff ORDER BY id")]
                ensure_staff_schema(db)
                after=[tuple(row)[:7] for row in db.execute("SELECT * FROM staff ORDER BY id")]
                self.assertEqual(after,before)
                self.assertEqual(db.execute("SELECT data FROM monthly_settings").fetchone()[0],payload)
                self.assertIsNone(db.execute("SELECT weekly_limit_units FROM staff WHERE id=7").fetchone()[0])
                db.execute("UPDATE staff SET employment='part',weekly_limit_units=5 WHERE id=42")
                db.commit()
                self.assertEqual(db.execute("SELECT employment FROM staff WHERE id=42").fetchone()[0],"part")
                self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='staff_name_index'").fetchone())
                ensure_staff_schema(db)
                self.assertEqual(db.execute("SELECT weekly_limit_units FROM staff WHERE id=42").fetchone()[0],5)
            finally:
                db.close()


    def test_unknown_extra_column_aborts_migration_without_dropping_data(self):
        from staff_schema import ensure_staff_schema
        with tempfile.TemporaryDirectory() as temp:
            db=sqlite3.connect(Path(temp)/"custom.sqlite3")
            db.row_factory=sqlite3.Row
            try:
                db.execute("CREATE TABLE staff(id INTEGER PRIMARY KEY,name TEXT,role TEXT,employment TEXT,veteran INTEGER,custom_note TEXT)")
                db.execute("INSERT INTO staff VALUES (1,'仮名','nurse','full',0,'保持する値')")
                db.commit()
                with self.assertRaises(RuntimeError):
                    ensure_staff_schema(db)
                self.assertEqual(db.execute("SELECT custom_note FROM staff").fetchone()[0],"保持する値")
            finally:
                db.close()
