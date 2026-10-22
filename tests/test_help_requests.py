import json
import re
import unittest
from app import app, connect_db
from help_requests import proposal, signer, load_requests
from schedule import read_snapshot
import test_scheduler as fixtures


class HelpRequestsTest(unittest.TestCase):
    def setUp(self):
        fixtures.ScheduleRouteTest.setUp(self)
        self.addCleanup(app.config.__setitem__, "HELP_REQUESTS_ENABLED", app.config.get("HELP_REQUESTS_ENABLED", False))
        app.config["HELP_REQUESTS_ENABLED"] = True
    tearDown = fixtures.ScheduleRouteTest.tearDown

    def fields(self):
        page = self.client.get("/help-requests?month=2026-02").get_data(as_text=True)
        return {name: re.search('name="' + name + '" value="([^"]*)"', page)[1]
                for name in ("csrf_token", "token")} if 'name="token"' in page else {
                    "csrf_token": self.csrf()}

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def create(self, count=2, veteran=1, half="午前", role="nurse"):
        self.client.get("/help-requests?month=2026-02")
        db = connect_db()
        try:
            _, fp, _ = read_snapshot(db, "2026-02")
        finally:
            db.close()
        rows = [dict(date="2026-02-02", half=half, missing=count, veteran_missing=veteran,
                     area="診療の看護師合計" if role == "nurse" else "検査技師（C番として計上）")]
        token = proposal(app, "2026-02", fp, rows, True)
        return self.client.post("/help-requests?month=2026-02",
                                data=dict(csrf_token=self.csrf(), action="create", proposal=token))

    def helpers(self):
        db = connect_db()
        for row in [(21,"ヘルプ仮名","nurse",1,"ABC"), (22,"技師仮名","technician",0,"C")]:
            db.execute("INSERT INTO staff(id,name,role,veteran,allowed_areas,is_help,employment) VALUES (?,?,?,?,?,1,'full')", row)
        db.commit()
        db.close()

    def data(self):
        db = connect_db()
        try:
            return load_requests(db, "2026-02")
        finally:
            db.close()

    def post(self, key, **values):
        return self.client.post("/help-requests?month=2026-02",
                                data=dict(self.fields(), key=key, **values))

    def test_create_deduplicate_and_preserve_reply(self):
        self.assertEqual(self.create().status_code, 302)
        key = next(iter(self.data()["slots"]))
        self.post(key, action="save", status="waiting", person="")
        self.create()
        data = self.data()
        self.assertEqual(len(data["slots"]), 2)
        self.assertEqual(data["slots"][key]["status"], "waiting")
        self.assertEqual(sum(x["veteran"] for x in data["slots"].values()), 1)

    def test_veteran_only_is_one_replacement_not_extra_count(self):
        self.create(count=0)
        items = list(self.data()["slots"].values())
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["replacement"])
        self.assertIn("人数は充足", self.client.get("/help-requests?month=2026-02").get_data(as_text=True))

    def test_apply_merge_and_duplicate_person_rejected(self):
        self.helpers()
        self.create()
        keys = list(self.data()["slots"])
        response = self.post(keys[0], action="apply", status="ok", person="21", period="am")
        self.assertEqual(response.status_code, 302)
        response = self.post(keys[1], action="apply", status="ok", person="21", period="am")
        self.assertIn("同じ人", response.get_data(as_text=True))
        self.create(half="午後")
        key = next(k for k in self.data()["slots"] if "_pm_" in k)
        self.assertEqual(self.post(key, action="apply", status="ok", person="21", period="pm").status_code, 302)
        db = connect_db()
        visits = json.loads(db.execute("SELECT data FROM help_availability WHERE month='2026-02'").fetchone()[0])
        db.close()
        self.assertEqual(visits["21_2026-02-02"], "full")

    def test_reject_wrong_role_pm_technician_and_stale_forms_atomically(self):
        self.helpers()
        self.create(count=1, veteran=0, role="technician", half="午後")
        key = next(iter(self.data()["slots"]))
        for person in ("21", "22"):
            response = self.post(key, action="apply", status="ok", person=person, period="pm")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(self.data()["slots"][key]["applied"])
        old = self.fields()
        self.post(key, action="save", status="waiting", person="22")
        response = self.client.post("/help-requests?month=2026-02",
                                   data=dict(old, key=key, action="save", status="no", person="22"))
        self.assertIn("別の画面", response.get_data(as_text=True))
        self.assertEqual(self.data()["slots"][key]["status"], "waiting")
        self.assertEqual(self.post(key, action="apply", status="ok", person="22", period="full").status_code,302)

    def test_tampered_proposal_and_csrf_cannot_write(self):
        self.client.get("/help-requests?month=2026-02")
        self.assertEqual(self.client.post("/help-requests?month=2026-02", data={"action":"create"}).status_code, 400)
        response = self.client.post("/help-requests?month=2026-02",
                                   data=dict(action="create", csrf_token=self.csrf(), proposal="tampered"))
        self.assertIn("候補が無効", response.get_data(as_text=True))
        self.assertFalse(self.data()["slots"])

    def test_draft_goes_directly_to_visits_without_consultation(self):
        db = connect_db()
        row = db.execute("SELECT data FROM monthly_settings").fetchone()
        data = json.loads(row[0])
        data["wishes"]["1_2026-02-02"] = "full"
        data["targets"]["1"] = "28"
        data["wishes"]["2_2026-02-02"] = "full"
        data["targets"]["2"] = "28"
        db.execute("UPDATE monthly_settings SET data=?", (json.dumps(data),))
        db.commit()
        db.close()
        fields = fixtures.ScheduleRouteTest.fields(self)
        fields["mode"] = "draft"
        response = self.client.post("/schedule?month=2026-02", data=fields)
        page = response.get_data(as_text=True)
        self.assertNotIn('name="proposal"', page)
        self.assertNotIn('href="/help-requests', page)
        self.assertIn('href="/help?month=2026-02"', page)
        self.assertIn("決まったヘルプの来院予定を登録する", page)

    def bulk(self, keys, **values):
        return self.client.post("/help-requests?month=2026-02",
                                data=dict(self.fields(), action="bulk", keys=keys, **values))

    def test_bulk_status_and_no_implicit_visits(self):
        self.create()
        keys = list(self.data()["slots"])
        self.assertEqual(self.bulk(keys, operation="save", status="waiting", person="", period="requested").status_code,302)
        self.assertTrue(all(x["status"] == "waiting" for x in self.data()["slots"].values()))
        db = connect_db()
        self.assertIsNone(db.execute("SELECT data FROM help_availability").fetchone())
        db.close()

    def test_bulk_both_halves_merge_for_technician(self):
        self.helpers()
        self.create(count=1, veteran=0, role="technician", half="午前")
        self.create(count=1, veteran=0, role="technician", half="午後")
        # 更新時に以前の候補は不要扱いになるため、このテストでは同日両時間帯の候補を明示する。
        db=connect_db()
        data=load_requests(db,"2026-02")
        for item in data["slots"].values():
            item["obsolete"]=False
        db.execute("UPDATE help_requests SET data=?", (json.dumps(data),))
        db.commit()
        db.close()
        response=self.bulk(list(data["slots"]), operation="apply",status="ok",person="22",period="requested")
        self.assertEqual(response.status_code,302)
        self.assertTrue(all(item["applied"] for item in self.data()["slots"].values()))
        db=connect_db()
        visits=json.loads(db.execute("SELECT data FROM help_availability").fetchone()[0])
        db.close()
        self.assertEqual(visits["22_2026-02-02"],"full")

    def test_bulk_duplicate_rolls_back_entire_batch(self):
        self.helpers()
        self.create()
        before=self.data()
        response=self.bulk(list(before["slots"]),operation="apply",status="ok",person="21",period="requested")
        self.assertIn("同じ人",response.get_data(as_text=True))
        self.assertEqual(self.data(),before)
        db=connect_db()
        self.assertIsNone(db.execute("SELECT data FROM help_availability").fetchone())
        db.close()

    def test_bulk_invalid_key_and_stale_token_preserve_records(self):
        self.create()
        keys=list(self.data()["slots"])
        old=self.fields()
        before=self.data()
        response=self.bulk([keys[0],"not-a-slot"],operation="save",status="no",person="",period="requested")
        self.assertIn("見つかりません",response.get_data(as_text=True))
        self.assertEqual(self.data(),before)
        self.bulk(keys,operation="save",status="waiting",person="",period="requested")
        response=self.client.post("/help-requests?month=2026-02",
                                 data=dict(old,action="bulk",keys=keys,operation="save",status="no"))
        self.assertIn("別の画面",response.get_data(as_text=True))
        self.assertTrue(all(item["status"]=="waiting" for item in self.data()["slots"].values()))


