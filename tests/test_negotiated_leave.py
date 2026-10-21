import json
import re
import unittest
import test_scheduler as fixtures
from app import connect_db
from schedule import read_snapshot
from manual_schedule import seed_draft


class NegotiatedLeaveTest(unittest.TestCase):
    setUp = fixtures.ScheduleRouteTest.setUp
    tearDown = fixtures.ScheduleRouteTest.tearDown

    def setup_roster(self):
        db = connect_db()
        data = json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        data["closures"].pop("2026-02-03", None)
        data["wishes"]["5_2026-02-02"] = "full"
        data["targets"] = {str(i): "26" for i in range(1,5)}
        data["targets"]["5"] = "27"
        db.execute("UPDATE monthly_settings SET data=?", (json.dumps(data),))
        db.commit()
        snapshot, fp, _ = read_snapshot(db, "2026-02")
        days = [f"2026-02-{d:02}" for d in range(1,29)]
        grid = [["RR"]*5 for _ in days]
        grid[1] = ["DD"]*4+["RR"]
        grid[2] = ["DD"]*4+["CC"]
        seed_draft(db, "2026-02", snapshot, fp,
                   dict(problem=dict(days=days, people=snapshot["staff"]), grid=grid))
        db.commit()
        db.close()

    def fields(self):
        text = self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        fields = {key: re.search('name="'+key+'" value="([^"]*)"', text)[1]
                  for key in ("csrf_token","fingerprint","revision")}
        return dict(fields, staff="5", day="2026-02-02", period="full", swap="2026-02-03",
                    reason="本人に相談し出勤と代わりの希望休の了承を得た。")

    def post(self, fields, action, consent=""):
        return self.client.post("/schedule/agreed-change?month=2026-02",
                                data=dict(fields, action=action, consent=consent))

    def dump(self):
        db=connect_db()
        result=list(db.iterdump())
        db.close()
        return result

    def test_get_and_preview_do_not_change_data(self):
        self.setup_roster()
        before=self.dump()
        fields=self.fields()
        text=self.post(fields,"preview").get_data(as_text=True)
        self.assertIn("まだ保存していません",text)
        self.assertIn("27.0日 → 27.0日",text)
        self.assertEqual(self.dump(),before)

    def test_apply_requires_preview_and_explicit_consent(self):
        self.setup_roster()
        fields=self.fields()
        before=self.dump()
        self.post(fields,"save","yes")
        self.assertEqual(before,self.dump())
        self.post(fields,"preview")
        self.post(fields,"save")
        self.assertEqual(before,self.dump())

    def test_atomic_wish_roster_and_audit_with_replacement(self):
        self.setup_roster()
        fields=self.fields()
        self.post(fields,"preview")
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        manual=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertNotIn("5_2026-02-02",settings["wishes"])
        self.assertEqual(settings["wishes"]["5_2026-02-03"],"full")
        self.assertEqual(settings["targets"]["5"],"27")
        self.assertEqual(manual["grid"][1][4],"CC")
        self.assertEqual(manual["grid"][2][4],"RR")
        self.assertEqual(manual["grid"][1][:4],["DD"]*4)
        record=settings["agreed_wish_changes"][0]
        self.assertEqual(record["original_wish"],"full")
        self.assertEqual(record["reason"],fields["reason"])
        self.assertEqual(manual["history"][-1]["grid"][1][4],"RR")
        self.assertEqual(manual["input_hash"],read_snapshot(db,"2026-02")[1])
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='generated_schedules'").fetchone())
        db.close()
        page=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        self.assertIn("変更の記録（1件）",page)
        self.assertIn(fields["reason"],page)
        page=self.client.get("/schedule?month=2026-02&help_source=manual").get_data(as_text=True)
        self.assertNotIn('name="help_source"',page)

    def test_half_day_consent_preserves_other_half_wish(self):
        self.setup_roster()
        # このテストは反対側の希望休維持を検証する。公休は変更後に一致させる。
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        settings["targets"]["5"]="26.5"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(settings),))
        db.commit();db.close()
        fields=self.fields()
        fields.update(period="am",swap="")
        self.post(fields,"preview")
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        manual=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(settings["wishes"]["5_2026-02-02"],"pm")
        self.assertEqual(manual["grid"][1][4],"CR")
        db.close()

    def test_paid_leave_and_meeting_replacement_are_not_cancelled(self):
        self.setup_roster()
        db=connect_db()
        leave=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])
        leave["leaves"]["5_2026-02-02"]="full"
        db.execute("UPDATE leave_history SET data=?",(json.dumps(leave),))
        db.commit();db.close()
        before=self.dump()
        text=self.post(self.fields(),"preview").get_data(as_text=True)
        self.assertIn("不足一覧に表示された日",text)
        self.assertEqual(before,self.dump())

    def test_stale_form_and_tampered_reason_do_not_apply(self):
        self.setup_roster()
        fields=self.fields()
        self.post(fields,"preview")
        changed=dict(fields,reason="異なる変更")
        text=self.post(changed,"save","yes").get_data(as_text=True)
        self.assertIn("本人の了承確認",text)
        db=connect_db()
        db.execute("UPDATE staff SET veteran=0 WHERE id=1")
        db.commit();db.close()
        before=self.dump()
        text=self.post(fields,"save","yes").get_data(as_text=True)
        self.assertIn("別の画面で変更",text)
        self.assertEqual(before,self.dump())

    def test_no_wish_and_other_month_are_rejected(self):
        self.setup_roster()
        before=self.dump()
        fields=self.fields()
        text=self.post(dict(fields,day="2026-03-02"),"preview").get_data(as_text=True)
        self.assertIn("対象月の出勤日",text)
        text=self.post(dict(fields,staff="1"),"preview").get_data(as_text=True)
        self.assertIn("希望休・有給がありません",text)
        self.assertEqual(before,self.dump())

    def test_helpers_added_after_draft_do_not_block_agreed_change(self):
        self.setup_roster()
        db=connect_db()
        seed=json.loads(db.execute("SELECT data FROM manual_schedule_seeds").fetchone()[0])
        original=seed["grid"]
        seed.update(history=[dict(grid=original,saved="old")],updated="old")
        db.execute("CREATE TABLE manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO manual_schedules VALUES ('2026-02',?)",(json.dumps(seed),))
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'追加ヘルプ仮名','nurse','full',0,1,'ABC')")
        db.commit();db.close()
        fields=self.fields()
        self.post(fields,"preview")
        response=self.post(fields,"save","yes")
        self.assertEqual(response.status_code,303,response.get_data(as_text=True)[:100])
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        db.close()
        self.assertEqual(len(saved["people"]),6)
        self.assertTrue(all(row[-1]=="RR" for row in saved["grid"]))
        self.assertEqual(saved["staff_alignment_original"]["grid"],original)
        self.assertEqual(saved["grid"][1][:4],original[1][:4])
        self.assertTrue(all(len(row)==6 for history in saved["history"] for row in history["grid"]))

    def test_completed_and_manual_tables_preserve_original_wish_for_comparison(self):
        self.setup_roster()
        fields=self.fields()
        self.post(fields,"preview")
        self.post(fields,"save","yes")
        manual=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        self.assertIn('request-agreed-note',manual)
        self.assertIn("了承出勤",manual)
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'検査ヘルプ仮名','technician','',0,1,'C')")
        db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO help_availability VALUES ('2026-02',?)",(json.dumps({"9_2026-02-03":"full"}),))
        db.commit();db.close()
        with self.client.session_transaction() as session: token=session["csrf_token"]
        refreshed=self.client.post("/help/shortages?month=2026-02",data=dict(csrf_token=token))
        self.assertEqual(refreshed.status_code,303)
        page=self.client.get("/schedule?month=2026-02").get_data(as_text=True)
        data={key:re.search('name="'+key+'" value="([^"]*)"',page)[1]
              for key in ("csrf_token","fingerprint","result_token","seed_token")}
        response=self.client.post("/schedule?month=2026-02",data=dict(data,mode="help",help_source="manual"))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True)[:100])
        completed=self.client.get(response.location).get_data(as_text=True)
        self.assertIn("了承出勤",completed)
        self.assertIn("代替休",completed)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM generated_schedules").fetchone()[0])
        db.close()
        self.assertNotIn("5_2026-02-02",saved["comparison_inputs"]["wishes"])
        self.assertEqual(saved["monthly_context"]["agreed_wish_changes"][0]["original_wish"],"full")


    def test_save_uses_reviewed_plan_without_searching_again_and_rejects_old_preview(self):
        from unittest.mock import patch
        self.setup_roster()
        fields=self.fields()
        self.post(fields,"preview")
        with self.client.session_transaction() as state:first=state["agreed_change_plan"]
        self.post(fields,"preview")
        stale=self.client.post("/schedule/agreed-change?month=2026-02",
            data=dict(fields,action="save",consent="yes",plan_token=first))
        self.assertIn("別の画面で調整案",stale.get_data(as_text=True))
        with patch("negotiated_leave.change_plan",side_effect=AssertionError("保存時に再探索しない")):
            response=self.post(fields,"save","yes")
        self.assertEqual(response.status_code,303)
