"""Excelの色分け・文字枠は未確定の候補として扱う。"""
import hashlib
import json
import posixpath
import re
import secrets
from meeting_rules import checked_times, check_meeting_overlap
from collections import Counter
from datetime import date
from xml.etree import ElementTree as ET

S = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
X = {"x": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def extract_events(raw, sheet, rows):
    from doctor_import import open_book, xml_read, sheet_paths
    result = {"closures": [], "meetings": []}
    columns = {re.sub(r"\d+", "", row["cell"]): row["date"] for row in rows}
    with open_book(raw) as book:
        path = dict(sheet_paths(book))[sheet]
        root = xml_read(book, path)
        cells = {c.get("r"): c for c in root.findall(".//s:sheetData/s:row/s:c", S)}
        if "xl/styles.xml" in book.namelist():
            styles = xml_read(book, "xl/styles.xml")
            xfs = styles.findall("s:cellXfs/s:xf", S)
            fills = styles.findall("s:fills/s:fill", S)
            def fill(ref):
                cell = cells.get(ref)
                index = int(cell.get("s", "0")) if cell is not None else 0
                if index >= len(xfs):
                    return None
                idx = int(xfs[index].get("fillId", "0"))
                return ET.tostring(fills[idx]) if idx < len(fills) else None
            normal = Counter(fill(col + "4") for col, day in columns.items() if date.fromisoformat(day).weekday() != 6)
            common = normal.most_common(1)[0][0] if normal else None
            sunday = {fill(col + "4") for col, day in columns.items() if date.fromisoformat(day).weekday() == 6}
            for col, day in columns.items():
                color = fill(col + "4")
                if date.fromisoformat(day).weekday() != 6 and color is not None and color != common and color == fill(col + "5"):
                    result["closures"].append({"id": col, "date": day, "reason": "日曜と同じ色分け" if color in sunday else "通常と異なる色分け"})
        relpath = posixpath.join(posixpath.dirname(path), "_rels", posixpath.basename(path) + ".rels")
        if relpath not in book.namelist():
            return result
        links = {r.get("Id"): r for r in xml_read(book, relpath)}
        for drawing in root.findall("s:drawing", S):
            link = links.get(drawing.get("{" + REL + "}id"))
            if link is None or link.get("TargetMode") == "External":
                continue
            target = link.get("Target", "")
            drawingpath = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(path), target))
            for index, anchor in enumerate(xml_read(book, drawingpath)):
                start = anchor.find("x:from", X)
                if start is None:
                    continue
                rownum = int(start.findtext("x:row", "-1", X))
                if rownum not in (5, 6):
                    continue
                paragraphs = ["".join(t.text or "" for t in p.findall(".//a:t", X)).strip() for p in anchor.findall(".//a:p", X)]
                paragraphs = [p for p in paragraphs if p]
                if not any(re.search("会議|ミーティング|委員会|研修|学習|師長会|医師会|理事会|総会|医活研|予演会", p) for p in paragraphs):
                    continue
                for part, title in enumerate(paragraphs):
                    key = hashlib.sha256((sheet + ":" + drawingpath + ":" + str(index) + ":" + str(part)).encode()).hexdigest()[:24]
                    result["meetings"].append({"id": key, "title": title, "source": sheet + "・文字枠" + str(index + 1), "date": ""})
    return result


def monthly_snapshot(db, month):
    db.execute("CREATE TABLE IF NOT EXISTS monthly_settings(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
    row = db.execute("SELECT data FROM monthly_settings WHERE month=?", (month,)).fetchone()
    return row["data"] if row else None


def apply_events(db, month, preview, form):
    extras = preview.get("extras", {})
    closures = [item for item in extras.get("closures", []) if form.get("closure_pick_" + item["id"]) == "yes"]
    meetings = [item for item in extras.get("meetings", []) if form.get("meeting_pick_" + item["id"]) == "yes"]
    if not closures and not meetings:
        return
    # 最新の月別入力へ追加する。公休・希望休等の無関係な変更で候補を失効させない。
    # 既存予定との衝突は下で検証し、保存時にも最新値との比較で同時更新を防ぐ。
    original = monthly_snapshot(db, month)
    data = json.loads(original) if original else {"targets": {}, "wishes": {}, "closures": {}, "meetings": []}
    ids = {str(row["id"]) for row in db.execute("SELECT id FROM staff")}
    for item in closures:
        day = item["date"]
        kind = form.get("closure_kind_" + item["id"], "")
        if kind not in ("holiday", "year_end"):
            raise ValueError(day + "：休診日の区分を選択してください。")
        if day in data["closures"] and data["closures"][day] != kind:
            raise ValueError(day + "：既存の休診区分と異なります。月別入力で確認してください。")
        if any(m["date"] == day for m in data["meetings"]):
            raise ValueError(day + "：会議が登録済みのため、休診日に変更できません。")
        data["closures"][day] = kind
    for item in meetings:
        prefix = "meeting_" + item["id"]
        day = form.get(prefix + "_date", "")
        title = form.get(prefix + "_title", "").strip()
        participants = list(dict.fromkeys(form.getlist(prefix + "_participants")))
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            raise ValueError("会議の日付を指定してください。")
        if parsed.strftime("%Y-%m") != month or parsed.weekday() == 6 or day in data["closures"]:
            raise ValueError("会議は対象月の休診日以外を選択してください。")
        if not title or len(title) > 80:
            raise ValueError("会議名は1～80文字で入力してください。")
        if not participants or not set(participants) <= ids:
            raise ValueError("会議の参加者を選択してください。")
        start, end = checked_times(form.get(prefix + "_start", ""), form.get(prefix + "_end", ""))
        proposed = {"date": day, "title": title, "participants": participants, "start": start, "end": end}
        previous = next((m for m in data["meetings"] if m.get("import_source") == item["id"]), None)
        if previous:
            if any(previous.get(k, "") != proposed[k] for k in proposed):
                raise ValueError("同じ文字枠の会議が登録済みです。月別入力で確認してください。")
            continue
        check_meeting_overlap(data["meetings"], proposed)
        data["meetings"].append(dict(proposed, id=secrets.token_hex(8), import_source=item["id"]))
    encoded = json.dumps(data, ensure_ascii=False)
    if original is None:
        try:
            db.execute("INSERT INTO monthly_settings VALUES (?, ?)", (month, encoded))
        except __import__("sqlite3").IntegrityError:
            raise ValueError("月別入力が変更されました。読み取り直してください。")
    elif db.execute("UPDATE monthly_settings SET data=? WHERE month=? AND data=?", (encoded, month, original)).rowcount != 1:
        raise ValueError("月別入力が変更されました。読み取り直してください。")
