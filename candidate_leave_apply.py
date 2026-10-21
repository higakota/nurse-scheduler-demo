"""有給候補の1件を、入力と編集用勤務表へ同時に反映する。"""
import json,secrets
from datetime import datetime,timezone
from flask import request,session,abort,redirect,url_for,flash,render_template
from ui import selected_month
from schedule import digest,read_snapshot
from help_shortages import source_data,conditions_hash,write_reference
from leave_candidates import leave_candidates,source_token
from scheduler_engine import prepare,draft_shortages
from schedule_display import grouped_shortages

def register_candidate_leave(app,connect_db):
    @app.post("/schedule/paid-candidate")
    def apply_candidate_leave():
        month=selected_month()
        if not session.get("csrf_token") or not secrets.compare_digest(session["csrf_token"],request.form.get("csrf_token","")):
            abort(400)
        kind=request.form.get("source_kind","manual")
        return_url=(url_for("manual_schedule",month=month,paid_open="1",_anchor="paid-candidates") if kind=="manual" else
                    url_for("schedule",month=month,resume="1",paid_open="1",_anchor="paid-candidates") if kind=="draft" else
                    url_for("schedule",month=month,paid_open="1",_anchor="paid-candidates"))
        db=connect_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            snapshot,fp,generated=read_snapshot(db,month)
            if request.form.get("fingerprint")!=fp:
                raise ValueError("入力が変更されています。有給候補を確認し直してください。")
            kind=request.form.get("source_kind")
            if kind not in ("manual","draft","generated"):raise ValueError("元の勤務表を選び直してください。")
            raw=generated if kind=="generated" else source_data(db,month,kind)
            source=json.loads(raw) if raw else None
            if source and kind=="manual":
                from manual_schedule import align_helper_rows
                source=align_helper_rows(snapshot,source)
            if not source or source_token(source)!=request.form.get("source_token"):
                raise ValueError("勤務表が更新されています。有給候補を確認し直してください。")
            manual_raw=source_data(db,month,"manual")
            from manual_schedule import align_helper_rows
            aligned_source=align_helper_rows(snapshot,source)
            manual=align_helper_rows(snapshot,json.loads(manual_raw)) if manual_raw else None
            different=kind!="manual" and manual and manual["grid"]!=aligned_source["grid"]
            options=leave_candidates(snapshot,source,fp)
            pid,day,period=(request.form.get(k,"") for k in ("staff","day","period"))
            if not any(g["period"]==period and any(d["date"]==day and any(str(p["id"])==pid for p in d["people"]) for d in g["days"]) for g in options["groups"]):
                raise ValueError("この有給は現在の候補ではありません。最新の候補を確認してください。")
            if different:
                token=digest(manual_raw)
                if request.form.get("confirm_replace")!="yes":
                    positions={str(p["id"]):i for i,p in enumerate(manual["people"])}
                    changes=[]
                    d_target=aligned_source["days"].index(day)
                    target_halves={"full":(0,1),"am":(0,),"pm":(1,)}[period]
                    for d,date in enumerate(aligned_source["days"]):
                        for i,person in enumerate(aligned_source["people"]):
                            before=manual["grid"][d][positions[str(person["id"])]]
                            after=aligned_source["grid"][d][i]
                            if d==d_target and str(person["id"])==pid:
                                pair=list(after)
                                for h in target_halves:pair[h]="P"
                                after="".join(pair)
                            if before!=after:changes.append(dict(date=date,name=person["name"],before=before,after=after))
                    person=next(p for p in source["people"] if str(p["id"])==pid)
                    return render_template("candidate_leave_review.html",month=month,changes=changes,person=person,
                                           day=day,period=period,manual_token=token,values=request.form,return_url=return_url)
                if request.form.get("manual_token")!=token:
                    raise ValueError("編集中の勤務表が変わりました。候補から選び直してください。")
            elif request.form.get("confirm_replace")=="yes" and request.form.get("manual_token")!=digest(manual_raw):
                raise ValueError("編集中の勤務表が変わりました。候補から選び直してください。")
            source=aligned_source
            leaves=snapshot.setdefault("leave_history",{}).setdefault("leaves",{})
            leaves[pid+"_"+day]=period
            db.execute("CREATE TABLE IF NOT EXISTS leave_history(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            db.execute("INSERT INTO leave_history VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",(month,json.dumps(snapshot["leave_history"],ensure_ascii=False)))
            updated,new_fp,_=read_snapshot(db,month)
            grid=[list(row) for row in source["grid"]]
            d=source["days"].index(day);i=next(i for i,p in enumerate(source["people"]) if str(p["id"])==pid)
            pair=list(grid[d][i])
            for h in {"full":(0,1),"am":(0,),"pm":(1,)}[period]:pair[h]="P"
            grid[d][i]="".join(pair)
            saved=dict(source,grid=grid,input_hash=new_fp,conditions_hash=conditions_hash(updated),updated=datetime.now(timezone.utc).isoformat(),
                       history=((manual.get("history",[]) if manual else source.get("history",[]))+[dict(grid=manual["grid"] if manual else source["grid"],saved=datetime.now(timezone.utc).isoformat())])[-20:])
            db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            raw=json.dumps(saved,ensure_ascii=False)
            db.execute("INSERT INTO manual_schedules VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",(month,raw))
            problem=prepare(updated,use_help=True)
            positions={str(p["id"]):j for j,p in enumerate(source["people"])}
            aligned=[[row[positions[str(p["id"])]] if str(p["id"]) in positions else "RR" for p in problem["people"]] for row in grid]
            rows=grouped_shortages([r for d,row in enumerate(aligned) for r in draft_shortages(problem,d,row)],problem,aligned)
            write_reference(db,updated,new_fp,rows,kind="draft",source_kind="manual",source_raw=raw)
            db.commit()
            flash("有給を登録し、選んだ表に反映しました。","candidate-leave")
        except ValueError as exc:
            db.rollback()
            flash(str(exc),"candidate-leave")
            return redirect(return_url,code=303)
        finally:db.close()
        return redirect(url_for("manual_schedule",month=month))
