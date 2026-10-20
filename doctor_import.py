"""提供見本のxlsx（4行目=日付、6行目=医師）をローカルで取り込む。"""
import calendar
import hashlib
import io
import json
import posixpath
import re
import secrets
import sqlite3
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from flask import abort, redirect, render_template, request, session, url_for

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
IMPORT_VERSION = 5


def xml_read(book, path):
    raw = book.read(path)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("このExcelのXML形式には対応していません。")
    return ET.fromstring(raw)


def open_book(raw):
    try:
        book = zipfile.ZipFile(io.BytesIO(raw))
        items = book.infolist()
        if len(items) > 2000 or sum(item.file_size for item in items) > 30 * 1024 * 1024:
            book.close()
            raise ValueError("Excelの展開サイズが大きすぎます。")
        return book
    except zipfile.BadZipFile as exc:
        raise ValueError("xlsx形式のExcelを選択してください。") from exc


def sheet_paths(book):
    workbook = xml_read(book, "xl/workbook.xml")
    relationships = xml_read(book, "xl/_rels/workbook.xml.rels")
    paths = {}
    for rel in relationships:
        if rel.get("TargetMode") != "External":
            target = rel.get("Target", "")
            paths[rel.get("Id")] = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
    return [(sheet.get("name"), paths.get(sheet.get("{" + REL + "}id")))
            for sheet in workbook.findall("s:sheets/s:sheet", NS)]


def plain_text(node):
    # rPh（ふりがな）を除き、通常文字とリッチテキストのみを読む。
    return "".join(item.text or "" for item in node.findall("s:t", NS) + node.findall("s:r/s:t", NS))


