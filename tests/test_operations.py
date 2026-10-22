from contextlib import closing
import json, sqlite3, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from previous_roster import history_code, inherited_history, apply_inheritance
from automatic_backup import backup_database
import launcher
import runtime_tools

class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.db=self.root/"staff.sqlite3"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE manual_schedules(month TEXT,data TEXT)")
            db.execute("CREATE TABLE input(value TEXT)")
            db.execute("INSERT INTO input VALUES ('original')")
    def tearDown(self):
        self.temp.cleanup()
    def test_history_codes(self):
        for pair,expected in dict(DD="full",DM="full",TT="full",DR="am",RD="pm",DP="pm_paid",PD="am_paid",PP="paid",SS="rest").items():
            self.assertEqual(history_code(pair),expected)
    def save_previous(self,pair="DD"):
        source=dict(updated="saved",people=[dict(id=7,is_help=0),dict(id=8,is_help=1)],days=["2024-02-29"],grid=[[pair,"DD"]])
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("DELETE FROM manual_schedules")
            db.execute("INSERT INTO manual_schedules VALUES (?,?)",("2024-02",json.dumps(source)))
    def test_inherit_leap_day_and_manual_override(self):
        self.save_previous()
        people=[dict(id=7,is_help=0),dict(id=8,is_help=1),dict(id=9,is_help=0)]
        with closing(sqlite3.connect(self.db)) as db, db:
            history,source=inherited_history(db,"2024-03",people)
            self.assertEqual(history,{"7_2024-02-29":"full"})
            data,_=apply_inheritance(db,"2024-03",people,{"history":{"7_2024-02-29":"rest"}})
            self.assertEqual(data["history"]["7_2024-02-29"],"rest")
            self.assertEqual(source["month"],"2024-02")
        self.save_previous("RR")
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(inherited_history(db,"2024-03",people)[0]["7_2024-02-29"],"rest")
    def test_no_previous_is_empty(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(inherited_history(db,"2026-01",[]),({},None))
    def test_daily_backups_start_immutable_latest_updated_and_jst_date(self):
        now=datetime(2026,10,21,16,tzinfo=timezone.utc)
        start=backup_database(self.db,"start",now)
        self.assertTrue(start.name.startswith("2026-10-22"))
        latest=backup_database(self.db,"latest",now)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE input SET value='changed'")
        backup_database(self.db,"start",now)
        backup_database(self.db,"latest",now)
        with closing(sqlite3.connect(start)) as db:
            self.assertEqual(db.execute("SELECT value FROM input").fetchone()[0],"original")
        with closing(sqlite3.connect(latest)) as db:
            self.assertEqual(db.execute("SELECT value FROM input").fetchone()[0],"changed")
    def test_atomic_backup_failure_keeps_previous_copy(self):
        target=backup_database(self.db)
        old=target.read_bytes()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE input SET value='changed'")
        with patch("automatic_backup.os.fsync",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                backup_database(self.db)
        self.assertEqual(target.read_bytes(),old)
    def test_launch_reuses_existing_server(self):
        with patch("launcher.health",return_value={"app":"nurse-scheduler","version":"workspace","owner":launcher.token(self.root)}),patch("launcher.subprocess.Popen") as spawn,patch("launcher.webbrowser.open") as browser:
            launcher.launch(self.root)
            spawn.assert_not_called()
            browser.assert_called_once()
    def test_launch_rejects_other_application(self):
        with patch("launcher.health",return_value={"app":"other"}),patch("launcher.subprocess.Popen") as spawn:
            with self.assertRaises(RuntimeError):
                launcher.launch(self.root)
            spawn.assert_not_called()
    def test_stop_does_not_kill_unowned_server(self):
        with patch("launcher.health",return_value={"app":"nurse-scheduler","pid":123,"owner":"other"}),patch("launcher.os.kill") as kill:
            with self.assertRaises(RuntimeError):
                launcher.stop_owned(self.root)
            kill.assert_not_called()
    def test_rollback_preserves_database(self):
        old={"code":"old","python":"python","version":"a"}
        new={"code":"new","python":"python","version":"b"}
        launcher.atomic_json(self.root/".runtime/versions.json",{"current":new,"previous":old})
        before=self.db.read_bytes()
        with patch("runtime_tools.launch"),patch("runtime_tools.stop_owned"):
            runtime_tools.rollback(self.root)
        self.assertEqual(launcher.state(self.root)["current"],old)
        self.assertEqual(self.db.read_bytes(),before)
    def test_failed_activation_returns_to_old_manifest(self):
        before=launcher.state(self.root)
        with patch("runtime_tools.launch",side_effect=[RuntimeError("bad release"),None]),patch("runtime_tools.stop_owned"):
            with self.assertRaises(RuntimeError):
                runtime_tools.activate(self.root,{"current":{"version":"bad"}})
        self.assertEqual(launcher.state(self.root),before)
    def test_archive_path_traversal_rejected(self):
        import io,zipfile
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,"w") as zipped:
            zipped.writestr("../outside.txt","bad")
        with patch("runtime_tools.git",return_value=archive.getvalue()):
            with self.assertRaises(ValueError):
                runtime_tools.extract_release(self.root,"a"*40)
        self.assertFalse((self.root/".runtime/outside.txt").exists())


    def test_launch_keeps_database_in_original_folder(self):
        token=launcher.token(self.root)
        current={"code":str(self.root/"release"),"python":"python","version":"a"*40}
        launcher.atomic_json(self.root/".runtime/versions.json",{"current":current})
        process=type("Process",(),{"pid":42})()
        with patch("launcher.health",side_effect=[None,{"owner":token,"version":"a"*40}]),patch("launcher.subprocess.Popen",return_value=process) as spawn,patch("automatic_backup.backup_database"):
            launcher.launch(self.root,open_browser=False)
        self.assertEqual(spawn.call_args.kwargs["env"]["NURSE_SCHEDULER_DATABASE"],str(self.root/"instance/staff.sqlite3"))

    def test_update_failed_tests_keeps_current_release(self):
        (self.root/"requirements.txt").write_text("same")
        candidate=self.root/"candidate"
        candidate.mkdir()
        (candidate/"requirements.txt").write_text("same")
        before=launcher.state(self.root)
        result=type("Result",(),{"returncode":1})()
        with patch("runtime_tools.git",side_effect=[b"",b"",b"a"*40]),patch("runtime_tools.extract_release",return_value=candidate),patch("runtime_tools.subprocess.run",return_value=result),patch("runtime_tools.activate") as activate:
            (self.root/".runtime").mkdir(exist_ok=True)
            with self.assertRaises(RuntimeError):
                runtime_tools.update(self.root)
            activate.assert_not_called()
        self.assertEqual(launcher.state(self.root),before)

class BackupHooksTest(unittest.TestCase):
    def test_post_is_backed_up_and_failed_backup_prevents_write(self):
        from flask import Flask
        from automatic_backup import register_automatic_backup
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"db.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE sample(value TEXT)")
            app=Flask(__name__)
            app.config["DATABASE"]=str(path)
            register_automatic_backup(app)
            @app.post("/save")
            def save():
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("INSERT INTO sample VALUES ('saved')")
                return "ok"
            client=app.test_client()
            self.assertEqual(client.post("/save").status_code,200)
            self.assertEqual(len(list((path.parent/"backups/automatic").glob("*.sqlite3"))),2)
            with patch("automatic_backup.backup_database",side_effect=OSError("disk full")), patch.object(app.logger,"exception"):
                self.assertEqual(client.post("/save").status_code,503)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sample").fetchone()[0],1)
