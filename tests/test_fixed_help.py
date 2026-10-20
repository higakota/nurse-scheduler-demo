import copy
import json
import unittest
import test_scheduler as fixtures
from fixed_help import generate_fixed_help
from help_shortages import conditions_hash
from scheduler_engine import generate_draft, verify


class FixedHelpTest(unittest.TestCase):
    def setup_case(self):
        snapshot = fixtures.sample()
        for identifier in ("1", "2"):
            snapshot["monthly_settings"]["wishes"][identifier + "_2026-02-02"] = "full"
            snapshot["monthly_settings"]["targets"][identifier] = "28"
        outcome = generate_draft(snapshot, seconds=2)
        self.assertEqual(outcome["status"], "draft", outcome["messages"])
        seed = dict(days=outcome["problem"]["days"], people=outcome["problem"]["people"],
                    grid=outcome["grid"], conditions_hash=conditions_hash(snapshot))
        snapshot["staff"].append(dict(id=9, name="ヘルプ仮名", role="nurse", employment="full",
                                      veteran=1, is_help=1, allowed_areas="ABC"))
        return snapshot, json.dumps(seed), seed

    def test_help_fills_shortage_without_changing_any_own_cell(self):
        snapshot, raw, seed = self.setup_case()
        snapshot["help_availability"] = {"9_2026-02-02": "full"}
        before = copy.deepcopy((snapshot, seed))
        result = generate_fixed_help(snapshot, raw, seconds=3)
        self.assertEqual(result["status"], "success", result["messages"])
        self.assertEqual(verify(result["problem"], result["grid"], max_full_days=result["max_full_days"]), [])
        for d, row in enumerate(seed["grid"]):
            self.assertEqual(list(row), list(result["grid"][d][:len(row)]))
        self.assertEqual(result["grid"][1][-1], "DD")
        self.assertEqual((snapshot, seed), before)

    def test_insufficient_help_does_not_fall_back_to_rearranging_own_staff(self):
        snapshot, raw, seed = self.setup_case()
        snapshot["help_availability"] = {"9_2026-02-02": "am"}
        result = generate_fixed_help(snapshot, raw, seconds=2)
        self.assertNotEqual(result["status"], "success")
        self.assertIsNone(result["grid"])
        self.assertIn("自院の仮表は変更していません", result["messages"][0])
        self.assertTrue(any("午後：看護師1人不足" in message for message in result["messages"]))
        self.assertTrue(result["shortages"])

    def test_changed_own_conditions_are_rejected_and_legacy_seed_is_revalidated(self):
        snapshot, raw, seed = self.setup_case()
        snapshot["monthly_settings"]["targets"]["3"] = "26"
        self.assertEqual(generate_fixed_help(snapshot, raw)["status"], "input_error")
        snapshot, raw, seed = self.setup_case()
        snapshot["help_availability"] = {"9_2026-02-02": "full"}
        seed.pop("conditions_hash")
        result = generate_fixed_help(snapshot, json.dumps(seed), seconds=2)
        self.assertEqual(result["status"], "success", result["messages"])

