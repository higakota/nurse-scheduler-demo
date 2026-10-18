import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.config.update(
    SECRET_KEY=secrets.token_hex(32),
    DATABASE=str(Path(app.instance_path) / "staff.sqlite3"),
    SESSION_COOKIE_SAMESITE="Strict",
    MAX_CONTENT_LENGTH=64 * 1024,
)


def connect_db():
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('nurse', 'technician')),
        employment TEXT NOT NULL CHECK(employment IN ('full', 'part', '')),
        veteran INTEGER NOT NULL CHECK(veteran IN (0, 1)),
        CHECK((role = 'nurse' AND employment IN ('full', 'part'))
           OR (role = 'technician' AND employment = '' AND veteran = 0))
    )""")
    return db


@app.route("/")
def index():
    return redirect(url_for("staff_settings"))


@app.route("/staff", methods=["GET", "POST"])
def staff_settings():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    error = None
    values = {"name": "", "role": "nurse", "employment": "full", "veteran": False}
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
            }
            if not values["name"] or len(values["name"]) > 50:
                error = "名前は1～50文字で入力してください。"
            elif values["role"] not in ("nurse", "technician"):
                error = "職種を選択してください。"
            elif values["role"] == "nurse" and values["employment"] not in ("full", "part"):
                error = "看護師の勤務区分を選択してください。"
            if values["role"] == "technician":
                values.update(employment="", veteran=False)
            if edit_id is not None and db.execute(
                "SELECT id FROM staff WHERE id = ?", (edit_id,)
            ).fetchone() is None:
                abort(404)
            if error is None:
                data = (values["name"], values["role"], values["employment"], int(values["veteran"]))
                if edit_id is None:
                    db.execute("INSERT INTO staff (name, role, employment, veteran) VALUES (?, ?, ?, ?)", data)
                else:
                    db.execute("UPDATE staff SET name=?, role=?, employment=?, veteran=? WHERE id=?", data + (edit_id,))
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False)
