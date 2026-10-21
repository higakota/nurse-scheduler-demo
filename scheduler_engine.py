"""標準ライブラリだけで日別候補を列挙し、月全体の必須条件を探索する。"""
import calendar
import itertools
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from doctor_import import IMPORT_VERSION
from help_limits import nurse_helper_excess, planned_helper_roles

from leave_and_history import trailing_full_days
from meeting_rules import checked_times, check_meeting_overlap
from weekly_rules import build_weekly, work_units, weekly_summary

WORK = {"A", "B", "C", "D", "M", "O"}


def split_rest(pair):
    """有給単独を除き、半日勤務＋半日通常休みかを判定する。"""
    return pair.count("R") == 1 and any(code in WORK or code == "W" for code in pair)



def automatic_half_rest(problem, d, i, pair):
    """本人の半休希望は分散ペナルティから除く。ヘルプの来院区分も対象外。"""
    return (not problem["people"][i]["is_help"] and split_rest(pair)
            and (d, i) not in problem.get("requested_half_rests", set()))


def rest_units(pair):
    if "P" in pair:
        return 2 if "R" in pair else 0
    return pair.count("R")


def agreed_work_halves(monthly):
    """了承出勤を勤務条件として保持する。後で明示した代休はその日の合意を置き換える。"""
    slots={}
    for record in monthly.get("agreed_wish_changes",[]):
        if record.get("cancelled"):
            continue
        key=str(record["staff_id"])+"_"+record["date"]
        slots.setdefault(key,set()).update({"full":(0,1),"am":(0,),"pm":(1,)}.get(record.get("work_period"),()))
        replacement=record.get("replacement_date")
        if replacement:
            slots.pop(str(record["staff_id"])+"_"+replacement,None)
    return slots


