import copy
import unittest
from schedule_display import monthly_display, grouped_shortages, merge_veteran_shortages


class PaperDisplayTest(unittest.TestCase):
    def test_work_labels_keep_half_day_meaning_without_changing_grid(self):
        days = ["2026-11-" + str(d).zfill(2) for d in range(1,9)]
        person = dict(id=1, name="看護 仮名", employment="full", is_help=0)
        grid = [("AA",), ("AM",), ("AR",), ("RA",), ("PP",), ("AP",), ("AO",), ("PR",)]
        original = copy.deepcopy(grid)
        result = monthly_display(days, [person], grid, targets={"1": 2})
        self.assertEqual([cell["label"] for cell in result["rows"][0]["cells"]],
                         ["日", "日/会", "日/休", "休/日", "有休", "日/有休", "日", "有休/休"])
        self.assertEqual(result["rows"][0]["cells"][6]["detail"], "診/O")
        self.assertIn("午後：業", result["rows"][0]["cells"][6]["hint"])
        self.assertEqual(grid, original)
        self.assertEqual(result["rows"][0]["total"], "2.0日／2日")

    def test_shortages_remain_separate_by_half_and_qualification(self):
        people = [dict(id=1, name="看護 仮名", employment="full", is_help=0)]
        rows = [{"date": "2026-11-02", "half": "午前", "area": "B（診察室）", "missing": 2},
                {"date": "2026-11-02", "half": "午前", "area": "診療側のベテラン看護師（配置人数と重複）", "missing": 1}]
        display = monthly_display(["2026-11-02"], people, [("AA",)], shortages=rows)
        self.assertEqual(display["deficits"][0]["cells"][0]["label"], "B2人・ベテラン1人")
        self.assertEqual(display["deficits"][1]["cells"][0]["label"], "—")
        self.assertFalse(display["deficits"][1]["cells"][0]["missing"])

    def test_c_and_required_technician_are_one_shortage(self):
        source = [
            dict(date="2026-11-02", half="午前", area="C（検査室）", required=2, available=0, missing=2),
            dict(date="2026-11-02", half="午前", area="他院の検査技師（C番人数と重複）", required=1, available=0, missing=1)]
        original = copy.deepcopy(source)
        rows = grouped_shortages(source, {}, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["missing"], 2)
        self.assertIn("不足人数に含む", rows[0]["note"])
        self.assertEqual(source, original)

    def test_nurses_already_cover_c_technician_is_role_condition(self):
        source = [dict(date="2026-11-02", half="午前", area="他院の検査技師（C番人数と重複）", required=1, available=0, missing=1)]
        problem = dict(days=["2026-11-02"], requirements=[((2,1,1),(2,1,1))],
                       people=[dict(role="nurse"),dict(role="technician")])
        rows = grouped_shortages(source, problem, [("CC","RR")])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["required"], rows[0]["available"], rows[0]["missing"]), (1,1,0))
        self.assertTrue(rows[0]["requires_technician"])
        self.assertIn("交代を検討", rows[0]["note"])

    def test_c_shortage_without_technician_condition_is_unchanged(self):
        source = [dict(date="2026-11-02", half="午前", area="C（検査室）", required=2, available=1, missing=1)]
        self.assertEqual(grouped_shortages(source, {}, []), source)

    def test_technician_help_reduces_aggregate_nurse_need_without_double_counting(self):
        raw = [
            dict(date="2026-11-02", half="午前", area="診療の看護師合計", required=4, available=3, missing=1),
            dict(date="2026-11-02", half="午前", area="他院の検査技師（C番として計上）", required=1, available=0, missing=1)]
        original = copy.deepcopy(raw)
        rows = grouped_shortages(raw, {}, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["area"], "検査技師（C番として計上）")
        self.assertEqual(rows[0]["missing"], 1)
        self.assertEqual(raw, original)
        raw[0].update(required=6, available=3, missing=3)
        rows = grouped_shortages(raw, {}, [])
        self.assertEqual((rows[0]["required"], rows[0]["missing"]), (5,2))
        self.assertEqual(rows[1]["missing"], 1)

    def test_comparison_distinguishes_wish_paid_halves_and_empty_days(self):
        person = dict(id=1, name="看護 仮名", employment="full", is_help=0)
        inputs = {"wishes": {"1_2026-11-02": "am"}, "leaves": {"1_2026-11-02": "pm", "1_2026-11-03": "full"}}
        display = monthly_display(["2026-11-02", "2026-11-03", "2026-11-04"], [person],
                                  [("RP",), ("PP",), ("DD",)], comparison_inputs=inputs)
        cells = display["rows"][0]["cells"]
        self.assertEqual([item["label"] for item in cells[0]["requests"]], ["午前休", "午後有休"])
        self.assertEqual([item["kind"] for item in cells[0]["requests"]], ["wish", "paid"])
        self.assertEqual(cells[1]["requests"][0]["label"], "有休")
        self.assertEqual(cells[2]["requests"], [])
        self.assertTrue(display["comparison_available"])

    def test_unknown_comparison_inputs_are_not_treated_as_empty_wishes(self):
        person = dict(id=1, name="看護 仮名", employment="full", is_help=0)
        display = monthly_display(["2026-11-02"], [person], [("DD",)])
        self.assertFalse(display["comparison_available"])

    def test_doctor_halves_and_fixed_closed_periods_are_explicit(self):
        people = [dict(id=1, name="看護 仮名", employment="full", is_help=0)]
        days = ["2026-11-02", "2026-11-03", "2026-11-06", "2026-11-08"]
        plans = {day: {"am": ["午前医師"], "pm": ["午後医師"]} for day in days}
        display = monthly_display(days, people, [("DD",)]*4, monthly={"closures":{"2026-11-03":"holiday"}},
                                  doctor_plans=plans)
        self.assertEqual(display["days"][0]["doctors_am"], ["午前医師"])
        self.assertEqual(display["days"][0]["doctors_pm"], ["午後医師"])
        self.assertEqual(display["days"][1]["doctors_am"], [])
        self.assertEqual(display["days"][2]["doctors_pm"], [])
        self.assertEqual(display["days"][3]["doctors_am"], [])
        self.assertTrue(display["doctors_available"])
        self.assertEqual(plans[days[2]]["pm"], ["午後医師"])

    def test_comparison_uses_same_symbols_and_keeps_unspecified_halves_distinct(self):
        people = [dict(id=1, name="看護 仮名", employment="full", is_help=0)]
        days = ["2026-11-02", "2026-11-03", "2026-11-04"]
        inputs = {"wishes": {"1_2026-11-02": "am"}, "leaves": {"1_2026-11-03": "full"}}
        display = monthly_display(days, people, [("RD",), ("PP",), ("DD",)], comparison_inputs=inputs)
        cells = display["rows"][0]["cells"]
        self.assertEqual([x["label"] for x in cells[0]["request_segments"]], ["休", "—"])
        self.assertEqual([x["label"] for x in cells[1]["request_segments"]], ["有休"])
        self.assertEqual(cells[2]["request_segments"], [])
        self.assertEqual([x["has_request"] for x in cells], [True, True, False])
        self.assertIn("午前", cells[0]["request_hint"])

    def test_veteran_is_shown_inside_missing_nurse_count(self):
        raw = [
            dict(date="2026-11-02", half="午前", area="診療の看護師合計", required=5, available=3, missing=2),
            dict(date="2026-11-02", half="午前", area="診療側のベテラン看護師（看護師人数の内数）", required=1, available=0, missing=1)]
        original = copy.deepcopy(raw)
        rows = grouped_shortages(raw, {}, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["missing"], rows[0]["veteran_missing"]), (2,1))
        self.assertEqual(raw, original)
        people = [dict(id=1, name="看護 仮名", employment="full", is_help=0)]
        display = monthly_display(["2026-11-02"], people, [("DD",)], shortages=rows)
        self.assertEqual(display["deficits"][0]["cells"][0]["label"], "看護師2人（うちベテラン1人）")

    def test_veteran_only_does_not_claim_one_extra_nurse_is_needed(self):
        rows = merge_veteran_shortages([
            dict(date="2026-11-02", half="午後", area="診療側のベテラン看護師（看護師人数の内数）",
                 required=1, available=0, missing=1)])
        self.assertEqual(rows[0]["missing"], 0)
        self.assertEqual(rows[0]["veteran_missing"], 1)
        self.assertIn("人数は充足", rows[0]["area"])
        self.assertIn("追加人数の不足ではありません", rows[0]["note"])
