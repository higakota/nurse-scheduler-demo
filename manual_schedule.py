"""手動編集用の下書き。有給の編集は確認後に登録と同期し、再作成の元へ引き継ぐ。"""
import calendar
import hashlib
import json
import secrets
from datetime import date, datetime, timezone
from flask import abort, redirect, render_template, request, session, url_for
from ui import selected_month
from schedule import read_snapshot, digest
from schedule_display import monthly_display, grouped_shortages
from scheduler_engine import prepare, verify, draft_shortages, six_day_runs

CODES = {"S":"夏季休暇", "T":"あおば支援", "R":"休み", "D":"診療勤務（看護師）", "C":"検査室（検査技師）",
         "O":"通常業務", "M":"会議", "P":"有給", "A":"診療勤務（旧A）", "B":"診療勤務（旧B）"}


def seed_draft(db, month, snapshot, fingerprint, outcome):
    """仮作成の結果を編集開始用として保管する。編集中の下書きは変えない。"""
    problem = outcome["problem"]
    from help_shortages import conditions_hash
    data = dict(conditions_hash=conditions_hash(snapshot), days=problem["days"], people=problem["people"], grid=outcome["grid"],
                input_hash=fingerprint, source="仮作成の表", created=datetime.now(timezone.utc).isoformat(),
                included_help=bool(outcome.get("included_help")),advance_help=bool(outcome.get("advance_help")),
                rebalanced=bool(outcome.get("rebalanced")),notes=outcome.get("messages",[]))
    db.execute("CREATE TABLE IF NOT EXISTS manual_schedule_seeds(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    db.execute("INSERT INTO manual_schedule_seeds VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
               (month,json.dumps(data,ensure_ascii=False)))


def load_manual(db, month, snapshot, fingerprint, generated):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def raw(table):
        row = db.execute("SELECT data FROM "+table+" WHERE month=?",(month,)).fetchone() if table in tables else None
        return row[0] if row else ""
    original = raw("manual_schedules")
    seed = raw("manual_schedule_seeds")
    token = digest(json.dumps([original, seed, generated]))
    if original:
        return json.loads(original), token
    year, number = map(int,month.split("-"))
    days = [date(year,number,d).isoformat() for d in range(1,calendar.monthrange(year,number)[1]+1)]
    people = snapshot["staff"]
    candidates=[json.loads(value) for value in (seed,generated) if value]
    from roster_navigation import stamp
    source=max(candidates,key=lambda item:(item.get("input_hash")==fingerprint,stamp(item))) if candidates else {}
    source_days = {day:d for d,day in enumerate(source.get("days",[]))}
    source_people = {str(p["id"]):i for i,p in enumerate(source.get("people",[]))}
    grid = []
    for day in days:
        grid.append([source["grid"][source_days[day]][source_people[str(p["id"])]]
                     if day in source_days and str(p["id"]) in source_people else "RR" for p in people])
    return dict(source,days=days,people=people,grid=grid,history=source.get("history",[]),input_hash=source.get("input_hash",fingerprint),
                source=source.get("source","保存済みの自動作成結果" if generated else "手入力（初期状態は全員休み）")), token


def align_helper_rows(snapshot, base):
    """後から追加したヘルプの空行を補い、自院の全セルと元データを保持する。"""
    current = snapshot["staff"]
    if {str(p["id"]) for p in base["people"] if not p["is_help"]} != {str(p["id"]) for p in current if not p["is_help"]}:
        raise ValueError("自院スタッフの構成が下書きと異なります。現在の表を確認してください。")
    if [str(p["id"]) for p in base["people"]] == [str(p["id"]) for p in current]:
        return dict(base, people=current)
    indexes = {str(p["id"]): i for i,p in enumerate(base["people"])}
    def remap(grid):
        if any(len(row) != len(base["people"]) for row in grid):
            raise ValueError("下書き履歴のスタッフ構成を確認できません。変更は保存していません。")
        return [[row[indexes[str(p["id"])]] if str(p["id"]) in indexes else "RR" for p in current] for row in grid]
    aligned = dict(base, people=current, grid=remap(base["grid"]))
    aligned["staff_alignment_original"] = dict(people=base["people"], grid=base["grid"])
    aligned["history"] = []
    for entry in base.get("history", []):
        item = dict(entry, grid=remap(entry["grid"]))
        item.setdefault("staff_alignment_original", dict(people=base["people"], grid=entry["grid"]))
        aligned["history"].append(item)
    return aligned


