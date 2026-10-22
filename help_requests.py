"""不足に基づく相談記録。外部送信や未承諾の来院登録は行わない。"""
import hashlib
import json
import re
import secrets
from datetime import date
from flask import abort, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeSerializer, BadSignature
from help_availability import load_help
from schedule import read_snapshot

STATUSES = {"new": "未相談", "waiting": "返事待ち", "ok": "来院OK", "no": "来院不可"}


def signer(app):
    return URLSafeSerializer(app.secret_key, salt="help-consultations-v1")


def proposal(app, month, fingerprint, rows, experimental=False):
    slots = {}
    for row in rows:
        role = "technician" if "検査技師" in row["area"] else "nurse"
        half = {"午前": "am", "午後": "pm", "am": "am", "pm": "pm"}.get(row["half"])
        if not half:
            raise ValueError("不足の時間帯を読み取れません。")
        count = int(row["missing"])
        veteran = int(row.get("veteran_missing", 0))
        for i in range(max(count, veteran)):
            key = f'{row["date"]}_{half}_{role}_{i}'
            slots[key] = dict(date=row["date"], half=half, role=role,
                              veteran=i < veteran, replacement=count == 0,
                              status="new", person="", applied=False)
    return signer(app).dumps(dict(month=month, fingerprint=fingerprint,
                                 experimental=bool(experimental), slots=slots)) if slots else None


def load_requests(db, month):
    db.execute("CREATE TABLE IF NOT EXISTS help_requests(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
    row = db.execute("SELECT data FROM help_requests WHERE month=?", (month,)).fetchone()
    return json.loads(row["data"]) if row else {"slots": {}, "fingerprint": "", "experimental": False}


def page_token(data, fingerprint):
    return hashlib.sha256(json.dumps([data, fingerprint], sort_keys=True).encode()).hexdigest()


def apply_visit(item, person, period, visits, closures):
    day = date.fromisoformat(item["date"])
    if day.weekday() == 6 or item["date"] in closures or (day.weekday() == 4 and item["half"] == "pm"):
        raise ValueError("この時間帯は休診です。不足を再確認してください。")
    if not person or person["role"] != item["role"] or (item["veteran"] and not person["veteran"]):
        raise ValueError("職種・ベテラン条件を満たすヘルプを選んでください。")
    if period not in (item["half"], "full"):
        raise ValueError("不足時間帯を含む来院区分を選んでください。")
    key = str(person["id"]) + "_" + item["date"]
    old = visits.get(key, "")
    merged = "full" if old == "full" or period == "full" or {old, period} == {"am", "pm"} else period
    if person["role"] == "technician" and merged == "pm":
        raise ValueError("検査技師の午後のみ来院は登録できません。全日来院が決まっている場合だけ全日を選んでください。")
    visits[key] = merged


def consultation_calendar(data, month, visits=None):
    import calendar
    year, number = map(int, month.split("-"))
    by_date = {}
    for key, item in sorted(data["slots"].items()):
        if not item.get("obsolete"):
            shown = dict(item, key=key)
            if visits is not None and shown.get("applied"):
                shown["applied"] = visits.get(shown.get("applied_person", "") + "_" + shown["date"]) in ("full", shown["half"])
            by_date.setdefault(item["date"], []).append(shown)
    days = {}
    for text, slots in by_date.items():
        summaries = []
        for half in ("am", "pm"):
            for role in ("nurse", "technician"):
                group = [s for s in slots if s["half"] == half and s["role"] == role]
                if not group:
                    continue
                count = sum(not s["replacement"] for s in group)
                veteran = sum(s["veteran"] for s in group)
                label = ("午前 " if half == "am" else "午後 ") + ("看護師" if role == "nurse" else "技師")
                label += str(count) + "人" if count else "交代（人数は充足）"
                if veteran:
                    label += "（うちベテラン" + str(veteran) + "）" if count else "（ベテラン）"
                summaries.append(label)
        days[text] = dict(slots=slots, summaries=summaries)
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, number)
    return [[dict(number=n, date=f"{month}-{n:02d}",
                  info=days.get(f"{month}-{n:02d}")) if n else None for n in week] for week in weeks]


