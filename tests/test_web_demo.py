from contextlib import closing
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from flask import Flask, request, session
from automatic_backup import register_automatic_backup
from storage import database_path
from web_demo import DemoStore, register_web_demo

class WebDemoTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Flask(__name__)
        self.app.secret_key="test-only-key"
        self.app.config["DATABASE"]=str(Path(self.temp.name)/"unused.sqlite3")
        register_automatic_backup(self.app)
        register_web_demo(self.app,Path(self.temp.name)/"visitors",secure=False)
        @self.app.route("/",methods=["GET","POST"])
        def sample():
            with closing(sqlite3.connect(database_path(self.app.config))) as db, db:
                if request.method=="POST":
                    if request.form.get("csrf_token")!=session["csrf_token"]:
                        return "invalid",400
                    db.execute("UPDATE staff SET name=? WHERE id=1",(request.form["name"],))
                return {"name":db.execute("SELECT name FROM staff WHERE id=1").fetchone()[0]}
    def tearDown(self):
        self.temp.cleanup()
    def identity(self,client):
        with client.session_transaction() as state:
            return state["web_demo_id"],state["csrf_token"]
    def test_two_visitors_and_backups_are_separate(self):
        a=self.app.test_client();b=self.app.test_client()
        self.assertEqual(a.get("/").json,b.get("/").json)
        aid,csrf=self.identity(a);bid,_=self.identity(b)
        self.assertNotEqual(aid,bid)
        self.assertEqual(a.post("/",data={"name":"架空変更","csrf_token":csrf}).status_code,200)
        self.assertEqual(a.get("/").json["name"],"架空変更")
        self.assertNotEqual(b.get("/").json["name"],"架空変更")
        root=Path(self.temp.name)/"visitors"
        self.assertEqual(len(list((root/aid/"backups/automatic").glob("*.sqlite3"))),2)
        self.assertFalse((root/bid/"backups").exists())
        self.assertFalse(Path(self.app.config["DATABASE"]).exists())
    def test_reset_requires_csrf_and_only_resets_own_browser(self):
        a=self.app.test_client();b=self.app.test_client()
        a.get("/");b.get("/")
        aid,csrf=self.identity(a);bid,bcsrf=self.identity(b)
        a.post("/",data={"name":"架空変更A","csrf_token":csrf})
        b.post("/",data={"name":"架空変更B","csrf_token":bcsrf})
        self.assertEqual(a.post("/demo/reset").status_code,400)
        self.assertEqual(a.post("/demo/reset",data={"csrf_token":csrf}).status_code,302)
        self.assertNotEqual(a.get("/").json["name"],"架空変更A")
        self.assertNotEqual(self.identity(a)[0],aid)
        self.assertEqual(self.identity(b)[0],bid)
        self.assertEqual(b.get("/").json["name"],"架空変更B")
    def test_health_static_and_headers(self):
        client=self.app.test_client()
        response=client.get("/health")
        self.assertEqual(response.json,{"status":"ok"})
        self.assertFalse(list((Path(self.temp.name)/"visitors").iterdir()))
        response=client.get("/")
        self.assertEqual(response.headers["Cache-Control"],"no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")
        self.assertTrue(response.headers["Set-Cookie"].find("HttpOnly")>=0)
        self.assertEqual(client.get("/",headers={"Host":"evil.example"}).status_code,400)
        self.assertEqual(client.get("/health",headers={"Host":"sample.onrender.com"}).status_code,200)
    def test_invalid_identifier_does_not_select_arbitrary_path(self):
        client=self.app.test_client()
        with client.session_transaction() as state:state["web_demo_id"]="../escape"
        self.assertEqual(client.get("/").status_code,200)
        token,_=self.identity(client)
        self.assertRegex(token,r"^[0-9a-f]{64}$")
        self.assertFalse((Path(self.temp.name)/"escape").exists())
    def test_expired_data_cleanup_and_capacity(self):
        store=DemoStore(Path(self.temp.name)/"limited",limit=1,ttl=10)
        token,path,lock=store.open(None)
        store.close(token,lock)
        old=time.time()-20
        os.utime(path.parent,(old,old))
        newer,newpath,newlock=store.open(None)
        store.close(newer,newlock)
        self.assertFalse(path.exists())
        with self.app.test_request_context():
            with self.assertRaises(Exception) as error:store.open(None)
            self.assertEqual(error.exception.code,503)
    def test_same_visitor_is_serialized_and_other_visitors_can_open(self):
        store=DemoStore(Path(self.temp.name)/"parallel")
        token,path,lock=store.open(None)
        acquired=threading.Event()
        def another():
            same,_,otherlock=store.open(token)
            acquired.set()
            store.close(same,otherlock)
        thread=threading.Thread(target=another);thread.start()
        other,_,otherlock=store.open(None)
        self.assertNotEqual(token,other)
        self.assertFalse(acquired.is_set())
        store.close(other,otherlock);store.close(token,lock)
        thread.join(timeout=5)
        self.assertTrue(acquired.is_set())
        self.assertFalse(thread.is_alive())
    def test_real_application_routes_use_visitor_database(self):
        code="""
import tempfile,sqlite3
from contextlib import closing
from pathlib import Path
from app import app
from web_demo import register_web_demo
with tempfile.TemporaryDirectory() as folder:
    app.secret_key='test-only-key'
    app.config['TESTING']=True
    shared=Path(folder)/'must-not-create.sqlite3'
    app.config['DATABASE']=str(shared)
    register_web_demo(app,Path(folder)/'visitors',secure=False)
    a=app.test_client(); b=app.test_client()
    for path in ['/?month=2026-11','/staff','/doctors?month=2026-11','/monthly?month=2026-11','/coverage?month=2026-11','/backup']:
        response=a.get(path)
        assert response.status_code==200,(path,response.status_code)
    b.get('/')
    with a.session_transaction() as state: aid=state['web_demo_id']
    with b.session_transaction() as state: bid=state['web_demo_id']
    assert aid!=bid
    with closing(sqlite3.connect(Path(folder)/'visitors'/aid/'demo.sqlite3')) as db, db:
        db.execute("UPDATE staff SET name='test-isolated-name' WHERE id=1")
    assert 'test-isolated-name' in a.get('/staff').get_data(as_text=True)
    assert 'test-isolated-name' not in b.get('/staff').get_data(as_text=True)
    assert not shared.exists()
    assert app.test_client().get('/health').json=={'status':'ok'}
"""
        result=subprocess.run([sys.executable,"-B","-c",code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
