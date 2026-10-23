"""Linux上で本番用Gunicornを起動し、2人分の変更とバックアップを確認する。"""
import html
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def run():
    with tempfile.TemporaryDirectory() as folder:
        env=dict(os.environ,DEMO_SECRET_KEY=secrets.token_hex(32),DEMO_STORAGE_DIR=folder)
        process=subprocess.Popen([sys.executable,"-m","gunicorn","web_entry:app","--bind","127.0.0.1:8765","--workers","1","--threads","4","--timeout","180"],env=env)
        try:
            for attempt in range(100):
                if process.poll() is not None:raise RuntimeError("Gunicorn failed to start")
                try:
                    with urlopen("http://127.0.0.1:8765/health",timeout=2) as response:
                        assert json.load(response)=={"status":"ok"}
                    break
                except OSError:time.sleep(.2)
            else:raise RuntimeError("Gunicorn did not become ready")
            class Browser:
                cookie=""
                def fetch(self,path,data=None):
                    req=Request("http://127.0.0.1:8765"+path,data=urlencode(data,doseq=True).encode() if data else None,headers={"Cookie":self.cookie})
                    with urlopen(req,timeout=30) as response:
                        cookies=SimpleCookie()
                        for value in response.headers.get_all("Set-Cookie",[]):
                            assert "Secure" in value and "HttpOnly" in value
                            cookies.load(value)
                        if cookies:self.cookie="; ".join(key+"="+value.value for key,value in cookies.items())
                        return response.read()
            a=Browser();b=Browser()
            page=a.fetch("/staff?edit=1").decode()
            b.fetch("/staff")
            csrf=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page)[1])
            a.fetch("/staff",dict(csrf_token=csrf,id="1",name="test-isolated-visitor",role="nurse",employment="full",veteran="1",no_c="0"))
            if "test-isolated-visitor" not in a.fetch("/staff").decode():
                raise AssertionError("Staff change did not save")
            assert "test-isolated-visitor" not in b.fetch("/staff").decode()
            for browser,expected in [(a,True),(b,False)]:
                db=sqlite3.connect(":memory:")
                try:
                    db.deserialize(browser.fetch("/backup/download"))
                    found=db.execute("SELECT name FROM staff WHERE id=1").fetchone()[0]=="test-isolated-visitor"
                    assert found==expected
                finally:db.close()
            print("Gunicorn smoke passed: independent visitors, writes, and downloaded backups.")
        finally:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=="__main__":run()