def prepare(snapshot, use_help=False, allow_nurse_help=True):
    month = snapshot["month"]
    year, number = map(int, month.split("-"))
    days = [date(year, number, i).isoformat() for i in range(1, calendar.monthrange(year, number)[1] + 1)]
    monthly = snapshot.get("monthly_settings") or {}
    history = snapshot.get("leave_history") or {}
    leaves = history.get("leaves", {})
    wishes = monthly.get("wishes", {})
    closures = monthly.get("closures", {})
    staff = snapshot["staff"]
    people = [p for p in staff if not p["is_help"] or (use_help and (allow_nurse_help or p["role"] == "technician"))]
    regular = [i for i, p in enumerate(people) if not p["is_help"] and p["employment"] != "part"]
    errors, shortages = [], []
    weekly = build_weekly(snapshot, people, days)
    errors.extend(weekly["errors"])
    local_tech = [i for i,p in enumerate(people) if p["role"] == "technician" and not p["is_help"]]
    helper_tech = [i for i,p in enumerate(people) if p["role"] == "technician" and p["is_help"]]
    exceptions = {day for day, allowed in (snapshot.get("technician_exceptions") or {}).items() if allowed is True}
    if not local_tech:
        errors.append("自院の検査技師を登録してください。全日休みの代替条件を判定できません。")
    if not any(not person["is_help"] for person in people):
        errors.append("自院スタッフを登録してください。")
    review = snapshot.get("doctor_plan_reviews") or {}
    if not snapshot.get("doctor_plans") or review.get("version") != IMPORT_VERSION or review.get("data") != snapshot.get("doctor_raw"):
        errors.append("医師予定を最新の方式で確認・保存してください。")
    targets = []
    for i in regular:
        person = people[i]
        try:
            raw = Decimal(str(monthly.get("targets", {}).get(str(person["id"]), "")))
            if not raw.is_finite() or raw < 0 or raw > len(days) or raw * 2 != (raw * 2).to_integral_value():
                raise ValueError
            targets.append(int(raw * 2))
        except (ValueError, InvalidOperation):
            errors.append(person["name"] + "：月の休日日数を0.5日単位で指定してください。")
            targets.append(0)
    agreed_work = agreed_work_halves(monthly)
    meetings = monthly.get("meetings", [])
    ids = {str(p["id"]) for p in staff}
    meeting_people = {}
    for index, meeting in enumerate(meetings):
        day = meeting["date"]
        if day not in days or date.fromisoformat(day).weekday() == 6 or day in closures:
            errors.append(day + "：休診日など、会議の日付を見直してください。")
        if not meeting["participants"]:
            errors.append(day + "：会議の参加者が未設定です。参加者を指定し直してください。")
        if not set(meeting["participants"]) <= ids:
            errors.append(day + "：会議に未登録の参加者がいます。")
        elif not set(meeting["participants"]) <= {str(p["id"]) for p in people}:
            errors.append(day + "：会議の参加者にヘルプが含まれています。来院予定を確認し、ヘルプ込みの再作成を選んでください。")
        try:
            checked_times(meeting.get("start", ""), meeting.get("end", ""))
            for old in meetings[:index]:
                check_meeting_overlap([old], meeting)
        except ValueError as exc:
            errors.append(day + "：" + str(exc))
        if meeting.get("start") and meeting.get("end"):
            for person in staff:
                if str(person["id"]) not in meeting["participants"]:
                    continue
                if person["role"] == "technician":
                    earliest, latest = "13:00", "16:40"
                else:
                    earliest = "13:15" if person["employment"] == "full" else "13:30"
                    latest = "17:00"
                if meeting["start"] < earliest or meeting["end"] > latest:
                    errors.append(day + " " + person["name"] + "：会議時刻が通常の午後勤務時間の範囲外です。時間外勤務の扱いは未確認のため作成を止めています。")
        meeting_people.setdefault(day, set()).update(meeting["participants"])
    requirements, options = [], []
    for day_index, day_text in enumerate(days):
        day = date.fromisoformat(day_text)
        closed = day.weekday() == 6 or day_text in closures
        req = []
        for half in ("am", "pm"):
            if closed or (half == "pm" and day.weekday() == 4):
                req.append((0, 0, 0))
                continue
            names = (snapshot.get("doctor_plans") or {}).get(day_text, {}).get(half)
            if not isinstance(names, list) or not names:
                errors.append(day_text + " " + ("午前" if half == "am" else "午後") + "：担当医・診療の有無を確認してください。")
                req.append((0, 0, 0))
                continue
            c = 2 if len(names) >= 3 else None
            if c is None:
                saved = (snapshot.get("coverage_settings") or {}).get(day_text + "_" + half, {})
                if sorted(saved.get("doctors", [])) == sorted(names) and saved.get("c") in (1, 2):
                    c = saved["c"]
                else:
                    errors.append(day_text + " " + ("午前" if half == "am" else "午後") + "：C番の最低人数を確認・保存してください。")
                    c = 1
            req.append((2, len(names), c))
        requirements.append(tuple(req))
        choices = []
        for person_index, person in enumerate(people):
            key = str(person["id"]) + "_" + day_text
            wish, paid = wishes.get(key, ""), leaves.get(key, "")
            participant = str(person["id"]) in meeting_people.get(day_text, set())
            if paid and closed:
                errors.append(day_text + " " + person["name"] + "：休診日と有給の集計は未確認です。入力を見直してください。")
            if paid and wish and (paid == "full" or wish == "full" or paid == wish):
                errors.append(day_text + " " + person["name"] + "：希望休と有給が同じ時間帯に重なっています。")
            halves = []
            visit = (snapshot.get("help_availability") or {}).get(key, "") if use_help else ""
            for h, half in enumerate(("am", "pm")):
                wanted = wish in ("full", half)
                on_paid = paid in ("full", half)
                meeting = participant and half == "pm"
                can_visit = not person["is_help"] or visit in ("full", half)
                if meeting and (wanted or on_paid or closed or not can_visit):
                    errors.append(day_text + " " + person["name"] + "：会議と希望休・有給・休診日・来院予定が矛盾しています。")
                if closed:
                    halves.append(("R",))
                elif on_paid:
                    halves.append(("P",))
                elif wanted:
                    halves.append(("R",))
                elif meeting and can_visit:
                    halves.append(("M",))
                elif half == "pm" and day.weekday() == 4 and not person["is_help"]:
                    halves.append(("O", "R"))
                elif req[h][0] and can_visit:
                    halves.append(("W", "R"))
                elif person["is_help"] and visit == "full" and can_visit:
                    halves.append(("O", "R"))
                else:
                    halves.append(("R",))
            possible = []
            for a, b in itertools.product(*halves):
                if person["role"] == "technician" and b in ("W", "M", "O") and a not in ("W", "M", "O"):
                    continue
                pair = a + b
                if any(pair[h] not in ("W","M","O") for h in agreed_work.get(key,())):
                    continue
                if (day_index,person_index) in weekly["fixed"] and work_units(pair) != weekly["fixed"][(day_index,person_index)]:
                    continue
                if person_index in weekly["parts"]:
                    k = weekly["parts"].index(person_index)
                    w = weekly["week_for_day"][day_index]
                    if work_units(pair) + weekly["external"][w][k] > weekly["limits"][k]:
                        continue
                possible.append(pair)
            if not possible:
                errors.append(day_text + " " + person["name"] + "：許可された勤務区分がありません。")
            choices.append(tuple(possible))
        options.append(tuple(choices))
        forced_absence = local_tech and not any(any(any(code in ("W", "M", "O") for code in pair) for pair in choices[i]) for i in local_tech)
        if forced_absence and day_text not in exceptions:
            for h, half in enumerate(("午前", "午後")):
                if req[h][0] and not any(any(pair[h] == "W" for pair in choices[i]) for i in helper_tech):
                    shortages.append(dict(date=day_text, half=half, area="他院の検査技師（全日休みの代替）", required=1, available=0, missing=1))
        for h, half in enumerate(("午前", "午後")):
            if not req[h][0]:
                continue
            nurses = [p for i, p in enumerate(people) if p["role"] == "nurse" and any(v[h] == "W" for v in choices[i])]
            tech = sum(p["role"] == "technician" and any(v[h] == "W" for v in choices[i]) for i, p in enumerate(people))
            need = req[h][0] + req[h][1] + max(0, req[h][2] - int(tech))
            for area, required in (("A（受付）", req[h][0]), ("B（診察室）", req[h][1]), ("全配置の看護師合計", need)):
                if len(nurses) < required:
                    shortages.append(dict(date=day_text, half=half, area=area, required=required, available=len(nurses), missing=required-len(nurses)))
            c_need = max(0, req[h][2] - int(tech))
            c_available = sum("C" in p.get("allowed_areas", "ABC") for p in nurses)
            if c_available < c_need:
                shortages.append(dict(date=day_text, half=half, area="検査室を担当できる看護師", required=c_need, available=c_available, missing=c_need-c_available))
            if not any(p["veteran"] for p in nurses):
                shortages.append(dict(date=day_text, half=half, area="診療側のベテラン看護師", required=1, available=0, missing=1))
    tails = []
    attendance_tails = []
    for i, person in enumerate(people):
        # ヘルプの勤務管理は所属院で行う。前月末・連勤は参照しない。
        if person["is_help"]:
            tails.append(0)
            attendance_tails.append(0)
            continue
        raw = history.get("history", {})
        vals = []
        for offset in range(6, 0, -1):
            day = date.fromisoformat(days[0]) - timedelta(days=offset)
            fixed = day.weekday() == 6 or day.isoformat() in snapshot.get("previous_closures", {})
            key = str(person["id"]) + "_" + day.isoformat()
            code = raw.get(key, "")
            if not code and key in weekly["prefix"]:
                code = {0:"rest",1:"am",2:"full"}[weekly["prefix"][key]]
            vals.append("rest" if fixed else code)
        tail = trailing_full_days(vals)
        full_possible = any(pair[0] in ("W","M","O") and pair[1] in ("W","M","O") for pair in options[0][i])
        if tail is None and full_possible:
            errors.append(person["name"] + "：月初の全日勤務を判定するため、前月末勤務を補完してください。")
        tails.append(tail or 0)
        attending = 0
        for value in reversed(vals):
            if value in ("full","am","pm","am_paid","pm_paid"):
                attending += 1
            else:
                break
        attendance_tails.append(attending)
    return dict(month=month, days=days, people=people, regular=regular, targets=tuple(targets), requirements=requirements,
                options=options, requested_half_rests={
                    (d,i) for d,day in enumerate(days) for i,p in enumerate(people)
                    if wishes.get(str(p["id"])+"_"+day) in ("am","pm")
                }, weekly=weekly, local_tech=local_tech, helper_tech=helper_tech, technician_exceptions=exceptions, tails=tuple(tails), attendance_tails=tuple(attendance_tails), errors=list(dict.fromkeys(errors)), shortages=shortages)



def compulsory_six_runs(problem):
    """月公休から6日間の全日勤務が必須と証明できる場合だけ抽出する。"""
    runs=[]
    for k,i in enumerate(problem["regular"]):
        choices=[day[i] for day in problem["options"]]
        if not all(choices):
            continue
        minimum=[min(rest_units(pair) for pair in options) for options in choices]
        slack=problem["targets"][k]-sum(minimum)
        if slack<0:
            continue
        run=problem["tails"][i]
        for d,options in enumerate(choices):
            possible=[pair for pair in options if rest_units(pair)<=minimum[d]+slack]
            forced=bool(possible) and all(all(c in ("W","M","O") for c in pair) for pair in possible)
            run=run+1 if forced else 0
            if run==6:
                end=date.fromisoformat(problem["days"][d])
                runs.append(dict(index=i,name=problem["people"][i]["name"],
                                 start=(end-timedelta(days=5)).isoformat(),end=end.isoformat()))
    return runs


def allocate(problem, day_index, pairs, partial=False):
    people = problem["people"]
    grid = [[a, b] for a, b in pairs]
    absent = not any(any(code in ("W", "M", "O") for code in pairs[i]) for i in problem["local_tech"])
    if not partial and absent and problem["days"][day_index] not in problem["technician_exceptions"]:
        for half in (0, 1):
            if problem["requirements"][day_index][half][0] and not any(pairs[i][half] == "W" for i in problem["helper_tech"]):
                return None
    for half in (0, 1):
        a, b, c = problem["requirements"][day_index][half]
        if not a:
            if any(pair[half] == "W" for pair in pairs):
                return None
            continue
        nurses = [i for i, p in enumerate(people) if p["role"] == "nurse" and pairs[i][half] == "W"]
        techs = [i for i, p in enumerate(people) if p["role"] == "technician" and pairs[i][half] == "W"]
        c_nurses = max(0, c - len(techs))
        if not partial and (len(nurses) < a + b + c_nurses or sum("C" in people[i].get("allowed_areas", "ABC") for i in nurses) < c_nurses or not any(people[i]["veteran"] for i in nurses)):
            return None
        for i in nurses:
            grid[i][half] = "D"
        for i in techs:
            grid[i][half] = "C"
    return tuple("".join(row) for row in grid)