def parse_schedule(raw, sheet_name, month):
    with open_book(raw) as book:
        paths = dict(sheet_paths(book))
        if sheet_name not in paths or not paths[sheet_name]:
            raise ValueError("対象シートが見つかりません。")
        workbook = xml_read(book, "xl/workbook.xml")
        properties = workbook.find("s:workbookPr", NS)
        epoch = date(1904, 1, 1) if properties is not None and properties.get("date1904") in ("1", "true") else date(1899, 12, 30)
        from excel_font_colors import FontColors, clinical_groups
        colors = FontColors(book)
        shared_nodes = []
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared_nodes = xml_read(book, "xl/sharedStrings.xml").findall("s:si", NS)
            shared = [plain_text(node) for node in shared_nodes]
        cells = {}
        rotations = {}
        color_flags = {}
        styles = []
        if "xl/styles.xml" in book.namelist():
            style_root = xml_read(book, "xl/styles.xml").find("s:cellXfs", NS)
            styles = list(style_root) if style_root is not None else []
        formulas = set()
        root = xml_read(book, paths[sheet_name])
        for cell in root.findall("s:sheetData/s:row/s:c", NS):
            ref = cell.get("r", "")
            if cell.find("s:f", NS) is not None:
                formulas.add(ref)
            value = cell.find("s:v", NS)
            text = value.text or "" if value is not None else ""
            text_node = None
            if cell.get("t") == "s":
                text_node = shared_nodes[int(text)]
                text = shared[int(text)]
            elif cell.get("t") == "inlineStr":
                inline = cell.find("s:is", NS)
                text_node = inline
                text = plain_text(inline) if inline is not None else ""
            style = styles[int(cell.get("s", "0"))] if styles else None
            color_flags[ref] = colors.characters(text_node, text, style)
            cells[ref] = text
            rotation = 0
            if styles:
                alignment = styles[int(cell.get("s", "0"))].find("s:alignment", NS)
                if alignment is not None:
                    rotation = int(alignment.get("textRotation", "0"))
            rotations[ref] = rotation
        # 文字色を変える条件付き書式だけ個別確認へ。背景色・罫線は担当医の赤字判定に影響しない。
        for conditional in root.findall("s:conditionalFormatting", NS):
            if not colors.conditional_font_uncertain(conditional):
                continue
            for area in conditional.get("sqref", "").split():
                ends = area.replace("$", "").split(":")
                parsed = [re.fullmatch(r"([A-Z]+)([0-9]+)", end) for end in ends]
                if not all(parsed):
                    continue
                first, last = parsed[0], parsed[-1]
                def column_number(value):
                    total = 0
                    for letter in value:
                        total = total * 26 + ord(letter) - 64
                    return total
                if int(first[2]) <= 6 <= int(last[2]):
                    for address, text in cells.items():
                        match = re.fullmatch(r"([A-Z]+)6", address)
                        if match and column_number(first[1]) <= column_number(match[1]) <= column_number(last[1]):
                            color_flags[address] = [None] * len(text)
        year, number = map(int, month.split("-"))
        found = {}
        detected_months = set()
        for ref, value in cells.items():
            match = re.fullmatch(r"([A-Z]+)4", ref)
            if not match or match[1] in ("A", "B"):
                continue
            try:
                day = date.fromisoformat(value[:10]) if "-" in value else epoch + timedelta(days=float(value))
            except (ValueError, OverflowError):
                continue
            detected_months.add(day.strftime("%Y-%m"))
            if day.strftime("%Y-%m") != month:
                continue
            if day.isoformat() in found:
                raise ValueError("日付が重複しています。見本と同じ4行目の日付配置か確認してください。")
            column = match[1]
            raw_text = cells.get(column + "6", "")
            groups, excluded, color_uncertain = clinical_groups(raw_text, color_flags.get(column + "6", []))
            am, pm, note = "", "", ""
            if day.weekday() == 6:
                note = "日曜は全日休診です。午前・午後とも診療担当医0人に固定します。"
            elif not groups:
                note = "空欄です。午前・午後の担当医を入力するか、担当医なしを確認してください。"
            elif day.weekday() == 4:
                # 金曜の医師表記はすべて午前。縦書きの文字順より優先する。
                am = "/".join(dict.fromkeys(name for group in groups for name in split_names(group)))
                note = "金曜は記載された医師をすべて午前に割り当てています。午後は診療なし（0人）です。"
            elif len(groups) == 2 and rotations.get(column + "6", 0) in (0, 255):
                if rotations.get(column + "6", 0) == 255:
                    # 見本は縦書きで文字列の先頭が右列（午後）、後半が左列（午前）。
                    pm, am = groups
                    note = "縦書き：前半を右列（午後）、後半を左列（午前）の候補にしています。Excelと照合してください。"
                else:
                    am, pm = groups
                    note = "横書きの左・右の候補です。Excelと照合してください。"
            else:
                note = "午前・午後を判別できません。両欄への自動割当はしていません。元のExcelを見て入力してください。"
            if color_uncertain and day.weekday() != 6:
                am, pm = "", ""
                note = "文字色を確定できないため、出勤候補を自動入力していません。赤字は休みとして元のExcelで確認してください。"
            elif excluded and day.weekday() != 6:
                note = "赤字の医師を休みとして出勤候補から除外しました。 " + note
            if column + "6" in formulas or ref in formulas:
                note = "数式の保存済み値です。最新の内容か必ず確認してください。 " + note
            found[day.isoformat()] = {"date": day.isoformat(), "raw": raw_text, "am": am, "pm": pm, "note": note, "cell": column + "6", "sheet": sheet_name, "rotation": rotations.get(column + "6", 0), "friday": day.weekday() == 4, "sunday": day.weekday() == 6, "ambiguous": day.weekday() != 6 and (color_uncertain or not groups or (day.weekday() != 4 and (len(groups) != 2 or rotations.get(column + "6", 0) not in (0, 255))))}
        expected = calendar.monthrange(year, number)[1]
        if len(found) != expected:
            detected = "、".join(sorted(detected_months)) or "日付を検出できませんでした"
            raise ValueError(
                f"対象月は{month}ですが、シート「{sheet_name}」の日付は{detected}です。"
                f"対象月の読取は{len(found)}/{expected}日です。"
                "上の対象月と対象シートの月を合わせて、もう一度読み取ってください。"
                "月が合っている場合は4行目の日付・数式の計算結果を確認してください。"
            )
        return [found[key] for key in sorted(found)]


