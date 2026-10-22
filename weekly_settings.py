"""非常勤の月境界週の実績と決定済み勤務。未定を休みにしない。"""
import calendar
import json
import re
import secrets
from datetime import date
from flask import abort, redirect, render_template, request, session, url_for
from weekly_rules import boundary_dates, outside_sources, parse_units, HISTORY_UNITS


def register_weekly_settings(app,connect_db):
    @app.route("/weekly",methods=["GET","POST"])
    def weekly_settings():
        from schedule import read_snapshot
        month=request.args.get("month",session.get("ui_month",date.today().strftime("%Y-%m")))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}",month):
            abort(400)
        year,number=map(int,month.split("-"))
        if not 1900<=year<=9998 or not 1<=number<=12:
            abort(400)
        session.setdefault("csrf_token",secrets.token_hex(32))
        error=None
        db=connect_db()
        try:
            if request.method=="POST":
                if not secrets.compare_digest(session["csrf_token"].encode(),request.form.get("csrf_token","").encode()):
                    abort(400)
                db.execute("BEGIN IMMEDIATE")
            snapshot,fingerprint,_=read_snapshot(db,month)
            staff=[p for p in snapshot["staff"] if p["employment"]=="part" and not p["is_help"]]
            outside=boundary_dates(month)
            if request.method=="POST":
                try:
                    if not secrets.compare_digest(fingerprint.encode(),request.form.get("fingerprint","").encode()):
                        raise ValueError("別の画面で入力が変更されました。最新の値を確認してください。")
                    candidate=dict(snapshot.get("weekly_work_boundaries") or {})
                    for person in staff:
                        for day in outside:
                            key=str(person["id"])+"_"+day.isoformat()
                            field="boundary_"+key
                            if field not in request.form:
                                continue
                            raw=request.form[field]
                            if raw=="":
                                candidate.pop(key,None)
                                continue
                            units=parse_units(raw)
                            sources=outside_sources(dict(snapshot,weekly_work_boundaries={}),person,day)
                            if any(value!=units for _,value in sources):
                                raise ValueError(person["name"]+" "+day.isoformat()+"：前月末勤務・休診日・他月の決定済み入力と一致しません。")
                            candidate[key]=str(units/2)
                    db.execute("CREATE TABLE IF NOT EXISTS weekly_work_boundaries(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
                    db.execute("INSERT INTO weekly_work_boundaries VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                               (month,json.dumps(candidate,ensure_ascii=False)))
                    db.commit()
                    return redirect(url_for("weekly_settings",month=month,saved="1"))
                except ValueError as exc:
                    db.rollback()
                    error=str(exc)
            rows=[]
            for person in staff:
                slots=[]
                for day in outside:
                    key=str(person["id"])+"_"+day.isoformat()
                    saved=(snapshot.get("weekly_work_boundaries") or {}).get(key,"")
                    sources=outside_sources(snapshot,person,day)
                    value=saved if saved!="" else (str(sources[0][1]/2) if sources else "")
                    if value != "":
                        value = str(parse_units(value)/2)
                    slots.append(dict(key=key,day=day.isoformat(),value=request.form.get("boundary_"+key,value) if error else value,
                                      past=day<date(year,number,1),sources="・".join(source for source,_ in sources)))
                rows.append(dict(person=person,slots=slots))
        finally:
            db.close()
        return render_template("weekly_settings.html",month=month,rows=rows,fingerprint=fingerprint,error=error)