class SearchLimit(Exception):
    pass



def full_run_allowed(problem, i, d, run, maximum):
    limit=min(maximum,problem.get("full_day_limits",[maximum]*len(problem["people"]))[i])
    if run>limit:
        return False
    return not (run==6 and problem.get("six_only_when_compulsory")
                and (i,problem["days"][d]) not in problem.get("compulsory_six_ends",set()))


def verify(problem, grid, allow_shortages=False, max_full_days=6):
    """生成器の選択順を使わず、結果の各制約を再計算する。"""
    if max_full_days not in (5, 6):
        raise ValueError("Unsupported consecutive-day limit")
    errors = []
    if len(grid) != len(problem["days"]):
        return ["作成結果の日数が一致しません。"]
    rest = [0] * len(problem["people"])
    runs = list(problem["tails"])
    for d, rows in enumerate(grid):
        if len(rows) != len(problem["people"]):
            return ["作成結果のスタッフ数が一致しません。"]
        for i, row in enumerate(rows):
            if len(row) != 2 or any(code not in "ABCDMORP" for code in row):
                return ["作成結果の勤務記号が不正です。"]
            abstract = "".join("W" if code in "ABCD" else code for code in row)
            person = problem["people"][i]
            if abstract not in problem["options"][d][i]:
                if person["is_help"] and any(code in WORK for code in row):
                    errors.append(problem["days"][d]+" "+person["name"]+"：表の出勤時間がヘルプの来院予定に入っていません。編集内容を確認・保存して来院予定へ反映してください。")
                else:
                    errors.append(problem["days"][d] + "：希望休・有給・会議・来院予定・職種の条件違反です。")
            if person["role"] == "technician" and any(code in "ABD" for code in row):
                errors.append("検査技師を検査室以外に配置しています。")
            if person["role"] == "nurse" and "C" not in person.get("allowed_areas", "ABC") and "C" in row:
                errors.append(person["name"] + "：検査室を担当できないスタッフに検査室を指定しています。")
            # 休みと有給の算入は、勤務表の記号から再計算する。
            if "P" in row:
                rest[i] += 2 if "R" in row else 0
            else:
                rest[i] += sum(code == "R" for code in row)
            runs[i] = runs[i] + 1 if not person["is_help"] and all(code in WORK for code in row) else 0
            limit=min(max_full_days,problem.get("full_day_limits",[max_full_days]*len(problem["people"]))[i])
            if not full_run_allowed(problem,i,d,runs[i],max_full_days):
                effective=limit if runs[i]>limit else 5
                errors.append("前月末を含む全日勤務が" + str(effective) + "連勤を超えています。")
        absent = not any(any(code in WORK for code in rows[i]) for i in problem["local_tech"])
        if not allow_shortages and absent and problem["days"][d] not in problem["technician_exceptions"]:
            for half in (0,1):
                if problem["requirements"][d][half][0] and not any(rows[i][half] == "C" for i in problem["helper_tech"]):
                    errors.append(problem["days"][d] + "：自院の検査技師が全日休みですが、他院の検査技師を配置していません。看護師のみの例外は未承認です。")
        for half in (0, 1):
            need_a, need_b, need_c = problem["requirements"][d][half]
            codes = [row[half] for row in rows]
            if not need_a:
                if any(code in "ABCD" for code in codes):
                    errors.append("休診時間帯に診療配置があります。")
                continue
            nurses = [i for i, p in enumerate(problem["people"]) if p["role"] == "nurse"]
            tech_present = sum(p["role"] == "technician" and rows[i][half] == "C" for i,p in enumerate(problem["people"]))
            required_nurses = need_a + need_b + max(0, need_c-int(tech_present))
            available_nurses = sum(rows[i][half] in "ABCD" for i in nurses)
            if not allow_shortages and available_nurses < required_nurses:
                errors.append("診療に必要な看護師の合計人数が不足しています。")
            c_available = sum(rows[i][half] in "ABCD" and "C" in problem["people"][i].get("allowed_areas", "ABC") for i in nurses)
            if not allow_shortages and c_available < max(0, need_c-int(tech_present)):
                errors.append("検査室を担当できる看護師が不足しています。")
            if not allow_shortages and not any(problem["people"][i]["veteran"] and rows[i][half] in "ABCD" for i in nurses):
                errors.append("診療側のベテラン看護師が不足しています。")
    for k, i in enumerate(problem["regular"]):
        if rest[i] != problem["targets"][k]:
            errors.append(problem["people"][i]["name"] + "：指定休日日数と一致しません。")
    weekly = problem["weekly"]
    for w,week in enumerate(weekly["weeks"]):
        for k,i in enumerate(weekly["parts"]):
            actual = weekly["external"][w][k] + sum(sum(code in WORK for code in grid[d][i]) for d in week["indices"])
            if actual > weekly["limits"][k]:
                errors.append(problem["people"][i]["name"] + " " + week["start"] + "の週：前後月を含む非常勤の週勤務上限を超えています。")
    return list(dict.fromkeys(errors))



def daily_shortages_from_options(problem, d):
    """その日に勤務可能な人数の上限から、確実に不足する職種・時間帯を調べる。"""
    rows=[]
    people=problem["people"]
    choices=problem["options"][d]
    absent=not any(any(any(c in "WMO" for c in pair) for pair in choices[i]) for i in problem["local_tech"])
    def add(half,area,required,available):
        if required>available:
            rows.append(dict(date=problem["days"][d],half=half,area=area,
                             required=required,available=available,missing=required-available))
    for h,label in enumerate(("午前","午後")):
        a,b,c=problem["requirements"][d][h]
        if not a:
            continue
        possible=[i for i in range(len(people)) if any(pair[h]=="W" for pair in choices[i])]
        nurses=[i for i in possible if people[i]["role"]=="nurse"]
        tech=sum(people[i]["role"]=="technician" for i in possible)
        add(label,"診療の看護師合計",a+b+max(0,c-tech),len(nurses))
        add(label,"検査室を担当できる看護師",max(0,c-tech),
            sum("C" in people[i].get("allowed_areas","ABC") for i in nurses))
        add(label,"診療側のベテラン看護師（看護師人数の内数）",1,
            int(any(people[i]["veteran"] for i in nurses)))
        if absent and problem["days"][d] not in problem["technician_exceptions"]:
            add(label,"他院の検査技師（C番として計上）",1,
                int(any(i in possible for i in problem["helper_tech"])))
    from schedule_display import grouped_shortages
    grouped=grouped_shortages(rows,problem,[])
    for row in grouped:
        if row["area"]=="検査技師（C番として計上）":
            row["area"]="他院の検査技師（C番として計上）"
    return grouped


