import json
import re
import unittest
import test_staff as helpers
from app import connect_db


class StaffDeletionTest(unittest.TestCase):
    setUp=helpers.StaffSettingsTest.setUp
    tearDown=helpers.StaffSettingsTest.tearDown
    save=helpers.StaffSettingsTest.save
    rows=helpers.StaffSettingsTest.rows

    def fields(self,staff_id=1):
        text=self.client.get("/staff/"+str(staff_id)+"/delete?month=2026-10").get_data(as_text=True)
        return dict(csrf_token=self.token,confirmed="yes",fingerprint=re.search(r'name="fingerprint" value="([^"]+)"',text)[1])

    def seed(self):
        self.save()
        self.save(name="看護 次郎")
        db=connect_db()
        try:
            monthly={"targets":{"1":"9","2":"10"},"wishes":{"1_2026-10-20":"full","2_2026-10-20":"am"},
                     "closures":{"2026-10-12":"holiday"},
                     "meetings":[{"id":"a","date":"2026-10-20","title":"会議","participants":["1","2"]},
                                 {"id":"b","date":"2026-10-21","title":"会議2","participants":["1"]}]}
            leave={"leaves":{"1_2026-10-20":"am","2_2026-10-21":"pm"},"history":{"1_2026-09-30":"rest","2_2026-09-30":"full"}}
            for table,data in (("monthly_settings",monthly),("leave_history",leave),("help_availability",{"1_2026-10-22":"am","2_2026-10-23":"full"})):
                db.execute("CREATE TABLE "+table+"(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
                for month in ("2026-10","2026-11"):
                    db.execute("INSERT INTO "+table+" VALUES (?,?)",(month,json.dumps(data)))
            db.execute("CREATE TABLE generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            db.execute("INSERT INTO generated_schedules VALUES ('2026-10','unchanged')")
            db.commit()
        finally:
            db.close()

    def test_preview_does_not_delete_and_csrf_and_confirmation_required(self):
        self.save()
        fields=self.fields()
        self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.client.post("/staff/1/delete",data={}).status_code,400)
        fields.pop("confirmed")
        response=self.client.post("/staff/1/delete",data=fields)
        self.assertIn("確認してチェック",response.get_data(as_text=True))
        self.assertEqual(len(self.rows()),1)

    def test_related_inputs_removed_atomically_others_and_results_preserved(self):
        self.seed()
        response=self.client.post("/staff/1/delete?month=2026-10",data=self.fields())
        self.assertEqual(response.status_code,302)
        self.assertEqual([p["id"] for p in self.rows()],[2])
        db=connect_db()
        try:
            for month in ("2026-10","2026-11"):
                monthly=json.loads(db.execute("SELECT data FROM monthly_settings WHERE month=?",(month,)).fetchone()[0])
                self.assertEqual(monthly["targets"],{"2":"10"})
                self.assertEqual(monthly["wishes"],{"2_2026-10-20":"am"})
                self.assertEqual(monthly["meetings"][0]["participants"],["2"])
                self.assertEqual(monthly["meetings"][1]["participants"],[])
                self.assertEqual(monthly["closures"],{"2026-10-12":"holiday"})
                leave=json.loads(db.execute("SELECT data FROM leave_history WHERE month=?",(month,)).fetchone()[0])
                self.assertEqual(leave["leaves"],{"2_2026-10-21":"pm"})
                self.assertEqual(leave["history"],{"2_2026-09-30":"full"})
                visits=json.loads(db.execute("SELECT data FROM help_availability WHERE month=?",(month,)).fetchone()[0])
                self.assertEqual(visits,{"2_2026-10-23":"full"})
            self.assertEqual(db.execute("SELECT data FROM generated_schedules").fetchone()[0],"unchanged")
            archive=json.loads(db.execute("SELECT data FROM deleted_staff").fetchone()[0])
            self.assertEqual(archive["staff"]["id"],1)
            self.assertEqual(len(archive["changes"]),6)
        finally:
            db.close()

    def test_changed_related_input_prevents_deletion(self):
        self.seed()
        fields=self.fields()
        db=connect_db()
        try:
            db.execute("UPDATE monthly_settings SET data=replace(data,'9','8')")
            db.commit()
        finally:
            db.close()
        response=self.client.post("/staff/1/delete",data=fields)
        self.assertIn("変更されました",response.get_data(as_text=True))
        self.assertEqual(len(self.rows()),2)

    def test_changed_profile_prevents_deletion_and_ids_not_reused(self):
        self.save()
        fields=self.fields()
        self.save(id="1",name="変更後の仮名")
        self.assertIn("変更されました",self.client.post("/staff/1/delete",data=fields).get_data(as_text=True))
        self.client.post("/staff/1/delete",data=self.fields())
        self.save(name="新しい仮名")
        self.assertEqual(self.rows()[0]["id"],2)

    def test_missing_staff_and_repeat_delete(self):
        self.assertEqual(self.client.get("/staff/999/delete").status_code,404)
        self.save()
        fields=self.fields()
        self.assertEqual(self.client.post("/staff/1/delete",data=fields).status_code,302)
        self.assertEqual(self.client.post("/staff/1/delete",data=fields).status_code,404)

    def test_id_prefix_does_not_remove_another_staff(self):
        self.seed()
        db=connect_db()
        try:
            data=json.loads(db.execute("SELECT data FROM monthly_settings WHERE month='2026-10'").fetchone()[0])
            data["wishes"]["11_2026-10-20"]="pm"
            db.execute("UPDATE monthly_settings SET data=? WHERE month='2026-10'",(json.dumps(data),))
            db.commit()
        finally:
            db.close()
        self.client.post("/staff/1/delete",data=self.fields())
        db=connect_db()
        try:
            data=json.loads(db.execute("SELECT data FROM monthly_settings WHERE month='2026-10'").fetchone()[0])
            self.assertEqual(data["wishes"]["11_2026-10-20"],"pm")
        finally:
            db.close()


    def test_weekly_boundary_records_deleted_only_for_target(self):
        self.save()
        self.save(name="看護 次郎")
        db=connect_db()
        try:
            db.execute("CREATE TABLE weekly_work_boundaries(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            db.execute("INSERT INTO weekly_work_boundaries VALUES (?,?)",("2026-02",json.dumps({"1_2026-01-31":"0.5","2_2026-01-31":"1.0"})))
            db.commit()
        finally:
            db.close()
        self.client.post("/staff/1/delete",data=self.fields())
        db=connect_db()
        try:
            data=json.loads(db.execute("SELECT data FROM weekly_work_boundaries").fetchone()[0])
            self.assertEqual(data,{"2_2026-01-31":"1.0"})
        finally:
            db.close()
