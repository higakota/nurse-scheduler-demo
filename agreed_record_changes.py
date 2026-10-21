"""保存した了承出勤の変更・取り消し。履歴を消さず、競合する後編集は上書きしない。"""
import copy
import json
import secrets
from datetime import datetime,timezone
from flask import abort,render_template,request,session,redirect,url_for
from ui import selected_month
from schedule import read_snapshot,digest
from manual_schedule import load_manual,align_helper_rows,diagnostics


def cancellation_plan(snapshot,base,index):
    updated=copy.deepcopy(snapshot)
    records=updated.get("monthly_settings",{}).get("agreed_wish_changes",[])
    if index<0 or index>=len(records) or records[index].get("cancelled"):
        raise ValueError("この了承出勤は取り消し済みか、記録がありません。")
    record=records[index]
    pid=str(record["staff_id"])
    changed=record.get("changes",[])
    if not changed:
        raise ValueError("元の勤務の記録がないため、自動では取り消せません。編集画面で確認してください。")
    affected={(change.get("staff_id",pid),change["day"]) for change in changed}
    for later in records[index+1:]:
        if not later.get("cancelled") and affected & {(c.get("staff_id",str(later["staff_id"])),c["day"]) for c in later.get("changes",[])}:
            raise ValueError("この後に同じ日の了承変更があります。後の変更から先に取り消してください。")
    i=next((i for i,p in enumerate(base["people"]) if str(p["id"])==pid),None)
    if i is None:
        raise ValueError("対象スタッフが見つかりません。")
    grid=[list(row) for row in base["grid"]]
    delta=[]
    abstract=lambda c:"W" if c in "ABCD" else c
    for change in changed:
        changed_id=change.get("staff_id",pid)
        i=next((j for j,p in enumerate(base["people"]) if str(p["id"])==changed_id),None)
        if i is None:
            raise ValueError("調整したスタッフが見つかりません。")
        if change["day"] not in base["days"]:
            raise ValueError("変更した日が元の表にありません。")
        d=base["days"].index(change["day"])
        pair=list(grid[d][i])
        for h in (0,1):
            if change["before"][h]==change["after"][h]:
                continue
            if abstract(pair[h])!=abstract(change["after"][h]):
                raise ValueError(change["day"]+"は後から編集されています。上書きを避けるため、先に編集内容を確認してください。")
            pair[h]=change["before"][h]
        after="".join(pair)
        if grid[d][i]!=after:
            delta.append(dict(day=change["day"],before=grid[d][i],after=after,**({k:change[k] for k in ("staff_id","name") if k in change})))
        grid[d][i]=after
    settings=updated["monthly_settings"]
    wishes=settings.setdefault("wishes",{})
    key=pid+"_"+record["date"]
    if wishes.get(key,"") != (record.get("remaining_wish") or ""):
        raise ValueError("希望休が後から変更されています。先に入力内容を確認してください。")
    wishes[key]=record["original_wish"]
    if record.get("replacement_date"):
        replacement=pid+"_"+record["replacement_date"]
        if wishes.get(replacement)!="full":
            raise ValueError("代わりの希望休が後から変更されています。")
        if record.get("prior_replacement_wish"):
            wishes[replacement]=record["prior_replacement_wish"]
        else:
            wishes.pop(replacement,None)
    now=datetime.now(timezone.utc).isoformat()
    record.update(cancelled=True,cancelled_at=now)
    boundaries=[]
    for change in record.get("boundary_changes",[]):
        entries=updated.get("weekly_neighbor_boundaries",{}).get(change["month"],{})
        if entries.get(change["key"])!=change["after"]:
            raise ValueError("前後月の勤務記録が後から変更されています。")
        entries[change["key"]]=change["before"]
        boundaries.append(dict(change,after=change["before"],before=change["after"]))
    audit=dict(created=now,boundary_changes=boundaries,paid_changes=[],automatic_rest_dates=[])
    return updated,grid,delta,audit


