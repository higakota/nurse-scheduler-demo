import unittest
from schedule_display import concise_shortages


class ConciseShortagesTest(unittest.TestCase):
    def test_combines_halves_but_keeps_nurse_shortage(self):
        rows = [dict(date="2026-10-28", half=half, area="他院の検査技師（全日休みの代替）", missing=1) for half in ("午前", "午後")]
        rows.append(dict(date="2026-10-28", half="午前", area="全配置の看護師合計", missing=1))
        self.assertEqual(concise_shortages(rows), [dict(date="2026-10-28", items=["午前・午後：検査技師1人不足", "午前：看護師1人不足"])])

    def test_different_counts_stay_separate(self):
        rows = [dict(date="2026-10-28", half=half, area="診療の看護師合計", missing=count) for half, count in (("午前", 2), ("午後", 1))]
        self.assertEqual(len(concise_shortages(rows)[0]["items"]), 2)

    def test_veteran_is_included(self):
        rows = [dict(date="2026-10-28", half="午前", area="診療の看護師合計", missing=2, veteran_missing=1)]
        self.assertEqual(concise_shortages(rows)[0]["items"], ["午前：看護師2人不足（うちベテラン1人）"])
