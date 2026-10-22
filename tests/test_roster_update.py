import copy, html, json, re, unittest
from unittest.mock import patch
import test_scheduler as fixtures
from app import connect_db
from scheduler_engine import generate
from roster_update import update_patch


class RosterUpdateTest(unittest.TestCase):
    def test_new_paid_leave_and_helper_are_reflected_together(self):
        snapshot=fixtures.sample()
        generated=generate(snapshot,seconds=2)
        base=dict(days=generated["problem"]["days"],people=snapshot["staff"],grid=[list(row) for row in generated["grid"]])
        updated=copy.deepcopy(snapshot)
        updated["leave_history"]["leaves"]={"1_2026-02-02":"full","2_2026-02-02":"full"}
        updated["staff"].append(dict(id=9,name="応援仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC",advance_help=0))
        updated["help_availability"]={"9_2026-02-02":"full"}
        base["people"]=updated["staff"]
        base["grid"]=[row+["RR"] for row in base["grid"]]
        before=copy.deepcopy(updated)
        changes=json.loads(update_patch(updated,base,seconds=2))
        self.assertEqual(changes["1_0"],"PP")
        self.assertNotEqual(changes["1_5"],"RR")
        self.assertEqual(updated,before)

    def test_existing_requested_helper_stays_in_place(self):
        snapshot=fixtures.sample()
        snapshot["staff"].append(dict(id=9,name="応援仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC",advance_help=0))
        snapshot["help_availability"]={"9_2026-02-02":"full"}
        generated=generate(snapshot,seconds=2)
        base=dict(days=generated["problem"]["days"],people=snapshot["staff"],grid=[list(row)+["RR"] for row in generated["grid"]])
        base["grid"][1][-1]="DD"
        changes=json.loads(update_patch(snapshot,base,seconds=2))
        self.assertEqual(changes["1_5"],"DD")
        for d,person in enumerate(snapshot["staff"]):
            self.assertEqual(changes[f"1_{d}"],base["grid"][1][d])

    def test_global_adjustment_fills_shortage_that_fixed_own_roster_cannot(self):
        from manual_schedule import checked_patch
        from help_shortages import shortages_from_source
        snapshot=fixtures.sample(open_days=(2,3))
        snapshot["staff"][-1].update(employment="part",weekly_limit_units=2)
        snapshot["monthly_settings"]["targets"].pop("5")
        from weekly_rules import boundary_dates
        snapshot["weekly_work_boundaries"]={"5_"+day.isoformat():"0.0" for day in boundary_dates(snapshot["month"])}
        snapshot["staff"].append(dict(id=9,name="技師応援仮名",role="technician",employment="full",veteran=0,is_help=1,allowed_areas="C",advance_help=0))
        snapshot["help_availability"]={"9_2026-02-03":"full"}
        problem=__import__("scheduler_engine").prepare(snapshot,use_help=True)
        grid=[["RR"]*6 for _ in problem["days"]]
        for d in (1,2):
            grid[d][:4]=["DD"]*4
        grid[2][4]="CC"
        base=dict(days=problem["days"],people=snapshot["staff"],grid=grid)
        changes=update_patch(snapshot,base,seconds=3)
        updated,_=checked_patch(base,changes)
        self.assertEqual(updated[1][4],"CC")
        self.assertEqual(updated[2][5],"CC")
        self.assertEqual(shortages_from_source(snapshot,json.dumps(dict(base,grid=updated))),[])

    def test_shortage_refresh_counts_already_reflected_requested_helpers(self):
        from help_shortages import shortages_from_source
        snapshot=fixtures.sample()
        snapshot["staff"].append(dict(id=9,name="応援仮名",role="nurse",employment="full",veteran=1,is_help=1,allowed_areas="ABC",advance_help=0))
        snapshot["help_availability"]={"9_2026-02-02":"full"}
        for pid in ("1","2"):
            snapshot["monthly_settings"]["wishes"][pid+"_2026-02-02"]="full"
            snapshot["monthly_settings"]["targets"][pid]="28"
        result=generate(snapshot,use_help=True,seconds=3)
        self.assertEqual(result["status"],"success")
        base=dict(days=result["problem"]["days"],people=result["problem"]["people"],grid=result["grid"])
        self.assertEqual(shortages_from_source(snapshot,json.dumps(base)),[])


class RosterUpdateRouteTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def test_one_button_review_then_save_and_repeated_update(self):
        fields=fixtures.ScheduleRouteTest.fields(self)
        self.client.post("/schedule?month=2026-02",data=fields)
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        self.assertEqual(page.count('value="update_roster"'),1)
        self.assertNotIn("入力の変更をこの表に反映",page)
        def tokens(text):
            return {k:html.unescape(re.search('name="'+k+'" value="([^"]*)"',text)[1])
                    for k in ("csrf_token","fingerprint","revision")}
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(tokens(page),action="update_roster"))
        review=response.get_data(as_text=True)
        self.assertIn("保存前の変更確認",review)
        db=connect_db()
        self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedules'").fetchone())
        db.close()
        patch_value=html.unescape(re.search('name="patch" value="([^"]*)"',review)[1])
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(tokens(review),action="save",patch=patch_value,input_priority="yes",confirm="yes"))
        self.assertEqual(response.status_code,303)
        page=self.client.get(response.location).get_data(as_text=True)
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(tokens(page),action="update_roster"))
        self.assertIn("保存前の変更確認",response.get_data(as_text=True))

    def test_stale_tab_cannot_update(self):
        self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        fields={k:html.unescape(re.search('name="'+k+'" value="([^"]*)"',page)[1])
                for k in ("csrf_token","fingerprint","revision")}
        with patch("roster_update.update_patch") as update:
            response=self.client.post("/schedule/manual?month=2026-02",data=dict(fields,action="update_roster",fingerprint="old"))
        self.assertIn("別の画面で変更",response.get_data(as_text=True))
        update.assert_not_called()
