"""ヘルプ登録時に参照する不足表示。相談状況や勤務条件は管理しない。"""
import hashlib
import json
from datetime import datetime, timezone


def conditions_hash(snapshot):
    values={key:value for key,value in snapshot.items() if key!="help_availability"}
    if values.get("rules_version")==20:
        values["rules_version"]=19
    values["staff"]=[{key:value for key,value in p.items() if key!="advance_help"} for p in snapshot["staff"] if not p["is_help"]]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def included_helper_visits(people, days, grid):
    from scheduler_engine import WORK
    visits = {}
    for d, day in enumerate(days):
        for i, person in enumerate(people):
            if not person["is_help"]:
                continue
            pair = grid[d][i]
            am, pm = pair[0] in WORK, pair[1] in WORK
            if am or pm:
                visits[str(person["id"]) + "_" + day] = "full" if am and pm else "am" if am else "pm"
    return visits


def write_reference(db, snapshot, fingerprint, rows, kind="draft", source_kind=None, source_raw=None):
    db.execute("CREATE TABLE IF NOT EXISTS help_shortage_previews(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    value=dict(input_hash=fingerprint,conditions_hash=conditions_hash(snapshot),rules_version=snapshot.get("rules_version"),rows=rows,
               kind=kind,created=datetime.now(timezone.utc).isoformat())
    if kind == "verified":
        previous=db.execute("SELECT data FROM help_shortage_previews WHERE month=?",(snapshot["month"],)).fetchone()
        if previous:
            old=json.loads(previous[0])
            for key in ("source_kind","source_hash"):
                if key in old:
                    value[key]=old[key]
    if source_kind is not None and source_raw is not None:
        source = json.loads(source_raw)
        value["included_visits"] = included_helper_visits(source["people"], source["days"], source["grid"])
        value.update(source_kind=source_kind,source_hash=hashlib.sha256(source_raw.encode()).hexdigest())
    db.execute("INSERT INTO help_shortage_previews VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
               (snapshot["month"],json.dumps(value,ensure_ascii=False)))


def publish_reference(connect_db, snapshot, fingerprint, rows, kind="draft", outcome=None, expected_source=None):
    from schedule import read_snapshot
    db=connect_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _,latest,_=read_snapshot(db,snapshot["month"])
        if latest!=fingerprint:
            db.rollback()
            return False
        if expected_source:
            source_kind, source_raw = expected_source
            current = source_data(db, snapshot["month"], source_kind)
            if current != source_raw:
                db.rollback()
                return False
        write_reference(db,snapshot,fingerprint,rows,kind=kind,
                        source_kind=expected_source[0] if expected_source else None,
                        source_raw=expected_source[1] if expected_source else None)
        if expected_source:
            row = db.execute("SELECT data FROM help_shortage_previews WHERE month=?", (snapshot["month"],)).fetchone()
            value = json.loads(row[0])
            value.update(source_kind=source_kind, source_hash=hashlib.sha256(source_raw.encode()).hexdigest())
            db.execute("UPDATE help_shortage_previews SET data=? WHERE month=?", (json.dumps(value, ensure_ascii=False), snapshot["month"]))
        if outcome is not None:
            from manual_schedule import seed_draft
            seed_draft(db, snapshot["month"], snapshot, fingerprint, outcome)
            stored = json.loads(db.execute("SELECT data FROM help_shortage_previews WHERE month=?", (snapshot["month"],)).fetchone()[0])
            stored["included_visits"] = included_helper_visits(outcome["problem"]["people"], outcome["problem"]["days"], outcome["grid"])
            stored["source_kind"] = "draft"
            stored["source_hash"] = hashlib.sha256(source_data(db, snapshot["month"], "draft").encode()).hexdigest()
            db.execute("UPDATE help_shortage_previews SET data=? WHERE month=?", (json.dumps(stored, ensure_ascii=False), snapshot["month"]))
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
    source_changed = bool(reference.get("source_hash")) and reference["source_hash"] != hashlib.sha256(
        source_data(db, month, reference["source_kind"]).encode()).hexdigest()
    if (reference.get("rules_version",19) != snapshot.get("rules_version",19)) or source_changed or reference["conditions_hash"]!=conditions_hash(snapshot) or (
        reference["kind"]=="verified" and reference["input_hash"]!=fp
    ):
        return dict(state="outdated",days={},kind=reference["kind"],created=reference["created"])
    if "included_visits" not in reference:
        raw = source_data(db, month, reference.get("source_kind", "draft"))
        if raw:
            source = json.loads(raw)
            reference["included_visits"] = included_helper_visits(source["people"], source["days"], source["grid"])
    days={}
    for item in reference["rows"]:
        count=item["missing"]
        veteran=item.get("veteran_missing",0)
        if veteran:
            label=(f"看護師{count}人（うちベテラン{veteran}人）" if count else
                   f"人数充足・ベテラン{veteran}人への交代")
        elif item["area"] == "検査室を担当できる看護師":
            label=f"看護師{count}人（検査室を担当できる人）"
        elif "検査技師" in item["area"]:
            label=f"他院の検査技師{count}人"
        else:
            label=f"看護師{count}人"
        days.setdefault(item["date"],[]).append(dict(half=item["half"],label=label))
    return dict(state="reference" if reference["input_hash"]!=fp else "current",days=days,
                kind=reference["kind"],created=reference["created"],included_visits=reference.get("included_visits", {}))


def source_data(db, month, kind):
    from fixed_help import load_seed, load_manual_source
    return (load_manual_source if kind == "manual" else load_seed)(db, month)


def shortages_from_source(snapshot, raw):
    """保存した自院勤務を維持して不足だけを再計算する。"""
    from scheduler_engine import prepare, verify, draft_shortages
    from schedule_display import grouped_shortages
    source = json.loads(raw)
    if source.get("conditions_hash") not in (None, conditions_hash(snapshot)):
        raise ValueError("元の勤務表の保存後に条件が変わっています。編集画面で確認・保存してから不足を更新してください。")
    source_ids={str(p["id"]) for p in source["people"]}
    advance={str(p["id"]) for p in snapshot["staff"] if p["is_help"] and p.get("advance_help") and str(p["id"]) in source_ids}
    inputs=dict(snapshot,staff=[p for p in snapshot["staff"] if not p["is_help"] or str(p["id"]) in advance])
    problem = prepare(inputs, use_help=bool(advance))
    if problem["errors"]:
        raise ValueError(problem["errors"][0])
    positions = {str(p["id"]): i for i, p in enumerate(source["people"]) if not p["is_help"] or str(p["id"]) in advance}
    if set(positions) != {str(p["id"]) for p in problem["people"]} or source["days"] != problem["days"]:
        raise ValueError("自院スタッフ・対象日が変わっています。編集画面で元の勤務表を確認してください。")
    grid = [[rows[positions[str(p["id"])]] for p in problem["people"]] for rows in source["grid"]]
    errors = verify(problem, grid, allow_shortages=True, max_full_days=6)
    if errors:
        raise ValueError("保存した自院勤務を確認してください：" + errors[0])
    shortages = [row for d, rows in enumerate(grid) for row in draft_shortages(problem, d, rows)]
    return grouped_shortages(shortages, problem, grid)
