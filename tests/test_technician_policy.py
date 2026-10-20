import copy
import json
import re
import unittest
import test_staff as staff_helpers
from test_scheduler import sample
from app import connect_db
from scheduler_engine import generate, prepare, verify


def full_tech_absence():
    data=sample()
    data["monthly_settings"]["wishes"]["5_2026-02-02"]="full"
    data["monthly_settings"]["targets"]["5"]="28"
    return data


class TechnicianPolicyTest(unittest.TestCase):
    def test_full_day_off_requires_external_technician_not_nurse(self):
        data=full_tech_absence()
        helper=dict(id=9,name="看護ヘルプ仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC")
        data["staff"].append(helper)
        data["help_availability"]={"9_2026-02-02":"full"}
        before=copy.deepcopy(data)
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"infeasible")
        self.assertTrue(any("他院の検査技師" in row["area"] for row in result["shortages"]))
        self.assertEqual(data,before)

    def test_confirmed_external_technician_covers_both_open_halves(self):
        data=full_tech_absence()
        data["staff"].append(dict(id=9,name="検査ヘルプ仮名",role="technician",employment="",veteran=0,is_help=1,allowed_areas="C"))
        data["help_availability"]={"9_2026-02-02":"full"}
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][-1],"CC")
        self.assertEqual(verify(result["problem"],result["grid"]),[])
        data["help_availability"]={"9_2026-02-02":"am"}
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"infeasible")
        self.assertTrue(any(row["half"]=="午後" and "他院の検査技師" in row["area"] for row in result["shortages"]))

    def test_explicit_exception_allows_nurses_only_and_is_revalidated(self):
        data=full_tech_absence()
        for value in (False,"true",None):
            data["technician_exceptions"]={"2026-02-02":value}
            self.assertEqual(generate(data,seconds=1)["status"],"infeasible")
        data["technician_exceptions"]={"2026-02-02":True}
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertTrue(any("明示された" in text for text in result["messages"]))
        self.assertEqual(result["grid"][1][4],"RR")
        self.assertTrue(sum(row=="DD" for row in result["grid"][1][:4]) == 4)
        unapproved=copy.deepcopy(result["problem"])
        unapproved["technician_exceptions"]=set()
        self.assertTrue(any("未承認" in e for e in verify(unapproved,result["grid"])))
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="full"
        data["monthly_settings"]["targets"]["1"]="28"
        self.assertEqual(generate(data,seconds=2)["status"],"infeasible")

    def test_morning_only_technician_allows_nurse_afternoon_without_exception(self):
        data=sample()
        data["monthly_settings"]["wishes"]["5_2026-02-02"]="pm"
        data["monthly_settings"]["targets"]["5"]="27.5"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][4],"CR")
        self.assertTrue(sum(row[1]=="D" for row in result["grid"][1][:4]) == 4)
        self.assertEqual(verify(result["problem"],result["grid"]),[])

    def test_closed_hours_need_no_technician_help(self):
        data=sample(open_days=())
        self.assertEqual(generate(data,seconds=2)["status"],"success")
        data=sample(open_days=(6,))
        for p in data["staff"]:
            data["monthly_settings"]["targets"][str(p["id"])]="27.5"
        data["monthly_settings"]["wishes"]["5_2026-02-06"]="full"
        data["monthly_settings"]["targets"]["5"]="28"
        data["staff"].append(dict(id=9,name="検査ヘルプ",role="technician",employment="",veteran=0,is_help=1,allowed_areas="C"))
        data["help_availability"]={"9_2026-02-06":"am"}
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][5][-1],"CR")

    def test_nurse_helpers_not_used_when_self_staff_can_cover(self):
        data=sample()
        data["staff"].append(dict(id=9,name="看護ヘルプ",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        data["help_availability"]={"9_2026-02-02":"full"}
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertFalse(any(p["is_help"] and p["role"]=="nurse" for p in result["problem"]["people"]))
        self.assertTrue(any("ヘルプを使っていません" in note for note in result["messages"]))

    def test_registered_external_technician_is_not_used_if_self_staff_suffice(self):
        data=sample()
        data["staff"].append(dict(id=9,name="検査ヘルプ",role="technician",employment="",veteran=0,is_help=1,allowed_areas="C"))
        data["help_availability"]={"9_2026-02-02":"full"}
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertFalse(any(person["is_help"] for person in result["problem"]["people"]))

    def test_nurse_helper_available_only_after_nurse_free_attempt_fails(self):
        data=sample(regular_count=3)
        data["monthly_settings"]["wishes"]["4_2026-02-02"]="pm"
        data["monthly_settings"]["targets"]["4"]="27.5"
        data["staff"].append(dict(id=9,name="看護ヘルプ",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC"))
        data["help_availability"]={"9_2026-02-02":"pm"}
        result=generate(data,True,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][-1][0],"R")
        self.assertEqual(result["grid"][1][-1][1],"D")
        self.assertTrue(any("少なく使う" in text for text in result["messages"]))


class TechnicianExceptionRouteTest(unittest.TestCase):
    setUp=staff_helpers.StaffSettingsTest.setUp
    tearDown=staff_helpers.StaffSettingsTest.tearDown

    def fields(self,days):
        text=self.client.get("/help?month=2026-02").get_data(as_text=True)
        fingerprint=re.search(r'name="fingerprint" value="([^"]+)"',text)[1]
        return dict(csrf_token=self.token,action="exceptions",fingerprint=fingerprint,exception_dates=days)

    def stored(self):
        db=connect_db()
        try:
            row=db.execute("SELECT data FROM technician_exceptions WHERE month='2026-02'").fetchone()
            return json.loads(row[0]) if row else {}
        finally:
            db.close()

    def test_exception_available_without_registered_helpers_and_can_be_revoked(self):
        response=self.client.post("/help?month=2026-02",data=self.fields(["2026-02-02"]))
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.location.endswith("#technician-exceptions"))
        self.assertEqual(self.stored(),{"2026-02-02":True})
        response=self.client.post("/help?month=2026-02",data=self.fields([]))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.stored(),{})

    def test_invalid_date_and_stale_form_keep_saved_exception(self):
        self.client.post("/help?month=2026-02",data=self.fields(["2026-02-02"]))
        stale=self.fields([])
        self.client.post("/help?month=2026-02",data=self.fields(["2026-02-03"]))
        response=self.client.post("/help?month=2026-02",data=stale)
        self.assertIn("別の画面",response.get_data(as_text=True))
        self.assertEqual(self.stored(),{"2026-02-03":True})
        for day in ("2026-02-01","2026-03-01","bad"):
            response=self.client.post("/help?month=2026-02",data=self.fields([day]))
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.stored(),{"2026-02-03":True})
        self.assertEqual(self.client.post("/help?month=2026-02",data={"action":"exceptions"}).status_code,400)

    def test_rule_change_marks_old_saved_schedule_stale(self):
        from schedule import read_snapshot
        self.client.get("/help?month=2026-02")
        db=connect_db()
        try:
            before=read_snapshot(db,"2026-02")[1]
        finally:
            db.close()
        self.client.post("/help?month=2026-02",data=self.fields(["2026-02-02"]))
        db=connect_db()
        try:
            snapshot,after,_=read_snapshot(db,"2026-02")
            self.assertEqual(snapshot["technician_exceptions"],{"2026-02-02":True})
            self.assertNotEqual(before,after)
        finally:
            db.close()

    def test_old_rule_result_is_shown_as_stale_even_without_new_exception(self):
        from schedule import digest, read_snapshot
        self.client.get("/schedule?month=2026-02")
        db=connect_db()
        try:
            snapshot,_,_=read_snapshot(db,"2026-02")
            snapshot.pop("rules_version")
            snapshot.pop("technician_exceptions")
            old_hash=digest(json.dumps(snapshot,ensure_ascii=False,sort_keys=True))
            saved={"input_hash":old_hash,"mode":"self","days":[],"people":[],"grid":[],"targets":{},"notes":[]}
            db.execute("CREATE TABLE generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            db.execute("INSERT INTO generated_schedules VALUES (?,?)",("2026-02",json.dumps(saved)))
            db.commit()
        finally:
            db.close()
        text=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertIn("以前の結果",text)