def _generate(snapshot, use_help=False, seconds=10, allow_nurse_help=True, partial=False, draft_max_full_days=5, fixed_regular=None):
    problem = prepare(snapshot, use_help, allow_nurse_help)
    mandatory=compulsory_six_runs(problem) if draft_max_full_days==5 and not problem["errors"] else []
    permitted={run["index"] for run in mandatory}
    problem["full_day_limits"]=tuple(6 if i in permitted else draft_max_full_days for i in range(len(problem["people"])))
    problem["six_only_when_compulsory"]=draft_max_full_days==5
    problem["compulsory_six_ends"]={(r["index"],r["end"]) for r in mandatory}
    problem["compulsory_six_runs"]=mandatory
    draft_max_full_days=max(problem["full_day_limits"],default=draft_max_full_days)
    base = dict(problem=problem, grid=None, messages=[], shortages=problem["shortages"])
    if problem["errors"]:
        return dict(base, status="input_error", messages=problem["errors"])
    if use_help:
        for d, day in enumerate(problem["days"]):
            choices = list(problem["options"][d])
            for i, person in enumerate(problem["people"]):
                if not person["is_help"] or snapshot.get("help_availability", {}).get(str(person["id"]) + "_" + day) != "full":
                    continue
                full = tuple(pair for pair in choices[i] if all(code in ("W", "M", "O") for code in pair))
                if full:
                    # 来院OKの全日を使う。余剰人数を理由に半日だけには切り詰めない。
                    choices[i] = tuple(pair for pair in choices[i] if pair in full or not any(code in ("W", "M", "O") for code in pair))
            problem["options"][d] = tuple(choices)
    commitments=snapshot.get("fixed_help_commitments",{})
    if commitments:
        for d,day in enumerate(problem["days"]):
            choices=list(problem["options"][d])
            for i,person in enumerate(problem["people"]):
                key=str(person["id"])+"_"+day
                if not person["is_help"] or key not in commitments:
                    continue
                pair=commitments[key]
                abstract="".join("W" if code in "ABCD" else code for code in pair)
                if abstract not in choices[i]:
                    return dict(base,status="input_error",messages=[
                        day+" "+person["name"]+"：依頼済みの勤務と現在の来院予定・職種等が一致しません。ヘルプの予定を確認してください。"])
                choices[i]=(abstract,)
            problem["options"][d]=tuple(choices)
    if fixed_regular is not None:
        for d, day in enumerate(problem["days"]):
            choices = list(problem["options"][d])
            for i, person in enumerate(problem["people"]):
                if person["is_help"]:
                    continue
                pair = fixed_regular.get((day, str(person["id"])))
                abstract = "".join("W" if code in "ABCD" else code for code in (pair or ""))
                if abstract not in choices[i]:
                    return dict(base, status="input_error", messages=[
                        day + " " + person["name"] + "：元の仮表と現在の入力条件が一致しません。自院の仮表を確認してください。"])
                choices[i] = (abstract,)
            problem["options"][d] = tuple(choices)
    if partial:
        issues = []
        for k, i in enumerate(problem["regular"]):
            if all(problem["options"][d][i] for d in range(len(problem["days"]))):
                minimum = sum(min(rest_units(pair) for pair in problem["options"][d][i]) for d in range(len(problem["days"])))
                maximum = sum(max(rest_units(pair) for pair in problem["options"][d][i]) for d in range(len(problem["days"])))
                if not minimum <= problem["targets"][k] <= maximum:
                    issues.append(problem["people"][i]["name"] + "：希望休・有給・休診日・会議などから可能な休日日数は"
                                  + str(minimum / 2) + "～" + str(maximum / 2)
                                  + "日ですが、指定は" + str(problem["targets"][k] / 2)
                                  + "日です。希望休等は変更していません。休日日数と入力内容を確認してください。")
        if issues:
            return dict(base, status="input_error", messages=issues)
    if partial:
        return _draft_by_person(problem, seconds, max_full_days=draft_max_full_days)
    if problem["shortages"] and not partial:
        affected={row["date"] for row in problem["shortages"]}
        rows=[row for d,day in enumerate(problem["days"]) if day in affected for row in daily_shortages_from_options(problem,d)]
        rows=rows or problem["shortages"]
        from schedule_display import concise_shortages
        messages=[day["date"]+" "+item+"。" for day in concise_shortages(rows) for item in day["items"]]
        return dict(base,status="infeasible",shortages=rows,messages=messages)
    started = time.monotonic()
    deadline = started + seconds
    n = len(problem["people"])
    patterns, cache = [], {}
    try:
        for d, choices in enumerate(problem["options"]):
            key = (choices, problem["requirements"][d], problem["days"][d] in problem["technician_exceptions"])
            if key not in cache:
                candidates = []
                candidate_indices = {}
                cached_count = sum(len(items) for items in cache.values())
                for count, pairs in enumerate(itertools.product(*choices)):
                    if count % 64 == 0 and time.monotonic() >= deadline:
                        raise SearchLimit
                    grid = allocate(problem, d, pairs, partial=partial)
                    if grid is None:
                        continue
                    rests = tuple(rest_units(pair) for pair in pairs)
                    full = tuple(all(code in ("W","M","O") for code in pair) for pair in pairs)
                    attend = tuple(any(code in ("W","M","O") for code in pair) for pair in pairs)
                    help_used = (
                        max(0,planned_helper_roles(problem,d,grid)[0]-1) if partial else nurse_helper_excess(problem['people'],pairs),
                        sum(sum(code in ("W","M","O") for code in pairs[i]) for i,p in enumerate(problem["people"]) if p["is_help"] and p["role"] == "nurse"),
                        sum(sum(code in ("W","M","O") for code in pairs[i]) for i,p in enumerate(problem["people"]) if p["is_help"]))
                    candidate = (grid, tuple(rests[i] for i in problem["regular"]), full, attend, help_used,
                                       tuple(work_units(pairs[i]) for i in problem["weekly"]["parts"]),
                                       sum(r["missing"] for r in draft_shortages(problem, d, grid)) if partial else 0)
                    state_key = candidate[1:4] + (candidate[5],)
                    if partial and state_key in candidate_indices:
                        index = candidate_indices[state_key]
                        if (candidate[6],candidate[4]) < (candidates[index][6],candidates[index][4]):
                            candidates[index] = candidate
                        continue
                    if len(candidates) + cached_count >= (250000 if partial else 50000):
                        raise SearchLimit
                    candidate_indices[state_key] = len(candidates)
                    candidates.append(candidate)
                cache[key] = candidates
            patterns.append(cache[key])
            if not patterns[-1]:
                rows=daily_shortages_from_options(problem,d)
                from schedule_display import concise_shortages
                summary=concise_shortages(rows)
                messages=[day["date"]+" "+item+"。" for day in summary for item in day["items"]]
                if not messages:
                    messages=[problem["days"][d]+"：午前・午後を同時に担当できる配置がありません。自院の勤務かヘルプの来院予定を調整してください。"]
                return dict(base,status="infeasible",shortages=rows,messages=messages)
        width = len(problem["regular"])
        low = [[0]*width for _ in range(len(patterns)+1)]
        high = [[0]*width for _ in range(len(patterns)+1)]
        for d in range(len(patterns)-1, -1, -1):
            for k in range(width):
                low[d][k] = low[d+1][k] + min(p[1][k] for p in patterns[d])
                high[d][k] = high[d+1][k] + max(p[1][k] for p in patterns[d])
        total_low = [0]*(len(patterns)+1)
        total_high = [0]*(len(patterns)+1)
        local_low = []
        local_high = []
        for d in range(len(patterns)):
            local_low.append(tuple(min(p[1][k] for p in patterns[d]) for k in range(width)))
            local_high.append(tuple(max(p[1][k] for p in patterns[d]) for k in range(width)))
        for d in range(len(patterns)-1,-1,-1):
            total_low[d] = total_low[d+1] + min(sum(p[1]) for p in patterns[d])
            total_high[d] = total_high[d+1] + max(sum(p[1]) for p in patterns[d])
        weekly = problem["weekly"]
        part_count = len(weekly["parts"])
        week_min = [[0]*part_count for _ in range(len(patterns)+1)]
        week_max = [[0]*part_count for _ in range(len(patterns)+1)]
        rest_minus_part = [0]*(len(patterns)+1)
        for d in range(len(patterns)-1,-1,-1):
            same_week = d+1 < len(patterns) and weekly["week_for_day"][d] == weekly["week_for_day"][d+1]
            for k in range(part_count):
                week_min[d][k] = min(p[5][k] for p in patterns[d]) + (week_min[d+1][k] if same_week else 0)
                week_max[d][k] = max(p[5][k] for p in patterns[d]) + (week_max[d+1][k] if same_week else 0)
            rest_minus_part[d] = rest_minus_part[d+1] + max(sum(p[1])-sum(p[5]) for p in patterns[d])
        future_part_capacity = [0]*(len(weekly["weeks"])+1)
        for w in range(len(weekly["weeks"])-1,-1,-1):
            first_day = weekly["weeks"][w]["indices"][0]
            future_part_capacity[w] = future_part_capacity[w+1] + sum(min(weekly["limits"][k]-weekly["external"][w][k],week_max[first_day][k]) for k in range(part_count))
        answer = None
        def search(strict, limit, whole_rest_first=False, limit_split=False):
            failed = set()
            path = []
            half_caps = tuple(max(problem["targets"][k] % 2,
                sum(all(automatic_half_rest(problem,d,i,pair) for pair in choices[i])
                    for d,choices in enumerate(problem["options"])))
                for k,i in enumerate(problem["regular"]))
            def visit(d, remaining, runs, attendance, week_used, half_used):
                nonlocal answer
                if time.monotonic() >= limit or len(failed) > 100000:
                    raise SearchLimit
                if any(not low[d][k] <= remaining[k] <= high[d][k] for k in range(width)) or not total_low[d] <= sum(remaining) <= total_high[d]:
                    return False
                if d == len(patterns):
                    answer = list(path)
                    return True
                w = weekly["week_for_day"][d]
                if d == 0 or weekly["week_for_day"][d-1] != w:
                    week_used = tuple(0 for _ in range(part_count))
                if any(week_used[k] + weekly["external"][w][k] + week_min[d][k] > weekly["limits"][k] for k in range(part_count)):
                    return False
                available_part = future_part_capacity[w+1] + sum(min(weekly["limits"][k]-weekly["external"][w][k]-week_used[k],week_max[d][k]) for k in range(part_count))
                # 各日 rest - part_work <= 最大値。週上限から月末までの part_work の上限を合わせる。
                if sum(remaining) > rest_minus_part[d] + available_part:
                    return False
                state = (d, remaining, runs, attendance if strict else (), week_used, half_used if limit_split else ())
                if state in failed:
                    return False
                desired = tuple(local_low[d][k] + (remaining[k]-low[d][k]) / max(1,high[d][k]-low[d][k]) * (local_high[d][k]-local_low[d][k]) for k in range(width))
                ordered = sorted(patterns[d], key=lambda p: (
                    p[6],
                    sum(p[2][i] and runs[i] >= 5 for i in range(n)),
                    sum(p[3][i] and attendance[i] >= 6 for i in range(n)),
                    sum(automatic_half_rest(problem,d,i,pair) for i,pair in enumerate(p[0])) if whole_rest_first else 0,
                    p[4],
                    sum((p[1][k] - desired[k])**2 for k in range(width)),
                    sum(automatic_half_rest(problem,d,i,pair) for i,pair in enumerate(p[0])),
                    -sum(p[5])))
                for grid, rest, full, attend, _, part_work, _ in ordered:
                    if time.monotonic() >= limit:
                        raise SearchLimit
                    new_runs = tuple(runs[i]+1 if full[i] and not problem["people"][i]["is_help"] else 0 for i in range(n))
                    new_attendance = tuple(attendance[i]+1 if attend[i] and not problem["people"][i]["is_help"] else 0 for i in range(n))
                    if any(not full_run_allowed(problem,i,d,run,draft_max_full_days) for i,run in enumerate(new_runs)) or (strict and max(new_attendance, default=0) > 6):
                        continue
                    new_week_used = tuple(week_used[k]+part_work[k] for k in range(part_count))
                    if any(new_week_used[k] + weekly["external"][w][k] > weekly["limits"][k] for k in range(part_count)):
                        continue
                    new_halves = tuple(half_used[k] + int(automatic_half_rest(problem,d,i,grid[i]))
                                       for k,i in enumerate(problem["regular"]))
                    if limit_split and any(value > cap for value,cap in zip(new_halves,half_caps)):
                        continue
                    new_remaining = tuple(remaining[k]-rest[k] for k in range(width))
                    path.append(grid)
                    if visit(d+1, new_remaining, new_runs, new_attendance, new_week_used, new_halves):
                        return True
                    path.pop()
                failed.add(state)
                return False
            return visit(0, problem["targets"], problem["tails"], problem["attendance_tails"], tuple(0 for _ in range(part_count)), tuple(0 for _ in range(width)))
        try:
            search(True, min(deadline, time.monotonic() + max(0, deadline-time.monotonic())*0.15), whole_rest_first=True, limit_split=True)
        except SearchLimit:
            pass
        if answer is None:
            try:
                search(True, min(deadline, time.monotonic() + max(0, deadline-time.monotonic())*0.65))
            except SearchLimit:
                pass
        if answer is None:
            search(False, deadline)
        if answer is None:
            return dict(base, status="infeasible", messages=["常勤の指定休日日数・非常勤の週上限・月境界の連勤上限を含む全条件を同時に満たす勤務表がありません。原因を特定の日・配置の不足人数には分解できていません。"])
        validation = verify(problem, answer, allow_shortages=partial, max_full_days=draft_max_full_days)
        if validation:
            return dict(base, status="unknown", messages=["結果の再検証に失敗したため保存しません。"] + validation)
        if partial:
            shortages = [row for d, rows in enumerate(answer) for row in draft_shortages(problem, d, rows)]
            return dict(base, status="draft", grid=answer, shortages=shortages,
                        messages=["ヘルプ相談用の仮表です。希望休・有給・公休・週上限・全日6連勤上限を再検証しました。診療人数・ベテラン・検査技師の不足は未解決です。",
                                  "不足はこの仮配置での人数です。月全体で不足が最小になることや、この日にヘルプが必須であることは保証しません。ベテラン・検査技師の条件は配置人数と重複するため、単純に合計しないでください。"])
        from schedule_improvement import improve_jointly
        answer = improve_jointly(problem, answer, max_full_days=draft_max_full_days, seconds=min(1, max(0, seconds*0.1)))
        answer = consolidate_rest_days(problem, answer, max_full_days=draft_max_full_days, seconds=min(2, max(0.1, seconds*0.15)))
        approved = [problem["days"][d] for d,rows in enumerate(answer)
                    if problem["days"][d] in problem["technician_exceptions"]
                    and any(problem["requirements"][d][h][0] for h in (0,1))
                    and not any(any(code in WORK for code in rows[i]) for i in problem["local_tech"])
                    and any(problem["requirements"][d][h][0] and not any(rows[i][h] == "C" for i in problem["helper_tech"]) for h in (0,1))]
        notes = ["希望休・休日日数・最低人数・ベテラン・会議・来院予定と、自院スタッフの全日" + str(draft_max_full_days) + "連勤上限を再検証しました。", "本人が希望していない半休の分散を避け、丸1日の休みを優先しています。希望した半休は維持し、全日休みの最大化は保証しません。"]
        notes.append("半日勤務を含む6連勤以内を優先して探索しますが、最適性は保証しません。月境界の半日勤務を含む連続出勤の希望評価は、履歴が直前6日分のため限定的です。")
        if weekly["parts"]:
            notes.append("非常勤は月曜〜日曜の週上限を検証しました。半日勤務は0.5日、有給は勤務日数に含めません。常勤の公休を守ったうえで上限ちょうどを優先しますが、最適性は保証しません。")
            if any(days for week in weekly["pending"] for days in week):
                notes.append("月末週の翌月未定日は休みとみなしていません。週ごとの残り枠を確認し、翌月作成時も前月の実績を入力して同じ上限を守ってください。")
        if approved:
            notes.append("明示された看護師のみ対応の例外を使用した日：" + "、".join(approved))
        if use_help:
            notes.append("ヘルプの勤務管理は所属院で行います。このアプリでは公休・週勤務日数・連勤を調整せず、承諾済みの来院予定だけを参照して配置します。")
        return dict(base, status="success", grid=answer, messages=notes)
    except SearchLimit:
        return dict(base, status="unknown", messages=["探索時間または探索量の上限に達し、勤務表を見つけられませんでした。条件が矛盾しているとは断定できません。入力を見直すか、再試行してください。"])