class SimplifiedHelpFlowTest(unittest.TestCase):
    setUp = fixtures.ScheduleRouteTest.setUp
    tearDown = fixtures.ScheduleRouteTest.tearDown

    def test_old_links_and_posts_preserve_data_and_redirect_to_visits(self):
        self.assertFalse(app.config.get("HELP_REQUESTS_ENABLED"))
        db=connect_db()
        old={"slots": {"example": {"status": "waiting"}}, "fingerprint": "", "experimental": False}
        db.execute("CREATE TABLE help_requests(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("CREATE TABLE help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        raw=json.dumps(old)
        visits=json.dumps({"9_2026-02-02":"am"})
        db.execute("INSERT INTO help_requests VALUES (?,?)",("2026-02",raw))
        db.execute("INSERT INTO help_availability VALUES (?,?)",("2026-02",visits))
        db.commit()
        db.close()
        for method in ("get","post"):
            response=getattr(self.client,method)("/help-requests?month=2026-02")
            self.assertEqual(response.status_code,303)
            self.assertEqual(response.location,"/help?month=2026-02")
        db=connect_db()
        self.assertEqual(db.execute("SELECT data FROM help_requests").fetchone()[0],raw)
        self.assertEqual(db.execute("SELECT data FROM help_availability").fetchone()[0],visits)
        db.close()
        for url in ("/?month=2026-02","/schedule?month=2026-02","/help?month=2026-02"):
            page=self.client.get(url).get_data(as_text=True)
            self.assertNotIn('href="/help-requests',page)
            self.assertNotIn("ヘルプ相談リスト",page)
