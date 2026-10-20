"""ヘルプ登録時に参照する不足表示。相談状況や勤務条件は管理しない。"""
import hashlib
import json
from datetime import datetime, timezone


def conditions_hash(snapshot):
    values={key:value for key,value in snapshot.items() if key!="help_availability"}
    values["staff"]=[p for p in snapshot["staff"] if not p["is_help"]]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def write_reference(db, snapshot, fingerprint, rows, kind="draft"):
    db.execute("CREATE TABLE IF NOT EXISTS help_shortage_previews(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    value=dict(input_hash=fingerprint,conditions_hash=conditions_hash(snapshot),rows=rows,
               kind=kind,created=datetime.now(timezone.utc).isoformat())
    db.execute("INSERT INTO help_shortage_previews VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
               (snapshot["month"],json.dumps(value,ensure_ascii=False)))


def publish_reference(connect_db, snapshot, fingerprint, rows, kind="draft"):
    from schedule import read_snapshot
    db=connect_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _,latest,_=read_snapshot(db,snapshot["month"])
        if latest!=fingerprint:
            db.rollback()
            return False
        write_reference(db,snapshot,fingerprint,rows,kind=kind)
        db.commit()
        return True
    finally:
        db.close()


def load_reference(db, month):
    from schedule import read_snapshot
    exists=db.execute("SELECT name FROM sqlite_master WHERE name='help_shortage_previews'").fetchone()
    row=db.execute("SELECT data FROM help_shortage_previews WHERE month=?",(month,)).fetchone() if exists else None
    if not row:
        return dict(state="missing",days={},kind="draft",created="")
    reference=json.loads(row["data"])
    snapshot,fp,_=read_snapshot(db,month)
    if reference["conditions_hash"]!=conditions_hash(snapshot) or (
        reference["kind"]=="verified" and reference["input_hash"]!=fp
    ):
        return dict(state="outdated",days={},kind=reference["kind"],created=reference["created"])
    days={}
    for item in reference["rows"]:
        count=item["missing"]
        veteran=item.get("veteran_missing",0)
        if veteran:
            label=(f"看護師{count}人（うちベテラン{veteran}人）" if count else
                   f"人数充足・ベテラン{veteran}人への交代")
        elif "検査技師" in item["area"]:
            label=f"検査技師{count}人（C番）"
        else:
            label=f"看護師{count}人"
        days.setdefault(item["date"],[]).append(dict(half=item["half"],label=label))
    return dict(state="reference" if reference["input_hash"]!=fp else "current",days=days,
                kind=reference["kind"],created=reference["created"])