def finish_policy(result, limit):
    result["experimental"]=False
    result["max_full_days"]=max(result.get("problem",{}).get("full_day_limits",[limit]),default=limit)
    if result.get("grid") is not None:
        result["six_day_runs"]=six_day_runs(result["problem"],result["grid"])
        result["messages"].append("原則5連勤以内で、人員不足時はヘルプを先に検討します。公休・希望休・有給等から本人の6連勤が必須の場合だけ、その人に6連勤を許容します。7連勤以上は禁止です。")
        for run in result["problem"].get("compulsory_six_runs",[]):
            result["messages"].append(run["name"]+"："+run["start"]+"～"+run["end"]+"は、公休・希望休・有給等から6連勤が必須のため許容しました。ヘルプでは本人の休日日数を変えられないため、この条件で作成を続けています。")
    return result


def rest_plan_key(result):
    """6連勤の回避、希望外の半休の回避、ヘルプ使用の抑制の順に比較する。"""
    problem,grid=result["problem"],result["grid"]
    halves=sum(automatic_half_rest(problem,d,i,pair) for d,rows in enumerate(grid) for i,pair in enumerate(rows))
    helpers=sum(sum(code in WORK for code in pair) for rows in grid for person,pair in zip(problem["people"],rows) if person["is_help"])
    return len(six_day_runs(problem,grid)),halves,helpers


