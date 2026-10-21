"""本人了承後の希望休変更。入力と手動下書きを確認後に同時保存する。"""
import calendar
import copy
import json
import secrets
from datetime import date, datetime, timezone
from flask import abort, redirect, render_template, request, session, url_for
from ui import selected_month
from schedule import read_snapshot, digest
from manual_schedule import load_manual, diagnostics, align_helper_rows, synchronize_paid_inputs, save_paid_inputs
from scheduler_engine import WORK, rest_units




def approved_help_preview(snapshot, base):
    """自院の全セルを維持し、承諾済みヘルプを日別に配置する確認用の表。"""
    from itertools import product
    from scheduler_engine import prepare, draft_shortages
    from help_limits import nurse_helper_excess
    aligned=align_helper_rows(snapshot,base)
    problem=prepare(snapshot,use_help=True)
    if problem["errors"]:
        raise ValueError("ヘルプを含む不足確認に必要な入力を確認してください。")
    people=problem["people"]
    if [str(p["id"]) for p in people] != [str(p["id"]) for p in aligned["people"]]:
        raise ValueError("スタッフ構成が変わりました。不足を確認し直してください。")
    helpers=[i for i,p in enumerate(people) if p["is_help"]]
    grid=[list(row) for row in aligned["grid"]]
    for d,day in enumerate(problem["days"]):
        choices=[]
        for i in helpers:
            allowed=problem["options"][d][i]
            if snapshot.get("help_availability",{}).get(str(people[i]["id"])+"_"+day)=="full":
                allowed=[pair for pair in allowed if all(c in "WMO" for c in pair) or not any(c in "WMO" for c in pair)]
            choices.append(allowed)
        best=None
        for count,pairs in enumerate(product(*choices)):
            if count>=50000:
                raise ValueError("ヘルプの候補が多いため確認できませんでした。来院予定を絞って確認してください。")
            candidate=list(grid[d])
            for i,pair in zip(helpers,pairs):
                candidate[i]="".join(("C" if people[i]["role"]=="technician" else "D") if c=="W" else c for c in pair)
            rows=draft_shortages(problem,d,candidate)
            score=(sum(r["missing"] for r in rows),nurse_helper_excess(people,candidate),
                   sum(sum(c in WORK for c in candidate[i]) for i in helpers))
            if best is None or score<best[0]:
                best=(score,candidate)
        if best is None:
            raise ValueError("来院予定に合うヘルプ配置を確認できませんでした。")
        grid[d]=best[1]
    return dict(aligned,grid=grid)


def automatic_rest(snapshot, base, grid, person_id, protected_day):
    """指定公休に不足する分を、他の日の全日休みで補う。既存の不足は増やさない。"""
    from scheduler_engine import prepare, verify, draft_shortages, six_day_runs
    from itertools import combinations
    person = next(p for p in snapshot["staff"] if str(p["id"]) == person_id)
    target = snapshot.get("monthly_settings", {}).get("targets", {}).get(person_id)
    if person["employment"] == "part" or target in (None, ""):
        return grid, []
    i = next(i for i,p in enumerate(base["people"]) if str(p["id"]) == person_id)
    needed = round(float(target)*2) - sum(rest_units(row[i]) for row in grid)
    if needed <= 0:
        return grid, []
    problem = prepare(snapshot, use_help=True)
    if problem["errors"] or [str(p["id"]) for p in problem["people"]] != [str(p["id"]) for p in base["people"]]:
        raise ValueError("公休を自動調整できません。入力内容を確認するか、代わりの休みを選んでください。")
    before_errors = set(verify(problem,grid,allow_shortages=True,max_full_days=6))
    def shortage_map(rows):
        return {(r["half"],r["area"]):r["missing"] for r in rows}
    before_shortages = [shortage_map(draft_shortages(problem,d,row)) for d,row in enumerate(grid)]
    candidates = []
    for d,day in enumerate(base["days"]):
        if day == protected_day or "RR" not in problem["options"][d][i]:
            continue
        pair=grid[d][i]
        # 希望・有給・会議を変更せず、新しい半休を作らない。
        if "M" in pair or "P" in pair or not any(c in WORK for c in pair):
            continue
        gain=2-rest_units(pair)
        if gain <= 0 or gain > needed:
            continue
        trial=list(grid[d]); trial[i]="RR"
        after=shortage_map(draft_shortages(problem,d,trial))
        if any(count>before_shortages[d].get(key,0) for key,count in after.items()):
            continue
        candidates.append((d,gain))
    tried=0
    best=None
    for count in range(1,min(needed,len(candidates))+1):
        for selected in combinations(candidates,count):
            tried+=1
            if tried>5000:
                break
            if sum(gain for _,gain in selected)!=needed:
                continue
            trial=[list(row) for row in grid]
            changes=[]
            for d,_ in selected:
                changes.append(dict(day=base["days"][d],before=trial[d][i],after="RR",automatic=True))
                trial[d][i]="RR"
            if not (set(verify(problem,trial,allow_shortages=True,max_full_days=6))-before_errors):
                score=len(six_day_runs(problem,trial))
                if best is None or score<best[0]:
                    best=(score,trial,changes)
                if score==0:
                    return trial,changes
        if tried>5000:
            break
    if best is not None:
        return best[1],best[2]
    raise ValueError("公休を補える日が見つかりませんでした。人数不足を増やさず調整できる代わりの休みを選ぶか、自院の勤務・ヘルプを見直してください。")


