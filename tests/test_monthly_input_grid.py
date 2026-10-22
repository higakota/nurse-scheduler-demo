import io
import json
import re
import unittest
import zipfile
from xml.etree import ElementTree as ET
import test_monthly as monthly
import test_excel_events as excel
from app import connect_db
from doctor_import import parse_schedule
from excel_events import extract_events, drawing_date


class InputSheetTest(unittest.TestCase):
    setUp=monthly.MonthlyTest.setUp
    tearDown=monthly.MonthlyTest.tearDown
    post=monthly.MonthlyTest.post

    def test_grid_has_all_staff_dates_and_single_save_form(self):
        db=connect_db()
        db.execute("INSERT INTO staff(name,role,employment,veteran) VALUES ('仮名次郎','nurse','part',0)")
        db.commit()
        for month,length in (("2026-10",31),("2028-02",29)):
            text=self.client.get("/monthly?month="+month).get_data(as_text=True)
            self.assertEqual(text.count('data-input-person="'),2*length)
            self.assertEqual(text.count('id="absence-form"'),1)
            self.assertIn('id="absence-person-view" hidden',text)
            wishes=text.split('id="wishes"',1)[1].split('id="absence-person-view"',1)[0]
            self.assertIn('input-sheet-fit',wishes)
            self.assertIn('class="input-doctor-inline"',wishes)
            self.assertNotIn('class="input-meeting-row"',wishes)
            self.assertNotIn('data-attendance-day=',wishes)
            self.assertNotIn('input-doctor-disclosure',wishes)
        db.close()

    def test_candidate_is_shown_on_date_but_not_registered(self):
        db=connect_db()
        db.execute("INSERT INTO excel_event_drafts VALUES ('test','2026-10',?)",(json.dumps(dict(extras=dict(closures=[],meetings=[dict(id="candidate",date="2026-10-02",title="仮名研修",source="仮名シート")]))),))
        db.commit()
        before=list(db.iterdump())
        page=self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        self.assertIn('data-attendance-day="2026-10-02"',page)
        self.assertIn('value="2026-10-02" selected',page)
        self.assertIn("参加者を指定",page)
        self.assertEqual(before,list(db.iterdump()))
        db.close()

    def test_existing_meeting_is_linked_to_editing_and_participant(self):
        self.post(action="meeting_add",meeting_date="2026-10-02",title="仮名会議",participants="1")
        page=self.client.get("/monthly?month=2026-10").get_data(as_text=True)
        self.assertIn('class="input-participating"',page)
        self.assertIn('data-meeting-day="2026-10-02"',page)
        self.assertIn('id="meeting-',page)
        self.assertIn("仮名会議",page)
        meeting_section=page.split('id="meetings"',1)[1].split('<h3>登録済み',1)[0]
        self.assertNotIn('class="input-static-wish"',meeting_section)
        self.assertNotIn('class="input-static-paid"',meeting_section)
        self.assertNotIn('class="input-doctor-row"',meeting_section)
        self.assertIn("医師予定を見る",meeting_section)



class DrawingDateTest(unittest.TestCase):
    def test_extent_resolves_date_and_keeps_paragraphs(self):
        original=excel.event_book()
        out=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as src,zipfile.ZipFile(out,"w") as dst:
            for name in src.namelist():
                data=src.read(name)
                if name=="xl/drawings/drawing1.xml":
                    data=data.replace(b"</x:from>",b'</x:from><x:ext cx="100000" cy="100000"/>')
                dst.writestr(name,data)
        raw=out.getvalue()
        meetings=extract_events(raw,"12月",parse_schedule(raw,"12月","2026-12"))["meetings"]
        self.assertEqual([m["date"] for m in meetings],["2026-12-02"]*2)
        self.assertEqual([m["title"] for m in meetings],["職場会議","感染委員会"])

    def test_large_offset_uses_visual_position_not_anchor_column(self):
        root=ET.fromstring('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        anchor=ET.fromstring('<x:oneCellAnchor xmlns:x="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"><x:from><x:col>2</x:col><x:colOff>600000</x:colOff></x:from><x:ext cx="300000"/></x:oneCellAnchor>')
        self.assertEqual(drawing_date(root,anchor,{"C":"2026-12-01","D":"2026-12-02"}),"2026-12-02")

    def test_unknown_geometry_stays_blank(self):
        root=ET.fromstring('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        anchor=ET.fromstring('<x:oneCellAnchor xmlns:x="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"><x:from><x:col>2</x:col></x:from></x:oneCellAnchor>')
        self.assertEqual(drawing_date(root,anchor,{"C":"2026-12-01"}),"")