def help_plan_key(result):
    key=rest_plan_key(result)
    repeated_nurses=sum(nurse_helper_excess(result["problem"]["people"],rows) for rows in result["grid"])
    return key[:2]+(repeated_nurses,key[2])


def generate(snapshot, use_help=False, seconds=10, allow_six=False):
    """全日休みを確保できるなら承諾済みヘルプの案も比較する。6連勤への緩和は従来どおり。"""
    started=time.monotonic()
    stages=[(False,True)]
    if use_help:
        stages.append((True,False))
        if any(p["is_help"] and p["role"]=="nurse" for p in snapshot["staff"]):
            stages.append((True,True))
    fixed=snapshot.get("fixed_help_commitments",{})
    locked_ids={key.partition("_")[0] for key,pair in fixed.items() if any(c in WORK for c in pair)}
    locked_nurse=any(str(p["id"]) in locked_ids and p["role"]=="nurse" for p in snapshot["staff"])
    if locked_ids:
        stages=[stage for stage in stages if stage[0] and (stage[1] or not locked_nurse)]
    result=None
    for limit in ((5,6) if allow_six else (5,)):
        best=None
        own_halves=None
        for index,(include_help,include_nurse) in enumerate(stages):
            remaining=max(0,seconds-(time.monotonic()-started))
            budget=remaining/(len(stages)-index)
            if limit==5 and allow_six:
                budget*=0.65
            result=_generate(snapshot,include_help,budget,allow_nurse_help=include_nurse,
                             draft_max_full_days=limit)
            finish_policy(result,limit)
            if result["status"]!="success":
                continue
            key=rest_plan_key(result)
            if not include_help:
                own_halves=key[1]
            if best is None or help_plan_key(result)<help_plan_key(best):
                best=result
            # 希望外の半休も6連勤もない案なら、追加のヘルプを探す必要はない。
            if rest_plan_key(best)[:2]==(0,0):
                break
        if best is not None:
            six,halves,helper_units=rest_plan_key(best)
            best["messages"].append("本人が希望していない半休："+str(halves)+"回。半休の回避をヘルプ使用の抑制より優先して比較しました。最適性は保証しません。")
            best["messages"].append("6連勤と希望外の半休が同じ案では、ヘルプを少なく使う方を優先しています。最少人数を保証するものではありません。")
            if helper_units:
                best["messages"].append("承諾済みの来院予定からヘルプを配置しました。未承諾の人・時間帯は使っていません。")
            else:
                best["messages"].append("採用した勤務表ではヘルプを使っていません。")
            if own_halves is not None and halves<own_halves:
                best["messages"].append("ヘルプも候補に含めて再検討し、希望外の半休を"+str(own_halves)+"回から"+str(halves)+"回に減らしました。希望した半休・公休日数は維持しています。")
            if halves:
                best["messages"].append("希望外の半休が残っています。公休日数の端数等で必要な場合もあり、今回の探索で全日休みにまとめられないことが確定したわけではありません。必要に応じてヘルプの来院予定を追加して再作成してください。")
            if limit==6:
                best["messages"].append("ヘルプ確保が難しい場合の最終案として6連勤まで許容しました。希望休・公休等は変更していません。")
            return best
    if not allow_six and result["status"] in ("infeasible","unknown"):
        result["messages"].append("人員不足を補うための6連勤は自動採用していません。ヘルプを先に相談してください。本人の公休等から必須の6連勤は既に許容して探索しています。")
    return result