def split_names(text):
    return [name.strip() for name in re.split(r"[/／、,\n]+", text) if name.strip()]


def same_plan(left, right):
    return right is not None and all(sorted(left.get(half, [])) == sorted(right.get(half, [])) for half in ("am", "pm"))


def register_doctor_import(app, connect_db):
    @app.template_filter("date_with_weekday")
    def date_with_weekday(value):
        try:
            day = date.fromisoformat(value)
        except (ValueError, TypeError):
            return value
        return value + "（" + "月火水木金土日"[day.weekday()] + "）"

    @app.route("/doctors", methods=["GET", "POST"])
    def doctor_import():
        month = request.args.get("month", date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            abort(400)
        year, number = map(int, month.split("-"))
        if not 1900 <= year <= 9998 or not 1 <= number <= 12:
            abort(400)
        session.setdefault("csrf_token", secrets.token_hex(32))
        session.setdefault("import_owner", secrets.token_hex(24))
        error = None
        loaded_filename = ""
        extra_staff = []
        selected_sheet = request.form.get("sheet", "")
        preview = None
        sheets = []
        db = connect_db()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS doctor_plans(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS doctor_plan_reviews(month TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS doctor_aliases(alias TEXT PRIMARY KEY, name TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS doctor_import_draft(owner TEXT PRIMARY KEY, workbook BLOB NOT NULL, preview TEXT)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(doctor_import_draft)")}
            if "filename" not in columns:
                db.execute("ALTER TABLE doctor_import_draft ADD COLUMN filename TEXT NOT NULL DEFAULT ''")
            extra_staff = db.execute("SELECT id, name FROM staff ORDER BY id").fetchall()
            current_row = db.execute("SELECT data FROM doctor_plans WHERE month=?", (month,)).fetchone()
            current_raw = current_row["data"] if current_row else None
            current = json.loads(current_raw) if current_raw else {}
            review = db.execute("SELECT data, version FROM doctor_plan_reviews WHERE month=?", (month,)).fetchone()
            needs_recheck = bool(current) and (not review or review["version"] != IMPORT_VERSION or review["data"] != current_raw)
            aliases = dict(db.execute("SELECT alias, name FROM doctor_aliases").fetchall())
            draft = db.execute("SELECT * FROM doctor_import_draft WHERE owner=?", (session["import_owner"],)).fetchone()
            if draft:
                loaded_filename = draft["filename"] or "Excel（読み込み済み）"
                with open_book(draft["workbook"]) as book:
                    sheets = [name for name, _ in sheet_paths(book)]
                preview = json.loads(draft["preview"]) if draft["preview"] else None
                if preview and (preview["month"] != month or preview.get("version") != IMPORT_VERSION):
                    preview = None
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400, description="画面を開き直してください。")
                action = request.form.get("action")
                try:
                    if action == "upload":
                        upload = request.files.get("workbook")
                        if not upload or not upload.filename.lower().endswith(".xlsx"):
                            raise ValueError("xlsx形式のExcelを選択してください。")
                        raw = upload.read(5 * 1024 * 1024 + 1)
                        if len(raw) > 5 * 1024 * 1024:
                            raise ValueError("Excelは5MB以下にしてください。")
                        with open_book(raw) as book:
                            sheets = [name for name, _ in sheet_paths(book)]
                        loaded_filename = upload.filename.replace("\\\\", "/").replace("\\", "/").rsplit("/", 1)[-1]
                        db.execute("INSERT INTO doctor_import_draft(owner, workbook, preview, filename) VALUES (?, ?, NULL, ?) ON CONFLICT(owner) DO UPDATE SET workbook=excluded.workbook, preview=NULL, filename=excluded.filename",
                                   (session["import_owner"], raw, loaded_filename))
                        preview = None
                    elif action == "read":
                        if not draft:
                            raise ValueError("先にExcelを選択してください。")
                        rows = parse_schedule(draft["workbook"], request.form.get("sheet", ""), month)
                        for item in rows:
                            for half in ("am", "pm"):
                                names = split_names(item[half])
                                unknown = [name for name in names if name not in aliases]
                                item[half] = "/".join(aliases.get(name, name) for name in names)
                                if unknown:
                                    item["note"] += " 未登録の医師表記：" + "、".join(unknown) + "。"
                        for item in rows:
                            item["initial_am"], item["initial_pm"] = item["am"], item["pm"]
                        preview = {"month": month, "rows": rows, "original": current_raw, "version": IMPORT_VERSION}
                        from excel_events import extract_events, monthly_snapshot
                        preview["extras"] = extract_events(draft["workbook"], request.form.get("sheet", ""), rows)
                        preview["monthly_original"] = monthly_snapshot(db, month)
                        db.execute("CREATE TABLE IF NOT EXISTS excel_event_drafts(owner TEXT, month TEXT, data TEXT NOT NULL, PRIMARY KEY(owner, month))")
                        db.execute("INSERT INTO excel_event_drafts VALUES (?, ?, ?) ON CONFLICT(owner, month) DO UPDATE SET data=excluded.data",
                                   (session["import_owner"], month, json.dumps({"extras": preview["extras"], "monthly_original": preview["monthly_original"]}, ensure_ascii=False)))
                        db.execute("UPDATE doctor_import_draft SET preview=? WHERE owner=?", (json.dumps(preview, ensure_ascii=False), session["import_owner"]))
                    elif action == "save":
                        if not preview:
                            raise ValueError("先にシートを読み取ってください。")
                        for item in preview["rows"]:
                            item["am"] = request.form.get("am_" + item["date"], "")
                            item["pm"] = request.form.get("pm_" + item["date"], "")
                        if request.form.get("confirmed") != "yes":
                            raise ValueError("全日付・担当医なしの欄と変更内容を確認してチェックしてください。")
                        if current_raw != preview["original"]:
                            raise ValueError("保存済み予定が別の画面で変更されました。シートを読み取り直してください。")
                        if current and request.form.get("replace") != "yes":
                            raise ValueError("保存済み予定を置き換えることを確認してください。")
                        new_aliases = {}
                        for line in request.form.get("aliases", "").splitlines():
                            if not line.strip():
                                continue
                            key, sep, name = line.partition("=")
                            if not sep or not key.strip() or not name.strip() or max(len(key.strip()), len(name.strip())) > 50:
                                raise ValueError("略称は「略称=表示名」の形式で1行ずつ入力してください。")
                            new_aliases[key.strip()] = name.strip()
                        mapping = dict(aliases, **new_aliases)
                        plan = {}
                        for item in preview["rows"]:
                            plan[item["date"]] = {}
                            for half in ("am", "pm"):
                                names = [mapping.get(name, name) for name in split_names(item[half])]
                                if any(len(name) > 50 for name in names) or len(names) != len(set(names)):
                                    raise ValueError(item["date"] + "：名前は50文字以内とし、同じ時間帯の重複を修正してください。")
                                if date.fromisoformat(item["date"]).weekday() == 6 and names:
                                    raise ValueError(item["date"] + "：日曜は全日休診のため、医師は登録できません。")
                                if date.fromisoformat(item["date"]).weekday() == 4 and half == "pm" and names:
                                    raise ValueError(item["date"] + "：金曜午後は診療なしのため、医師は登録できません。")
                                plan[item["date"]][half] = names
                        unchecked = []
                        for item in preview["rows"]:
                            day_key = item["date"]
                            candidate = {half: [mapping.get(name, name) for name in split_names(item.get("initial_" + half, item[half]))] for half in ("am", "pm")}
                            required = item.get("ambiguous", True)
                            required = required or bool(current and not same_plan(plan[day_key], current.get(day_key)))
                            required = required or not same_plan(plan[day_key], candidate)
                            if required and request.form.get("review_" + day_key) != "yes":
                                unchecked.append(day_key)
                        if unchecked:
                            raise ValueError("元のExcelとの日別確認が必要です。未確認：" + "、".join(unchecked))
                        # 確認画面を開いた後の変更は、SQLでも検出して上書きを防ぐ。
                        encoded = json.dumps(plan, ensure_ascii=False)
                        if current_raw is None:
                            try:
                                db.execute("INSERT INTO doctor_plans VALUES (?, ?)", (month, encoded))
                            except sqlite3.IntegrityError:
                                raise ValueError("他の画面で予定が保存されました。読み取り直してください。")
                        else:
                            result = db.execute("UPDATE doctor_plans SET data=? WHERE month=? AND data=?", (encoded, month, current_raw))
                            if result.rowcount != 1:
                                raise ValueError("予定が変更されました。読み取り直してください。")
                        db.execute("INSERT INTO doctor_plan_reviews VALUES (?, ?, ?) ON CONFLICT(month) DO UPDATE SET data=excluded.data, version=excluded.version",
                                   (month, encoded, IMPORT_VERSION))
                        for alias, name in new_aliases.items():
                            db.execute("INSERT INTO doctor_aliases VALUES (?, ?) ON CONFLICT(alias) DO UPDATE SET name=excluded.name", (alias, name))
                        db.execute("DELETE FROM doctor_import_draft WHERE owner=?", (session["import_owner"],))
                        db.commit()
                        return redirect(url_for("doctor_import", month=month, saved="1"))
                    else:
                        abort(400)
                    db.commit()
                except (ValueError, KeyError, IndexError, ET.ParseError, zipfile.BadZipFile, RuntimeError) as exc:
                    db.rollback()
                    error = str(exc) if isinstance(exc, ValueError) else "Excelを読み取れませんでした。ファイルと書式を確認してください。"
            # 対象月の全日付を実際に読めるシートだけを初期選択する。
            if sheets and not selected_sheet:
                source = db.execute("SELECT workbook FROM doctor_import_draft WHERE owner=?", (session["import_owner"],)).fetchone()
                if source:
                    for candidate in sheets:
                        try:
                            parse_schedule(source["workbook"], candidate, month)
                        except (ValueError, KeyError, IndexError, ET.ParseError, zipfile.BadZipFile, RuntimeError):
                            continue
                        selected_sheet = candidate
                        break
            if preview:
                for item in preview["rows"]:
                    value = {half: split_names(item[half]) for half in ("am", "pm")}
                    item["changed"] = bool(current) and not same_plan(value, current.get(item["date"]))
                    baseline = {half: split_names(item.get("initial_" + half, item[half])) for half in ("am", "pm")}
                    item["individual"] = item.get("ambiguous", True) or item["changed"] or not same_plan(value, baseline)
        finally:
            db.close()
        return render_template("doctors.html", month=month, error=error, sheets=sheets, preview=preview,
                               extra_staff=extra_staff, current=current, needs_recheck=needs_recheck, aliases=aliases, loaded_filename=loaded_filename, selected_sheet=selected_sheet, saved=request.args.get("saved") == "1")

    @app.route("/doctors/edit", methods=["GET", "POST"])
    def doctor_edit():
        month = request.args.get("month", "")
        day_text = request.args.get("day", "")
        try:
            day = date.fromisoformat(day_text)
            if day.strftime("%Y-%m") != month:
                raise ValueError
        except ValueError:
            abort(400)
        session.setdefault("csrf_token", secrets.token_hex(32))
        session.setdefault("import_owner", secrets.token_hex(24))
        db = connect_db()
        error = None
        proposed = None
        try:
            db.execute("CREATE TABLE IF NOT EXISTS doctor_plans(month TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS doctor_edit_drafts(owner TEXT PRIMARY KEY, month TEXT, day TEXT, original TEXT, proposed TEXT)")
            row = db.execute("SELECT data FROM doctor_plans WHERE month=?", (month,)).fetchone()
            if not row:
                abort(404)
            original = row["data"]
            current = json.loads(original)
            if day_text not in current:
                abort(404)
            values = {half: "/".join(current[day_text][half]) for half in ("am", "pm")}
            if request.method == "POST":
                if not secrets.compare_digest(session["csrf_token"], request.form.get("csrf_token", "")):
                    abort(400)
                try:
                    if request.form.get("action") == "preview":
                        values = {half: request.form.get(half, "") for half in ("am", "pm")}
                        proposed = {half: split_names(values[half]) for half in ("am", "pm")}
                        for half, names in proposed.items():
                            if len(names) != len(set(names)) or any(len(name) > 50 for name in names):
                                raise ValueError("名前は50文字以内とし、同じ時間帯の重複を修正してください。")
                        if day.weekday() == 6 and any(proposed.values()):
                            raise ValueError("日曜は全日休診のため、医師は登録できません。")
                        if day.weekday() == 4 and proposed["pm"]:
                            raise ValueError("金曜午後は診療なしのため、医師は登録できません。")
                        db.execute("INSERT INTO doctor_edit_drafts VALUES (?, ?, ?, ?, ?) ON CONFLICT(owner) DO UPDATE SET month=excluded.month, day=excluded.day, original=excluded.original, proposed=excluded.proposed",
                                   (session["import_owner"], month, day_text, original, json.dumps(proposed, ensure_ascii=False)))
                        db.commit()
                    elif request.form.get("action") == "confirm":
                        draft = db.execute("SELECT * FROM doctor_edit_drafts WHERE owner=?", (session["import_owner"],)).fetchone()
                        if not draft or draft["month"] != month or draft["day"] != day_text:
                            raise ValueError("変更内容をもう一度確認してください。")
                        proposed = json.loads(draft["proposed"])
                        if day.weekday() == 6 and any(proposed.values()):
                            raise ValueError("日曜は全日休診のため、医師は登録できません。")
                        if draft["original"] != original:
                            raise ValueError("別の画面で予定が変更されました。編集画面を開き直してください。")
                        if request.form.get("confirmed") != "yes":
                            raise ValueError("変更前後を確認してチェックしてください。")
                        expected_token = hashlib.sha256((draft["original"] + draft["proposed"]).encode()).hexdigest()
                        if not secrets.compare_digest(expected_token, request.form.get("edit_token", "")):
                            raise ValueError("確認中の変更内容が別の画面で更新されました。変更前後をもう一度確認してください。")
                        updated = dict(current)
                        updated[day_text] = proposed
                        encoded = json.dumps(updated, ensure_ascii=False)
                        result = db.execute("UPDATE doctor_plans SET data=? WHERE month=? AND data=?", (encoded, month, original))
                        if result.rowcount != 1:
                            raise ValueError("別の画面で予定が変更されました。編集画面を開き直してください。")
                        # 既に月全体が確認済みの場合だけ、その状態を引き継ぐ。
                        db.execute("UPDATE doctor_plan_reviews SET data=? WHERE month=? AND data=? AND version=?",
                                   (encoded, month, original, IMPORT_VERSION))
                        db.execute("DELETE FROM doctor_edit_drafts WHERE owner=?", (session["import_owner"],))
                        db.commit()
                        return redirect(url_for("doctor_import", month=month, saved="1") + "#saved-plans")
                    else:
                        abort(400)
                except ValueError as exc:
                    db.rollback()
                    error = str(exc)
        finally:
            db.close()
        edit_token = hashlib.sha256((original + json.dumps(proposed, ensure_ascii=False)).encode()).hexdigest() if proposed is not None else ""
        return render_template("doctor_edit.html", edit_token=edit_token, month=month, day=day_text, current=current[day_text],
                               proposed=proposed, values=values, friday=day.weekday() == 4, sunday=day.weekday() == 6, error=error)