def register_help_requests(app, connect_db):
    @app.route("/help-requests", methods=["GET", "POST"])
    def help_requests():
        month = request.args.get("month", session.get("ui_month", date.today().strftime("%Y-%m")))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400)
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400)
        if not app.config.get("HELP_REQUESTS_ENABLED", False):
            # 旧URL・旧フォームからも、記録や来院予定を変更せず新しい導線へ進む。
            return redirect(url_for("help_availability", month=month), code=303)
        session.setdefault("csrf_token", secrets.token_hex(32))
        error = None
        db = connect_db()
        try:
            data = load_requests(db, month)
            visits, staff, closures, _ = load_help(db, month)
            _, fingerprint, _ = read_snapshot(db, month)
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400)
                db.commit()
                db.execute("BEGIN IMMEDIATE")
                data = load_requests(db, month)
                visits, staff, closures, _ = load_help(db, month)
                _, fingerprint, _ = read_snapshot(db, month)
                try:
                    action = request.form.get("action")
                    if action == "create":
                        try:
                            incoming = signer(app).loads(request.form.get("proposal", ""))
                        except BadSignature:
                            raise ValueError("相談候補が無効です。仮作成し直してください。")
                        if incoming["month"] != month or incoming["fingerprint"] != fingerprint:
                            raise ValueError("入力が変わっています。最新の条件で仮作成し直してください。")
                        # 古い相談記録を失わない。不要になった項目は取消として残す。
                        for key, item in data["slots"].items():
                            item["obsolete"] = key not in incoming["slots"]
                        for key, item in incoming["slots"].items():
                            if key not in data["slots"]:
                                data["slots"][key] = item
                            else:
                                previous = data["slots"][key]
                                previous.update(veteran=item["veteran"], replacement=item["replacement"], obsolete=False)
                        data.update(fingerprint=fingerprint, experimental=incoming["experimental"])
                    elif action in ("save", "apply", "bulk"):
                        if request.form.get("token") != page_token(data, fingerprint):
                            raise ValueError("別の画面で入力・相談状況が変わりました。最新の内容を確認してください。")
                        operation = request.form.get("operation") if action == "bulk" else action
                        if operation not in ("save", "apply"):
                            raise ValueError("保存方法を選んでください。")
                        keys = list(dict.fromkeys(request.form.getlist("keys"))) if action == "bulk" else [request.form.get("key", "")]
                        if not keys or len(keys) > len(data["slots"]):
                            raise ValueError("変更する日・時間帯を選んでください。")
                        # 全件を同一トランザクションで検証・保存する。午前を先に処理する。
                        for selected_key in sorted(keys):
                            change = dict(key=selected_key, status=request.form.get("status"),
                                          person=request.form.get("person", ""), period=request.form.get("period"))
                            key = change["key"]
                            if key not in data["slots"]:
                                raise ValueError("相談項目が見つかりません。")
                            item = data["slots"][key]
                            # カレンダーで取消済みの履歴は、相談状況を再編集できる。
                            for recorded in data["slots"].values():
                                visit_key = recorded.get("applied_person", "") + "_" + recorded["date"]
                                if recorded.get("applied") and visits.get(visit_key) not in ("full", recorded["half"]):
                                    recorded["applied"] = False
                            status = change["status"]
                            if status not in STATUSES:
                                raise ValueError("相談状況を選んでください。")
                            person_id = change.get("person") or (item.get("person", "") if action == "bulk" else "")
                            person = next((p for p in staff if str(p["id"]) == person_id), None)
                            if person_id and (not person or person["role"] != item["role"] or (item["veteran"] and not person["veteran"])):
                                raise ValueError("条件に合うヘルプを選んでください。")
                            if operation == "apply":
                                if status != "ok" or item.get("obsolete"):
                                    raise ValueError("現在必要な項目で、来院OKと確認した場合だけ反映できます。")
                                if item.get("applied") and item.get("applied_person") != person_id:
                                    raise ValueError("反映済みの人の変更は、来院カレンダーで以前の予定を修正してから行ってください。")
                                for other_key, other in data["slots"].items():
                                    if other_key != key and other.get("applied") and other.get("applied_person") == person_id and other["date"] == item["date"] and other["half"] == item["half"]:
                                        raise ValueError("同じ人を同じ時間帯の別の相談人数には数えられません。")
                                apply_visit(item, person, item["half"] if change.get("period") == "requested" else change.get("period"), visits, closures)
                                db.execute("INSERT INTO help_availability VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                                           (month, json.dumps(visits, ensure_ascii=False)))
                                item.update(applied=True, applied_person=person_id)
                            elif item.get("applied") and (person_id != item.get("person") or status != "ok"):
                                raise ValueError("反映済みの来院予定は来院カレンダーで先に修正してください。相談記録だけでは取消しません。")
                            item.update(status=status, person=person_id)
                    else:
                        abort(400)
                    db.execute("INSERT INTO help_requests VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                               (month, json.dumps(data, ensure_ascii=False)))
                    db.commit()
                    return redirect(url_for("help_requests", month=month, saved="1"))
                except ValueError as exc:
                    db.rollback()
                    error = str(exc)
                    data = load_requests(db, month)
                    visits, staff, closures, _ = load_help(db, month)
                    _, fingerprint, _ = read_snapshot(db, month)
            token = page_token(data, fingerprint)
        finally:
            db.close()
        lines = [month + " ヘルプのご相談（仮表に基づく候補・必要最少人数を保証するものではありません）"]
        for item in data["slots"].values():
            if item.get("obsolete") or item["status"] == "ok":
                continue
            lines.append(item["date"] + " " + ("午前" if item["half"] == "am" else "午後") + " " +
                         ("検査技師" if item["role"] == "technician" else "看護師") +
                         ("（ベテランへの交代）" if item["replacement"] else " 1人") +
                         ("・ベテラン必須" if item["veteran"] else ""))
        return render_template("help_requests.html", month=month, data=data, staff=staff,
                               visits=visits, statuses=STATUSES, token=token, error=error,
                               changed=bool(data["slots"] and data["fingerprint"] != fingerprint),
                               weeks=consultation_calendar(data, month, visits),
                               selected_keys=request.form.getlist("keys") if error else [],
                               copy_text="\n".join(lines))
