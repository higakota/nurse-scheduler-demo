"""相談の基になった自院の仮表を変えずにヘルプだけを配置する。"""
import json
from help_shortages import conditions_hash
from scheduler_engine import _generate, finish_policy, prepare, six_day_runs


def load_manual_source(db, month):
    if not db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedules'").fetchone():
        return ""
    row = db.execute("SELECT data FROM manual_schedules WHERE month=?", (month,)).fetchone()
    return row[0] if row else ""


def load_seed(db, month):
    if not db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedule_seeds'").fetchone():
        return ""
    row = db.execute("SELECT data FROM manual_schedule_seeds WHERE month=?", (month,)).fetchone()
    return row[0] if row else ""


def preferred_help_source(snapshot, draft_raw, manual_raw):
    """条件一致を優先し、より新しく保存した表を初期選択する。"""
    choices = []
    current = conditions_hash(snapshot)
    for kind, raw in (("draft", draft_raw), ("manual", manual_raw)):
        if not raw:
            continue
        value = json.loads(raw)
        saved_conditions = value.get("conditions_hash")
        freshness = 2 if saved_conditions == current else 1 if saved_conditions is None else 0
        stamp = value.get("updated") or value.get("created") or ""
        choices.append((freshness, stamp, kind))
    return max(choices)[2] if choices else "draft"


def generate_fixed_help(snapshot, seed_raw, seconds=10, source_name="自院の仮表", partial=False):
    seed = json.loads(seed_raw)
    if seed.get("conditions_hash") is not None and seed["conditions_hash"] != conditions_hash(snapshot):
        return dict(status="input_error", grid=None, shortages=[], messages=[
            source_name + "の保存後に勤務条件が変更されています。元の表を現在の条件で確認・保存し直してください。ヘルプ来院予定は保持しています。"])
    own = {str(p["id"]) for p in snapshot["staff"] if not p["is_help"]}
    seed_own = {str(p["id"]) for p in seed["people"] if not p["is_help"]}
    if own != seed_own:
        return dict(status="input_error", grid=None, shortages=[], messages=["自院スタッフが変更されています。仮表を作り直してください。"])
    fixed = {(day, str(person["id"])): seed["grid"][d][i]
             for d, day in enumerate(seed["days"])
             for i, person in enumerate(seed["people"]) if not person["is_help"]}
    # 不足を残す仮表では、元の自院勤務にある6連勤も未調整事項として表示する。
    # 自院勤務は固定したままなので、新しい6連勤を作ることはない。
    existing_six = False
    if partial:
        check = prepare(snapshot,use_help=True)
        positions = {str(p["id"]):i for i,p in enumerate(seed["people"])}
        if not check["errors"]:
            rows = [[seed["grid"][d][positions[str(p["id"])]] if str(p["id"]) in positions else "RR"
                     for p in check["people"]] for d in range(len(seed["days"]))]
            existing_six = bool(six_day_runs(check,rows))
    result = _generate(snapshot, use_help=True, seconds=seconds, fixed_regular=fixed, partial=partial,
                       draft_max_full_days=6 if existing_six else 5)
    if partial and existing_six:
        result.update(experimental=False,max_full_days=6)
        if result.get("grid") is not None:
            result["six_day_runs"]=six_day_runs(result["problem"],result["grid"])
    else:
        finish_policy(result, 5)
    if result["status"] in ("success", "draft"):
        # 最終確認でも自院の勤務記号が変わっていないことを保証する。
        for d, day in enumerate(result["problem"]["days"]):
            for i, person in enumerate(result["problem"]["people"]):
                if not person["is_help"] and result["grid"][d][i] != fixed[(day, str(person["id"]))]:
                    return dict(status="unknown", grid=None, shortages=[], messages=["自院勤務の維持確認に失敗したため保存しませんでした。"])
        result["messages"].append(source_name + "を維持し、承諾済みのヘルプだけを配置しました。")
        if partial:
            result["included_help"] = True
            if existing_six:
                result["messages"].append("元の自院勤務に6連勤が残っています。未調整の仮表として表示しています。完成前に連勤を確認・調整してください。")
    else:
        result["messages"].insert(0, source_name + "は変更していません。現在の来院予定では固定した表を完成できませんでした。来院日時・職種・ベテランの条件を確認してください。")
    return result


def consulted_help_source(db, month, manual_raw):
    """不足表示に使った表だけをヘルプ追加の基準にする。"""
    import hashlib
    if db.execute("SELECT name FROM sqlite_master WHERE name='help_shortage_previews'").fetchone():
        row=db.execute("SELECT data FROM help_shortage_previews WHERE month=?",(month,)).fetchone()
        reference=json.loads(row[0]) if row else {}
        if reference.get("source_kind") == "manual":
            matches=bool(manual_raw) and reference.get("source_hash") == hashlib.sha256(manual_raw.encode()).hexdigest()
            return "manual", matches
    return "draft", True
