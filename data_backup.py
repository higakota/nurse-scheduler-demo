"""勤務ルールに依存しない、SQLiteの整合したバックアップ。"""
from datetime import datetime
from io import BytesIO
import sqlite3
import hashlib
import secrets
import json
from pathlib import Path
from flask import abort, redirect, render_template, request, send_file, session, url_for
from ui import selected_month
from staff_schema import SCHEMA

def register_data_backup(app, connect_db):
    register_restore(app, connect_db)
    @app.get("/backup")
    def data_backup():
        session.setdefault("csrf_token", secrets.token_hex(32))
        from automatic_backup import list_backups
        return render_template("backup.html", month=selected_month(),automatic_backups=list_backups(app.config["DATABASE"]))

    @app.get("/backup/automatic/<name>")
    def download_automatic_backup(name):
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_(start|latest)\.sqlite3",name):abort(404)
        path=Path(app.config["DATABASE"]).parent/"backups"/"automatic"/name
        if not path.is_file():abort(404)
        return send_file(path.resolve(),as_attachment=True,download_name=name,mimetype="application/octet-stream")

    @app.get("/backup/download")
    def download_backup():
        source = connect_db()
        target = sqlite3.connect(":memory:")
        try:
            source.backup(target)
            payload = target.serialize()
        finally:
            target.close()
            source.close()
        response = send_file(
            BytesIO(payload), mimetype="application/octet-stream",
            as_attachment=True,
            download_name=datetime.now().strftime("nurse-scheduler_%Y%m%d_%H%M%S.sqlite3"),
        )
        response.headers["Cache-Control"] = "no-store"
        return response


# Schema definitions come from this application, never from the uploaded SQL.
MONTH_TABLES = (
    "monthly_settings", "doctor_plans", "coverage_settings", "leave_history",
    "help_availability", "technician_exceptions", "weekly_work_boundaries",
    "generated_schedules", "help_requests", "help_shortage_previews",
    "manual_schedules", "manual_schedule_seeds",
)
SCHEMAS = {name: "(month TEXT PRIMARY KEY, data TEXT NOT NULL)" for name in MONTH_TABLES}
SCHEMAS.update({
    "staff": SCHEMA,
    "doctor_plan_reviews": "(month TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL)",
    "doctor_aliases": "(alias TEXT PRIMARY KEY, name TEXT NOT NULL)",
    "deleted_staff": "(id INTEGER PRIMARY KEY, data TEXT NOT NULL, deleted_at TEXT NOT NULL)",
    "doctor_import_draft": "(owner TEXT PRIMARY KEY, workbook BLOB NOT NULL, preview TEXT)",
    "excel_event_drafts": "(owner TEXT, month TEXT, data TEXT NOT NULL, PRIMARY KEY(owner, month))",
    "doctor_edit_drafts": "(owner TEXT PRIMARY KEY, month TEXT, day TEXT, original TEXT, proposed TEXT)",
})
DRAFTS = {"doctor_import_draft", "excel_event_drafts", "doctor_edit_drafts"}


def fingerprint(db):
    return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def validated_backup(payload):
    source = sqlite3.connect(":memory:")
    clean = sqlite3.connect(":memory:")
    try:
        source.deserialize(payload)
        source.execute("PRAGMA trusted_schema=OFF")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("ファイルが破損しています。")
        objects = source.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if any(kind != "table" or name not in SCHEMAS for kind, name in objects):
            raise ValueError("このアプリで対応していない内容が含まれています。")
        tables = {name for _, name in objects}
        if "staff" not in tables:
            raise ValueError("勤務表アプリのバックアップではありません。")
        counts = {}
        for table in tables:
            clean.execute("CREATE TABLE " + table + SCHEMAS[table])
            expected = [r[1] for r in clean.execute("PRAGMA table_info(" + table + ")")]
            actual = [r[1] for r in source.execute("PRAGMA table_info(" + table + ")")]
            if table=="staff" and actual==[name for name in expected if name!="advance_help"]:
                source.execute("ALTER TABLE staff ADD COLUMN advance_help INTEGER NOT NULL DEFAULT 0 CHECK(advance_help IN (0,1))")
                actual = [r[1] for r in source.execute("PRAGMA table_info(staff)")]
            if actual != expected:
                raise ValueError("このバージョンと項目が異なるため復元できません。")
            rows = source.execute("SELECT * FROM " + table).fetchall()
            if "data" in expected:
                index = expected.index("data")
                for row in rows:
                    json.loads(row[index])
            clean.executemany("INSERT INTO " + table + " VALUES (" + ",".join("?" for _ in expected) + ")", rows)
            counts[table] = len(rows)
        clean.commit()
        return clean.serialize(), counts
    except (sqlite3.Error, ValueError, TypeError, OverflowError) as exc:
        raise ValueError("バックアップを確認できませんでした。対応するSQLiteバックアップを選んでください。") from exc
    finally:
        source.close()
        clean.close()