def avoid_six_after_agreement(snapshot, base, grid, person_id, protected_day):
    """Try local whole-day rest moves before fixing the agreed roster for help."""
    from scheduler_engine import prepare, verify, draft_shortages, six_day_runs
    person = next(p for p in snapshot["staff"] if str(p["id"]) == person_id)
    i = next(i for i,p in enumerate(base["people"]) if str(p["id"]) == person_id)
    problem = prepare(snapshot,use_help=True)
    if problem["errors"] or [str(p["id"]) for p in problem["people"]] != [str(p["id"]) for p in base["people"]]:
        return grid, []
    def runs(rows):
        run=problem["tails"][i]
        count=0
        for row in rows:
            run=run+1 if all(code in WORK for code in row[i]) else 0
            count+=int(run==6)
        return count
    initial = runs(grid)
    if not initial:
        return grid, []
    before_errors = set(verify(problem,grid,allow_shortages=True,max_full_days=6))
    def deficits(d,row):
        return {(r["half"],r["area"]):r["missing"] for r in draft_shortages(problem,d,row)}
    before = [deficits(d,row) for d,row in enumerate(grid)]
    def acceptable(d,pair):
        row=list(grid[d]);row[i]=pair
        return all(value<=before[d].get(key,0) for key,value in deficits(d,row).items())
    off=[]
    on=[]
    for d,day in enumerate(base["days"]):
        if day==protected_day:
            continue
        pair=grid[d][i]
        if all(c in WORK for c in pair) and "M" not in pair and "RR" in problem["options"][d][i] and acceptable(d,"RR"):
            off.append(d)
        if pair=="RR":
            for option in problem["options"][d][i]:
                if all(c in WORK for c in option) and "M" not in option:
                    clinical="".join(("C" if person["role"]=="technician" else "D") if c=="W" else c for c in option)
                    if acceptable(d,clinical):
                        on.append((d,clinical))
    best=None
    # Keep the person's rest total by moving an existing day off first.
    for d in off:
        for replacement,pair in on:
            trial=[list(row) for row in grid];trial[d][i]="RR";trial[replacement][i]=pair
            if set(verify(problem,trial,allow_shortages=True,max_full_days=6))-before_errors:
                continue
            count=runs(trial)
            if count<initial and (best is None or count<best[0]):
                best=(count,trial)
                if count==0:
                    break
        if best is not None and best[0]==0:
            break
    # Part-time staff have a weekly maximum, not an exact public-holiday target.
    # A whole-day rest is also allowed if no move can avoid the run.
    if person["employment"]=="part" and (best is None or best[0]>0):
        for d in off:
            trial=[list(row) for row in grid];trial[d][i]="RR"
            if set(verify(problem,trial,allow_shortages=True,max_full_days=6))-before_errors:
                continue
            count=runs(trial)
            if count<initial and (best is None or count<best[0]):
                best=(count,trial)
                if count==0:
                    break
    if best is None:
        return grid, []
    result=best[1]
    changes=[dict(day=day,before=grid[d][i],after=result[d][i],automatic=True)
             for d,day in enumerate(base["days"]) if result[d][i]!=grid[d][i]]
    return result,changes


