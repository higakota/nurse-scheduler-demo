import unittest
from scheduler_engine import prepare, allocate, verify, consolidate_rest_days, automatic_half_rest, draft_shortages
from schedule_improvement import improve_jointly
from test_scheduler import sample


class JointImprovementTest(unittest.TestCase):
    def problem_and_grid(self, requested=False):
        data=sample(open_days=(2,3),regular_count=4)
        data["monthly_settings"]["targets"]["1"]="27"
        data["monthly_settings"]["targets"]["2"]="27"
        if requested:
            data["monthly_settings"]["wishes"]["1_2026-02-02"]="pm"
        problem=prepare(data)
        grid=[]
        for d,options in enumerate(problem["options"]):
            pairs=["WW" if "WW" in choices else choices[0] for choices in options]
            if d in (1,2):
                pairs[0],pairs[1]="WR","RW"
            grid.append(allocate(problem,d,pairs))
        self.assertEqual(verify(problem,grid),[])
        return problem,grid

    def half_count(self,problem,grid):
        return sum(automatic_half_rest(problem,d,i,pair) for d,rows in enumerate(grid) for i,pair in enumerate(rows))

    def test_two_staff_exchange_removes_halves_when_one_person_cannot(self):
        problem,grid=self.problem_and_grid()
        alone=consolidate_rest_days(problem,grid,seconds=1)
        self.assertEqual(self.half_count(problem,alone),4)
        improved=improve_jointly(problem,grid,seconds=2)
        self.assertEqual(self.half_count(problem,improved),0)
        self.assertEqual(verify(problem,improved),[])
        self.assertEqual(grid[1][0],"DR")  # 元の結果を破壊しない。

    def test_requested_half_is_preserved(self):
        problem,grid=self.problem_and_grid(requested=True)
        improved=improve_jointly(problem,grid,seconds=2)
        self.assertEqual(improved[1][0],"DR")
        self.assertEqual(verify(problem,improved),[])

    def test_zero_budget_returns_valid_original(self):
        problem,grid=self.problem_and_grid()
        self.assertEqual(improve_jointly(problem,grid,seconds=0),grid)

    def test_draft_shortage_categories_never_increase(self):
        problem,grid=self.problem_and_grid()
        damaged=list(grid)
        # 個人の公休は変えず、配置済み人数が偏る仮表を作る。
        first=["WR","WR","WW","WW","WW"]
        second=["RW","RW","WW","WW","WW"]
        damaged[1]=allocate(problem,1,first,partial=True)
        damaged[2]=allocate(problem,2,second,partial=True)
        self.assertEqual(verify(problem,damaged,allow_shortages=True),[])
        improved=improve_jointly(problem,damaged,allow_shortages=True,seconds=2)
        def counts(table):
            result=[0,0,0]
            for d,rows in enumerate(table):
                for row in draft_shortages(problem,d,rows):
                    k=1 if "検査技師" in row["area"] else (2 if "ベテラン" in row["area"] else 0)
                    result[k]+=row["missing"]
            return result
        self.assertTrue(all(new<=old for new,old in zip(counts(improved),counts(damaged))))
        self.assertEqual(verify(problem,improved,allow_shortages=True),[])

    def test_full_rest_does_not_trigger_six_day_work(self):
        from unittest.mock import patch
        from scheduler_engine import prefer_five
        data=sample(open_days=(2,3,4,5,6,7,9),regular_count=5)
        for key in data["monthly_settings"]["targets"]:
            data["monthly_settings"]["targets"][key]="22"
        data["technician_exceptions"]={"2026-02-03":True}
        problem=prepare(data)
        first=[]
        off_days={1:3,2:4,3:5,4:6,5:3}
        for d,day in enumerate(problem["days"]):
            number=int(day[-2:])
            pairs=[]
            for i,choices in enumerate(problem["options"][d]):
                if number not in (2,3,4,5,6,7,9) or off_days.get(i)==number:
                    pair="RR"
                elif i==0 and number in (2,7):
                    pair="WR"
                else:
                    pair="WO" if number==6 else "WW"
                self.assertIn(pair,choices)
                pairs.append(pair)
            first.append(allocate(problem,d,pairs))
        second=list(first)
        for number,pair in ((2,"WW"),(7,"WW"),(9,"RR")):
            d=number-1
            pairs=["".join("W" if c in "ABCD" else c for c in row) for row in first[d]]
            pairs[0]=pair
            second[d]=allocate(problem,d,pairs)
        self.assertEqual(verify(problem,first,max_full_days=5),[])
        self.assertEqual(verify(problem,second),[])
        def answer(grid):
            return dict(status="success",problem=problem,grid=grid,messages=[])
        with patch("scheduler_engine._generate",side_effect=[answer(first),answer(second)]):
            result=prefer_five(data,seconds=3,allow_six=True)
        self.assertEqual(result["grid"],first)
        self.assertFalse(result["six_day_runs"])
