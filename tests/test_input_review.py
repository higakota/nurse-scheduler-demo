import json
import tempfile
import unittest
from pathlib import Path
from app import app, connect_db
from doctor_import import IMPORT_VERSION

class InputReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=app.config["DATABASE"]
        app.config["DATABASE"]=str(Path(self.temp.name)/"db.sqlite3")
        self.client=app.test_client()
        self.db=connect_db()

    def tearDown(self):
        self.db.close()
        app.config["DATABASE"]=self.old
        self.temp.cleanup()

    def put(self,table,month,data):
        self.db.execute("CREATE TABLE IF NOT EXISTS "+table+"(month TEXT PRIMARY KEY,data TEXT)")
        self.db.execute("INSERT INTO "+table+" VALUES (?,?)",(month,json.dumps(data)))
        self.db.commit()

    def test_empty_month_does_not_create_monthly_records(self):
        before=list(self.db.iterdump())
        text=self.client.get("/inputs?month=2026-11").get_data(as_text=True)
        self.assertIn("2026年11月の入力内容",text)
        self.assertIn("自院スタッフが未登録",text)
        self.assertIn("医師予定：未登録",text)
        self.assertEqual(before,list(self.db.iterdump()))
        self.assertEqual(self.client.get("/inputs?month=2026-13").status_code,400)

    def test_all_inputs_are_shown_without_mutation_or_month_leak(self):
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran) VALUES (1,'仮名常勤','nurse','full',0)")
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran,weekly_limit_units) VALUES (2,'仮名非常勤','technician','part',0,6)")
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help) VALUES (3,'仮名ヘルプ','nurse','full',0,1)")
        self.db.commit()
        self.put("monthly_settings","2026-11",{"targets":{"1":"9.0"},"wishes":{"1_2026-11-02":"am"},"closures":{"2026-11-03":"holiday"},"meetings":[{"date":"2026-11-06","title":"仮名研修","participants":["1"]}]})
        self.put("leave_history","2026-11",{"leaves":{"1_2026-11-02":"pm"}})
        self.put("doctor_plans","2026-11",{"2026-11-02":{"am":["仮名医師甲"],"pm":["仮名医師乙"]}})
        self.put("help_availability","2026-11",{"3_2026-11-02":"am"})
        self.put("doctor_plans","2026-12",{"2026-12-01":{"am":["別月限定医師"],"pm":[]}})
        before=list(self.db.iterdump())
        page=self.client.get("/inputs?month=2026-11")
        self.assertEqual(page.status_code,200)
        text=page.get_data(as_text=True)
        for value in ("仮名常勤","仮名非常勤","公休 9.0日","週上限 3.0日","希望休：午前","有給：午後","仮名研修","仮名医師甲","仮名医師乙","仮名ヘルプ","祝日・休診","金曜午後は診療なし","医師予定：再確認が必要"):
            self.assertIn(value,text)
        self.assertNotIn("別月限定医師",text)
        self.assertIn("/monthly?month=2026-11",text)
        self.assertIn("/help?month=2026-11",text)
        self.assertEqual(before,list(self.db.iterdump()))

    def test_review_status_matches_saved_doctors_and_html_is_escaped(self):
        raw=json.dumps({"2026-11-02":{"am":["<script>仮名</script>"],"pm":[]}})
        self.db.execute("CREATE TABLE doctor_plans(month TEXT PRIMARY KEY,data TEXT)")
        self.db.execute("INSERT INTO doctor_plans VALUES ('2026-11',?)",(raw,))
        self.db.execute("CREATE TABLE doctor_plan_reviews(month TEXT PRIMARY KEY,data TEXT,version INTEGER)")
        self.db.execute("INSERT INTO doctor_plan_reviews VALUES ('2026-11',?,?)",(raw,IMPORT_VERSION))
        self.db.commit()
        text=self.client.get("/inputs?month=2026-11").get_data(as_text=True)
        self.assertIn("医師予定：確認して保存済み",text)
        self.assertIn("&lt;script&gt;",text)
        self.assertNotIn("<script>仮名",text)
        text=self.client.get("/inputs?month=2026-12").get_data(as_text=True)
        self.assertIn("医師予定：未登録",text)

    def test_missing_inputs_skip_closed_periods_and_keep_data(self):
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran) VALUES (1,'仮名常勤','nurse','full',1)")
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran) VALUES (2,'仮名非常勤','nurse','part',0)")
        self.db.commit()
        self.put("monthly_settings","2026-11",{"targets":{},"closures":{"2026-11-03":"holiday"},"meetings":[{"date":"2026-11-06","title":"仮名会議","participants":[]}]})
        self.put("doctor_plans","2026-11",{"2026-11-06":{"am":["仮名医師"],"pm":[]}})
        before=list(self.db.iterdump())
        text=self.client.get("/inputs?month=2026-11").get_data(as_text=True)
        panel=text.split('class="panel review-missing"',1)[1].split('<nav class="review-jump"',1)[0]
        for title in ("公休日数が未設定","週の勤務上限が未設定","参加者の確認","検査室の必要人数が未設定"):
            self.assertIn(title,panel)
        self.assertNotIn("1日（日） 午前",panel)
        self.assertNotIn("3日（火） 午前",panel)
        self.assertNotIn("6日（金） 午後",panel)
        self.assertIn("2日（月） 午前",panel)
        self.assertEqual(before,list(self.db.iterdump()))

    def test_zero_target_is_configured_and_three_doctors_need_no_c_input(self):
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran) VALUES (1,'仮名常勤','nurse','full',1)")
        self.db.commit()
        self.put("monthly_settings","2026-11",{"targets":{"1":"0"},"closures":{},"meetings":[]})
        self.put("doctor_plans","2026-11",{"2026-11-02":{"am":["仮名甲","仮名乙","仮名丙"],"pm":["仮名甲"]}})
        self.put("coverage_settings","2026-11",{"2026-11-02_pm":{"c":1,"doctors":["仮名甲"]}})
        text=self.client.get("/inputs?month=2026-11").get_data(as_text=True)
        panel=text.split('class="panel review-missing"',1)[1].split('<nav class="review-jump"',1)[0]
        self.assertNotIn("公休日数が未設定",panel)
        self.assertNotIn("検査室の必要人数が未設定",panel)