class FixedHelpRouteTest(unittest.TestCase):
    setUp = fixtures.ScheduleRouteTest.setUp
    tearDown = fixtures.ScheduleRouteTest.tearDown

    def create_baseline_and_help(self):
        from app import connect_db
        db = connect_db()
        data = json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        for identifier in ("1", "2"):
            data["wishes"][identifier + "_2026-02-02"] = "full"
            data["targets"][identifier] = "28"
        db.execute("UPDATE monthly_settings SET data=?", (json.dumps(data),))
        db.commit()
        db.close()
        response = self.client.post("/schedule?month=2026-02", data=dict(fixtures.ScheduleRouteTest.fields(self), mode="draft"))
        self.assertEqual(response.status_code, 200)
        db = connect_db()
        seed = json.loads(db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0])
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'仮名ヘルプ','nurse','full',1,1,'ABC')")
        db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY,data TEXT)")
        db.execute("INSERT INTO help_availability VALUES ('2026-02',?)", (json.dumps({"9_2026-02-02":"full"}),))
        db.commit()
        db.close()
        return seed

    def help_fields(self):
        import re
        text = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        return {name: re.search('name="' + name + '" value="([^"]*)"', text)[1]
                for name in ("csrf_token", "fingerprint", "result_token", "seed_token")}

    def test_help_route_saves_the_same_own_roster(self):
        from app import connect_db
        seed = self.create_baseline_and_help()
        response = self.client.post("/schedule?month=2026-02", data=dict(self.help_fields(), mode="help"))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:100])
        db = connect_db()
        saved = json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        db.close()
        for d, row in enumerate(seed["grid"]):
            self.assertEqual(row, saved["grid"][d][:len(row)])

    def test_changed_baseline_token_blocks_creation(self):
        from app import connect_db
        self.create_baseline_and_help()
        fields = self.help_fields()
        db = connect_db()
        seed = json.loads(db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0])
        seed["created"] = "changed-in-another-tab"
        db.execute("UPDATE manual_schedule_seeds SET data=?", (json.dumps(seed),))
        db.commit()
        db.close()
        response = self.client.post("/schedule?month=2026-02", data=dict(fields, mode="help"))
        self.assertIn("自院の仮表が変更", response.get_data(as_text=True))

    def save_manual_change(self):
        import re
        page = self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        fields = {key: re.search('name="' + key + '"[^>]*value="([^"]*)"', page)[1]
                  for key in ("csrf_token", "fingerprint", "revision")}
        patch = json.dumps({"1_0":"DD"})
        self.client.post("/schedule/manual?month=2026-02", data=dict(fields, action="preview", patch=patch))
        response = self.client.post("/schedule/manual?month=2026-02",
                                    data=dict(fields, action="save", patch=patch, confirm="yes"))
        self.assertEqual(response.status_code, 303)

    def test_saved_manual_edit_is_used_instead_of_original_draft(self):
        from app import connect_db
        seed = self.create_baseline_and_help()
        db = connect_db()
        monthly = json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        monthly["wishes"].pop("1_2026-02-02")
        monthly["targets"]["1"] = "27"
        db.execute("UPDATE monthly_settings SET data=?", (json.dumps(monthly),))
        db.commit()
        db.close()
        self.save_manual_change()
        page = self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        self.assertIn("この表の不足を確認してヘルプを追加", page)
        with self.client.session_transaction() as session: token=session["csrf_token"]
        self.client.post("/help/shortages?month=2026-02",data=dict(csrf_token=token))
        reopened = self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('name="help_source"', reopened)
        response = self.client.post("/schedule?month=2026-02",
                                    data=dict(self.help_fields(), mode="help"))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:100])
        db = connect_db()
        manual = json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        saved = json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        db.close()
        self.assertEqual(seed["grid"][1][0], "RR")
        self.assertEqual(saved["grid"][1][0], "DD")
        for d, row in enumerate(manual["grid"]):
            self.assertEqual(row[:5], saved["grid"][d][:5])
        self.assertIn("conditions_hash", manual)
        response = self.client.post("/schedule?month=2026-02", data=dict(self.help_fields(),mode="help",replace="yes"))
        self.assertEqual(response.status_code,302)
        db=connect_db()
        again=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        db.close()
        self.assertEqual(again["grid"][1][0],"DD")

    def test_unreviewed_manual_is_not_silently_used_as_help_baseline(self):
        from app import connect_db
        seed=self.create_baseline_and_help()
        manual=dict(seed,updated="2099-01-01",history=[],source="未確認の編集")
        manual["grid"]=[list(row) for row in seed["grid"]]
        manual["grid"][1][0]="DD"
        db=connect_db()
        db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO manual_schedules VALUES ('2026-02',?)",(json.dumps(manual),))
        db.commit();db.close()
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        self.assertNotIn('name="help_source"',page)
        response=self.client.post("/schedule?month=2026-02",data=dict(self.help_fields(),mode="help",help_source="manual"))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        db=connect_db()
        result=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        db.close()
        self.assertEqual(result["grid"][1][0],"RR")

    def test_manual_source_changed_after_opening_blocks_creation(self):
        from app import connect_db
        self.create_baseline_and_help()
        self.save_manual_change()
        fields = self.help_fields()
        db = connect_db()
        value = json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        value["updated"] = "modified-in-another-tab"
        db.execute("UPDATE manual_schedules SET data=?", (json.dumps(value),))
        db.commit()
        db.close()
        response = self.client.post("/schedule?month=2026-02",
                                    data=dict(fields, mode="help", help_source="manual"))
        self.assertIn("別の画面で", response.get_data(as_text=True))

class PreferredHelpSourceTest(unittest.TestCase):
    def test_current_manual_beats_stale_draft_even_if_draft_timestamp_is_newer(self):
        from fixed_help import preferred_help_source
        from help_shortages import conditions_hash
        snapshot = fixtures.sample()
        draft = json.dumps(dict(conditions_hash="old",created="2099"))
        manual = json.dumps(dict(conditions_hash=conditions_hash(snapshot),updated="2026"))
        self.assertEqual(preferred_help_source(snapshot,draft,manual),"manual")

    def test_explicitly_newer_current_draft_can_be_the_default(self):
        from fixed_help import preferred_help_source
        from help_shortages import conditions_hash
        snapshot = fixtures.sample()
        fp = conditions_hash(snapshot)
        draft = json.dumps(dict(conditions_hash=fp,created="2026-10-21"))
        manual = json.dumps(dict(conditions_hash=fp,updated="2026-10-20"))
        self.assertEqual(preferred_help_source(snapshot,draft,manual),"draft")
