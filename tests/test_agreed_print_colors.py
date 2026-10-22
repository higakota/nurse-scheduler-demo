import unittest
from flask import render_template
from app import app
from schedule_display import monthly_display

class AgreedPrintColorsTest(unittest.TestCase):
    def display(self,cancelled=False,pair="DD"):
        person=dict(id=1,name="職員仮名",employment="full",is_help=0)
        monthly=dict(agreed_wish_changes=[dict(staff_id=1,date="2026-09-01",original_wish="full",work_period="full",cancelled=cancelled)])
        return monthly_display(["2026-09-01"],[person],[[pair]],monthly=monthly,comparison_inputs=dict(wishes={},leaves={}))

    def test_agreed_attendance_is_red_and_original_wish_stays_below(self):
        display=self.display()
        cell=display["rows"][0]["cells"][0]
        self.assertTrue(cell["agreed_work"])
        self.assertEqual(cell["request_segments"][0]["label"],"休")
        with app.test_request_context("/schedule/manual?month=2026-09"):
            page=render_template("_schedule_grid.html",month="2026-09",display=display,is_draft=False)
        self.assertIn("paper-agreed-work",page)
        self.assertIn('paper-request-wish">(休)</span>',page)
        self.assertNotIn('class="paper-schedule comparison-enabled"',page)
        self.assertNotIn('data-compare-schedule="saved" checked',page)
        self.assertNotIn('class="request-agreed-note"',page)

    def test_cancelled_or_non_working_changes_are_not_marked_red(self):
        self.assertFalse(self.display(cancelled=True)["rows"][0]["cells"][0]["agreed_work"])
        self.assertFalse(self.display(pair="RR")["rows"][0]["cells"][0]["agreed_work"])

    def test_original_paid_leave_is_preserved_below_agreed_work(self):
        person=dict(id=1,name="職員仮名",employment="full",is_help=0)
        monthly=dict(agreed_wish_changes=[dict(staff_id=1,date="2026-09-01",original_wish="",original_paid="full",work_period="full")])
        display=monthly_display(["2026-09-01"],[person],[["DD"]],monthly=monthly,comparison_inputs=dict(wishes={},leaves={}))
        cell=display["rows"][0]["cells"][0]
        self.assertTrue(cell["agreed_work"])
        self.assertEqual(cell["request_segments"][0]["label"],"有休")
