import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import date

from app import app, connect_db
from doctor_import import parse_schedule


def workbook():
    output = io.BytesIO()
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rows = []
    for day in range(1, 32):
        number = day + 2
        column = ""
        while number:
            number, digit = divmod(number - 1, 26)
            column = chr(65 + digit) + column
        serial = (date(2026, 12, day) - date(1899, 12, 30)).days
        rows.append((column, serial))
    with zipfile.ZipFile(output, "w") as book:
        book.writestr("xl/workbook.xml", '<workbook xmlns="' + namespace + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="12月" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        book.writestr("xl/sharedStrings.xml", '<sst xmlns="' + namespace + '"><si><t>医A/医B　　　医C</t><rPh><t>ふりがな</t></rPh></si></sst>')
        body = '<row r="4">' + "".join('<c r="' + col + '4"><v>' + str(serial) + '</v></c>' for col, serial in rows) + '</row>'
        body += '<row r="6"><c r="C6" t="s"><v>0</v></c><c r="D6" t="inlineStr"><is><t>医D</t></is></c></row>'
        book.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="' + namespace + '"><sheetData>' + body + '</sheetData></worksheet>')
    return output.getvalue()


class DoctorImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config["DATABASE"]
        app.config.update(TESTING=True, DATABASE=str(Path(self.temp.name) / "db.sqlite3"))
        self.client = app.test_client()
        self.client.get("/doctors?month=2026-12")
        with self.client.session_transaction() as state:
            self.token = state["csrf_token"]

    def tearDown(self):
        app.config["DATABASE"] = self.old
        self.temp.cleanup()

    def post(self, **data):
        return self.client.post("/doctors?month=2026-12", data=dict(csrf_token=self.token, **data))

    def read(self):
        response = self.post(action="upload", workbook=(io.BytesIO(workbook()), "test.xlsx"))
        self.assertEqual(response.status_code, 200)
        response = self.post(action="read", sheet="12月")
        self.assertIn("確認・修正して保存", response.get_data(as_text=True))

    def plan(self):
        db = connect_db()
        try:
            row = db.execute("SELECT data FROM doctor_plans WHERE month='2026-12'").fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def save_fields(self):
        fields = dict(action="save", confirmed="yes", aliases="医A=医師 花子")
        for day in range(1, 32):
            fields["am_2026-12-" + str(day).zfill(2)] = "医A/医B" if day == 1 else ""
            fields["pm_2026-12-" + str(day).zfill(2)] = "医C" if day == 1 else ""
        for day in range(1, 32):
            fields["review_2026-12-" + str(day).zfill(2)] = "yes"
        return fields

    def test_parser_excludes_phonetics_and_marks_ambiguity(self):
        rows = parse_schedule(workbook(), "12月", "2026-12")
        self.assertEqual(len(rows), 31)
        self.assertEqual((rows[0]["am"], rows[0]["pm"]), ("医A/医B", "医C"))
        self.assertNotIn("ふりがな", rows[0]["raw"])
        self.assertTrue(rows[1]["note"])
        self.assertTrue(rows[2]["note"])
        with self.assertRaisesRegex(ValueError, "2026-11.*2026-12.*0/30"):
            parse_schedule(workbook(), "12月", "2026-11")

    def test_confirmation_then_save_and_alias_reuse(self):
        self.read()
        self.assertIsNone(self.plan())
        fields = self.save_fields()
        fields.pop("confirmed")
        self.post(**fields)
        self.assertIsNone(self.plan())
        fields["confirmed"] = "yes"
        self.assertEqual(self.post(**fields).status_code, 302)
        self.assertEqual(self.plan()["2026-12-01"]["am"], ["医師 花子", "医B"])
        self.assertIn("医師 花子", self.client.get("/doctors?month=2026-12").get_data(as_text=True))
        self.read()
        self.assertIn("医師 花子", self.client.get("/doctors?month=2026-12").get_data(as_text=True))
        # 既存予定は明示的な置換チェックなしでは更新しない。
        changed = self.save_fields()
        changed["am_2026-12-01"] = "別の医師"
        self.post(**changed)
        self.assertEqual(self.plan()["2026-12-01"]["am"], ["医師 花子", "医B"])
        changed["replace"] = "yes"
        self.assertEqual(self.post(**changed).status_code, 302)
        self.assertEqual(self.plan()["2026-12-01"]["am"], ["別の医師"])

    def test_bad_file_csrf_and_month(self):
        self.assertEqual(self.post(action="upload", workbook=(io.BytesIO(b"not excel"), "test.xlsx")).status_code, 200)
        self.assertIsNone(self.plan())
        self.assertEqual(self.client.post("/doctors?month=2026-12", data={"action": "read"}).status_code, 400)
        self.assertEqual(self.client.get("/doctors?month=2026-13").status_code, 400)

    def test_stale_preview_does_not_overwrite(self):
        self.read()
        db = connect_db()
        db.execute("INSERT INTO doctor_plans VALUES ('2026-12', ?)", (json.dumps({"changed": True}),))
        db.commit()
        db.close()
        fields = self.save_fields()
        fields["replace"] = "yes"
        response = self.post(**fields)
        self.assertIn("変更されました", response.get_data(as_text=True))
        self.assertEqual(self.plan(), {"changed": True})

    def test_duplicate_name_rejected(self):
        self.read()
        fields = self.save_fields()
        fields["am_2026-12-01"] = "医A/医A"
        self.post(**fields)
        self.assertIsNone(self.plan())

    def test_sheet_initial_selection_matches_target_month(self):
        self.post(action="upload", workbook=(io.BytesIO(workbook()), "test.xlsx"))
        page = self.client.get("/doctors?month=2026-12").get_data(as_text=True)
        self.assertIn('<option value="12月" selected>12月</option>', page)
        other = self.client.get("/doctors?month=2026-11").get_data(as_text=True)
        self.assertNotIn('<option value="12月" selected>12月</option>', other)

    def test_trailing_spaces_in_sheet_name_and_filename_remain(self):
        from html.parser import HTMLParser

        class Options(HTMLParser):
            def __init__(self):
                super().__init__()
                self.values = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "option" and "selected" in attrs:
                    self.values.append(attrs.get("value"))

        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(output, "w") as target:
            for name in source.namelist():
                raw = source.read(name)
                if name == "xl/workbook.xml":
                    raw = raw.decode().replace('name="12月"', 'name="12月  "').encode()
                target.writestr(name, raw)
        response = self.post(action="upload", workbook=(io.BytesIO(output.getvalue()), "予定表.xlsx"))
        page = response.get_data(as_text=True)
        self.assertIn("読込済み：予定表.xlsx", page)
        options = Options()
        options.feed(page)
        self.assertIn("12月  ", options.values)
        response = self.post(action="read", sheet=options.values[0])
        self.assertIn("確認・修正して保存", response.get_data(as_text=True))
        page = self.client.get("/doctors?month=2026-12").get_data(as_text=True)
        self.assertIn("読込済み：予定表.xlsx", page)
        self.assertIsNone(self.plan())

    def test_vertical_order_and_ambiguous_single_group(self):
        output = io.BytesIO()
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(output, "w") as target:
            for name in source.namelist():
                raw = source.read(name)
                if name == "xl/worksheets/sheet1.xml":
                    raw = raw.decode().replace('r="C6"', 'r="C6" s="0"').replace('r="D6"', 'r="D6" s="0"').encode()
                target.writestr(name, raw)
            target.writestr("xl/styles.xml", '<styleSheet xmlns="' + ns + '"><cellXfs><xf><alignment textRotation="255" wrapText="1"/></xf></cellXfs></styleSheet>')
        rows = parse_schedule(output.getvalue(), "12月", "2026-12")
        self.assertEqual(rows[0]["am"], "医C")
        self.assertEqual(rows[0]["pm"], "医A/医B")
        self.assertEqual(rows[0]["cell"], "C6")
        self.assertEqual(rows[0]["rotation"], 255)
        self.assertEqual((rows[1]["am"], rows[1]["pm"]), ("", ""))
        self.assertIn("自動割当はしていません", rows[1]["note"])

    def test_day_review_required_and_legacy_preview_rejected(self):
        self.read()
        fields = self.save_fields()
        fields.pop("review_2026-12-02")
        response = self.post(**fields)
        self.assertIn("日別確認が必要", response.get_data(as_text=True))
        self.assertIsNone(self.plan())
        db = connect_db()
        row = db.execute("SELECT owner, preview FROM doctor_import_draft").fetchone()
        old = json.loads(row["preview"])
        old.pop("version")
        db.execute("UPDATE doctor_import_draft SET preview=? WHERE owner=?", (json.dumps(old), row["owner"]))
        db.commit()
        db.close()
        response = self.post(**self.save_fields())
        self.assertIn("先にシートを読み取ってください", response.get_data(as_text=True))
        self.assertIsNone(self.plan())

    def test_legacy_saved_plan_marked_for_recheck(self):
        db = connect_db()
        db.execute("INSERT INTO doctor_plans VALUES ('2026-12', ?)", (json.dumps({"2026-12-01": {"am": ["医A"], "pm": ["医B"]}}),))
        db.commit()
        db.close()
        page = self.client.get("/doctors?month=2026-12").get_data(as_text=True)
        self.assertIn("午前・午後が逆の可能性", page)
        self.assertEqual(self.plan()["2026-12-01"]["am"], ["医A"])

    def test_friday_all_doctors_are_morning_even_in_vertical_layout(self):
        output = io.BytesIO()
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(output, "w") as target:
            for name in source.namelist():
                raw = source.read(name)
                if name == "xl/worksheets/sheet1.xml":
                    raw = raw.decode().replace('</row></sheetData>',
                        '<c r="F6" t="inlineStr"><is><t>医A/医B</t></is></c>'
                        '<c r="M6" t="inlineStr"><is><t>医A　　　医B/医A</t></is></c></row></sheetData>').encode()
                target.writestr(name, raw)
            target.writestr("xl/styles.xml", '<styleSheet xmlns="' + ns + '"><cellXfs><xf><alignment textRotation="255"/></xf></cellXfs></styleSheet>')
        rows = parse_schedule(output.getvalue(), "12月", "2026-12")
        for day in ("2026-12-04", "2026-12-11"):
            row = next(row for row in rows if row["date"] == day)
            self.assertEqual(row["am"], "医A/医B")
            self.assertEqual(row["pm"], "")
            self.assertTrue(row["friday"])
            self.assertIn("午後は診療なし", row["note"])

    def test_friday_afternoon_doctor_cannot_be_saved(self):
        self.read()
        fields = self.save_fields()
        fields["pm_2026-12-04"] = "医A"
        response = self.post(**fields)
        self.assertIn("金曜午後は診療なし", response.get_data(as_text=True))
        self.assertIsNone(self.plan())
        fields["pm_2026-12-04"] = ""
        fields["am_2026-12-04"] = "医B"
        self.assertEqual(self.post(**fields).status_code, 302)
        self.assertEqual(self.plan()["2026-12-04"], {"am": ["医B"], "pm": []})

    def test_clear_days_can_be_confirmed_together_but_changed_day_requires_check(self):
        self.read()
        fields = self.save_fields()
        fields.pop("review_2026-12-01")
        self.assertEqual(self.post(**fields).status_code, 302)
        self.read()
        fields["replace"] = "yes"
        self.assertEqual(self.post(**fields).status_code, 302)
        self.read()
        fields["am_2026-12-01"] = "別の医師"
        response = self.post(**fields)
        self.assertIn("日別確認が必要", response.get_data(as_text=True))
        self.assertEqual(self.plan()["2026-12-01"]["am"], ["医師 花子", "医B"])
        fields["review_2026-12-01"] = "yes"
        self.assertEqual(self.post(**fields).status_code, 302)

    def test_saved_day_edit_requires_preview_and_confirmation(self):
        self.read()
        self.post(**self.save_fields())
        before = self.plan()
        url = "/doctors/edit?month=2026-12&day=2026-12-01"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(url, data=dict(csrf_token=self.token, action="preview", am="医師 次郎", pm=""))
        self.assertIn("変更前 → 変更後", response.get_data(as_text=True))
        import re
        edit_token = re.search(r'name="edit_token" value="([^"]+)"', response.get_data(as_text=True))[1]
        self.assertEqual(self.plan(), before)
        self.client.post(url, data=dict(csrf_token=self.token, action="confirm"))
        self.assertEqual(self.plan(), before)
        self.assertEqual(self.client.post(url, data=dict(csrf_token=self.token, action="confirm", confirmed="yes", edit_token=edit_token)).status_code, 302)
        after = self.plan()
        self.assertEqual(after["2026-12-01"], {"am": ["医師 次郎"], "pm": []})
        self.assertEqual(after["2026-12-02"], before["2026-12-02"])
        page = self.client.get("/doctors?month=2026-12").get_data(as_text=True)
        self.assertNotIn("以前の読取方式", page)

    def test_saved_day_edit_rejects_friday_pm_and_stale_changes(self):
        self.read()
        self.post(**self.save_fields())
        url = "/doctors/edit?month=2026-12&day=2026-12-04"
        response = self.client.post(url, data=dict(csrf_token=self.token, action="preview", am="医A", pm="医B"))
        self.assertIn("金曜午後は診療なし", response.get_data(as_text=True))
        self.assertEqual(self.plan()["2026-12-04"]["pm"], [])
        url = "/doctors/edit?month=2026-12&day=2026-12-01"
        self.client.post(url, data=dict(csrf_token=self.token, action="preview", am="医A", pm=""))
        db = connect_db()
        altered = self.plan()
        altered["2026-12-02"]["am"] = ["医C"]
        db.execute("UPDATE doctor_plans SET data=? WHERE month='2026-12'", (json.dumps(altered),))
        db.commit()
        db.close()
        response = self.client.post(url, data=dict(csrf_token=self.token, action="confirm", confirmed="yes"))
        self.assertIn("別の画面で予定が変更", response.get_data(as_text=True))
        self.assertEqual(self.plan(), altered)

    def test_saved_day_edit_cannot_confirm_without_draft_or_csrf(self):
        self.read()
        self.post(**self.save_fields())
        url = "/doctors/edit?month=2026-12&day=2026-12-01"
        self.assertEqual(self.client.post(url, data=dict(action="preview", am="医A")).status_code, 400)
        response = self.client.post(url, data=dict(csrf_token=self.token, action="confirm", confirmed="yes"))
        self.assertIn("もう一度確認", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/doctors/edit?month=2026-12&day=2026-11-01").status_code, 400)

    def test_edit_confirm_cannot_save_another_tabs_preview(self):
        import re
        self.read()
        self.post(**self.save_fields())
        url = "/doctors/edit?month=2026-12&day=2026-12-01"
        first = self.client.post(url, data=dict(csrf_token=self.token, action="preview", am="医A", pm=""))
        token = re.search(r'name="edit_token" value="([^"]+)"', first.get_data(as_text=True))[1]
        before = self.plan()
        self.client.post(url, data=dict(csrf_token=self.token, action="preview", am="医B", pm=""))
        response = self.client.post(url, data=dict(csrf_token=self.token, action="confirm", confirmed="yes", edit_token=token))
        self.assertIn("確認中の変更内容が別の画面", response.get_data(as_text=True))
        self.assertEqual(self.plan(), before)

    def test_sunday_ignores_excel_doctors_and_needs_no_blank_review(self):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(output, "w") as target:
            for name in source.namelist():
                raw = source.read(name)
                if name == "xl/worksheets/sheet1.xml":
                    raw = raw.decode().replace('</row></sheetData>', '<c r="H6" t="inlineStr"><is><t>医A　　　医B</t></is></c></row></sheetData>').encode()
                target.writestr(name, raw)
        rows = parse_schedule(output.getvalue(), "12月", "2026-12")
        sunday = next(row for row in rows if row["date"] == "2026-12-06")
        self.assertEqual((sunday["am"], sunday["pm"]), ("", ""))
        self.assertTrue(sunday["sunday"])
        self.assertFalse(sunday["ambiguous"])
        self.read()
        fields = self.save_fields()
        fields.pop("review_2026-12-06")
        self.assertEqual(self.post(**fields).status_code, 302)

    def test_sunday_doctor_is_rejected_on_import_and_edit(self):
        self.read()
        fields = self.save_fields()
        for half in ("am", "pm"):
            invalid = dict(fields)
            invalid[half + "_2026-12-06"] = "医A"
            response = self.post(**invalid)
            self.assertIn("日曜は全日休診", response.get_data(as_text=True))
            self.assertIsNone(self.plan())
        self.assertEqual(self.post(**fields).status_code, 302)
        url = "/doctors/edit?month=2026-12&day=2026-12-06"
        for half in ("am", "pm"):
            response = self.client.post(url, data=dict(csrf_token=self.token, action="preview", **{half: "医A"}))
            self.assertIn("日曜は全日休診", response.get_data(as_text=True))
        self.assertEqual(self.plan()["2026-12-06"], {"am": [], "pm": []})

    def test_old_month_review_does_not_require_every_unchanged_day(self):
        self.read()
        self.post(**self.save_fields())
        db = connect_db()
        db.execute("DELETE FROM doctor_plan_reviews WHERE month='2026-12'")
        db.commit()
        db.close()
        self.read()
        page = self.client.get("/doctors?month=2026-12").get_data(as_text=True)
        self.assertIn("月間一覧で再確認", page)
        import re
        card = re.search(r'<article[^>]*data-required="([^"]+)"[^>]*>.*?2026-12-01', page, re.S)
        self.assertEqual(card[1], "no")
        fields = self.save_fields()
        fields.pop("review_2026-12-01")
        fields["replace"] = "yes"
        self.assertEqual(self.post(**fields).status_code, 302)
