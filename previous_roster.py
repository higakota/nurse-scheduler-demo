"""前月の保存済み編集表から勤務実績を読む。未反映の作成案は使わない。"""
import json
from datetime import date,timedelta

WORK=set("ABCDMOT")

def history_code(pair):
    am,pm=(c in WORK for c in pair)
    if am and pm:return "full"
    if am:return "pm_paid" if pair[1]=="P" else "am"
    if pm:return "am_paid" if pair[0]=="P" else "pm"
    return "paid" if pair=="PP" else "rest"

def inherited_history(db,month,staff):
    first=date.fromisoformat(month+"-01")
    previous=(first-timedelta(days=1)).strftime("%Y-%m")
    if not db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedules'").fetchone():return {},None
    row=db.execute("SELECT data FROM manual_schedules WHERE month=?",(previous,)).fetchone()
    if not row:return {},None
    source=json.loads(row[0])
    if not source.get("updated"):return {},None
    positions={str(p["id"]):i for i,p in enumerate(source["people"]) if not p["is_help"]}
    dates={day:d for d,day in enumerate(source["days"])}
    history={}
    for offset in range(6,0,-1):
        day=(first-timedelta(days=offset)).isoformat()
        if day not in dates:continue
        for p in staff:
            pid=str(p["id"])
            if p["is_help"] or pid not in positions:continue
            pair=source["grid"][dates[day]][positions[pid]]
            if len(pair)!=2 or any(c not in "ABCDMOTRPS" for c in pair):
                raise ValueError("前月の保存済み勤務表に不明な勤務記号があります。前月の表を確認してください。")
            history[pid+"_"+day]=history_code(pair)
    return history,dict(month=previous,updated=source["updated"])

def apply_inheritance(db,month,staff,leave):
    automatic,source=inherited_history(db,month,staff)
    return dict(leave,history=dict(automatic,**leave.get("history",{}))),source
