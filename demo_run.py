"""実用版と異なるDB・ポートで起動するローカルデモ。"""
import os,sys,webbrowser,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATABASE=ROOT/"instance/demo.sqlite3"
os.environ["NURSE_SCHEDULER_DATABASE"]=str(DATABASE)
from demo_seed import seed_database
seed_database(DATABASE)
from app import app
app.config["DEMO_MODE"]=True
if __name__=="__main__":
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5,lambda:webbrowser.open("http://127.0.0.1:5001/?month=2026-11")).start()
    app.run(host="127.0.0.1",port=5001,debug=False)