def change_plan(snapshot, base, person_id, day, period, swap, reason):
    snapshot,paid_changes=synchronize_paid_inputs(snapshot,base,base["grid"])
    if period not in ("full", "am", "pm"):
        raise ValueError("出勤する時間帯を選んでください。")
    if len(reason) > 200:
        raise ValueError("メモは200文字以内にしてください。")
    people = snapshot["staff"]
    person = next((p for p in people if str(p["id"]) == person_id and not p["is_help"]), None)
    if person is None:
        raise ValueError("対象の自院スタッフを選んでください。")
    if {str(p["id"]) for p in base["people"]} != {str(p["id"]) for p in people}:
        raise ValueError("下書きのスタッフ構成が異なります。編集・印刷で現在の表を確認してください。")
    days = base["days"]
    if day not in days or day[:7] != snapshot["month"]:
        raise ValueError("対象月の出勤日を選んでください。")
    settings = copy.deepcopy(snapshot.get("monthly_settings") or {})
    wishes = settings.setdefault("wishes", {})
    key = person_id + "_" + day
    original = wishes.get(key)
    requested = {"full": {0, 1}, "am": {0}, "pm": {1}}.get(original, set())
    agreed = {"full": {0, 1}, "am": {0}, "pm": {1}}[period]
    if not requested & agreed:
        raise ValueError("選択した時間帯には希望休がありません。通常の勤務修正は編集・印刷で行ってください。")
    if date.fromisoformat(day).weekday() == 6 or day in settings.get("closures", {}):
        raise ValueError("日曜・全日休診日は出勤へ変更できません。")
    paid = snapshot.get("leave_history", {}).get("leaves", {}).get(key)
    if any(paid in ("full", ("am", "pm")[h]) for h in agreed):
        raise ValueError("有給と重なっています。この操作では有給を取り消しません。")
    remaining = requested - agreed
    after = "full" if remaining == {0, 1} else "am" if remaining == {0} else "pm" if remaining == {1} else ""
    if after:
        wishes[key] = after
    else:
        wishes.pop(key, None)
    grid = [list(row) for row in base["grid"]]
    i = next(i for i,p in enumerate(base["people"]) if str(p["id"]) == person_id)
    d = days.index(day)
    pair = list(grid[d][i])
    for h in agreed:
        if pair[h] == "P":
            raise ValueError("下書きに有給が指定されています。有給は変更しません。")
        meeting = h == 1 and any(m["date"] == day and person_id in m["participants"] for m in settings.get("meetings", []))
        pair[h] = "M" if meeting else "O" if h == 1 and date.fromisoformat(day).weekday() == 4 else "C" if person["role"] == "technician" else "D"
    grid[d][i] = "".join(pair)
    if person["role"] == "technician" and grid[d][i][1] in WORK and grid[d][i][0] not in WORK:
        raise ValueError("検査技師の午後のみ勤務は、現在の勤務条件では登録できません。")
    changes = [dict(day=day, before=base["grid"][d][i], after=grid[d][i])]
    prior_replacement_wish=None
    if swap:
        if swap == day or swap not in days or swap[:7] != snapshot["month"]:
            raise ValueError("代わりの希望休は、出勤日と異なる対象月の日付を選んでください。")
        sd = days.index(swap)
        swap_key = person_id + "_" + swap
        prior_replacement_wish=wishes.get(swap_key)
        if not all(code in WORK for code in grid[sd][i]) or "M" in grid[sd][i]:
            raise ValueError("代わりの希望休は、会議のない全日勤務の日を選んでください。")
        if snapshot.get("leave_history", {}).get("leaves", {}).get(swap_key):
            raise ValueError("代わりの日に有給が登録されています。有給は変更しません。")
        if any(m["date"] == swap and person_id in m["participants"] for m in settings.get("meetings", [])):
            raise ValueError("代わりの日には会議があります。別の日を選んでください。")
        changes.append(dict(day=swap, before=grid[sd][i], after="RR"))
        grid[sd][i] = "RR"
        wishes[swap_key] = "full"
    automatic_changes=[]
    if not swap:
        grid, automatic_changes = automatic_rest(dict(snapshot,monthly_settings=settings),base,grid,person_id,day)
        changes.extend(automatic_changes)
    grid, run_changes = avoid_six_after_agreement(dict(snapshot,monthly_settings=settings),base,grid,person_id,day)
    changes.extend(run_changes)
    automatic_changes.extend(run_changes)
    from agreed_rebalance import rebalance_agreement
    grid,global_adjustment=rebalance_agreement(dict(snapshot,monthly_settings=settings),base,grid,person_id,day,period)
    automatic_days={change["day"] for change in automatic_changes}
    changes=[]
    for d,changed_day in enumerate(days):
        for j,changed_person in enumerate(base["people"]):
            if base["grid"][d][j]==grid[d][j]:
                continue
            change=dict(day=changed_day,before=base["grid"][d][j],after=grid[d][j])
            if j!=i:
                change.update(staff_id=str(changed_person["id"]),name=changed_person["name"],automatic=True)
            elif changed_day in automatic_days or changed_day!=day:
                change["automatic"]=True
            changes.append(change)
    automatic_changes=[change for change in changes if change.get("automatic") and
                       change.get("staff_id",person_id)==person_id and change["after"]=="RR"]
    boundary_changes=[]
    neighbor_boundaries=copy.deepcopy(snapshot.get("weekly_neighbor_boundaries",{}))
    from weekly_rules import work_units
    people_by_id={str(p["id"]):p for p in people}
    for change in changes:
        changed_id=change.get("staff_id",person_id)
        if people_by_id[changed_id]["employment"]!="part":
            continue
        boundary_key=changed_id+"_"+change["day"]
        units=work_units(change["after"])
        for neighbor,entries in neighbor_boundaries.items():
            if boundary_key in entries and float(entries[boundary_key])*2 != units:
                boundary_changes.append(dict(month=neighbor,key=boundary_key,before=entries[boundary_key],after=units/2))
                entries[boundary_key]=units/2
    snapshot=dict(snapshot,weekly_neighbor_boundaries=neighbor_boundaries)
    audit = dict(global_adjustment=global_adjustment,paid_changes=paid_changes,boundary_changes=boundary_changes,automatic_rest_dates=[change["day"] for change in automatic_changes],rest_before=sum(rest_units(row[i]) for row in base["grid"])/2,
                 rest_after=sum(rest_units(row[i]) for row in grid)/2,
                 rest_target=settings.get("targets", {}).get(person_id), staff_id=person_id, date=day, original_wish=original, remaining_wish=after,
                 work_period=period, replacement_date=swap, prior_replacement_wish=prior_replacement_wish, reason=reason.strip(),
                 changes=changes, created=datetime.now(timezone.utc).isoformat())
    settings.setdefault("agreed_wish_changes", []).append(audit)
    updated = dict(snapshot, monthly_settings=settings)
    return updated, grid, changes, audit


