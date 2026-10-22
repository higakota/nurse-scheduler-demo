import io
import unittest
import zipfile
from xml.etree import ElementTree as ET
from doctor_import import parse_schedule, NS
from test_doctor_import import workbook


def colored_book(shared=None, style="", styles=None, theme=None, conditional=False):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(workbook())) as source, zipfile.ZipFile(output, "w") as dest:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if shared is not None and entry.filename == "xl/sharedStrings.xml":
                content = ('<sst xmlns="' + NS["s"] + '"><si>' + shared + '</si></sst>').encode()
            if entry.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(b'r="C6" t="s"', ('r="C6" t="s" ' + style).encode())
                if conditional:
                    rule = conditional if isinstance(conditional, str) else '<conditionalFormatting sqref="C6"><cfRule type="expression"><formula>TRUE</formula></cfRule></conditionalFormatting>'
                    content = content.replace(b'</worksheet>', rule.encode() + b'</worksheet>')
            dest.writestr(entry.filename, content)
        if styles:
            dest.writestr("xl/styles.xml", styles)
        if theme:
            dest.writestr("xl/theme/theme1.xml", theme)
    return output.getvalue()


class DoctorColorsTest(unittest.TestCase):
    def row(self, **kwargs):
        return parse_schedule(colored_book(**kwargs), "12月", "2026-12")[0]

    def test_rich_red_name_is_absent_and_black_names_remain(self):
        row = self.row(shared='<r><t>医A/</t></r><r><rPr><color rgb="FFFF0000"/></rPr><t>医B</t></r><r><t>　　　医C</t></r>')
        self.assertEqual((row["am"], row["pm"]), ("医A", "医C"))
        self.assertFalse(row["ambiguous"])

    def test_entire_red_column_does_not_shift_am_pm(self):
        row = self.row(shared='<r><rPr><color rgb="FFFF0000"/></rPr><t>医A</t></r><r><t>　　　医C</t></r>')
        self.assertEqual((row["am"], row["pm"]), ("", "医C"))

    def test_split_name_across_runs_and_phonetics(self):
        row = self.row(shared='<r><rPr><color rgb="FFFF0000"/></rPr><t>医</t></r><r><rPr><color rgb="FFFF0000"/></rPr><t>A</t></r><r><t>　　　医C</t></r><rPh><t>ふりがな</t></rPh>')
        self.assertEqual((row["am"], row["pm"]), ("", "医C"))

    def test_partially_red_name_is_not_assumed_present(self):
        row = self.row(shared='<r><rPr><color rgb="FFFF0000"/></rPr><t>医</t></r><r><t>A　　　医C</t></r>')
        self.assertEqual((row["am"], row["pm"]), ("", ""))
        self.assertTrue(row["ambiguous"])

    def test_cell_font_red_and_rich_black_override(self):
        styles = '<styleSheet xmlns="' + NS["s"] + '"><fonts><font><color rgb="FFFF0000"/></font></fonts><cellXfs><xf fontId="0"/></cellXfs></styleSheet>'
        row = self.row(styles=styles, shared='<r><t>医A　　　</t></r><r><rPr><color rgb="FF000000"/></rPr><t>医C</t></r>')
        self.assertEqual((row["am"], row["pm"]), ("", "医C"))

    def test_indexed_red(self):
        styles = '<styleSheet xmlns="' + NS["s"] + '"><fonts><font><color indexed="10"/></font></fonts><cellXfs><xf fontId="0"/></cellXfs></styleSheet>'
        row = self.row(styles=styles)
        self.assertEqual((row["am"], row["pm"]), ("", ""))

    def test_unknown_theme_and_conditional_format_require_manual_review(self):
        row = self.row(shared='<r><rPr><color theme="5"/></rPr><t>医A</t></r><r><t>　　　医C</t></r>')
        self.assertEqual((row["am"], row["pm"]), ("", ""))
        self.assertTrue(row["ambiguous"])
        row = self.row(conditional=True)
        self.assertEqual((row["am"], row["pm"]), ("", ""))
        self.assertTrue(row["ambiguous"])

    def test_background_only_conditional_format_keeps_vertical_doctors_and_red_absences(self):
        styles='<styleSheet xmlns="'+NS["s"]+'"><fonts><font><color rgb="FF000000"/></font></fonts><cellXfs><xf fontId="0"><alignment textRotation="255"/></xf></cellXfs><dxfs><dxf><fill><patternFill><bgColor rgb="FFE0E0E0"/></patternFill></fill></dxf></dxfs></styleSheet>'
        conditional='<conditionalFormatting sqref="C6"><cfRule type="expression" dxfId="0"><formula>TRUE</formula></cfRule></conditionalFormatting>'
        shared='<r><rPr><color rgb="FFFF0000"/></rPr><t>医A</t></r><r><t>/医B　　　医C/</t></r><r><rPr><color rgb="FFFF0000"/></rPr><t>医A</t></r>'
        row=self.row(styles=styles,shared=shared,conditional=conditional)
        self.assertEqual((row["am"],row["pm"]),("医C","医B"))
        self.assertFalse(row["ambiguous"])
        self.assertIn("赤字",row["note"])

    def test_font_color_conditional_format_still_requires_review(self):
        styles='<styleSheet xmlns="'+NS["s"]+'"><cellXfs><xf/></cellXfs><dxfs><dxf><font><color rgb="FFFF0000"/></font></dxf></dxfs></styleSheet>'
        conditional='<conditionalFormatting sqref="C6"><cfRule type="expression" dxfId="0"><formula>TRUE</formula></cfRule></conditionalFormatting>'
        row=self.row(styles=styles,conditional=conditional)
        self.assertEqual((row["am"],row["pm"]),("",""))
        self.assertTrue(row["ambiguous"])

    def test_unknown_conditional_style_is_not_assumed_background_only(self):
        conditional='<conditionalFormatting sqref="C6"><cfRule type="expression" dxfId="99"><formula>TRUE</formula></cfRule></conditionalFormatting>'
        row=self.row(conditional=conditional)
        self.assertEqual((row["am"],row["pm"]),("",""))
        self.assertTrue(row["ambiguous"])

    def test_theme_red_and_vertical_columns(self):
        theme = '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:themeElements><a:clrScheme>' + ''.join('<a:c><a:srgbClr val="' + rgb + '"/></a:c>' for rgb in ("000000","FFFFFF","000000","FFFFFF","FF0000")) + '</a:clrScheme></a:themeElements></a:theme>'
        styles = '<styleSheet xmlns="' + NS["s"] + '"><fonts><font/></fonts><cellXfs><xf fontId="0"><alignment textRotation="255"/></xf></cellXfs></styleSheet>'
        row = self.row(styles=styles, theme=theme, shared='<r><rPr><color theme="4"/></rPr><t>医A</t></r><r><t>　　　医C</t></r>')
        self.assertEqual((row["am"], row["pm"]), ("医C", ""))

    def test_inline_red_and_friday_stay_morning_only(self):
        original = colored_book(shared='<r><t>医A/</t></r><r><rPr><color rgb="FFFF0000"/></rPr><t>医B</t></r><r><t>　　　医C</t></r>')
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, "w") as dest:
            shared = ET.fromstring(source.read("xl/sharedStrings.xml")).find("s:si", NS)
            for entry in source.infolist():
                content = source.read(entry.filename)
                if entry.filename.endswith("sheet1.xml"):
                    root = ET.fromstring(content)
                    cell = root.find('.//s:c[@r="C6"]', NS)
                    cell.set("r", "F6")
                    cell.set("t", "inlineStr")
                    cell.remove(cell.find("s:v", NS))
                    inline = ET.SubElement(cell, "{" + NS["s"] + "}is")
                    inline.extend(list(shared))
                    content = ET.tostring(root)
                dest.writestr(entry.filename, content)
        row = parse_schedule(output.getvalue(), "12月", "2026-12")[3]
        self.assertEqual((row["am"], row["pm"]), ("医A/医C", ""))

