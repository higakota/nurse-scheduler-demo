"""操作順の違い・繰り返し・半日単位の入力を一時DBで検証する。"""
import html,json,re,unittest
from app import connect_db
import test_scheduler as fixtures


class OperationSequencesTest(unittest.TestCase):
    setUp=fixtures.ScheduleRouteTest.setUp
    tearDown=fixtures.ScheduleRouteTest.tearDown

    def tokens(self,page):
        return {key:html.unescape(re.search('name="'+key+'" value="([^"]*)"',page)[1])
                for key in ("csrf_token","fingerprint","revision")}

    def stored(self):
        db=connect_db()
        try:
            if not db.execute("SELECT name FROM sqlite_master WHERE name=\'manual_schedules\'").fetchone():return None
            raw=db.execute("SELECT data FROM manual_schedules WHERE month='2026-02'").fetchone()
            return json.loads(raw[0]) if raw else None
        finally:db.close()

    def inputs(self,table,change):
        db=connect_db()
        try:
            value=json.loads(db.execute("SELECT data FROM "+table+" WHERE month='2026-02'").fetchone()[0])
            change(value)
            db.execute("UPDATE "+table+" SET data=? WHERE month='2026-02'",(json.dumps(value),))
            db.commit()
        finally:db.close()

    def start(self):
        result=self.client.post("/schedule?month=2026-02",data=fixtures.ScheduleRouteTest.fields(self))
        self.assertEqual(result.status_code,302)
        self.update()

    def review(self):
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        before=self.stored()
        response=self.client.post("/schedule/manual?month=2026-02",data=dict(self.tokens(page),action="update_roster"))
        review=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn("保存前の変更確認",review)
        self.assertEqual(self.stored(),before)
        return review

    def save_review(self,review):
        fields=dict(self.tokens(review),action="save",input_priority="yes",confirm="yes",help_consent="yes",
                    patch=html.unescape(re.search('name="patch" value="([^"]*)"',review)[1]))
        response=self.client.post("/schedule/manual?month=2026-02",data=fields)
        self.assertEqual(response.status_code,303,response.get_data(as_text=True)[:400])
        return fields

    def update(self):
        self.save_review(self.review())
        return self.stored()

    def test_paid_full_half_cancel_and_repeated_save(self):
        self.start()
        for value,pair in (("full","PP"),("am","PD"),("pm","DP"),("","DD"),("full","PP"),("","DD")):
            with self.subTest(period=value):
                def change(data):
                    data["leaves"]={"1_2026-02-02":value} if value else {}
                self.inputs("leave_history",change)
                saved=self.update()
                self.assertEqual(saved["grid"][1][0],pair)
                db=connect_db()
                try:leaves=json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])["leaves"]
                finally:db.close()
                self.assertEqual(leaves.get("1_2026-02-02",""),value)
                same=self.update()
                self.assertEqual(same["grid"],saved["grid"])

    def test_summer_and_outreach_switch_half_and_cancel(self):
        self.start()
        for kind,code in (("summer","S"),("support","T")):
            for value in ("full","am","pm",""):
                with self.subTest(kind=kind,period=value):
                    self.inputs("monthly_settings",lambda data:data.update({kind:{"1_2026-02-02":value} if value else {}}))
                    saved=self.update()
                    expected=code*2 if value=="full" else code+"D" if value=="am" else "D"+code if value=="pm" else "DD"
                    self.assertEqual(saved["grid"][1][0],expected)

    def test_old_review_and_double_save_cannot_overwrite_new_input(self):
        self.start()
        old=self.review()
        self.inputs("leave_history",lambda data:data.update(leaves={"1_2026-02-02":"full"}))
        before=self.stored()
        fields=dict(self.tokens(old),action="save",input_priority="yes",confirm="yes",
                    patch=html.unescape(re.search('name="patch" value="([^"]*)"',old)[1]))
        rejected=self.client.post("/schedule/manual?month=2026-02",data=fields).get_data(as_text=True)
        self.assertIn("別の画面で変更",rejected)
        self.assertEqual(self.stored(),before)
        new_fields=self.save_review(self.review())
        after=self.stored()
        self.client.post("/schedule/manual?month=2026-02",data=new_fields)
        self.assertEqual(self.stored(),after)

    def test_candidate_can_extend_existing_half_paid_leave(self):
        self.start()
        self.inputs("leave_history",lambda data:data.update(leaves={"1_2026-02-02":"am"}))
        self.update()
        page=self.client.get("/schedule/manual?month=2026-02").get_data(as_text=True)
        forms=[{k:html.unescape(v) for k,v in re.findall(r'name="([^"]+)" value="([^"]*)"',body)}
               for body in re.findall(r'<form[^>]+action="/schedule/paid-candidate[^"]*"[^>]*>(.*?)</form>',page,re.S)]
        candidate=next((f for f in forms if f.get("staff")=="1" and f.get("period")=="pm"),None)
        self.assertIsNotNone(candidate,"午前有給の人も、条件を満たす午後を追加できる")
        response=self.client.post("/schedule/paid-candidate?month=2026-02",data=candidate)
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.stored()["grid"][1][0],"PP")
        db=connect_db()
        try:self.assertEqual(json.loads(db.execute("SELECT data FROM leave_history").fetchone()[0])["leaves"]["1_2026-02-02"],"full")
        finally:db.close()

    def test_helper_full_half_cancel_and_reregister_then_refresh_shortages(self):
        self.start()
        def leave(data):
            for pid in ("1","2"):
                data["wishes"][pid+"_2026-02-02"]="full"
                data["targets"][pid]="28"
        self.inputs("monthly_settings",leave)
        self.update()
        db=connect_db()
        db.execute("INSERT INTO staff(id,name,role,employment,veteran,is_help,allowed_areas) VALUES (9,?, 'nurse','full',1,1,'ABC')",("応援仮名",))
        db.commit();db.close()
        from schedule import read_snapshot
        from help_shortages import shortages_from_source
        for period,expected in (("full","DD"),("am","DR"),("","RR"),("full","DD")):
            with self.subTest(period=period):
                page=self.client.get("/help?month=2026-02").get_data(as_text=True)
                fingerprint=re.search('name="fingerprint" value="([^"]*)"',page)[1]
                with self.client.session_transaction() as state:csrf=state["csrf_token"]
                response=self.client.post("/help?month=2026-02",data=dict(csrf_token=csrf,fingerprint=fingerprint,changes=json.dumps({"9_2026-02-02":period})))
                self.assertEqual(response.status_code,302)
                saved=self.update()
                index=next(i for i,p in enumerate(saved["people"]) if p["id"]==9)
                self.assertEqual(saved["grid"][1][index],expected)
                db=connect_db()
                try:
                    snapshot,_,_=read_snapshot(db,"2026-02")
                    missing=shortages_from_source(snapshot,json.dumps(saved))
                finally:db.close()
                self.assertEqual(bool(missing),period!="full")
                if period=="am":
                    self.assertTrue(all(row["half"]=="午後" for row in missing))
                response=self.client.post("/help/shortages?month=2026-02",data=dict(csrf_token=csrf))
                self.assertEqual(response.status_code,303)
                self.assertEqual(self.stored(),saved)

    def test_wishes_win_when_meetings_are_added_before_or_after_them(self):
        self.start()
        meeting=dict(id="sequence",date="2026-02-02",title="仮名会議",participants=["1"])
        def initial(data):
            data["wishes"]["1_2026-02-02"]="full"
            data["targets"]["1"]="28"
        self.inputs("monthly_settings",initial)
        saved=self.update()
        self.assertEqual(saved["grid"][1][0],"RR")
        self.inputs("monthly_settings",lambda data:data.update(meetings=[meeting]))
        self.assertEqual(self.update()["grid"][1][0],"RR")
        def remove(data):
            data["wishes"].pop("1_2026-02-02")
            data["targets"]["1"]="27"
        self.inputs("monthly_settings",remove)
        self.assertEqual(self.update()["grid"][1][0],"DM")
        self.inputs("monthly_settings",initial)
        self.assertEqual(self.update()["grid"][1][0],"RR")
