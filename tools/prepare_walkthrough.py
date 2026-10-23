"""動画用のコピーに限って、入力→保存を実演する架空データへ戻す。"""
import json
import secrets
import sqlite3
import sys
from pathlib import Path

def prepare(root):
    root=Path(root).resolve()
    if ".runtime" not in root.parts or not (root/"demo_seed.py").is_file():
        raise ValueError("撮影には.runtime内に作ったサンプル環境のコピーを指定してください。")
    sys.path.insert(0,str(root))
    from demo_seed import seed_database
    temporary=root/"instance"/("recording-seed-"+secrets.token_hex(8)+".sqlite3")
    source=target=None
    try:
        seed_database(temporary)
        source=sqlite3.connect(temporary)
        target=sqlite3.connect(root/"instance/demo.sqlite3")
        source.backup(target)
        monthly=json.loads(target.execute("SELECT data FROM monthly_settings WHERE month=?",("2026-11",)).fetchone()[0])
        monthly["wishes"].pop("7_2026-11-09",None)
        target.execute("UPDATE monthly_settings SET data=? WHERE month=?",(json.dumps(monthly,ensure_ascii=False),"2026-11"))
        visits=json.loads(target.execute("SELECT data FROM help_availability WHERE month=?",("2026-11",)).fetchone()[0])
        for key in ("8_2026-11-12","9_2026-11-09"):visits.pop(key,None)
        target.execute("UPDATE help_availability SET data=? WHERE month=?",(json.dumps(visits),"2026-11"))
        target.commit()
    finally:
        if source:source.close()
        if target:target.close()
        temporary.unlink(missing_ok=True)
