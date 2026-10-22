import json
import unittest
import test_scheduler as fixtures
from app import connect_db
from scheduler_engine import generate, generate_draft, verify


class ConsecutivePolicyTest(unittest.TestCase):
    def test_feasible_five_is_preferred_for_normal_and_draft(self):
        for create in (generate, generate_draft):
            result=create(fixtures.sample(), seconds=2)
            self.assertIn(result["status"], ("success","draft"))
            self.assertEqual(result["six_day_runs"], [])
            self.assertFalse(result["experimental"])

    def test_six_is_allowed_but_seventh_rejected_including_meeting_duty(self):
        data=fixtures.sample(open_days=(2,3,4,5,6,7))
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="22"
        result=generate(data,seconds=3,allow_six=True)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertTrue(result["six_day_runs"])
        self.assertEqual(verify(result["problem"],result["grid"]),[])
        self.assertTrue(verify(result["problem"],result["grid"],max_full_days=5))
        # 第1日に勤務を足すと7連勤。通常業務・会議も全日勤務として判定する。
        bad=list(result["grid"])
        bad[0]=tuple("OM" for _ in result["problem"]["people"])
        self.assertTrue(any("6連勤" in e for e in verify(result["problem"],bad)))

    def test_compulsory_six_is_permitted_without_special_button(self):
        data=fixtures.sample(open_days=(2,3,4,5,6,7))
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="22"
        self.assertEqual(generate(data,seconds=2)["status"],"success")
        self.assertEqual(generate_draft(data,seconds=2)["status"],"draft")
        final=generate(data,seconds=3,allow_six=True)
        self.assertEqual(final["status"],"success",final["messages"])
        self.assertEqual(final["max_full_days"],6)

    def test_five_day_helper_plan_precedes_six_day_own_plan(self):
        from unittest.mock import patch
        from scheduler_engine import prepare
        data=fixtures.sample()
        base=generate(data,seconds=2)
        data["staff"].append(dict(id=9,name="看護ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        calls=[]
        def attempt(snapshot,use_help,seconds,allow_nurse_help=True,draft_max_full_days=5,**kwargs):
            calls.append((use_help,allow_nurse_help,draft_max_full_days))
            if use_help and allow_nurse_help and draft_max_full_days==5:
                return dict(base,messages=list(base["messages"]))
            # 自院6連勤なら作れる場合も、ヘルプ5連勤より先に採用しない。
            if not use_help and draft_max_full_days==6:
                return dict(base,messages=list(base["messages"]))
            return dict(status="infeasible",problem=prepare(snapshot,use_help,allow_nurse_help),
                        grid=None,messages=[],shortages=[])
        with patch("scheduler_engine._generate",side_effect=attempt):
            result=generate(data,use_help=True,seconds=3,allow_six=True)
        self.assertEqual(result["status"],"success")
        self.assertEqual(calls,[(False,True,5),(True,False,5),(True,True,5)])
        self.assertEqual(result["max_full_days"],5)

    def test_compulsory_six_is_limited_to_that_person_and_period(self):
        import test_draft
        from scheduler_engine import full_run_allowed
        data=test_draft.ExperimentalSixTest().sample_six()
        result=generate_draft(data,seconds=3)
        self.assertEqual(result["status"],"draft",result["messages"])
        problem=result["problem"]
        self.assertEqual(problem["full_day_limits"][0],6)
        self.assertTrue(all(n==5 for n in problem["full_day_limits"][1:]))
        self.assertTrue(full_run_allowed(problem,0,13,6,6))  # 11月14日
        self.assertFalse(full_run_allowed(problem,0,20,6,6))  # 必須期間外
        self.assertFalse(full_run_allowed(problem,1,13,6,6))  # 別のスタッフ
        self.assertFalse(full_run_allowed(problem,0,13,7,6))
        self.assertEqual(verify(problem,result["grid"],allow_shortages=True,max_full_days=6),[])


class ConsecutivePolicyRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_normal_six_is_saved_with_periods_and_printed(self):
        db=connect_db()
        row=db.execute("SELECT data FROM monthly_settings").fetchone()
        monthly=json.loads(row[0])
        for d in (2,3,4,5,6,7):
            monthly["closures"].pop(f"2026-02-{d:02d}",None)
        monthly["targets"]={key:"22" for key in monthly["targets"]}
        db.execute("UPDATE monthly_settings SET data=?", (json.dumps(monthly),))
        db.commit()
        db.close()
        response=self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        self.assertEqual(response.status_code,302)
        saved=json.loads(fixtures.ScheduleRouteTest.stored(self))
        self.assertTrue(saved["six_day_runs"])
        self.assertEqual(saved["six_day_runs"][0]["start"],"2026-02-02")
        self.assertEqual(saved["six_day_runs"][0]["end"],"2026-02-07")
        page=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("6連勤になるスタッフ・期間",page)
        self.assertIn("6連勤：",page)
        self.assertNotIn("未確認ルール使用",page)

    def test_default_november_draft_continues_for_compulsory_six(self):
        import test_draft
        import re
        from doctor_import import IMPORT_VERSION
        data=test_draft.ExperimentalSixTest().sample_six()
        db=connect_db()
        for table in ("monthly_settings","doctor_plans","coverage_settings","leave_history"):
            raw=data["doctor_raw"] if table=="doctor_plans" else json.dumps(data[table],ensure_ascii=False)
            db.execute("INSERT INTO "+table+" VALUES (?,?)",(data["month"],raw))
        db.execute("INSERT INTO doctor_plan_reviews VALUES (?,?,?)",(data["month"],data["doctor_raw"],IMPORT_VERSION))
        db.commit()
        db.close()
        page=self.client.get("/schedule?month=2026-11").get_data(as_text=True)
        fields={key:re.search('name="'+key+'" value="([^"]*)"',page)[1] for key in ("csrf_token","fingerprint","result_token")}
        response=self.client.post("/schedule?month=2026-11",data=dict(fields,mode="draft"))
        text=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn("ヘルプ相談用の仮表",text)
        self.assertIn("2026-11-09～2026-11-14",text)
        self.assertIn("6連勤が必須のため許容",text)
        self.assertNotIn("全日勤務は最大5連勤のため作成できません",text)
