import json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from demo_seed import seed_database,sample_data,make_excel
from doctor_import import IMPORT_VERSION,parse_schedule
from scheduler_engine import generate,verify
from advance_help import generate_advance_draft
from app import app
class PortfolioDemoTest(unittest.TestCase):
    def test_fresh_seed_is_isolated_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"demo.sqlite3"
            self.assertTrue(seed_database(path))
            before=path.read_bytes()
            self.assertFalse(seed_database(path))
            self.assertEqual(path.read_bytes(),before)
            db=sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM staff").fetchone()[0],9)
                self.assertTrue(all("スタッフ" in row[0] for row in db.execute("SELECT name FROM staff")))
            finally:db.close()
    def test_excel_is_new_and_importable(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"sample.xlsx"
            make_excel(path)
            rows=parse_schedule(path.read_bytes(),"11月","2026-11")
            self.assertEqual(len(rows),30)
            self.assertEqual(rows[1]["am"],"サンプル医師A")
            self.assertEqual(rows[1]["pm"],"サンプル医師B")
            with zipfile.ZipFile(path) as book:
                self.assertFalse(any(name.startswith("docProps/") for name in book.namelist()))
    def snapshot(self):
        data=sample_data()
        data["doctor_raw"]=json.dumps(data["doctor_plans"],ensure_ascii=False)
        data["doctor_plan_reviews"]={"data":data["doctor_raw"],"version":IMPORT_VERSION}
        return data
    def test_demo_can_generate_and_verify(self):
        result=generate(self.snapshot(),True,seconds=5)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(verify(result["problem"],result["grid"]),[])
    def test_initial_advance_help_workflow(self):
        result=generate_advance_draft(self.snapshot(),seconds=5)
        self.assertIn(result["status"],("success","draft"),result["messages"])
        self.assertTrue(result.get("grid"))
    def test_demo_pages_render_from_fictional_database(self):
        saved=dict(app.config)
        try:
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/"demo.sqlite3"
                seed_database(path)
                app.config.update(TESTING=True,DATABASE=str(path))
                client=app.test_client()
                for endpoint in ("/","/staff","/monthly","/doctors","/schedule","/schedule/manual","/backup"):
                    response=client.get(endpoint+"?month=2026-11")
                    self.assertIn(response.status_code,(200,302),endpoint)
                    if response.status_code==200:
                        self.assertIn("サンプル環境",response.get_data(as_text=True))
        finally:
            app.config.clear();app.config.update(saved)