def checked_patch(base, text):
    try:
        changes=json.loads(text)
        if not isinstance(changes,dict) or len(changes)>len(base["days"])*len(base["people"]):
            raise ValueError
        grid=[list(row) for row in base["grid"]]
        entries=[]
        for key,pair in changes.items():
            d,i=map(int,key.split("_"))
            if not 0<=d<len(grid) or not 0<=i<len(base["people"]):
                raise ValueError
            if not isinstance(pair,str) or len(pair)!=2 or any(c not in CODES for c in pair):
                raise ValueError
            old=grid[d][i]
            if old!=pair:
                entries.append(dict(day=base["days"][d],name=base["people"][i]["name"],before=old,after=pair))
                grid[d][i]=pair
        return grid,entries
    except (ValueError,TypeError,KeyError,IndexError,AttributeError):
        raise ValueError("変更内容が正しくありません。画面を開き直してください。")


def diagnostics(snapshot, base, grid):
    problem=prepare(snapshot,use_help=True)
    messages=list(problem["errors"])
    shortages=[]
    same = [str(p["id"]) for p in problem["people"]] == [str(p["id"]) for p in base["people"]]
    if not same:
        messages.append("スタッフ構成が変わっています。現在のスタッフと下書きが異なるため、勤務条件の全体チェックはできません。")
    if same:
        # Explicitly identify wish conflicts, even if other inputs are incomplete.
        for d,day in enumerate(base["days"]):
            for i,p in enumerate(base["people"]):
                key=str(p["id"])+"_"+day
                wish=snapshot["monthly_settings"].get("wishes",{}).get(key)
                paid=snapshot["leave_history"].get("leaves",{}).get(key)
                for half,period in enumerate(("am","pm")):
                    if wish in ("full",period) and grid[d][i][half]!="R":
                        messages.append(day+" "+p["name"]+"："+("午前" if half==0 else "午後")+"の希望休と重なっています。")
                    if paid in ("full",period) and grid[d][i][half]!="P":
                        messages.append(day+" "+p["name"]+"："+("午前" if half==0 else "午後")+"の有給と異なります。")
        if not problem["errors"]:
            messages.extend(verify(problem,grid,allow_shortages=True,max_full_days=6))
            shortages=grouped_shortages([r for d,row in enumerate(grid) for r in draft_shortages(problem,d,row)],problem,grid)
            for run in six_day_runs(problem,grid):
                messages.append(run["name"]+"："+run["start"]+"〜"+run["end"]+"は全日6連勤です。できるだけ避け、ヘルプを先に確認してください。")
        else:
            messages.append("入力がそろっていないため、人数不足・公休日数・週上限等の全体チェックは未完了です。")
    return list(dict.fromkeys(messages)),shortages



def synchronize_paid_inputs(snapshot, base, grid, changed_only=False):
    """表で指定した有給と、その表で明示的に取り消した有給を入力へ反映する案。"""
    from copy import deepcopy
    updated=deepcopy(snapshot)
    leaves=updated.setdefault("leave_history",{}).setdefault("leaves",{})
    changes=[]
    periods={frozenset((0,1)):"full",frozenset((0,)):"am",frozenset((1,)):"pm"}
    for d,day in enumerate(base["days"]):
        for i,person in enumerate(base["people"]):
            if person["is_help"]:
                continue
            pair=grid[d][i]
            if changed_only and pair==base["grid"][d][i]:continue
            key=str(person["id"])+"_"+day
            for kind,code in (("summer","S"),("support","T")):
                target=updated.setdefault("monthly_settings",{}).setdefault(kind,{})
                current=periods.get(frozenset(h for h,c in enumerate(pair) if c==code),"")
                if pair!=base["grid"][d][i] and current!=target.get(key,""):
                    changes.append(dict(key=key,date=day,name=person["name"],kind=kind,before=target.get(key,""),after=current))
                    if current:target[key]=current
                    else:target.pop(key,None)
            paid=periods.get(frozenset(h for h,c in enumerate(pair) if c=="P"),"")
            old=leaves.get(key,"")
            if paid and paid!=old or not paid and old and "P" in base["grid"][d][i] and pair!=base["grid"][d][i]:
                changes.append(dict(key=key,date=day,name=person["name"],before=old,after=paid))
                if paid:
                    leaves[key]=paid
                else:
                    leaves.pop(key,None)
    return updated,changes