class DoctorColorConfirmationTest(unittest.TestCase):
    import test_doctor_import as fixtures
    setUp = fixtures.DoctorImportTest.setUp
    tearDown = fixtures.DoctorImportTest.tearDown
    post = fixtures.DoctorImportTest.post
    plan = fixtures.DoctorImportTest.plan
    save_fields = fixtures.DoctorImportTest.save_fields

    def test_clear_red_exclusion_can_be_saved_with_month_confirmation_only(self):
        raw = colored_book(shared='<r><t>医A/</t></r><r><rPr><color rgb="FFFF0000"/></rPr><t>医B</t></r><r><t>　　　医C</t></r>')
        self.post(action="upload", workbook=(io.BytesIO(raw), "test.xlsx"))
        self.post(action="read", sheet="12月")
        fields = self.save_fields()
        fields["am_2026-12-01"] = "医A"
        fields.pop("review_2026-12-01")
        response = self.post(**fields)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("医B", self.plan()["2026-12-01"]["am"])

    def test_uncertain_color_still_requires_individual_confirmation(self):
        raw = colored_book(conditional=True)
        self.post(action="upload", workbook=(io.BytesIO(raw), "test.xlsx"))
        self.post(action="read", sheet="12月")
        fields = self.save_fields()
        fields.pop("review_2026-12-01")
        response = self.post(**fields)
        self.assertEqual(response.status_code, 200)
        self.assertIn("日別確認が必要", response.get_data(as_text=True))
        self.assertIsNone(self.plan())
