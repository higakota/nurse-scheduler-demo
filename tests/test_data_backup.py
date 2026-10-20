import sqlite3
import tempfile
import unittest
from pathlib import Path
from app import app

class BackupTest(unittest.TestCase):
    def test_download_preserves_all_tables_without_changing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            old = app.config["DATABASE"]
            app.config["DATABASE"] = str(Path(folder) / "source.sqlite3")
            try:
                db = sqlite3.connect(app.config["DATABASE"])
                db.execute("CREATE TABLE sample(value TEXT)")
                db.execute("INSERT INTO sample VALUES (?)", ("仮名の予定",))
                db.commit()
                db.close()
                client = app.test_client()
                page = client.get("/backup?month=2026-11")
                self.assertEqual(page.status_code, 200)
                self.assertIn("バックアップ".encode(), page.data)
                result = client.get("/backup/download")
                self.assertEqual(result.status_code, 200)
                self.assertIn("attachment;", result.headers["Content-Disposition"])
                self.assertEqual(result.headers["Cache-Control"], "no-store")
                copy = sqlite3.connect(":memory:")
                copy.deserialize(result.data)
                self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(copy.execute("SELECT value FROM sample").fetchone()[0], "仮名の予定")
                self.assertIsNotNone(copy.execute("SELECT name FROM sqlite_master WHERE name='staff'").fetchone())
                copy.close()
                db = sqlite3.connect(app.config["DATABASE"])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 1)
                db.close()
            finally:
                app.config["DATABASE"] = old

class RestoreTest(unittest.TestCase):
    def setUp(self):
        from app import connect_db
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config["DATABASE"]
        app.config["DATABASE"] = str(Path(self.temp.name) / "staff.sqlite3")
        self.db = connect_db()
        self.db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('仮名一','nurse','full',0)")
        self.db.commit()
        self.client = app.test_client()
        self.client.get("/backup?month=2026-11")
        self.payload = self.client.get("/backup/download").data
        self.db.execute("UPDATE staff SET name='仮名二'")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.config["DATABASE"] = self.old
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as sess:
            return sess["csrf_token"]

    def preview(self, payload=None):
        from io import BytesIO
        return self.client.post("/backup/preview?month=2026-11",
            data={"csrf_token":self.csrf(),"backup":(BytesIO(payload or self.payload),"backup.sqlite3")})

    def restore(self):
        with self.client.session_transaction() as sess:
            token = sess["restore_preview"]["token"]
        return self.client.post("/backup/restore?month=2026-11",
            data={"csrf_token":self.csrf(),"token":token,"confirm":"yes"})

    def test_preview_then_restore_and_safety_copy(self):
        self.assertEqual(self.preview().status_code,200)
        self.assertEqual(self.db.execute("SELECT name FROM staff").fetchone()[0],"仮名二")
        self.assertEqual(self.restore().status_code,303)
        self.assertEqual(self.db.execute("SELECT name FROM staff").fetchone()[0],"仮名一")
        safety = list((Path(self.temp.name)/"backups").glob("before_restore_*.sqlite3"))
        self.assertEqual(len(safety),1)
        before = sqlite3.connect(safety[0])
        self.assertEqual(before.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        self.assertEqual(before.execute("SELECT name FROM staff").fetchone()[0],"仮名二")
        before.close()

    def test_concurrent_change_is_preserved(self):
        self.preview()
        self.db.execute("UPDATE staff SET name='仮名三'")
        self.db.commit()
        self.assertEqual(self.restore().status_code,400)
        self.assertEqual(self.db.execute("SELECT name FROM staff").fetchone()[0],"仮名三")

    def test_invalid_or_unexpected_database_is_rejected(self):
        self.assertEqual(self.preview(b"not sqlite").status_code,400)
        other=sqlite3.connect(":memory:")
        other.deserialize(self.payload)
        other.execute("CREATE TRIGGER unsafe AFTER INSERT ON staff BEGIN DELETE FROM staff; END")
        other.commit()
        self.assertEqual(self.preview(other.serialize()).status_code,400)
        other.close()
        self.assertEqual(self.db.execute("SELECT name FROM staff").fetchone()[0],"仮名二")

    def test_csrf_and_explicit_confirmation_required(self):
        self.assertEqual(self.client.post("/backup/preview").status_code,400)
        self.preview()
        with self.client.session_transaction() as sess:
            token=sess["restore_preview"]["token"]
        response=self.client.post("/backup/restore",data={"csrf_token":self.csrf(),"token":token})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.db.execute("SELECT name FROM staff").fetchone()[0],"仮名二")
