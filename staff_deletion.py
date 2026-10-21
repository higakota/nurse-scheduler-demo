"""スタッフ削除の影響確認と一括処理。保存済み勤務表は過去の結果として保持する。"""
import hashlib
import json
import secrets
from datetime import datetime, timezone
from flask import abort, redirect, render_template, request, session, url_for


def deletion_preview(db, staff_id):
    row = db.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    if row is None:
        abort(404)
    person = dict(row)
    target = str(staff_id)
    prefix = target + "_"
    counts = dict(targets=0, wishes=0, leaves=0, history=0, visits=0, meetings=0, weekly=0)
    changes = []
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("monthly_settings", "leave_history", "help_availability", "weekly_work_boundaries"):
        if table not in tables:
            continue
        for saved in db.execute(f"SELECT month,data FROM {table} ORDER BY month"):
            original = saved["data"]
            data = json.loads(original)
            changed = False
            if table == "monthly_settings":
                if target in data.get("targets", {}):
                    del data["targets"][target]
                    counts["targets"] += 1
                    changed = True
                for section in ("wishes","summer","support"):
                    keys = [key for key in data.get(section, {}) if key.startswith(prefix)]
                    for key in keys:
                        del data[section][key]
                    counts["wishes"] += len(keys)
                    changed |= bool(keys)
                for meeting in data.get("meetings", []):
                    if any(str(value) == target for value in meeting["participants"]):
                        meeting["participants"] = [value for value in meeting["participants"] if str(value) != target]
                        counts["meetings"] += 1
                        changed = True
            elif table == "leave_history":
                for section in ("leaves", "history"):
                    keys = [key for key in data.get(section, {}) if key.startswith(prefix)]
                    for key in keys:
                        del data[section][key]
                    counts[section] += len(keys)
                    changed |= bool(keys)
            else:
                keys = [key for key in data if key.startswith(prefix)]
                for key in keys:
                    del data[key]
                counts["visits" if table == "help_availability" else "weekly"] += len(keys)
                changed |= bool(keys)
            if changed:
                changes.append(dict(table=table, month=saved["month"], before=original,
                                    after=json.dumps(data, ensure_ascii=False)))
    encoded = json.dumps([person, changes], sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    return person, counts, changes, fingerprint


def next_staff_id(db):
    highest = db.execute("SELECT COALESCE(MAX(id),0) FROM staff").fetchone()[0]
    if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deleted_staff'").fetchone():
        archived = db.execute("SELECT COALESCE(MAX(id),0) FROM deleted_staff").fetchone()[0]
        highest = max(highest, archived)
    return highest + 1


def register_staff_deletion(app, connect_db):
    @app.route("/staff/<int:staff_id>/delete", methods=["GET", "POST"])
    def staff_delete(staff_id):
        session.setdefault("csrf_token", secrets.token_hex(32))
        error = None
        db = connect_db()
        try:
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"].encode(), request.form.get("csrf_token", "").encode()):
                    abort(400)
                db.execute("BEGIN IMMEDIATE")
            person, counts, changes, fingerprint = deletion_preview(db, staff_id)
            if request.method == "POST":
                if not secrets.compare_digest(fingerprint.encode(), request.form.get("fingerprint", "").encode()):
                    error = "確認画面を開いた後にスタッフ情報や関連する入力が変更されました。最新の件数を確認し直してください。"
                elif request.form.get("confirmed") != "yes":
                    error = "削除するスタッフと対象データを確認してチェックしてください。"
                else:
                    db.execute("CREATE TABLE IF NOT EXISTS deleted_staff(id INTEGER PRIMARY KEY, data TEXT NOT NULL, deleted_at TEXT NOT NULL)")
                    archive = json.dumps(dict(staff=person, changes=changes), ensure_ascii=False)
                    db.execute("INSERT INTO deleted_staff VALUES (?,?,?)",
                               (staff_id, archive, datetime.now(timezone.utc).isoformat()))
                    for change in changes:
                        result = db.execute(f"UPDATE {change['table']} SET data=? WHERE month=? AND data=?",
                                            (change["after"], change["month"], change["before"]))
                        if result.rowcount != 1:
                            raise RuntimeError("関連入力が更新されたため削除を中止しました。")
                    db.execute("DELETE FROM staff WHERE id=?", (staff_id,))
                    db.commit()
                    return redirect(url_for("staff_settings", month=request.args.get("month") or session.get("ui_month"), deleted="1"))
                db.rollback()
        finally:
            db.close()
        return render_template("staff_delete.html", person=person, counts=counts, fingerprint=fingerprint, error=error)