def calendar_context(snapshot, base, days):
    """表示用の希望休・有給と、従来の条件を満たす代替休候補。書き込みはしない。"""
    settings=snapshot.get("monthly_settings",{})
    wishes=settings.get("wishes",{})
    leaves=snapshot.get("leave_history",{}).get("leaves",{})
    staff=[p for p in snapshot["staff"] if not p["is_help"]]
    entries={day:[] for day in days}
    labels={"full":"全日","am":"午前","pm":"午後"}
    amended={}
    active_records={}
    for index,record in enumerate(settings.get("agreed_wish_changes",[])):
        if record.get("cancelled"):
            continue
        key=(str(record["staff_id"]),record["date"])
        amended.setdefault(key,record)
        active_records.setdefault(key,[]).append(dict(index=index,period=record["work_period"],label=labels.get(record["work_period"],"")))
    for day in days:
        for person in staff:
            key=str(person["id"])+"_"+day
            wish,paid=wishes.get(key),leaves.get(key)
            record=amended.get((str(person["id"]),day))
            if not (wish or paid or record):
                continue
            entries[day].append(dict(staff=str(person["id"]),name=person["name"],wish=wish or "",
                wish_label=labels.get(wish,""),paid_label=labels.get(paid,""),
                records=active_records.get((str(person["id"]),day),[]),amended=bool(record),original_label=labels.get(record.get("original_wish"),"") if record else ""))
    positions={str(p["id"]):i for i,p in enumerate(base["people"])}
    replacements={}
    for person in staff:
        pid=str(person["id"])
        if pid not in positions:
            replacements[pid]=[]
            continue
        i=positions[pid]
        replacements[pid]=[day for d,day in enumerate(base["days"])
            if day in entries and all(c in WORK for c in base["grid"][d][i]) and "M" not in base["grid"][d][i]
            and not leaves.get(pid+"_"+day)
            and not any(m["date"]==day and pid in m["participants"] for m in settings.get("meetings",[]))]
    year,month=map(int,snapshot["month"].split("-"))
    weeks=[[d.isoformat() if d.month==month else None for d in week]
           for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year,month)]
    closed={day for day in days if date.fromisoformat(day).weekday()==6 or day in settings.get("closures",{})}
    return dict(weeks=weeks,entries=entries,replacements=replacements,closed=closed)



