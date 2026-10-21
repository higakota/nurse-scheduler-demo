"""自院を優先し、特に看護師ヘルプが同じ日に重なる配置を減らす。"""
PREFERRED_DAILY_HELPERS = 2


def helper_count(people, rows):
    return sum(bool(p["is_help"]) and any(c in "ABCDWMOT" for c in pair)
               for p, pair in zip(people, rows))


def helper_demand_roles(problem, d, rows, *, prefer_technicians=False):
    """役割の重複を除いて、自院の不足を埋めるヘルプ人数の下限を求める。"""
    nurses, technicians = 0, 0
    for half, (a, b, c) in enumerate(problem["requirements"][d]):
        if not a:
            continue
        tech = sum(p["role"] == "technician" and row[half] == "C" for p,row in zip(problem["people"],rows))
        replacement = int(not any(rows[i][half] in "CW" for i in problem["local_tech"]) and problem["days"][d] not in problem["technician_exceptions"] and
                          not any(rows[i][half] == "C" for i in problem["helper_tech"]))
        nurses_present = [p for p,row in zip(problem["people"],rows) if p["role"] == "nurse" and row[half] in "ABCD"]
        c_need = max(0, c-int(tech)-replacement)
        needed = max(0, a+b+c_need-len(nurses_present),
                     c_need-sum("C" in p.get("allowed_areas","ABC") for p in nurses_present),
                     int(not any(p["veteran"] for p in nurses_present)))
        if prefer_technicians:
            # C番の残りは追加の技師でも担当できる。A・Bとベテランは看護師が必要。
            nurse_only = max(0, a+b-len(nurses_present),
                             int(not any(p["veteran"] for p in nurses_present)))
            extra_tech = max(0, needed-nurse_only)
            needed -= extra_tech
            replacement += extra_tech
        nurses = max(nurses, needed)
        technicians = max(technicians, replacement)
    return nurses, technicians


def visit_counts(data, staff_ids):
    days={}
    for key,period in data.items():
        person,_,day=key.partition("_")
        if person in staff_ids and period in ("full","am","pm"):
            days.setdefault(day,set()).add(person)
    return {day:len(people) for day,people in days.items()}


def helper_demand(problem, d, rows):
    return sum(helper_demand_roles(problem, d, rows))


def nurse_helper_excess(people, rows):
    """同じ日に来る看護師ヘルプが2人以上となる人数分。必須制限ではない。"""
    count=sum(p["is_help"] and p["role"] == "nurse" and any(c in "ABCDWMOT" for c in pair)
              for p,pair in zip(people,rows))
    return max(0,count-1)


def planned_helper_roles(problem,d,rows):
    """事前配置した人と、追加相談が必要な人数を合わせて比較する。"""
    nurses,techs=helper_demand_roles(problem,d,rows,prefer_technicians=True)
    nurses+=sum(p["is_help"] and p["role"]=="nurse" and any(c in "ABCDWMOT" for c in pair)
                for p,pair in zip(problem["people"],rows))
    techs+=sum(p["is_help"] and p["role"]=="technician" and any(c in "ABCDWMOT" for c in pair)
               for p,pair in zip(problem["people"],rows))
    return nurses,techs
