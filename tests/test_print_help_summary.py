import copy,unittest
import test_scheduler as fixtures
from schedule_display import monthly_display
from app import app

class PrintHelpSummaryTest(unittest.TestCase):
    def display(self):
        data=fixtures.sample()
        people=data["staff"]+[
            dict(id=9,name="事前仮名",role="nurse",employment="full",is_help=1,advance_help=1),
            dict(id=10,name="応援看護仮名",role="nurse",employment="full",is_help=1),
            dict(id=11,name="応援検査仮名",role="technician",employment="full",is_help=1)]
        days=list(data["doctor_plans"])
        grid=[["RR"]*len(people) for _ in days]
        grid[1][-3:]=["DD","DR","CC"]
        grid[2][-1]="RC"
        original=copy.deepcopy(grid)
        result=monthly_display(days,people,grid,monthly=data["monthly_settings"],comparison_inputs=dict(wishes={},leaves={}))
        self.assertEqual(grid,original)
        return result

    def test_groups_only_requested_helpers_and_keeps_time_and_role(self):
        display=self.display()
        self.assertTrue(display["has_requested_help"])
        self.assertEqual(display["requested_help"][1],[
            dict(name="応援看護仮名",role="看",period="午前"),
            dict(name="応援検査仮名",role="検",period="全日")])
        self.assertEqual(display["requested_help"][2][0]["period"],"午後")
        self.assertEqual(display["requested_help"][0],[])

    def render(self,editable=False,preview=False):
        from flask import render_template
        with app.test_request_context("/schedule/manual?month=2026-02"):
            return render_template("_schedule_grid.html",display=self.display(),month="2026-02",is_draft=False,manual_editable=editable,preview=preview)

    def test_printable_view_has_one_help_row_and_separate_advance_person(self):
        page=self.render().split('<details class="paper-placement"',1)[0]
        self.assertIn('class="paper-help-summary"',page)
        self.assertIn('<th scope="row">事前仮名',page)
        self.assertNotIn('<th scope="row">応援看護仮名',page)
        self.assertIn('<strong>応援看護仮名</strong><small>看・午前</small>',page)
        self.assertIn('<strong>応援検査仮名</strong><small>検・全日</small>',page)

    def test_editor_groups_helpers_but_keeps_original_edit_targets(self):
        page=self.render(True)
        self.assertIn('class="paper-help-summary"',page)
        self.assertEqual(page.count('class="paper-staff-block grouped-helper-row"'),2)
        self.assertIn('data-person="6"',page)
        self.assertIn('data-help-summary-day="1"',page)
        self.assertIn('id="manual-helper-picker"',page)
        self.assertIn('data-helper-person="6"',page)
        self.assertNotIn('data-compare-schedule="saved" checked',page)
        self.assertIn('class="paper-schedule"',page)

    def test_change_review_keeps_individual_changes_visible(self):
        page=self.render(False,True)
        self.assertNotIn('class="paper-help-summary"',page)
        self.assertIn('<th scope="row">応援看護仮名',page)