def persist_agreed_change(db, updated, base, grid, changes, audit, shortages):
    """希望休・勤務・境界記録・不足の参照元を同時に保存する。commitは呼び出し側。"""
    month=updated["month"]
    monthly=updated["monthly_settings"]
    db.execute("CREATE TABLE IF NOT EXISTS monthly_settings(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    db.execute("INSERT INTO monthly_settings VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",
               (month,json.dumps(monthly,ensure_ascii=False)))
    if audit.get("paid_changes"):
        save_paid_inputs(db,updated)
    boundary_months={change["month"] for change in audit.get("boundary_changes",[])}|set(audit.get("boundary_write_months",[]))
    for neighbor in boundary_months:
        db.execute("UPDATE weekly_work_boundaries SET data=? WHERE month=?",
                   (json.dumps(updated["weekly_neighbor_boundaries"][neighbor],ensure_ascii=False),neighbor))
    current,fp,_=read_snapshot(db,month)
    from help_shortages import conditions_hash,write_reference
    history=list(base.get("history",[]))
    if changes:
        history.append(dict(grid=base["grid"],saved=audit["created"]))
    saved=dict(base,grid=grid,history=history[-20:],input_hash=fp,
               conditions_hash=conditions_hash(current),updated=audit["created"])
    db.execute("CREATE TABLE IF NOT EXISTS manual_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
    raw=json.dumps(saved,ensure_ascii=False)
    db.execute("INSERT INTO manual_schedules VALUES (?,?) ON CONFLICT(month) DO UPDATE SET data=excluded.data",(month,raw))
    write_reference(db,current,fp,shortages,kind="draft",source_kind="manual",source_raw=raw)


def agreed_calendar_view(snapshot,base,scoped_days=None,preview=False,updated=None,grid=None):
    from schedule_display import concise_shortages
    data=calendar_context(snapshot,base,base["days"])
    messages,rows=diagnostics(updated if preview else snapshot,base,grid if preview else base["grid"])
    current={row["date"]:row["items"] for row in concise_shortages(rows)}
    selected=set(scoped_days) if scoped_days is not None else set(current)
    active={record["date"] for record in snapshot.get("monthly_settings",{}).get("agreed_wish_changes",[]) if not record.get("cancelled")}
    data.update(shortages=({day:items for day,items in current.items() if day in selected} if preview else scoped_days) if scoped_days is not None else current,
                editable_days=selected,visible_days=selected|active,scoped=True,
                shortages_checked=not any("未完了" in message or "全体チェックはできません" in message for message in messages))
    if scoped_days is not None and not preview:
        data["shortages_checked"]=True
    return data


def register_negotiated_leave(app, connect_db):
    @app.route("/schedule/agreed-change", methods=["GET", "POST"])
    def agreed_wish_change():
        month = selected_month()
        session.setdefault("csrf_token", secrets.token_hex(32))
        values = {key: request.form.get(key, request.args.get(key, ""))
                  for key in ("staff", "day", "period", "swap", "reason", "scope")}
        values["period"] = values["period"] or "full"
        error, preview, changes, warnings, shortages = None, False, [], [], []
        audit = None
        scoped_days = None
        db = connect_db()
        try:
            db.execute("BEGIN IMMEDIATE" if request.method == "POST" else "BEGIN")
            snapshot, fingerprint, generated = read_snapshot(db, month)
            base, revision = load_manual(db, month, snapshot, fingerprint, generated)
            if not values["scope"]:
                # 直接開いた場合も、最新の不足確認に使った表を選ぶ。
                from help_shortages import load_reference, source_data
                reference = load_reference(db, month)
                if reference["state"] in ("current", "reference") and reference["kind"] != "verified":
                    row = db.execute("SELECT data FROM help_shortage_previews WHERE month=?", (month,)).fetchone()
                    checked = json.loads(row[0])
                    kind = checked.get("source_kind", "draft")
                    source = source_data(db, month, kind)
                    # 旧版の仮作成は、参照元を以前の手動表のまま記録していた。
                    seed_raw = source_data(db, month, "draft")
                    if seed_raw:
                        seed = json.loads(seed_raw)
                        if (seed.get("input_hash")==checked.get("input_hash")
                            and seed.get("created","")>=checked.get("created","")):
                            kind, source = "draft", seed_raw
                    if source:
                        from itsdangerous import URLSafeSerializer
                        from schedule_display import concise_shortages
                        values["scope"] = URLSafeSerializer(app.secret_key, salt="agreed-shortage-days").dumps(
                            dict(month=month, fingerprint=fingerprint, source_kind=kind,
                                 source_hash=digest(source), days=concise_shortages(checked["rows"]),
                                 include_help=False))
            if values["scope"]:
                from itsdangerous import URLSafeSerializer, BadSignature
                scoped_days = {}
                try:
                    context = URLSafeSerializer(app.secret_key, salt="agreed-shortage-days").loads(values["scope"])
                except BadSignature:
                    raise ValueError("不足一覧のリンクを開き直してください。")
                if context["month"] != month or context["fingerprint"] != fingerprint:
                    raise ValueError("入力が変わりました。勤務表の不足を確認し直してください。")
                scoped_days = {row["date"]:row["items"] for row in context["days"]}
                if context.get("source_hash"):
                    from fixed_help import load_seed,load_manual_source
                    source=(load_manual_source if context["source_kind"]=="manual" else load_seed)(db,month)
                    if not source or digest(source)!=context["source_hash"]:
                        raise ValueError("元の自院勤務が変わりました。不足を確認し直してください。")
                    base=align_helper_rows(snapshot,json.loads(source))
                if context.get("include_help",True):
                    base=approved_help_preview(snapshot,base)


            if scoped_days is None:
                base = align_helper_rows(snapshot,base)
                from schedule_display import concise_shortages
                _, original_shortages = diagnostics(snapshot, base, base["grid"])
                scoped_days = {row["date"]:row["items"] for row in concise_shortages(original_shortages)}

            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400)
                if fingerprint != request.form.get("fingerprint") or revision != request.form.get("revision"):
                    raise ValueError("入力や下書きが別の画面で変更されました。画面を開き直してください。")
                base = align_helper_rows(snapshot, base)
                from agreed_preview import remember,recalled,forget
                signature = digest(json.dumps([month, fingerprint, revision, values], sort_keys=True))
                action = request.form.get("action")
                if action=="save":
                    if request.form.get("consent")!="yes" or session.get("agreed_change_confirmation")!=signature:
                        raise ValueError("変更内容を確認し、本人の了承確認にチェックしてください。")
                    updated,grid,changes,audit=recalled("agreed_change",signature)
                else:
                    updated, grid, changes, audit = change_plan(snapshot, base, values["staff"], values["day"],
                                                                values["period"], values["swap"], values["reason"])
                if scoped_days is not None and values["day"] not in scoped_days:
                    raise ValueError("不足一覧に表示された日を選んでください。")
                warnings, shortages = diagnostics(updated, base, grid)
                if action == "preview":
                    preview = True
                    session["agreed_change_confirmation"] = signature
                    remember("agreed_change",signature,(updated,grid,changes,audit))
                elif action == "save":
                    persist_agreed_change(db,updated,base,grid,changes,audit,shortages)
                    db.commit()
                    session.pop("agreed_change_confirmation", None)
                    forget("agreed_change")
                    return redirect(url_for("manual_schedule",month=month,saved="1",agreed="changed"),code=303)
                else:
                    abort(400)
            staff = [p for p in snapshot["staff"] if not p["is_help"]]
            records = list(reversed(snapshot.get("monthly_settings", {}).get("agreed_wish_changes", [])))
        except ValueError as exc:
            db.rollback()
            error = str(exc)
            staff = [p for p in snapshot["staff"] if not p["is_help"]]
            records = list(reversed(snapshot.get("monthly_settings", {}).get("agreed_wish_changes", [])))
        finally:
            db.close()
        person_name = next((p["name"] for p in staff if str(p["id"]) == values["staff"]), "")
        year, number = map(int, month.split("-"))
        days = [date(year, number, n).isoformat() for n in range(1, calendar.monthrange(year, number)[1]+1)]
        from schedule_display import concise_shortages
        calendar_data=agreed_calendar_view(snapshot,base,scoped_days,preview,updated if preview else None,grid if preview else None)
        return render_template("agreed_change.html", calendar_data=calendar_data, month=month, values=values, staff=staff, days=days,
                               person_name=person_name, fingerprint=fingerprint, revision=revision,
                               preview=preview, error=error, changes=changes, warnings=warnings,
                               shortages=shortages, shortage_summary=concise_shortages(shortages), records=records, audit=audit)

    from agreed_record_changes import register_agreed_record_changes
    register_agreed_record_changes(app,connect_db)