def record_plan(snapshot,base,index,operation,period,swap):
    from negotiated_leave import change_plan
    updated,restored,changes,audit=cancellation_plan(snapshot,base,index)
    if operation=="delete":
        return updated,restored,changes,audit
    if operation!="edit":
        raise ValueError("変更か取り消しを選んでください。")
    original=snapshot["monthly_settings"]["agreed_wish_changes"][index]
    updated,grid,_,new_audit=change_plan(updated,dict(base,grid=restored),str(original["staff_id"]),
                                        original["date"],period,swap,original.get("reason",""))
    new_audit["supersedes"]=index
    # 取り消し時の境界復元と、新しい出勤の境界更新を両方保存する。
    new_audit["boundary_write_months"]=list({change["month"] for change in audit["boundary_changes"]+new_audit.get("boundary_changes",[])})
    delta=[]
    for d,day in enumerate(base["days"]):
        for i,person in enumerate(base["people"]):
            if base["grid"][d][i]!=grid[d][i]:
                change=dict(day=day,before=base["grid"][d][i],after=grid[d][i])
                if str(person["id"])!=str(original["staff_id"]):
                    change.update(staff_id=str(person["id"]),name=person["name"])
                delta.append(change)
    return updated,grid,delta,new_audit


def register_agreed_record_changes(app,connect_db):
    @app.route("/schedule/agreed-change/record/<int:index>",methods=["GET","POST"])
    def agreed_record_edit(index):
        from negotiated_leave import agreed_calendar_view,persist_agreed_change,calendar_context
        from schedule_display import concise_shortages
        month=selected_month()
        session.setdefault("csrf_token",secrets.token_hex(32))
        db=connect_db()
        preview=False
        error=None
        warnings,shortages,changes=[],[],[]
        audit=None
        operation=request.form.get("operation","edit")
        period=request.form.get("period","")
        swap=request.form.get("swap","")
        updated=None
        grid=None
        replacement_days=[]
        try:
            db.execute("BEGIN IMMEDIATE" if request.method=="POST" else "BEGIN")
            snapshot,fp,generated=read_snapshot(db,month)
            records=snapshot.get("monthly_settings",{}).get("agreed_wish_changes",[])
            if index>=len(records):
                abort(404)
            record=records[index]
            base,revision=load_manual(db,month,snapshot,fp,generated)
            base=align_helper_rows(snapshot,base)
            period=period or record["work_period"]
            if request.method=="GET":
                swap=record.get("replacement_date","")
            try:
                restored,restored_grid,_,_=cancellation_plan(snapshot,base,index)
                replacement_days=calendar_context(restored,dict(base,grid=restored_grid),base["days"])["replacements"].get(str(record["staff_id"]),[])
            except ValueError as exc:
                error=str(exc)
            if request.method=="POST":
                if not secrets.compare_digest(session["csrf_token"],request.form.get("csrf_token","")):
                    abort(400)
                if request.form.get("fingerprint")!=fp or request.form.get("revision")!=revision:
                    raise ValueError("入力や勤務表が変更されました。画面を開き直してください。")
                from agreed_preview import remember,recalled,forget
                signature=digest(json.dumps([month,index,fp,revision,operation,period,swap]))
                if request.form.get("action")=="save":
                    if request.form.get("consent")!="yes" or session.get("agreed_record_confirmation")!=signature:
                        raise ValueError("変更内容を確認してチェックを入れてください。")
                    updated,grid,changes,audit=recalled("agreed_record",signature)
                else:
                    updated,grid,changes,audit=record_plan(snapshot,base,index,operation,period,swap)
                warnings,shortages=diagnostics(updated,base,grid)
                if request.form.get("action")=="preview":
                    preview=True
                    session["agreed_record_confirmation"]=signature
                    remember("agreed_record",signature,(updated,grid,changes,audit))
                elif request.form.get("action")=="save":
                    persist_agreed_change(db,updated,base,grid,changes,audit,shortages)
                    db.commit()
                    session.pop("agreed_record_confirmation",None)
                    forget("agreed_record")
                    return redirect(url_for("agreed_wish_change",month=month,saved="1",_anchor="agreed-day-"+record["date"]),code=303)
                else:
                    abort(400)
        except ValueError as exc:
            db.rollback()
            error=str(exc)
        finally:
            db.close()
        staff=[p for p in snapshot["staff"] if not p["is_help"]]
        name=next((p["name"] for p in staff if str(p["id"])==str(record["staff_id"])),"削除済みスタッフ")
        values=dict(staff=str(record["staff_id"]),day=record["date"],period=period,swap=swap,scope="")
        calendar_data=agreed_calendar_view(snapshot,base,preview=preview,updated=updated,grid=grid)
        return render_template("agreed_change.html",record_editor=True,record=record,record_index=index,
            operation=operation,replacement_days=replacement_days,calendar_data=calendar_data,
            month=month,values=values,staff=staff,days=base["days"],person_name=name,fingerprint=fp,
            revision=revision,preview=preview,error=error,changes=changes,warnings=warnings,shortages=shortages,
            shortage_summary=concise_shortages(shortages),records=list(reversed(records)),audit=audit)
