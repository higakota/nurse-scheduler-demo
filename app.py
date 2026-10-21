import secrets
import sqlite3
from pathlib import Path

from ui import register_ui, render_home

from flask import Flask, abort, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.config.update(
    SECRET_KEY=secrets.token_hex(32),
    DATABASE=str(Path(app.instance_path) / "staff.sqlite3"),
    SESSION_COOKIE_SAMESITE="Strict",
    HELP_REQUESTS_ENABLED=False,
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)


def connect_db():
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    from staff_schema import ensure_staff_schema
    ensure_staff_schema(db)
    return db


@app.route("/")
def index():
    return render_home(connect_db)


@app.route("/staff", methods=["GET", "POST"])
def staff_settings():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    error = None
    values = {"name": "", "role": "nurse", "employment": "full", "veteran": False, "is_help": False, "allowed_areas": "ABC", "advance_help": False}
    edit_id = request.args.get("edit", type=int)
    db = connect_db()
    try:
        if request.method == "POST":
            if not secrets.compare_digest(
                session["csrf_token"], request.form.get("csrf_token", "")
            ):
                abort(400, description="画面を開き直してから保存してください。")
            raw_id = request.form.get("id", "")
            if raw_id and (not raw_id.isascii() or not raw_id.isdecimal()):
                abort(400)
            edit_id = int(raw_id) if raw_id else None
            values = {
                "name": request.form.get("name", "").strip(),
                "role": request.form.get("role", ""),
                "employment": request.form.get("employment", ""),
                "veteran": request.form.get("veteran") == "1",
                "is_help": request.form.get("is_help") == "1",
                "allowed_areas": "ABC",
                "advance_help": request.form.get("advance_help")=="1" and request.form.get("is_help")=="1",
            }
            if not values["name"] or len(values["name"]) > 50:
                error = "名前は1～50文字で入力してください。"
            elif values["role"] not in ("nurse", "technician"):
                error = "職種を選択してください。"
            elif values["employment"] not in ("full", "part") and not values["is_help"] and not (values["role"] == "technician" and values["employment"] == ""):
                error = "勤務区分を選択してください。"
            if values["is_help"]:
                values["employment"] = "full"
            elif values["role"] == "nurse":
                values["allowed_areas"] = "AB" if request.form.get("no_c") == "1" else "ABC"
            if values["role"] == "technician":
                values.update(employment="full" if values["is_help"] else "part", veteran=False, allowed_areas="C")
            weekly_limit=None
            update_weekly="weekly_limit_days" in request.form and not values["is_help"] and values["employment"]=="part"
            if update_weekly:
                from decimal import Decimal,InvalidOperation
                try:
                    raw=request.form.get("weekly_limit_days","").strip()
                    value=Decimal(raw) if raw else None
                    if value is not None and (not value.is_finite() or value<0 or value>7 or value*2!=(value*2).to_integral_value()):raise ValueError()
                    weekly_limit=int(value*2) if value is not None else None
                except (ValueError,InvalidOperation):
                    error="週上限は0～7日、0.5日単位で入力してください。"
            if edit_id is not None and db.execute(
                "SELECT id FROM staff WHERE id = ?", (edit_id,)
            ).fetchone() is None:
                abort(404)
            if error is None:
                data = (values["name"], values["role"], values["employment"], int(values["veteran"]), int(values["is_help"]), values["allowed_areas"], int(values["advance_help"]))
                if edit_id is None:
                    from staff_deletion import next_staff_id
                    db.execute("BEGIN IMMEDIATE")
                    new_id = next_staff_id(db)
                    db.execute("INSERT INTO staff (id, name, role, employment, veteran, is_help, allowed_areas, advance_help) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (new_id,) + data)
                else:
                    db.execute("UPDATE staff SET name=?, role=?, employment=?, veteran=?, is_help=?, allowed_areas=?, advance_help=? WHERE id=?", data + (edit_id,))
                if update_weekly:
                    db.execute("UPDATE staff SET weekly_limit_units=? WHERE id=?",(weekly_limit,new_id if edit_id is None else edit_id))
                db.commit()
                return redirect(url_for("staff_settings", saved="1"))
        elif edit_id is not None:
            row = db.execute("SELECT * FROM staff WHERE id = ?", (edit_id,)).fetchone()
            if row is None:
                abort(404)
            values = dict(row)
        staff = db.execute("SELECT * FROM staff ORDER BY id").fetchall()
    finally:
        db.close()
    return render_template(
        "staff.html", staff=staff, values=values, edit_id=edit_id,
        error=error, saved=request.args.get("saved") == "1",
    )


from monthly import register_monthly

register_monthly(app, connect_db)

from doctor_import import register_doctor_import

register_doctor_import(app, connect_db)

from coverage import register_coverage

register_coverage(app, connect_db)

from leave_and_history import register_leave_and_history

register_leave_and_history(app, connect_db)


from help_availability import register_help_availability

register_help_availability(app, connect_db)

from schedule import register_schedule

register_schedule(app, connect_db)

from help_requests import register_help_requests

register_help_requests(app, connect_db)

from staff_deletion import register_staff_deletion

register_staff_deletion(app, connect_db)

from weekly_settings import register_weekly_settings

register_weekly_settings(app, connect_db)

from data_backup import register_data_backup

register_data_backup(app, connect_db)

from input_review import register_input_review

register_input_review(app, connect_db)

from manual_schedule import register_manual_schedule

register_manual_schedule(app, connect_db)

from negotiated_leave import register_negotiated_leave

register_negotiated_leave(app, connect_db)

register_ui(app)


from candidate_leave_apply import register_candidate_leave
register_candidate_leave(app, connect_db)

if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False)