def draft_shortages(problem, d, rows):
    """仮配置から不足と資格条件を再計算する。"""
    result = []
    people = problem["people"]
    absent = not any(any(code in WORK for code in rows[i]) for i in problem["local_tech"])
    for half, label in enumerate(("午前", "午後")):
        need = problem["requirements"][d][half]
        if not need[0]:
            continue
        def add(area, required, available):
            if required > available:
                result.append(dict(date=problem["days"][d], half=label, area=area,
                                   required=required, available=available, missing=required-available))
        tech_present = sum(row[half] == "C" and p["role"] == "technician" for p,row in zip(people,rows))
        available_nurses = sum(p["role"] == "nurse" and row[half] in "ABCD" for p,row in zip(people,rows))
        required_nurses = need[0]+need[1]+max(0,need[2]-int(tech_present))
        add("診療の看護師合計", required_nurses, available_nurses)
        add("検査室を担当できる看護師", max(0, need[2]-int(tech_present)),
            sum(p["role"] == "nurse" and row[half] in "ABCD" and "C" in p.get("allowed_areas", "ABC") for p,row in zip(people,rows)))
        add("診療側のベテラン看護師（看護師人数の内数）", 1,
            int(any(p["role"] == "nurse" and p["veteran"] and row[half] in "ABCD" for p,row in zip(people,rows))))
        if absent and problem["days"][d] not in problem["technician_exceptions"]:
            add("他院の検査技師（C番として計上）", 1,
                int(any(rows[i][half] == "C" for i in problem["helper_tech"])))
    return result


def six_day_runs(problem, grid):
    runs = []
    for i, person in enumerate(problem["people"]):
        if person["is_help"]:
            continue
        run = problem["tails"][i]
        for d, rows in enumerate(grid):
            run = run+1 if all(code in WORK for code in rows[i]) else 0
            if run == 6:
                end = date.fromisoformat(problem["days"][d])
                runs.append(dict(name=person["name"], start=(end-timedelta(days=5)).isoformat(), end=end.isoformat()))
    return runs


def preference_metrics(result):
    if result.get("grid") is None:
        return None
    problem,grid=result["problem"],result["grid"]
    shortages=[0,0,0]
    for d,rows in enumerate(grid):
        for row in draft_shortages(problem,d,rows):
            category=1 if "検査技師" in row["area"] else (2 if "ベテラン" in row["area"] else 0)
            shortages[category]+=row["missing"]
    halves=sum(automatic_half_rest(problem,d,i,pair) for d,rows in enumerate(grid) for i,pair in enumerate(rows))
    return shortages,halves,len(six_day_runs(problem,grid))


def prefer_five(snapshot, use_help=False, seconds=10, allow_nurse_help=True, partial=False, allow_six=False):
    """半休が減るだけでは6連勤を採用しない。6連勤は明示された最終案に限る。"""
    started=time.monotonic()
    first=_generate(snapshot,use_help,seconds*(0.4 if allow_six else 1),
                    allow_nurse_help=allow_nurse_help,partial=partial,draft_max_full_days=5)
    finish_policy(first,5)
    result=first
    if allow_six and first["status"] in ("infeasible","unknown"):
        result=_generate(snapshot,use_help,max(0,seconds-(time.monotonic()-started)),
                         allow_nurse_help=allow_nurse_help,partial=partial,draft_max_full_days=6)
        finish_policy(result,6)
        if result.get("grid") is not None:
            result["messages"].append("ヘルプ確保が難しい場合の最終案です。全日6連勤になるスタッフ・期間を確認してください。")
            if first["status"]=="unknown":
                result["messages"].append("5連勤以内の探索は上限に達したため、6連勤が不可避とは断定できません。")
    elif not allow_six and result["status"] in ("infeasible","unknown"):
        result["messages"].append("本人の公休等から必須の6連勤だけは許容して探索しています。人員不足はヘルプを先に相談してください。")
    return result


def generate_draft(snapshot, seconds=10, experimental_six=False, allow_six=False):
    """通常の相談用仮表は5連勤以内。旧引数は明示的な最終案との互換用。"""
    return prefer_five(snapshot,seconds=seconds,partial=True,allow_six=allow_six or experimental_six)


