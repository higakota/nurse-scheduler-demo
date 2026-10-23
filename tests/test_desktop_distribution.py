import hashlib, json, sqlite3, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
import desktop_runtime as runtime

class DesktopDistributionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.home=self.root/"installed"
        self.home.mkdir()
    def package(self,version="v1",extra=None):
        target=self.root/(version+".zip")
        files={runtime.EXE_NAME:b"fake executable","_internal/templates/home.html":b"fake template"}
        files.update(extra or {})
        manifest={"format":1,"version":version,"files":{name:hashlib.sha256(value).hexdigest() for name,value in files.items()}}
        with zipfile.ZipFile(target,"w") as archive:
            for name,value in files.items():archive.writestr(name,value)
            archive.writestr("package.json",json.dumps(manifest))
        return target
    def database(self):
        path=self.home/"data/staff.sqlite3";path.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE sample(value TEXT)")
            db.execute("INSERT INTO sample VALUES ('fictional input')")
        return path
    def values(self,path):
        with closing(sqlite3.connect(path)) as db, db:return db.execute("SELECT value FROM sample").fetchall()
    def test_first_install_update_and_rollback_preserve_data(self):
        db=self.database()
        with patch.object(runtime,"stop"),patch.object(runtime,"launch"),patch.object(runtime.subprocess,"run") as check:
            check.return_value.returncode=0
            runtime.install(self.package(),self.home,port=5088,shortcuts=False)
            self.assertEqual(runtime.installed_state(self.home)["current"],"v1")
            runtime.install(self.package("v2"),self.home,shortcuts=False)
            self.assertEqual(runtime.installed_state(self.home),{"current":"v2","previous":"v1","port":5088})
            with closing(sqlite3.connect(db)) as connection, connection:connection.execute("INSERT INTO sample VALUES ('after update')")
            runtime.rollback(self.home)
        self.assertEqual(runtime.installed_state(self.home)["current"],"v1")
        self.assertEqual(self.values(db),[("fictional input",),("after update",)])
        backups=list((self.home/"data/backups").glob("before_update_*.sqlite3"))
        self.assertEqual(len(backups),3)
        self.assertEqual(self.values(backups[0])[0],("fictional input",))
    def test_reinstall_same_version_does_not_reset_data(self):
        db=self.database()
        with patch.object(runtime,"stop"),patch.object(runtime,"launch"),patch.object(runtime.subprocess,"run") as check:
            check.return_value.returncode=0
            package=self.package()
            runtime.install(package,self.home,shortcuts=False)
            check.reset_mock()
            runtime.install(package,self.home,shortcuts=False)
            check.assert_not_called()
        self.assertEqual(self.values(db),[("fictional input",)])
    def test_bad_self_check_does_not_activate(self):
        db=self.database()
        with patch.object(runtime.subprocess,"run") as check:
            check.return_value.returncode=1
            with self.assertRaises(RuntimeError):runtime.install(self.package(),self.home,shortcuts=False)
        self.assertIsNone(runtime.installed_state(self.home))
        self.assertEqual(self.values(db),[("fictional input",)])
    def test_failed_start_restores_previous_code_and_keeps_backup(self):
        db=self.database()
        old={"current":"v1","previous":None,"port":5088}
        runtime.atomic_json(self.home/"installation.json",old)
        with patch.object(runtime,"stop"),patch.object(runtime,"launch",side_effect=[RuntimeError("failed"),None]):
            with self.assertRaises(RuntimeError):
                runtime.activate(self.home,dict(current="v2",previous="v1",port=5088))
        self.assertEqual(runtime.installed_state(self.home),old)
        self.assertEqual(self.values(db),[("fictional input",)])
        self.assertTrue(list((self.home/"data/backups").glob("*.sqlite3")))
    def test_corrupt_package_is_rejected_without_touching_data(self):
        db=self.database()
        target=self.package()
        with zipfile.ZipFile(target) as archive:
            content={name:archive.read(name) for name in archive.namelist()}
        content[runtime.EXE_NAME]=b"changed"
        with zipfile.ZipFile(target,"w") as archive:
            for name,payload in content.items():archive.writestr(name,payload)
        with self.assertRaises(ValueError):runtime.install(target,self.home,shortcuts=False)
        self.assertIsNone(runtime.installed_state(self.home))
        self.assertEqual(self.values(db),[("fictional input",)])
    def test_unsafe_paths_data_and_case_collisions_are_rejected(self):
        for name in ("../outside.exe","C:/outside.exe","_internal/../../outside.exe","instance/staff.sqlite3","data/value.txt","staff.db","INPUT.XLSX","_internal/CON.txt","_internal/file."):
            with self.subTest(name=name),self.assertRaises(ValueError):
                runtime.validate_package(self.package(extra={name:b"unsafe"}))
        with self.assertRaises(ValueError):
            runtime.validate_package(self.package(extra={"nursescheduler.exe":b"collision"}))
        self.assertFalse((self.root/"outside.exe").exists())
    def test_symlink_is_rejected(self):
        target=self.package()
        with zipfile.ZipFile(target,"a") as archive:
            entry=zipfile.ZipInfo("link")
            entry.create_system=3;entry.external_attr=0o120777<<16
            archive.writestr(entry,"../outside")
        with self.assertRaises(ValueError):runtime.validate_package(target)
    def test_windows_transient_file_lock_is_retried(self):
        source=self.root/"staging";source.mkdir()
        (source/"file.txt").write_text("application")
        destination=self.root/"release"
        original=Path.rename
        attempts=[]
        def rename(path,target):
            attempts.append(1)
            if len(attempts)==1:raise PermissionError("temporary file scan")
            return original(path,target)
        with patch.object(Path,"rename",rename),patch.object(runtime.time,"sleep"):
            runtime.move_staged_release(source,destination)
        self.assertEqual(len(attempts),2)
        self.assertTrue((destination/"file.txt").exists())
    def test_unknown_previous_version_is_rejected(self):
        with self.assertRaises(RuntimeError):runtime.rollback(self.home)
    def test_different_package_cannot_overwrite_existing_version(self):
        original=self.package()
        with patch.object(runtime,"stop"),patch.object(runtime,"launch"),patch.object(runtime.subprocess,"run") as check:
            check.return_value.returncode=0
            runtime.install(original,self.home,shortcuts=False)
            runtime.atomic_json(self.home/"installation.json",dict(current="v2",previous="v1",port=5088))
            replacement=self.package(extra={"extra.txt":b"different"})
            with self.assertRaises(ValueError):runtime.install(replacement,self.home,shortcuts=False)
        self.assertEqual(runtime.installed_state(self.home)["current"],"v2")
    def test_shortcut_failure_reports_successful_install(self):
        with patch.object(runtime,"stop"),patch.object(runtime,"launch"),patch.object(runtime.subprocess,"run") as check,patch.object(runtime,"create_shortcuts",side_effect=OSError("no desktop")):
            check.return_value.returncode=0
            message=runtime.install(self.package(),self.home)
        self.assertIn("ショートカット",message)
        self.assertEqual(runtime.installed_state(self.home)["current"],"v1")

if __name__=="__main__":unittest.main()
