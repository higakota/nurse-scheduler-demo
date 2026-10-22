"""1日の利用開始時と最後に保存した状態をSQLiteのbackup APIで保管する。"""
import os,secrets,sqlite3
from pathlib import Path
from datetime import datetime,timezone,timedelta
from flask import request,g

JST=timezone(timedelta(hours=9))

def backup_database(database,kind="latest",now=None):
    path=Path(database)
    if not path.exists():return None
    if kind not in ("start","latest"):raise ValueError("Unknown backup kind")
    day=(now or datetime.now(JST)).astimezone(JST).strftime("%Y-%m-%d")
    folder=path.parent/"backups"/"automatic"
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(day+"_"+kind+".sqlite3")
    if kind=="start" and target.exists():return target
    source=sqlite3.connect(str(path),timeout=15);memory=sqlite3.connect(":memory:")
    try:
        source.backup(memory)
        payload=memory.serialize()
    finally:source.close();memory.close()
    if target.exists() and target.read_bytes()==payload:return target
    temporary=folder/("."+secrets.token_hex(12)+".tmp")
    try:
        with temporary.open("xb") as file:
            file.write(payload);file.flush();os.fsync(file.fileno())
        if kind=="start" and target.exists():return target
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target

def list_backups(database):
    folder=Path(database).parent/"backups"/"automatic"
    return [dict(name=p.name,date=p.name[:10],kind="利用開始時" if "_start" in p.name else "最後の保存",size=p.stat().st_size)
            for p in sorted(folder.glob("????-??-??_*.sqlite3"),reverse=True)][:40]

def register_automatic_backup(app):
    def enabled():
        return not app.testing and app.config.get("AUTO_BACKUP_ENABLED",True)
    @app.before_request
    def before_write_backup():
        if enabled() and request.method=="POST":
            try:
                backup_database(app.config["DATABASE"],"start")
                g.backup_started=True
            except (OSError,sqlite3.Error):
                app.logger.exception("Automatic backup before write failed")
                return "自動バックアップを保存できないため、変更を保存していません。空き容量と保存先を確認してください。",503
    @app.after_request
    def after_write_backup(response):
        if enabled() and request.method=="POST" and getattr(g,"backup_started",False):
            try:
                backup_database(app.config["DATABASE"],"latest")
                app.config.pop("AUTO_BACKUP_ERROR",None)
            except (OSError,sqlite3.Error):
                app.logger.exception("Automatic backup after write failed")
                app.config["AUTO_BACKUP_ERROR"]="データは保存しましたが、自動バックアップに失敗しました。バックアップ画面から手動保存してください。"
        return response