def _draft_by_person(problem, seconds, max_full_days=5):
    """仮表は診療の不足を許容するため、個人の必須条件を個別に探索できる。"""
    deadline = time.monotonic() + seconds
    people, days, weekly = problem["people"], problem["days"], problem["weekly"]
    grid = [["RR" for _ in people] for _ in days]
    regular_targets = dict(zip(problem["regular"], problem["targets"]))
    base = dict(problem=problem, grid=None, shortages=problem["shortages"], messages=[])
    order = sorted(range(len(people)), key=lambda i: (i not in regular_targets, people[i]["role"] != "technician", not people[i]["veteran"]))
    try:
        for i in order:
            choices = [row[i] for row in problem["options"]]
            low, high = [0] * (len(days)+1), [0] * (len(days)+1)
            for d in range(len(days)-1, -1, -1):
                low[d] = low[d+1] + min(rest_units(pair) for pair in choices[d])
                high[d] = high[d+1] + max(rest_units(pair) for pair in choices[d])
            part = weekly["parts"].index(i) if i in weekly["parts"] else None
            target = regular_targets.get(i)
            def solve(strict, limit):
                failed, path = set(), []
                def visit(d, remaining, run, attendance, used):
                    if time.monotonic() >= limit or len(failed) > 200000:
                        raise SearchLimit
                    if remaining is not None and not low[d] <= remaining <= high[d]:
                        return None
                    if d == len(days):
                        return list(path)
                    w = weekly["week_for_day"][d]
                    if d == 0 or weekly["week_for_day"][d-1] != w:
                        used = 0
                    state = (d, remaining, run, attendance if strict else 0, used)
                    if state in failed:
                        return None
                    def rank(pair):
                        benefit = 0
                        for h, code in enumerate(pair):
                            if code != "W":
                                continue
                            need_a, need_b, need_c = problem["requirements"][d][h]
                            nurse_count = sum(people[j]["role"] == "nurse" and grid[d][j][h] == "W" for j in range(len(people)) if j != i)
                            tech_present = sum(people[j]["role"] == "technician" and grid[d][j][h] == "W" for j in range(len(people)) if j != i)
                            if people[i]["role"] == "technician":
                                benefit += int(need_c > 0 and not tech_present)
                            else:
                                benefit += int(nurse_count < need_a + need_b + max(0, need_c-int(tech_present)))
                                if people[i]["veteran"] and not any(people[j]["veteran"] and grid[d][j][h] == "W" for j in range(len(people)) if j != i):
                                    benefit += 1
                        desired = 0 if remaining is None else (remaining-low[d]) / max(1, high[d]-low[d])
                        rests = rest_units(pair)
                        minimum = min(rest_units(v) for v in choices[d])
                        maximum = max(rest_units(v) for v in choices[d])
                        return (int(run >= 5 and all(code in ("W","M","O") for code in pair)),
                                int(attendance >= 6 and work_units(pair) > 0),
                                int(automatic_half_rest(problem,d,i,pair)), -benefit,
                                work_units(pair) if people[i]["is_help"] else 0,
                                (rests-(minimum+desired*(maximum-minimum)))**2 if remaining is not None else 0,
                                -work_units(pair))
                    for pair in sorted(choices[d], key=rank):
                        full = all(code in ("W", "M", "O") for code in pair)
                        new_run = run+1 if full and not people[i]["is_help"] else 0
                        new_attendance = attendance+1 if work_units(pair) and not people[i]["is_help"] else 0
                        if not full_run_allowed(problem,i,d,new_run,max_full_days) or (strict and new_attendance > 6):
                            continue
                        new_used = used+work_units(pair) if part is not None else 0
                        if part is not None and new_used+weekly["external"][w][part] > weekly["limits"][part]:
                            continue
                        path.append(pair)
                        answer = visit(d+1, remaining-rest_units(pair) if remaining is not None else None,
                                       new_run, new_attendance, new_used)
                        if answer is not None:
                            return answer
                        path.pop()
                    failed.add(state)
                    return None
                return visit(0, target, problem["tails"][i], problem["attendance_tails"][i], 0)
            answer = None
            try:
                answer = solve(True, min(deadline, time.monotonic()+max(0, deadline-time.monotonic())*0.25))
            except SearchLimit:
                pass
            if answer is None:
                answer = solve(False, deadline)
            if answer is None:
                if target is not None:
                    slack = target-low[0]
                    forced_run = 0
                    for d in range(len(days)):
                        minimum = min(rest_units(pair) for pair in choices[d])
                        possible = [pair for pair in choices[d] if rest_units(pair) <= minimum+slack]
                        forced_full = possible and all(all(code in ("W", "M", "O") for code in pair) for pair in possible)
                        forced_run = forced_run+1 if forced_full else 0
                        if forced_run > max_full_days:
                            return dict(base, status="infeasible", messages=[
                                people[i]["name"] + "：指定公休" + str(target/2) + "日と現在の希望休・有給等を守ると、"
                                + days[d-max_full_days] + "～" + days[d] + "の" + str(max_full_days+1) + "日間がすべて全日勤務になります。全日勤務は最大" + str(max_full_days) + "連勤のため作成できません。",
                                "この期間に半日勤務や休みを入れる余地を作れるか、公休日数・希望休・有給等の入力を確認してください。条件は自動変更していません。"])
                return dict(base, status="infeasible", messages=[people[i]["name"] + "：公休・週上限・全日連勤上限等を同時に守れる勤務がありません。入力条件を確認してください。"])
            for d, pair in enumerate(answer):
                grid[d][i] = pair
        allocated = [allocate(problem, d, pairs, partial=True) for d, pairs in enumerate(grid)]
        errors = verify(problem, allocated, allow_shortages=True, max_full_days=max_full_days)
        if errors:
            return dict(base, status="unknown", messages=["仮表の再検証に失敗しました。"] + errors)
        from schedule_improvement import improve_jointly
        allocated = improve_jointly(problem, allocated, allow_shortages=True, max_full_days=max_full_days,
                                    seconds=min(2, max(0, seconds*0.25)))
        allocated = consolidate_rest_days(problem, allocated, allow_shortages=True, max_full_days=max_full_days, prefer_whole_rest=True,
                                          seconds=min(2, max(0.1, seconds*0.15)))
        allocated = improve_jointly(problem, allocated, allow_shortages=True, max_full_days=max_full_days,
                                    seconds=min(1, max(0, seconds*0.1)))
        shortages = [row for d, rows in enumerate(allocated) for row in draft_shortages(problem, d, rows)]
        six_day_runs = []
        for i, person in enumerate(people):
            if person["is_help"]:
                continue
            run = problem["tails"][i]
            for d, rows in enumerate(allocated):
                run = run+1 if all(code in WORK for code in rows[i]) else 0
                if run == 6:
                    end = date.fromisoformat(days[d])
                    six_day_runs.append(dict(name=person["name"], start=(end-timedelta(days=5)).isoformat(), end=days[d]))
        return dict(base, status="draft", grid=allocated, shortages=shortages, six_day_runs=six_day_runs, messages=[
            "ヘルプ相談用の仮表です。希望休・有給・公休・週上限・全日" + str(max_full_days) + "連勤上限を再検証しました。診療人数・ベテラン・検査技師の不足は未解決です。全日休みを確保するために残した不足も含むので、必要なヘルプを相談してください。",
            "本人が希望していない半休の分散より全日休みを優先し、希望した半休は維持します。全日休みの最大化は保証しません。スタッフごとに探索した後、複数スタッフの日付を交換して全体を調整しています。不足が最小になることや、特定の日のヘルプが必須であることは保証しません。資格条件の不足は配置人数と重複するため合計しないでください。"])
    except SearchLimit:
        return dict(base, status="unknown", messages=["仮表の探索上限に達しました。条件が矛盾しているとは断定できません。"])


def consolidate_rest_days(problem, grid, allow_shortages=False, max_full_days=5, seconds=1, prefer_whole_rest=False):
    """希望外の半休2回を全休へまとめる。相談用では必要なヘルプの増加を許す。"""
    result = list(grid)
    deadline = time.monotonic()+seconds
    def deficit_score(d, rows):
        counts = [0,0,0]
        for row in draft_shortages(problem, d, rows):
            category = 1 if "検査技師" in row["area"] else (2 if "ベテラン" in row["area"] else 0)
            counts[category] += row["missing"]
        return counts
    for i, person in enumerate(problem["people"]):
        if person["is_help"]:
            continue
        improved = True
        while improved:
            improved = False
            halves = [d for d, rows in enumerate(result) if automatic_half_rest(problem,d,i,rows[i])]
            for off in halves:
                if time.monotonic() >= deadline:
                    return result
                if "RR" not in problem["options"][off][i]:
                    continue
                for work in halves:
                    if work == off:
                        continue
                    if time.monotonic() >= deadline:
                        return result
                    full_options = [pair for pair in problem["options"][work][i] if all(code in ("W","M","O") for code in pair)]
                    if not full_options:
                        continue
                    original_score = [a+b for a,b in zip(deficit_score(off,result[off]),deficit_score(work,result[work]))] if allow_shortages else None
                    for full_pair in full_options:
                        candidate = list(result)
                        for d, pair in ((off,"RR"),(work,full_pair)):
                            pairs = ["".join("W" if code in "ABCD" else code for code in rows) for rows in result[d]]
                            pairs[i] = pair
                            candidate[d] = allocate(problem,d,pairs,partial=allow_shortages)
                        if candidate[off] is None or candidate[work] is None:
                            continue
                        if allow_shortages:
                            new_score = [a+b for a,b in zip(deficit_score(off,candidate[off]),deficit_score(work,candidate[work]))]
                            if not prefer_whole_rest and any(new > old for new,old in zip(new_score,original_score)):
                                continue
                        if verify(problem,candidate,allow_shortages=allow_shortages,max_full_days=max_full_days):
                            continue
                        if len(six_day_runs(problem,candidate))>len(six_day_runs(problem,result)):
                            continue
                        # 6連勤は明示的な最終案のみ。通常の上限5を含め、上の再検証で守る。
                        result = candidate
                        improved = True
                        break
                    if improved:
                        break
                if improved:
                    break
    return result
