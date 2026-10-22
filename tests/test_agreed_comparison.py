import copy
import unittest
from schedule_display import monthly_display


class AgreedComparisonTest(unittest.TestCase):
    def display(self, grid, wishes, records):
        people = [dict(id=1,name="看護仮名",role="nurse",employment="full",is_help=0)]
        monthly = dict(agreed_wish_changes=records)
        comparison = dict(wishes=wishes,leaves={})
        before = copy.deepcopy((grid,monthly,comparison))
        result = monthly_display(["2026-11-02","2026-11-04"],people,grid,monthly,comparison_inputs=comparison)
        self.assertEqual((grid,monthly,comparison),before)
        return result["rows"][0]["cells"]

    def record(self, **values):
        return dict(staff_id="1",date="2026-11-02",original_wish="full",
                    work_period="full",replacement_date="",**values)

    def test_original_full_wish_is_visible_after_agreed_attendance(self):
        cells=self.display([["DD"],["RR"]],{},[self.record()])
        self.assertEqual(cells[0]["request_segments"],[dict(label="休",kind="wish")])
        self.assertEqual(cells[0]["adjustment_label"],"了承出勤")
        self.assertIn("変更後の希望休：なし",cells[0]["request_hint"])

    def test_original_full_wish_remains_visible_after_half_day_agreement(self):
        record=self.record()
        record["work_period"]="am"
        cells=self.display([["DR"],["RR"]],{"1_2026-11-02":"pm"},[record])
        self.assertEqual(cells[0]["request_segments"],[dict(label="休",kind="wish")])
        self.assertIn("午前",cells[0]["adjustment_hint"])
        self.assertIn("変更後の希望休：午後",cells[0]["adjustment_hint"])

    def test_multiple_agreements_preserve_the_first_original_wish(self):
        first=self.record()
        first["work_period"]="am"
        second=self.record()
        second.update(original_wish="pm",work_period="pm")
        cells=self.display([["DD"],["RR"]],{},[first,second])
        self.assertEqual(cells[0]["request_segments"],[dict(label="休",kind="wish")])
        self.assertIn("午前、午後",cells[0]["adjustment_hint"])

    def test_replacement_rest_is_identified_separately(self):
        record=self.record()
        record["replacement_date"]="2026-11-04"
        cells=self.display([["DD"],["RR"]],{"1_2026-11-04":"full"},[record])
        self.assertEqual(cells[1]["adjustment_label"],"代替休")
        self.assertEqual(cells[1]["request_segments"],[dict(label="休",kind="wish")])

    def test_no_audit_does_not_invent_an_original_wish(self):
        cells=self.display([["DD"],["RR"]],{},[])
        self.assertFalse(cells[0]["has_request"])
        self.assertEqual(cells[0]["adjustment_label"],"")
