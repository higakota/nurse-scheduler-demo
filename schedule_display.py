"""保存データや勤務条件を変えず、Excel見本に寄せて月間表を整形する。"""
from datetime import date
from scheduler_engine import rest_units

LABELS = {"D": "日", "A": "日", "B": "日", "C": "日", "O": "日", "M": "会", "R": "休", "P": "有休"}
DETAILS = {"D": "診療（ABC担当は未定）", "A": "A（受付）", "B": "B（診察室）", "C": "C（検査室）", "O": "業（通常業務）", "M": "会（会議）", "R": "休", "P": "有休"}


def monthly_display(days, people, grid, monthly=None, targets=None, shortages=None, comparison_inputs=None, doctor_plans=None):
    monthly, targets = monthly or {}, targets or {}
    shortages = merge_veteran_shortages(shortages or [])
    headers = []
    for day in days:
        parsed = date.fromisoformat(day)
        headers.append(dict(date=day, number=parsed.day, weekday="月火水木金土日"[parsed.weekday()],
                            closed=parsed.weekday() == 6 or day in monthly.get("closures", {}),
                            saturday=parsed.weekday() == 5,
                            meetings=[m["title"] for m in monthly.get("meetings", []) if m["date"] == day],
                            doctors_am=([] if parsed.weekday() == 6 or day in monthly.get("closures", {}) else (doctor_plans or {}).get(day, {}).get("am")),
                            doctors_pm=([] if parsed.weekday() in (4,6) or day in monthly.get("closures", {}) else (doctor_plans or {}).get(day, {}).get("pm"))))
    rows = []
    for i, person in enumerate(people):
        cells = []
        rests = 0
        for d, day in enumerate(days):
            pair = grid[d][i]
            rests += rest_units(pair)
            labels = [("—" if person["is_help"] and code == "R" else LABELS[code]) for code in pair]
            label = labels[0] if labels[0] == labels[1] else "/".join(labels)
            detail_codes = [("診" if code in "ABD" or (code == "C" and person.get("role") == "nurse") else code) for code in pair]
            detail = "/".join(detail_codes) if detail_codes[0] != detail_codes[1] else detail_codes[0]
            hint = "午前：" + DETAILS[pair[0]] + "、午後：" + DETAILS[pair[1]]
            kind = "rest" if pair == "RR" else ("paid" if "P" in pair else ("meeting" if "M" in pair else ("half" if "R" in pair else "work")))
            requests = []
            key = str(person["id"]) + "_" + day
            if comparison_inputs is not None:
                wish = comparison_inputs.get("wishes", {}).get(key, "")
                paid = comparison_inputs.get("leaves", {}).get(key, "")
                if wish in ("full", "am", "pm"):
                    requests.append(dict(kind="wish", label={"full":"希望休", "am":"午前休", "pm":"午後休"}[wish],
                                         hint="希望休：" + {"full":"全日", "am":"午前", "pm":"午後"}[wish]))
                if paid in ("full", "am", "pm"):
                    requests.append(dict(kind="paid", label={"full":"有休", "am":"午前有休", "pm":"午後有休"}[paid],
                                         hint="有給：" + {"full":"全日", "am":"午前", "pm":"午後"}[paid]))
            request_halves = []
            for half in ("am", "pm"):
                paid_here = comparison_inputs is not None and comparison_inputs.get("leaves", {}).get(key, "") in ("full", half)
                wish_here = comparison_inputs is not None and comparison_inputs.get("wishes", {}).get(key, "") in ("full", half)
                request_halves.append(dict(label="有休" if paid_here else ("休" if wish_here else "—"),
                                           kind="paid" if paid_here else ("wish" if wish_here else "empty")))
            request_segments = []
            if requests:
                request_segments = [request_halves[0]] if request_halves[0] == request_halves[1] else request_halves
            cells.append(dict(label=label, detail=detail, hint=hint, kind=kind, requests=requests,
                              request_segments=request_segments, has_request=bool(requests),
                              request_hint="、".join(item["hint"] for item in requests)))
        if person["is_help"]:
            total = "対象外"
        elif person["employment"] == "part":
            limit = person.get("weekly_limit_units")
            total = "週" + str(limit / 2) + "日まで" if limit is not None else "週上限未設定"
        else:
            total = str(rests / 2) + "日"
            if str(person["id"]) in targets:
                total += "／" + str(targets[str(person["id"])]) + "日"
        rows.append(dict(id=person["id"], name=person["name"], is_help=person["is_help"], cells=cells, total=total))
    deficit_rows = []
    for half in ("午前", "午後"):
        cells = []
        for day in days:
            items = [r for r in shortages or [] if r["date"] == day and r["half"] == half]
            labels = []
            for item in items:
                area = item["area"]
                short = "看護師" if area == "診療の看護師合計" else ("ベテラン" if "ベテラン" in area else ("検査技師" if "検査技師" in area else area.split("（")[0]))
                if item.get("veteran_missing"):
                    count = item["veteran_missing"]
                    labels.append(("看護師" + str(item["missing"]) + "人（うちベテラン" + str(count) + "人）")
                                  if item["missing"] else ("ベテラン" + str(count) + "人へ交代（人数充足）"))
                elif item.get("requires_technician"):
                    labels.append(("C" + str(item["missing"]) + "人（要検査技師）") if item["missing"] else "C充足（要検査技師）")
                else:
                    labels.append(short + str(item["missing"]) + "人")
            cells.append(dict(label="・".join(labels) if labels else "—", missing=bool(items)))
        deficit_rows.append(dict(half=half, cells=cells))
    return dict(days=headers, rows=rows, deficits=deficit_rows, has_shortages=bool(shortages), comparison_available=comparison_inputs is not None, doctors_available=doctor_plans is not None)


