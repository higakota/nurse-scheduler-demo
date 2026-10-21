"""有給候補の1件を、入力と編集用勤務表へ同時に反映する。"""
import json,secrets
from datetime import datetime,timezone
from flask import request,session,abort,redirect,url_for,flash
from ui import selected_month
from schedule import read_snapshot
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
            if not source or source_token(source)!=request.form.get("source_token"):
                raise ValueError("勤務表が更新されています。有給候補を確認し直してください。")
            # 別の編集表がある場合、古い生成結果から上書きしない。
            manual_raw=source_data(db,month,"manual")
            if kind!="manual" and manual_raw:
                manual=json.loads(manual_raw)
                if manual.get("grid")!=source.get("grid"):
                    raise ValueError("編集中の勤務表があります。編集・印刷の有給候補から登録してください。")
            options=leave_candidates(snapshot,source,fp)
            pid,day,period=(request.form.get(k,"") for k in ("staff","day","period"))
            if not any(g["period"]==period and any(d["date"]==day and any(str(p["id"])==pid for p in d["people"]) for d in g["days"]) for g in options["groups"]):
                raise ValueError("この有給は現在の候補ではありません。最新の候補を確認してください。")
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
                       history=((json.loads(manual_raw).get("history",[]) if manual_raw else source.get("history",[]))+[dict(grid=source["grid"],saved=datetime.now(timezone.utc).isoformat())])[-20:])
            db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            raw=json.dumps(saved,ensure_ascii=False)
            db.execute("INSERT INTO manual_schedules VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",(month,raw))
            problem=prepare(updated,use_help=True)
            positions={str(p["id"]):j for j,p in enumerate(source["people"])}
            aligned=[[row[positions[str(p["id"])]] if str(p["id"]) in positions else "RR" for p in problem["people"]] for row in grid]
            rows=grouped_shortages([r for d,row in enumerate(aligned) for r in draft_shortages(problem,d,row)],problem,aligned)
            write_reference(db,updated,new_fp,rows,kind="draft",source_kind="manual",source_raw=raw)
            db.commit()
            flash("有給を登録し、勤務表に反映しました。ほかの勤務は変更していません。","candidate-leave")
        except ValueError as exc:
            db.rollback()
            flash(str(exc),"candidate-leave")
        finally:db.close()
        return redirect(url_for("manual_schedule",month=month))
