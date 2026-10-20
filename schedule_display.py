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
    comparison_wishes = dict(comparison_inputs.get("wishes", {})) if comparison_inputs is not None else {}
    original_wishes, agreed_changes, replacement_changes = {}, {}, {}
    if comparison_inputs is not None:
        # 作成条件の wishes は変更後のまま。比較欄だけ元の希望を復元する。
        for record in monthly.get("agreed_wish_changes", []):
            if record.get("cancelled"):
                continue
            key = str(record["staff_id"]) + "_" + record["date"]
            original_wishes.setdefault(key, record["original_wish"])
            agreed_changes.setdefault(key, []).append(record)
            if record.get("replacement_date"):
                replacement = str(record["staff_id"]) + "_" + record["replacement_date"]
                replacement_changes.setdefault(replacement, []).append(record)
        comparison_wishes.update(original_wishes)
    rows = []
    for i, person in enumerate(people):
        cells = []
        rests = 0
        for d, day in enumerate(days):
            pair = grid[d][i]
            rests += rest_units(pair)
            labels = [("—" if person["is_help"] and code == "R" else LABELS[code]) for code in pair]
            label = labels[0] if labels[0] == labels[1] else "/".join(labels)
            if person["is_help"]:
                label = "" if pair=="RR" else "午前" if pair[1]=="R" and pair[0] in "ABCDMO" else "午後" if pair[0]=="R" and pair[1] in "ABCDMO" else label
            detail_codes = [("診" if code in "ABD" or (code == "C" and person.get("role") == "nurse") else code) for code in pair]
            detail = "/".join(detail_codes) if detail_codes[0] != detail_codes[1] else detail_codes[0]
            if person["is_help"]:
                detail="" if pair=="RR" else detail.replace("R","—")
            hint = "午前：" + DETAILS[pair[0]] + "、午後：" + DETAILS[pair[1]]
            if person["is_help"] and pair=="RR":
                hint="来院なし"
            kind = "rest" if pair == "RR" else ("paid" if "P" in pair else ("meeting" if "M" in pair else ("half" if "R" in pair else "work")))
            requests = []
            key = str(person["id"]) + "_" + day
            if comparison_inputs is not None:
                wish = comparison_wishes.get(key, "")
                paid = comparison_inputs.get("leaves", {}).get(key, "")
                if wish in ("full", "am", "pm"):
                    requests.append(dict(kind="wish", label={"full":"希望休", "am":"午前休", "pm":"午後休"}[wish],
                                         hint="希望休：" + {"full":"全日", "am":"午前", "pm":"午後"}[wish]))
                if paid in ("full", "am", "pm"):
                    requests.append(dict(kind="paid", label={"full":"有休", "am":"午前有休", "pm":"午後有休"}[paid],
                                         hint="有給：" + {"full":"全日", "am":"午前", "pm":"午後"}[paid]))
            adjustment_label, adjustment_hint = "", ""
            records = agreed_changes.get(key, [])
            replacements = replacement_changes.get(key, [])
            if records:
                adjustment_label = "了承出勤" if any(code in "ABCDMO" for code in pair) else "了承変更"
                periods = {"full":"全日", "am":"午前", "pm":"午後"}
                adjustment_hint = "元の希望休を残して表示。本人了承で出勤へ変更：" + "、".join(
                    periods.get(record["work_period"], record["work_period"]) for record in records)
                current = comparison_inputs.get("wishes", {}).get(key, "")
                adjustment_hint += "。変更後の希望休：" + periods.get(current, "なし")
            if replacements:
                adjustment_label = adjustment_label or "代替休"
                adjustment_hint += ("。 " if adjustment_hint else "") + "本人了承で代わりの全日希望休に指定"
            if adjustment_label:
                requests.append(dict(kind="agreed", label=adjustment_label, hint=adjustment_hint))
            request_halves = []
            for half in ("am", "pm"):
                paid_here = comparison_inputs is not None and comparison_inputs.get("leaves", {}).get(key, "") in ("full", half)
                wish_here = comparison_inputs is not None and comparison_wishes.get(key, "") in ("full", half)
                request_halves.append(dict(label="有休" if paid_here else ("休" if wish_here else "—"),
                                           kind="paid" if paid_here else ("wish" if wish_here else "empty")))
            request_segments = []
            if requests:
                request_segments = [request_halves[0]] if request_halves[0] == request_halves[1] else request_halves
            cells.append(dict(label=label, detail=detail, hint=hint, kind=kind, requests=requests,
                              request_segments=request_segments, has_request=bool(requests),
                              adjustment_label=adjustment_label, adjustment_hint=adjustment_hint,
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
            if row["area"] in ("診療の看護師合計", "検査室を担当できる看護師") and key in tech_keys:
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
                tech = sum(p["role"] == "technician" and grid[d][i][h] == "C" for i,p in enumerate(problem["people"]))
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

def concise_shortages(rows):
    """同じ条件の午前午後をまとめる。異なる配置の不足は足し合わせない。"""
    days = {}
    for row in rows:
        area = row["area"]
        label = {
            "他院の検査技師（全日休みの代替）": "検査技師",
            "検査技師（C番として計上）": "検査技師",
            "他院の検査技師（C番として計上）": "検査技師",
            "全配置の看護師合計": "看護師",
            "診療の看護師合計": "看護師",
        }.get(area, area)
        missing = row.get("missing", 0)
        veteran = row.get("veteran_missing", 0)
        if not missing and veteran:
            text=f"ベテラン看護師{veteran}人への交代が必要"
            veteran=0
        else:
            text = f"{label}{missing}人不足" if missing else f"{label}への交代が必要"
        if veteran:
            text += f"（うちベテラン{veteran}人）" if missing else f"（ベテラン{veteran}人）"
        group = days.setdefault(row["date"], {})
        halves = group.setdefault(text, [])
        if row["half"] not in halves:
            halves.append(row["half"])
    return [
        {"date": day, "items": [
            ("午前・午後" if set(halves) == {"午前", "午後"} else "・".join(halves)) + "：" + text
            for text, halves in groups.items()
        ]}
        for day, groups in sorted(days.items())
    ]
