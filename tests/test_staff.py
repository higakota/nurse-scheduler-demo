import tempfile
import unittest
from pathlib import Path

from app import app, connect_db


class StaffSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_database = app.config["DATABASE"]
        app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "staff.sqlite3"))
        self.client = app.test_client()
        self.client.get("/staff")
        with self.client.session_transaction() as session:
            self.token = session["csrf_token"]

    def tearDown(self):
        app.config["DATABASE"] = self.old_database
        self.temp.cleanup()

    def save(self, **fields):
        data = dict(csrf_token=self.token, name="看護 花子", role="nurse", employment="full")
        data.update(fields)
        return self.client.post("/staff", data=data)

    def rows(self):
        db = connect_db()
        try:
            return [dict(row) for row in db.execute("SELECT * FROM staff")]
        finally:
            db.close()

    def test_register_edit_and_persist(self):
        self.assertEqual(self.save(veteran="1").status_code, 302)
        row = self.rows()[0]
        self.assertEqual((row["employment"], row["veteran"]), ("full", 1))
        self.assertEqual(self.save(id=str(row["id"]), name="看護 次郎", employment="part").status_code, 302)
        row = self.rows()[0]
        self.assertEqual((row["name"], row["employment"], row["veteran"]), ("看護 次郎", "part", 0))
        other_client = app.test_client()
        self.assertIn("看護 次郎", other_client.get("/staff").get_data(as_text=True))

    def test_technician_cannot_count_as_veteran(self):
        self.save(name="検査 花子", role="technician", employment="full", veteran="1")
        row = self.rows()[0]
        self.assertEqual((row["employment"], row["veteran"]), ("", 0))
        self.assertIn("検査室のみ", self.client.get("/staff").get_data(as_text=True))

    def test_invalid_input_does_not_write(self):
        for fields in (dict(name=" "), dict(name="あ" * 51), dict(role="invalid"), dict(employment="invalid")):
            self.assertEqual(self.save(**fields).status_code, 200)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.save(csrf_token="wrong").status_code, 400)
        self.assertEqual(self.save(id="999").status_code, 404)
        self.assertEqual(self.rows(), [])

    def test_output_escapes_html(self):
        self.save(name="<script>alert(1)</script>")
        page = self.client.get("/staff").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
