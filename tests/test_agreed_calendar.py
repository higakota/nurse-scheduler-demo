import json
import re
import unittest
import test_scheduler as schedule_fixtures
import test_negotiated_leave as agreed_fixtures
from app import connect_db


class AgreedCalendarTest(unittest.TestCase):
    setUp=schedule_fixtures.ScheduleRouteTest.setUp
    tearDown=schedule_fixtures.ScheduleRouteTest.tearDown
    setup_roster=agreed_fixtures.NegotiatedLeaveTest.setup_roster
    fields=agreed_fixtures.NegotiatedLeaveTest.fields
    post=agreed_fixtures.NegotiatedLeaveTest.post

    def calendar(self,text):
        return json.loads(re.search(r'<script id="agreed-calendar-data" type="application/json">(.*?)</script>',text,re.S)[1])

    def test_calendar_shows_all_own_staff_requests_and_paid_leave_without_writes(self):
        self.setup_roster()
        db=connect_db()
        monthly=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        monthly["wishes"].update({"1_2026-02-02":"am","9_2026-02-02":"full"})
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(monthly),))
        leaves=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])
        leaves["leaves"]["2_2026-02-02"]="pm"
        db.execute("UPDATE leave_history SET data=?",(json.dumps(leaves),))
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','nurse','full',0,1,'ABC')")
        db.commit()
        before=list(db.iterdump())
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        entries=self.calendar(text)["entries"]["2026-02-02"]
        self.assertEqual({e["staff"] for e in entries},{"1","2","5"})
        self.assertEqual(next(e["wish_label"] for e in entries if e["staff"]=="1"),"午前")
        self.assertEqual(next(e["paid_label"] for e in entries if e["staff"]=="2"),"午後")
        self.assertIn('data-agreed-staff="5"',text)
        self.assertEqual(before,list(db.iterdump()))
        db.close()

    def test_replacement_choices_follow_paid_leave_and_meeting_rules(self):
        self.setup_roster()
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        self.assertEqual(self.calendar(text)["replacements"]["5"],["2026-02-03"])
        db=connect_db()
        leave=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])
        leave["leaves"]["5_2026-02-03"]="am"
        db.execute("UPDATE leave_history SET data=?",(json.dumps(leave),));db.commit()
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        self.assertEqual(self.calendar(text)["replacements"]["5"],[])
        leave["leaves"].clear()
        db.execute("UPDATE leave_history SET data=?",(json.dumps(leave),))
        monthly=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        monthly["meetings"]=[dict(id="m",date="2026-02-03",title="仮名会議",participants=["5"])]
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(monthly),));db.commit();db.close()
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        self.assertEqual(self.calendar(text)["replacements"]["5"],[])

    def test_preview_highlights_work_and_replacement_without_writes(self):
        self.setup_roster()
        fields=self.fields()
        db=connect_db();before=list(db.iterdump())
        text=self.post(fields,"preview").get_data(as_text=True)
        cells=dict(re.findall(r'<td data-agreed-date="([^"]+)" class="([^"]*)"',text))
        self.assertIn("is-change",cells["2026-02-02"])
        self.assertIn("is-change",cells["2026-02-03"])
        self.assertIn("出勤へ変更",text)
        self.assertIn("代わりの全日希望休",text)
        self.assertEqual(before,list(db.iterdump()));db.close()

    def test_agreed_work_keeps_original_request_visible_in_calendar(self):
        self.setup_roster()
        fields=self.fields()
        self.post(fields,"preview")
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        self.assertIn("元の希望休 全日／出勤 全日",text)
        entry=next(e for e in self.calendar(text)["entries"]["2026-02-02"] if e["staff"]=="5")
        self.assertEqual(entry["wish"],"")
        self.assertEqual(entry["original_label"],"全日")
        self.assertTrue(entry["amended"])

    def test_calendar_escapes_staff_name(self):
        self.setup_roster()
        db=connect_db()
        db.execute("UPDATE staff SET name=? WHERE id=5",("<img src=x onerror=alert(1)>仮名",));db.commit();db.close()
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        self.assertNotIn("<img",text)
        self.assertIn("&lt;img",text)

    def test_impossible_automatic_rest_does_not_save(self):
        self.setup_roster()
        fields=dict(self.fields(),reason="",swap="")
        text=self.post(fields,"preview").get_data(as_text=True)
        self.assertIn("公休を補える日が見つかりませんでした",text)
        self.assertEqual(self.post(fields,"save","yes").status_code,200)
        db=connect_db()
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedules'").fetchone())
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        self.assertEqual(settings["wishes"]["5_2026-02-02"],"full")
        db.close()

    def test_shortage_appears_inside_calendar_date(self):
        from unittest.mock import patch
        self.setup_roster()
        rows=[dict(date="2026-02-02",half=h,area="他院の検査技師（全日休みの代替）",missing=1) for h in ("午前","午後")]
        with patch("negotiated_leave.diagnostics",return_value=([],rows)):
            text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        cell=re.search(r'<td data-agreed-date="2026-02-02".*?</td>',text,re.S)[0]
        self.assertIn("has-shortage",cell)
        self.assertIn("午前・午後：検査技師1人不足",cell)
        self.assertNotIn('textarea id="agreed-reason"',text)
        self.assertIn("休みを自動で探します",text)

    def test_automatic_rest_preserves_target_without_creating_wish(self):
        self.setup_roster()
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        settings["wishes"]["1_2026-02-02"]="full"
        settings["targets"]["1"]="27"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(settings),))
        # 元の希望休に合わせて自院仮表も更新する。
        db.commit();db.close()
        from schedule import read_snapshot
        from manual_schedule import seed_draft
        db=connect_db()
        snapshot,fp,_=read_snapshot(db,"2026-02")
        days=[f"2026-02-{d:02}" for d in range(1,29)]
        grid=[["RR"]*5 for _ in days]
        grid[1]=["RR","DD","DD","DD","RR"]
        grid[2]=["DD","DD","DD","DD","CC"]
        seed_draft(db,"2026-02",snapshot,fp,dict(problem=dict(days=days,people=snapshot["staff"]),grid=grid))
        db.commit();db.close()
        fields=dict(self.fields(),staff="1",swap="",reason="")
        text=self.post(fields,"preview").get_data(as_text=True)
        self.assertIn("27.0日 → 27.0日",text)
        self.assertIn("自動調整の休み",text)
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        manual=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        self.assertEqual(manual["grid"][1][0],"DD")
        self.assertEqual(manual["grid"][2][0],"RR")
        self.assertNotIn("1_2026-02-03",settings["wishes"])
        self.assertEqual(settings["agreed_wish_changes"][-1]["automatic_rest_dates"],["2026-02-03"])
        db.close()

    def shortage_scope(self, day="2026-02-02"):
        from itsdangerous import URLSafeSerializer
        from app import app
        from schedule import read_snapshot
        db=connect_db()
        _,fp,_=read_snapshot(db,"2026-02")
        db.close()
        return URLSafeSerializer(app.secret_key,salt="agreed-shortage-days").dumps(dict(
            month="2026-02",fingerprint=fp,days=[dict(date=day,items=["午前・午後：検査技師1人不足"])]))

    def test_result_shortage_scope_only_allows_listed_dates(self):
        self.setup_roster()
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        settings["wishes"]["1_2026-02-03"]="full"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(settings),))
        db.commit();db.close()
        scope=self.shortage_scope()
        text=self.client.get("/schedule/agreed-change",query_string=dict(month="2026-02",scope=scope)).get_data(as_text=True)
        active=re.findall(r'data-agreed-staff="[^"]+" data-agreed-day="([^"]+)"',text)
        self.assertEqual(set(active),{"2026-02-02"})
        self.assertIn("午前・午後：検査技師1人不足",text)
        fields=dict(self.fields(),scope=scope,staff="1",day="2026-02-03",swap="")
        response=self.post(fields,"preview").get_data(as_text=True)
        self.assertIn("不足一覧に表示された日を選んでください",response)
        fields=dict(self.fields(),scope=scope)
        preview=self.post(fields,"preview").get_data(as_text=True)
        self.assertIn("まだ保存していません",preview)
        self.assertIn('name="scope"',preview)
        self.assertEqual(self.post(fields,"save","yes").status_code,303)

    def test_stale_or_tampered_scope_does_not_allow_changes(self):
        self.setup_roster()
        scope=self.shortage_scope()
        fields=dict(self.fields(),scope=scope+"x")
        self.assertIn("不足一覧のリンクを開き直してください",self.post(fields,"preview").get_data(as_text=True))
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        settings["targets"]["1"]="25"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(settings),))
        db.commit();db.close()
        fields=dict(self.fields(),scope=scope)
        self.assertIn("入力が変わりました",self.post(fields,"preview").get_data(as_text=True))

    def test_approved_help_is_included_and_preserved_when_saving(self):
        self.setup_roster()
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,'ヘルプ仮名','technician','',0,1,'C')")
        db.execute("CREATE TABLE IF NOT EXISTS help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO help_availability VALUES (?,?)",("2026-02",json.dumps({"9_2026-02-02":"full"})))
        db.commit();db.close()
        scope=self.shortage_scope()
        fields=dict(self.fields(),scope=scope)
        text=self.post(fields,"preview").get_data(as_text=True)
        self.assertNotIn("検査技師（C番として計上）",text)
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        saved=json.loads(db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        helper=next(i for i,p in enumerate(saved["people"]) if p["id"]==9)
        self.assertEqual(saved["grid"][1][helper],"CC")
        self.assertEqual(saved["grid"][2][helper],"RR")
        db.close()

    def test_month_boundary_is_updated_only_after_confirmed_consent(self):
        from schedule import read_snapshot
        from manual_schedule import seed_draft
        data=schedule_fixtures.sample(open_days=(2,28))
        data["staff"][4].update(employment="part",weekly_limit_units=10)
        data["monthly_settings"]["wishes"]["5_2026-02-28"]="full"
        db=connect_db()
        db.execute("UPDATE staff SET employment='part',weekly_limit_units=10 WHERE id=5")
        for table in ("monthly_settings","doctor_plans","coverage_settings","leave_history"):
            value=data["doctor_raw"] if table=="doctor_plans" else json.dumps(data[table])
            db.execute("UPDATE "+table+" SET data=?",(value,))
        db.execute("UPDATE doctor_plan_reviews SET data=?",(data["doctor_raw"],))
        db.execute("CREATE TABLE IF NOT EXISTS weekly_work_boundaries(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        prior={f"5_2026-01-{d}":0 for d in range(26,32)}
        db.execute("INSERT INTO weekly_work_boundaries VALUES (?,?)",("2026-02",json.dumps(prior)))
        db.execute("INSERT INTO weekly_work_boundaries VALUES (?,?)",("2026-03",json.dumps({"5_2026-02-28":0,"other":"keep"})))
        db.commit()
        snapshot,fp,_=read_snapshot(db,"2026-02")
        days=[f"2026-02-{d:02}" for d in range(1,29)]
        grid=[["RR"]*5 for _ in days]
        grid[1]=["DD"]*4+["CC"]
        grid[27]=["DD"]*4+["RR"]
        seed_draft(db,"2026-02",snapshot,fp,dict(problem=dict(days=days,people=snapshot["staff"]),grid=grid))
        db.commit()
        before=list(db.iterdump());db.close()
        fields=dict(self.fields(),day="2026-02-28",swap="",reason="")
        text=self.post(fields,"preview").get_data(as_text=True)
        self.assertNotIn("条件違反です",text)
        self.assertIn("翌月側の勤務記録",text)
        db=connect_db();self.assertEqual(before,list(db.iterdump()));db.close()
        self.assertEqual(self.post(fields,"save","yes").status_code,303)
        db=connect_db()
        boundary=json.loads(db.execute("SELECT data FROM weekly_work_boundaries WHERE month='2026-03'").fetchone()[0])
        self.assertEqual(boundary,{"5_2026-02-28":1.0,"other":"keep"})
        db.close()

    def test_normal_entry_also_shows_names_only_on_shortage_days(self):
        self.setup_roster()
        db=connect_db()
        settings=json.loads(db.execute("SELECT data FROM monthly_settings").fetchone()[0])
        settings["wishes"]["1_2026-02-03"]="full"
        db.execute("UPDATE monthly_settings SET data=?",(json.dumps(settings),))
        db.commit();db.close()
        text=self.client.get("/schedule/agreed-change?month=2026-02").get_data(as_text=True)
        cells=dict(re.findall(r'<td data-agreed-date="([^"]+)"[^>]*>(.*?)</td>',text,re.S))
        self.assertIn('data-agreed-staff="5"',cells["2026-02-02"])
        self.assertNotIn("agreed-request",cells["2026-02-03"])
        self.assertNotIn("変更対象外",text)
        self.assertNotIn("希望休なし",cells["2026-02-03"])
        self.assertIn('<table class="agreed-calendar">',text)
        fields=dict(self.fields(),staff="1",day="2026-02-03",swap="")
        self.assertIn("不足一覧に表示された日",self.post(fields,"preview").get_data(as_text=True))
