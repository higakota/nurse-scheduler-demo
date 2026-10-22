import copy
import json
import unittest
import test_scheduler as fixtures
from help_commitments import lock_requested_help
from scheduler_engine import generate,prefer_five,verify


class HelpCommitmentTest(unittest.TestCase):
    def case(self):
        snapshot=fixtures.sample()
        for pid,advance in ((9,0),(10,1)):
            snapshot["staff"].append(dict(id=pid,name="ヘルプ仮名"+str(pid),role="nurse",
                employment="full",veteran=1,is_help=1,allowed_areas="ABC",advance_help=advance))
            snapshot["help_availability"][str(pid)+"_2026-02-02"]="full"
        days=[f"2026-02-{d:02}" for d in range(1,29)]
        grid=[["RR"]*7 for _ in days]
        grid[1]=["DD"]*4+["CC","DD","DD"]
        source=dict(days=days,people=snapshot["staff"],grid=grid)
        return snapshot,json.dumps(source)

    def test_requested_helper_is_kept_even_when_surplus_but_advance_helper_is_flexible(self):
        snapshot,source=self.case()
        before=copy.deepcopy(snapshot)
        locked=lock_requested_help(snapshot,source)
        self.assertEqual(locked["fixed_help_commitments"]["9_2026-02-02"],"DD")
        self.assertNotIn("10_2026-02-02",locked["fixed_help_commitments"])
        for partial in (False,True):
            with self.subTest(partial=partial):
                result=(prefer_five(locked,use_help=True,partial=True,seconds=3) if partial else generate(locked,use_help=True,seconds=3))
                self.assertEqual(result["status"],"draft" if partial else "success",result["messages"])
                positions={p["id"]:i for i,p in enumerate(result["problem"]["people"])}
                self.assertEqual(result["grid"][1][positions[9]],"DD")
                self.assertEqual(result["grid"][1][positions[10]],"RR")
                self.assertTrue(all(row[positions[9]]=="RR" for d,row in enumerate(result["grid"]) if d!=1))
                self.assertEqual(verify(result["problem"],result["grid"],allow_shortages=partial,max_full_days=result["max_full_days"]),[])
        self.assertEqual(snapshot,before)

    def test_conflicting_registered_visit_stops_instead_of_dropping_requested_shift(self):
        snapshot,source=self.case()
        snapshot["help_availability"].pop("9_2026-02-02")
        result=prefer_five(lock_requested_help(snapshot,source),use_help=True,partial=True,seconds=2)
        self.assertEqual(result["status"],"input_error")
        self.assertTrue(any("依頼済みの勤務" in m for m in result["messages"]))

    def test_missing_source_is_not_silently_replanned(self):
        snapshot,_=self.case()
        with self.assertRaises(ValueError):
            lock_requested_help(snapshot,"")