def register_restore(app, connect_db):
    def storage():
        folder = Path(app.config["DATABASE"]).parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def check_csrf():
        if not session.get("csrf_token") or not secrets.compare_digest(
            session["csrf_token"], request.form.get("csrf_token", "")
        ):
            abort(400)

    @app.post("/backup/preview")
    def preview_restore():
        check_csrf()
        month = selected_month()
        error = None
        try:
            upload = request.files.get("backup")
            if not upload:
                raise ValueError("バックアップファイルを選んでください。")
            payload = upload.read(5 * 1024 * 1024 + 1)
            if len(payload) > 5 * 1024 * 1024:
                raise ValueError("5MB以下のバックアップを選んでください。")
            clean, counts = validated_backup(payload)
            token = secrets.token_hex(32)
            old = session.pop("restore_preview", None)
            if old:
                (storage() / ("pending_" + old["token"] + ".sqlite3")).unlink(missing_ok=True)
            path = storage() / ("pending_" + token + ".sqlite3")
            path.write_bytes(clean)
            db = connect_db()
            try:
                db.execute("BEGIN")
                current = fingerprint(db)
            finally:
                db.close()
            session["restore_preview"] = dict(token=token, current=current,
                                             digest=hashlib.sha256(clean).hexdigest())
            return render_template("backup.html", month=month, preview=True,
                                   counts=counts, token=token)
        except ValueError as exc:
            error = str(exc)
        return render_template("backup.html", month=month, error=error), 400

    @app.post("/backup/restore")
    def restore_backup():
        check_csrf()
        month = selected_month()
        preview = session.get("restore_preview")
        if not preview or request.form.get("token") != preview["token"] or request.form.get("confirm") != "yes":
            return render_template("backup.html", month=month, error="内容を確認し、復元のチェックを入れてください。ファイルを選んで確認し直してください。"), 400
        path = storage() / ("pending_" + preview["token"] + ".sqlite3")
        db = None
        source = None
        try:
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != preview["digest"]:
                raise ValueError("確認中のファイルが変わりました。選び直してください。")
            clean, counts = validated_backup(payload)
            source = sqlite3.connect(":memory:")
            source.deserialize(clean)
            db = connect_db()
            db.execute("BEGIN IMMEDIATE")
            if fingerprint(db) != preview["current"]:
                raise ValueError("確認後にデータが変更されました。最新の状態でファイルを確認し直してください。")
            # Serialize under the write lock: no other save can occur between
            # the automatic safety copy and the replacement transaction.
            safety = storage() / ("before_restore_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(4) + ".sqlite3")
            with safety.open("xb") as handle:
                handle.write(db.serialize())
            existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing - set(SCHEMAS) - {"sqlite_sequence"}:
                raise ValueError("未対応のデータがあるため、復元を中止しました。")
            for table, schema in SCHEMAS.items():
                db.execute("CREATE TABLE IF NOT EXISTS " + table + schema)
                db.execute("DELETE FROM " + table)
                if table in counts and table not in DRAFTS:
                    rows = source.execute("SELECT * FROM " + table).fetchall()
                    columns = len(source.execute("PRAGMA table_info(" + table + ")").fetchall())
                    db.executemany("INSERT INTO " + table + " VALUES (" + ",".join("?" for _ in range(columns)) + ")", rows)
            db.commit()
            session.clear()
            session["ui_month"] = month
            return redirect(url_for("data_backup", month=month, restored="1"), code=303)
        except (OSError, sqlite3.Error, ValueError) as exc:
            if db:
                db.rollback()
            return render_template("backup.html", month=month, error=str(exc) if isinstance(exc, ValueError) else "復元できませんでした。現在のデータは変更していません。"), 400
        finally:
            if db:
                db.close()
            if source:
                source.close()
            path.unlink(missing_ok=True)
            session.pop("restore_preview", None)