def save_paid_inputs(db, snapshot):
    table=db.execute("SELECT name FROM sqlite_master WHERE name='monthly_settings'").fetchone()
    row=db.execute("SELECT data FROM monthly_settings WHERE month=?",(snapshot["month"],)).fetchone() if table else None
    original=json.loads(row[0]) if row else {}
    if any(original.get(k,{})!=snapshot["monthly_settings"].get(k,{}) for k in ("summer","support")):
        db.execute("CREATE TABLE IF NOT EXISTS monthly_settings(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("INSERT INTO monthly_settings VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",(snapshot["month"],json.dumps(snapshot["monthly_settings"],ensure_ascii=False)))
    db.execute("CREATE TABLE IF NOT EXISTS leave_history(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    db.execute("INSERT INTO leave_history VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
               (snapshot["month"],json.dumps(snapshot["leave_history"],ensure_ascii=False)))



def synchronize_help_inputs(snapshot, base, grid):
    """編集中のヘルプ出勤に必要な来院枠を提案する。承諾の保存は別に確認する。"""
    from copy import deepcopy
    updated=deepcopy(snapshot)
    visits=updated.setdefault("help_availability",{})
    periods={"full":{0,1},"am":{0},"pm":{1},"":set()}
    labels={frozenset((0,1)):"full",frozenset((0,)):"am",frozenset((1,)):"pm"}
    changes=[]
    for d,day in enumerate(base["days"]):
        for i,person in enumerate(base["people"]):
            if not person["is_help"]:
                continue
            needed={h for h,c in enumerate(grid[d][i]) if c in "ABCDMOT"}
            key=str(person["id"])+"_"+day
            before=visits.get(key,"")
            missing=needed-periods.get(before,set())
            if missing:
                after=labels[frozenset(needed|periods.get(before,set()))]
                visits[key]=after
                changes.append(dict(key=key,date=day,name=person["name"],before=before,after=after))
    return updated,changes


def save_help_inputs(db,snapshot):
    db.execute("CREATE TABLE IF NOT EXISTS help_availability(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    db.execute("INSERT INTO help_availability VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
               (snapshot["month"],json.dumps(snapshot["help_availability"],ensure_ascii=False)))


def register_manual_schedule(app, connect_db):
    @app.template_filter("manual_pair")
    def manual_pair(pair):
        labels={"S":"夏","T":"支","R":"休","D":"診","C":"検","O":"業","M":"会","P":"有","A":"診","B":"診"}
        return "／".join(labels.get(c,c) for c in pair)

    @app.route("/schedule/manual",methods=["GET","POST"])
    def manual_schedule():
        month=selected_month()
        session.setdefault("csrf_token",secrets.token_hex(32))
        db=connect_db()
        error=None
        paid_changes=[]
        help_changes=[]
        preview=False
        changes=[]
        patch="{}"
        initial_patch={}
        pending_kind,pending_value=None,None
        try:
            if request.method=="POST":
                if not secrets.compare_digest(session["csrf_token"],request.form.get("csrf_token","")):
                    abort(400)
                db.execute("BEGIN IMMEDIATE")
            else:
                db.execute("BEGIN")
            snapshot,fp,generated=read_snapshot(db,month)
            request_snapshot=snapshot
            base,token=load_manual(db,month,snapshot,fp,generated)
            if {str(p["id"]) for p in base["people"] if not p["is_help"]} == {str(p["id"]) for p in snapshot["staff"] if not p["is_help"]}:
                base=align_helper_rows(snapshot,base)
            grid=base["grid"]
            seed_row=db.execute("SELECT data FROM manual_schedule_seeds WHERE month=?",(month,)).fetchone() if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manual_schedule_seeds'").fetchone() else None
            import_sources={}
            if generated:
                import_sources["generated"]=json.loads(generated)
            if seed_row:
                import_sources["draft"]=json.loads(seed_row[0])
            pending_kind,pending_value=None,None
            from roster_navigation import pending_source,import_patch
            if "updated" in base:
                pending_kind,pending_value=pending_source(base,import_sources,fp)
            if request.method=="GET" and request.args.get("view_source"):
                kind=request.args["view_source"]
                source=import_sources.get(kind)
                if not source or digest(json.dumps(source,sort_keys=True,ensure_ascii=False))!=request.args.get("view_token"):
                    raise ValueError("指定した勤務表は更新されています。元の作成画面を開き直してください。")
                if source.get("input_hash")!=fp:
                    raise ValueError("指定した表の後に入力が変わっています。現在の入力を確認してください。")
                patch=import_patch(base,source,snapshot["staff"])
                grid,changes=checked_patch(base,patch)
                snapshot,paid_changes=synchronize_paid_inputs(snapshot,base,grid)
                snapshot,help_changes=synchronize_help_inputs(snapshot,base,grid)
                session["manual_confirmation"]=digest(json.dumps([month,fp,token,patch,False]))
                preview=True
            if request.method=="POST":
                if request.form.get("fingerprint")!=fp or request.form.get("revision")!=token:
                    error="入力条件または下書きが別の画面で変更されました。最新の内容を確認して編集し直してください。"
                else:
                    action=request.form.get("action")
                    patch=request.form.get("patch","{}")
                    if action=="import":
                        source=import_sources.get(request.form.get("source"))
                        if not source or source.get("input_hash")!=fp:
                            raise ValueError("取り込み元がないか、以前の条件の表です。現在の条件で作成し直してから取り込んでください。")
                        if {str(p["id"]) for p in base["people"]}!={str(p["id"]) for p in snapshot["staff"]}:
                            raise ValueError("下書きと現在のスタッフ構成が異なります。既存の下書きを残すため、取り込みを中止しました。")
                        source_days={day:d for d,day in enumerate(source["days"])}
                        source_people={str(p["id"]):i for i,p in enumerate(source["people"])}
                        if set(source["days"])!=set(base["days"]):
                            raise ValueError("取り込み元の日付が対象月と一致しません。")
                        patch=json.dumps({f"{d}_{i}":source["grid"][source_days[day]][source_people[str(person["id"])]] if str(person["id"]) in source_people else "RR"
                                          for d,day in enumerate(base["days"]) for i,person in enumerate(base["people"])})
                    input_priority = request.form.get("input_priority")=="yes" or action=="reflect_inputs"
                    if action=="reflect_inputs":
                        from input_reflection import reflection_patch
                        patch=reflection_patch(snapshot,base)
                    if action=="undo":
                        if not base.get("history"):
                            raise ValueError("戻せる修正履歴がありません。")
                        previous=base["history"][-1]["grid"]
                        patch=json.dumps({str(d)+"_"+str(i):pair for d,row in enumerate(previous) for i,pair in enumerate(row)})
                    grid,changes=checked_patch(base,patch)
                    if action!="edit":
                        snapshot,paid_changes=synchronize_paid_inputs(snapshot,base,grid,changed_only=input_priority)
                        snapshot,help_changes=synchronize_help_inputs(snapshot,base,grid)
                    signature=digest(json.dumps([month,fp,token,patch,input_priority]))
                    if action in ("preview","undo","import","reflect_inputs"):
                        preview=True
                        session["manual_confirmation"]=signature
                    elif action=="edit":
                        initial_patch={f"{d}_{i}":pair for d,row in enumerate(grid) for i,pair in enumerate(row) if pair!=base["grid"][d][i]}
                        grid=base["grid"]
                        session.pop("manual_confirmation",None)
                    elif action=="save":
                        if request.form.get("confirm")!="yes" or session.get("manual_confirmation")!=signature:
                            raise ValueError("変更内容を確認し、保存のチェックを入れてください。")
                        if help_changes and request.form.get("help_consent")!="yes":
                            raise ValueError("ヘルプの来院OKを確認し、来院予定への反映にチェックしてください。")
                        if changes or paid_changes or help_changes or base.get("input_hash") != fp or "updated" not in base:
                            from help_shortages import conditions_hash
                            history=list(base.get("history",[]))
                            if changes:
                                history.append(dict(grid=base["grid"],saved=datetime.now(timezone.utc).isoformat()))
                            if paid_changes:
                                save_paid_inputs(db,snapshot)
                            if help_changes:
                                save_help_inputs(db,snapshot)
                            current,new_fp,_=read_snapshot(db,month)
                            saved=dict(base,grid=grid,history=history[-20:],input_hash=new_fp,conditions_hash=conditions_hash(current),updated=datetime.now(timezone.utc).isoformat())
                            db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
                            saved_raw=json.dumps(saved,ensure_ascii=False)
                            db.execute("INSERT INTO manual_schedules VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
                                       (month,saved_raw))
                            from help_shortages import write_reference
                            _,saved_shortages=diagnostics(current,saved,grid)
                            write_reference(db,current,new_fp,saved_shortages,source_kind="manual",source_raw=saved_raw)
                            db.commit()
                        session.pop("manual_confirmation",None)
                        return redirect(url_for("manual_schedule",month=month,saved="1"),code=303)
                    else:
                        abort(400)
        except ValueError as exc:
            error=str(exc)
            snapshot=request_snapshot
        finally:
            db.close()
        warnings,shortages=diagnostics(snapshot,base,grid)
        checks_incomplete=any("全体チェックは未完了" in m or "全体チェックはできません" in m for m in warnings)
        display=monthly_display(base["days"],base["people"],grid,snapshot["monthly_settings"],
                                shortages=shortages,comparison_inputs={"summer":snapshot["monthly_settings"].get("summer",{}),"support":snapshot["monthly_settings"].get("support",{}),"wishes":snapshot["monthly_settings"].get("wishes",{}),"leaves":snapshot["leave_history"].get("leaves",{})},
                                doctor_plans=snapshot["doctor_plans"])
        if preview:
            for i, row in enumerate(display["rows"]):
                for d, cell in enumerate(row["cells"]):
                    before=base["grid"][d][i]
                    after=grid[d][i]
                    if before != after:
                        cell["manual_change"]=dict(before=manual_pair(before), after=manual_pair(after), anchor=f"manual-change-{d}-{i}")
        if checks_incomplete:
            for row in display["deficits"]:
                for cell in row["cells"]:
                    cell["label"]="未確認"
        from leave_candidates import leave_candidates
        paid_candidates = (leave_candidates(snapshot,base if "updated" in base else None,fp)
                           if not preview and not error else
                           dict(days=[],groups=[],message="編集内容を確認・保存してから、有給候補を確認してください。"))
        paid_candidates["source_kind"]="manual"
        pending_token=digest(json.dumps(pending_value,sort_keys=True,ensure_ascii=False)) if pending_value else ""
        return render_template("manual_schedule.html",source_view_error=bool(error and request.args.get("view_source")),pending_kind=pending_kind,pending_token=pending_token,help_changes=help_changes,paid_changes=paid_changes,paid_candidates=paid_candidates,month=month,base=base,grid=grid,display=display,
                               input_priority=bool(request.form.get("input_priority")=="yes" or request.form.get("action")=="reflect_inputs"),fingerprint=fp,revision=token,error=error,preview=preview,changes=changes,patch=patch,initial_patch=initial_patch,
                               warnings=warnings,shortages=shortages,codes=CODES,import_sources=import_sources,checks_incomplete=checks_incomplete,stale=base["input_hash"]!=fp)