def grouped_shortages(shortages, problem, grid):
    """人数の不足と検査技師の職種条件を、C番の同じ行にまとめる。元の判定は変えない。"""
    if any(r["area"] == "診療の看護師合計" or "C番として計上" in r["area"] for r in shortages):
        tech_keys = {(r["date"],r["half"]):r for r in shortages if "他院の検査技師" in r["area"]}
        result = []
        for original in shortages:
            row = dict(original)
            key = (row["date"],row["half"])
            if row["area"] == "診療の看護師合計" and key in tech_keys:
                # 検査技師1人がCを担当すると、その分だけ必要な看護師が減る。
                row["required"] = max(0,row["required"]-tech_keys[key]["missing"])
                row["missing"] = max(0,row["required"]-row["available"])
                row["note"] = "検査技師ヘルプをC番に含めた人数"
                if not row["missing"]:
                    continue
            elif "他院の検査技師" in row["area"]:
                row["area"] = "検査技師（C番として計上）"
                row["note"] = "C番の担当として必要"
            result.append(row)
        return merge_veteran_shortages(result)
    c_rows = {(r["date"], r["half"]): r for r in shortages if r["area"].startswith("C（")}
    tech_rows = {(r["date"], r["half"]): r for r in shortages if "他院の検査技師" in r["area"]}
    result = []
    for original in shortages:
        key = (original["date"], original["half"])
        is_tech = "他院の検査技師" in original["area"]
        is_c = original["area"].startswith("C（")
        if is_tech and key in c_rows:
            continue
        row = dict(original)
        if (is_c and key in tech_rows) or is_tech:
            row["requires_technician"] = True
            needed = tech_rows[key]["missing"]
            if is_tech:
                d = problem["days"].index(row["date"])
                h = 0 if row["half"] == "午前" else 1
                required = problem["requirements"][d][h][2]
                nurses = sum(p["role"] == "nurse" and grid[d][i][h] == "C" for i,p in enumerate(problem["people"]))
                tech = any(p["role"] == "technician" and grid[d][i][h] == "C" for i,p in enumerate(problem["people"]))
                available = nurses+int(tech)
                row.update(area="C（検査室）", required=required, available=available, missing=max(0,required-available))
            if row["missing"]:
                row["note"] = "検査技師のヘルプ" + str(needed) + "人が必要（C番の不足人数に含む）"
            else:
                row["note"] = "人数は充足。検査技師のヘルプ" + str(needed) + "人への交代を検討（看護師のみ対応の例外は未指定）"
        result.append(row)
    return merge_veteran_shortages(result)


def merge_veteran_shortages(shortages):
    """看護師不足の内数としてベテラン条件を併記し、人数の二重読取を避ける。"""
    nurses = {(row["date"],row["half"]): row for row in shortages if row["area"] == "診療の看護師合計"}
    veterans = {(row["date"],row["half"]): row for row in shortages if "ベテラン" in row["area"]}
    merged = []
    for original in shortages:
        row = dict(original)
        key = (row["date"],row["half"])
        if "ベテラン" in row["area"] and key in nurses:
            continue
        if row["area"] == "診療の看護師合計" and key in veterans:
            row["veteran_missing"] = veterans[key]["missing"]
            qualifier = "うちベテラン" + str(row["veteran_missing"]) + "人が必要"
            row["note"] = row.get("note", "") + ("。 " if row.get("note") else "") + qualifier
        elif "ベテラン" in row["area"] and "看護師人数の内数" in row["area"]:
            row.update(area="看護師の人数は充足（ベテランへの交代）", required=None, available=None,
                       missing=0, veteran_missing=row["missing"],
                       note="追加人数の不足ではありません。診療に入る看護師のうちベテラン" + str(row["missing"]) + "人を確保してください。")
        merged.append(row)
    return merged
