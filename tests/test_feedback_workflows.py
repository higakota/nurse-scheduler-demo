import copy,json,unittest
import test_scheduler as fixtures
from scheduler_engine import prepare,generate,generate_draft,verify,rest_units,WORK
from weekly_rules import work_units
from negotiated_leave import change_plan
from agreed_record_changes import cancellation_plan
from leave_candidates import leave_candidates
from input_reflection import reflection_patch

class FeedbackRulesTest(unittest.TestCase):
    def test_summer_is_neither_public_rest_nor_paid(self):
        data=fixtures.sample(regular_count=4)
        data["monthly_settings"]["summer"]={"1_2026-02-02":"full"}
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"SS")
        self.assertEqual(rest_units("SS"),0)
        self.assertEqual(work_units("SS"),0)
        self.assertEqual(verify(result["problem"],result["grid"]),[])

    def test_support_counts_as_work_but_not_local_coverage(self):
        data=fixtures.sample(regular_count=4)
        data["monthly_settings"]["support"]={"1_2026-02-02":"full"}
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"TT")
        self.assertEqual(work_units("TT"),2)
        self.assertTrue(all(c in WORK for c in "TT"))
        data["monthly_settings"]["support"]["2_2026-02-02"]="full"
        result=generate_draft(data,seconds=2)
        self.assertEqual(result["status"],"draft")
        self.assertTrue(result["shortages"])

    def test_special_half_days_and_overlap(self):
        data=fixtures.sample(regular_count=4)
        data["monthly_settings"].update(summer={"1_2026-02-02":"am"},support={"1_2026-02-02":"pm"})
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"ST")
        data["monthly_settings"]["support"]["1_2026-02-02"]="full"
        self.assertTrue(prepare(data)["errors"])

    def test_absence_wins_over_meeting_and_input_is_preserved(self):
        data=fixtures.sample(regular_count=5)
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="full"
        data["monthly_settings"]["targets"]["1"]="28"
        data["monthly_settings"]["meetings"]=[dict(id="test",date="2026-02-02",title="仮名会議",participants=["1"])]
        before=copy.deepcopy(data)
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"RR")
        self.assertEqual(data,before)

    def test_absent_person_does_not_block_generation_with_meeting_time_conflict(self):
        data=fixtures.sample(regular_count=5)
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="full"
        data["monthly_settings"]["targets"]["1"]="28"
        data["monthly_settings"]["meetings"]=[
            dict(id="a",date="2026-02-02",title="仮名会議A",participants=["1"],start="13:30",end="14:30"),
            dict(id="b",date="2026-02-02",title="仮名会議B",participants=["1"],start="13:45",end="14:45")]
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"RR")

    def test_paid_consent_and_cancellation_restore_original_paid(self):
        data=fixtures.sample(regular_count=4)
        data["leave_history"]["leaves"]={"1_2026-02-02":"full"}
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        base=dict(people=result["problem"]["people"],days=result["problem"]["days"],grid=result["grid"])
        updated,grid,changes,audit=change_plan(data,base,"1","2026-02-02","am","","")
        self.assertEqual(updated["leave_history"]["leaves"]["1_2026-02-02"],"pm")
        self.assertEqual(grid[1][0],"DP")
        self.assertEqual(audit["original_paid"],"full")
        from schedule_display import monthly_display
        display=monthly_display(base["days"],base["people"],grid,updated["monthly_settings"],
            comparison_inputs={"wishes":updated["monthly_settings"]["wishes"],"leaves":updated["leave_history"]["leaves"]})
        self.assertEqual(display["rows"][0]["cells"][1]["request_segments"],[dict(label="有休",kind="paid")])
        restored,old_grid,_,undo=cancellation_plan(updated,dict(base,grid=grid),0)
        self.assertEqual(restored["leave_history"]["leaves"]["1_2026-02-02"],"full")
        self.assertEqual(old_grid,[list(row) for row in base["grid"]])
        self.assertTrue(undo["paid_changes"])

    def test_reflection_preserves_unaffected_cells_and_helpers(self):
        data=fixtures.sample(regular_count=4)
        result=generate(data,seconds=2)
        base=dict(people=result["problem"]["people"],days=result["problem"]["days"],grid=result["grid"])
        data["leave_history"]["leaves"]={"1_2026-02-02":"am"}
        patch=json.loads(reflection_patch(data,base))
        self.assertEqual(patch,{"1_0":"PD"})

    def test_candidates_available_with_existing_shortage_without_making_it_worse(self):
        data=fixtures.sample(open_days=(2,3),regular_count=5)
        for i in (1,2,3):
            data["monthly_settings"]["wishes"][str(i)+"_2026-02-02"]="full"
            data["monthly_settings"]["targets"][str(i)]="27"
        result=generate_draft(data,seconds=2)
        self.assertEqual(result["status"],"draft")
        source=dict(days=result["problem"]["days"],people=result["problem"]["people"],grid=result["grid"],input_hash="now")
        candidates=leave_candidates(data,source,"now")
        self.assertFalse(candidates["message"])
        self.assertIn("2026-02-03",[d["date"] for d in candidates["days"]])
        self.assertNotIn("2026-02-02",[d["date"] for d in candidates["days"]])

    def test_support_uses_part_time_weekly_capacity(self):
        from weekly_rules import boundary_dates
        data=fixtures.sample(open_days=(2,3),regular_count=5)
        data["staff"][0].update(employment="part",weekly_limit_units=2)
        data["weekly_work_boundaries"]={"1_"+d.isoformat():"0" for d in boundary_dates(data["month"])}
        data["monthly_settings"]["support"]={"1_2026-02-02":"full","1_2026-02-03":"full"}
        result=generate(data,seconds=1)
        self.assertNotEqual(result["status"],"success")
        self.assertEqual(work_units("TT"),2)

    def test_public_rest_and_paid_on_opposite_halves_are_allowed(self):
        data=fixtures.sample(regular_count=4)
        data["monthly_settings"]["wishes"]["1_2026-02-02"]="am"
        data["leave_history"]["leaves"]["1_2026-02-02"]="pm"
        data["monthly_settings"]["targets"]["1"]="28"
        result=generate(data,seconds=2)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(result["grid"][1][0],"RP")

class CandidateApplyRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_direct_apply_changes_one_cell_and_rejects_old_candidate(self):
        from app import connect_db
        from schedule import read_snapshot
        from leave_candidates import source_token
        fields=fixtures.ScheduleRouteTest.fields(self)
        self.client.post("/schedule?month=2026-02",data=dict(fields,mode="self"))
        db=connect_db()
        snapshot,fp,raw=read_snapshot(db,"2026-02")
        source=json.loads(raw)
        options=leave_candidates(snapshot,source,fp)
        day=options["groups"][0]["days"][0]
        person=day["people"][0]
        with self.client.session_transaction() as sess:csrf=sess["csrf_token"]
        form=dict(csrf_token=csrf,fingerprint=fp,source_token=source_token(source),source_kind="generated",staff=str(person["id"]),day=day["date"],period="full")
        db.close()
        response=self.client.post("/schedule/paid-candidate?month=2026-02",data=form)
        self.assertEqual(response.status_code,302)
        db=connect_db()
        after=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        changes=sum(a!=b for row1,row2 in zip(source["grid"],after["grid"]) for a,b in zip(row1,row2))
        self.assertEqual(changes,1)
        before=list(db.iterdump());db.close()
        self.client.post("/schedule/paid-candidate?month=2026-02",data=form)
        db=connect_db()
        self.assertEqual(before,list(db.iterdump()))
        db.close()


    def test_input_reflection_removes_paid_without_recreating_other_cells(self):
        import re
        from app import connect_db
        from schedule import read_snapshot
        fields=fixtures.ScheduleRouteTest.fields(self)
        self.client.post("/schedule?month=2026-02",data=dict(fields,mode="self"))
        db=connect_db()
        snapshot,fp,raw=read_snapshot(db,"2026-02")
        source=json.loads(raw)
        source["grid"][1][0]="PP"
        source["updated"]="test"
        db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO manual_schedules VALUES (?,?)",("2026-02",json.dumps(source)))
        db.commit();db.close()
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        tokens={k:re.search('name="'+k+'"[^>]*value="([^"]*)"',page)[1] for k in ("csrf_token","fingerprint","revision")}
        preview=self.client.post("/schedule/manual?month=2026-02",data=dict(tokens,action="reflect_inputs")).get_data(as_text=True)
        import html
        patch=html.unescape(re.search('name="patch" value="([^"]*)"',preview)[1])
        self.assertEqual(json.loads(patch),{"1_0":"DD"})
        self.assertEqual(self.client.post("/schedule/manual?month=2026-02",data=dict(tokens,action="save",input_priority="yes",patch=patch,confirm="yes")).status_code,303)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(saved["grid"][1][0],"DD")
        for d,row in enumerate(source["grid"]):
            for i,pair in enumerate(row):
                if (d,i)!=(1,0):self.assertEqual(saved["grid"][d][i],pair)
        leaves=db.execute("SELECT data FROM leave_history").fetchone()
        self.assertFalse(json.loads(leaves[0]).get("leaves",{}))
        db.close()

    def test_new_browser_session_reopens_same_draft_without_recreation(self):
        from app import app,connect_db
        fields=fixtures.ScheduleRouteTest.fields(self)
        self.client.post("/schedule?month=2026-02",data=dict(fields,mode="draft"))
        db=connect_db()
        before=db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0]
        db.close()
        new_client=app.test_client()
        for _ in range(2):
            page=new_client.get("/schedule?month=2026-02&resume=1").get_data(as_text=True)
            self.assertIn("前回作成した仮表を表示",page)
        db=connect_db()
        self.assertEqual(db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0],before)
        db.close()


class StaffWeeklyFeedbackTest(unittest.TestCase):
    def test_technician_has_individual_weekly_limit(self):
        import test_staff
        fixture=test_staff.StaffSettingsTest()
        fixture.setUp()
        try:
            response=fixture.save(role="technician",weekly_limit_days="3.5")
            self.assertEqual(response.status_code,302)
            person=fixture.rows()[0]
            self.assertEqual(person["employment"],"part")
            self.assertEqual(person["weekly_limit_units"],7)
        finally:fixture.tearDown()
