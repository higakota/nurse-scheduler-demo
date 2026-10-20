import copy
import unittest
import test_scheduler as fixtures
from scheduler_engine import generate, verify, draft_shortages, help_plan_key
from help_limits import nurse_helper_excess, helper_demand_roles


class HelpRolePreferenceTest(unittest.TestCase):
    def data(self, include_technician=True):
        data=fixtures.sample(regular_count=3)
        data["monthly_settings"]["wishes"]["3_2026-02-02"]="full"
        data["monthly_settings"]["targets"]["3"]="28"
        for half in ("am","pm"):
            data["coverage_settings"]["2026-02-02_"+half]["c"]=2
        roles=[(9,"nurse"),(10,"nurse")]
        if include_technician:roles.append((11,"technician"))
        for person_id,role in roles:
            data["staff"].append(dict(id=person_id,name="ヘルプ仮名"+str(person_id),role=role,
                employment="full" if role=="nurse" else "",veteran=int(role=="nurse"),is_help=1,
                allowed_areas="ABC" if role=="nurse" else "C"))
            data["help_availability"][str(person_id)+"_2026-02-02"]="full"
        return data

    def test_mixed_pair_is_preferred_and_two_technicians_count_as_two_c_staff(self):
        result=generate(self.data(),use_help=True,seconds=3)
        self.assertEqual(result["status"],"success",result["messages"])
        people=result["problem"]["people"]
        working=[p for p,pair in zip(people,result["grid"][1]) if p["is_help"] and pair!="RR"]
        self.assertEqual(sorted(p["role"] for p in working),["nurse","technician"])
        self.assertEqual(sum(pair=="CC" for pair in result["grid"][1]),2)
        self.assertEqual(draft_shortages(result["problem"],1,result["grid"][1]),[])
        self.assertEqual(helper_demand_roles(result["problem"],1,result["grid"][1]),(0,0))
        self.assertEqual(verify(result["problem"],result["grid"],max_full_days=result["max_full_days"]),[])
        other=copy.deepcopy(result)
        for i,p in enumerate(people):
            if p["id"] in (9,10):other["grid"][1]=tuple("DD" if j==i else pair for j,pair in enumerate(other["grid"][1]))
            if p["id"]==11:other["grid"][1]=tuple("RR" if j==i else pair for j,pair in enumerate(other["grid"][1]))
        self.assertEqual(verify(other["problem"],other["grid"],max_full_days=other["max_full_days"]),[])
        self.assertLess(help_plan_key(result),help_plan_key(other))

    def test_two_nurse_helpers_remain_allowed_if_needed(self):
        result=generate(self.data(include_technician=False),use_help=True,seconds=3)
        self.assertEqual(result["status"],"success",result["messages"])
        self.assertEqual(nurse_helper_excess(result["problem"]["people"],result["grid"][1]),1)
        self.assertEqual(verify(result["problem"],result["grid"],max_full_days=result["max_full_days"]),[])

    def test_nurse_pair_penalty_does_not_apply_to_mixed_pair(self):
        people=[dict(is_help=1,role=role) for role in ("nurse","nurse","technician")]
        self.assertEqual(nurse_helper_excess(people,["DD","RR","CC"]),0)
        self.assertEqual(nurse_helper_excess(people,["DD","DD","RR"]),1)
        self.assertEqual(nurse_helper_excess(people,["DR","RD","RR"]),1)

    def test_draft_prefers_mixed_pair_over_two_nurses_with_same_total_shortage(self):
        from scheduler_engine import prepare, allocate
        from schedule_improvement import improve_jointly
        data=fixtures.sample(open_days=(2,3),regular_count=5)
        data["staff"][2]["veteran"]=1
        data["monthly_settings"]["targets"]={str(i):"26" if i==3 else "27" for i in range(1,7)}
        data["monthly_settings"]["wishes"]["6_2026-02-03"]="full"
        problem=prepare(data)
        problem["requirements"][1]=((2,3,1),(2,3,1))
        problem["requirements"][2]=((1,2,1),(1,2,1))
        grid=[tuple(["RR"]*6) for _ in problem["days"]]
        grid[1]=allocate(problem,1,["RR","RR","WW","WW","WW","WW"],partial=True)
        grid[2]=allocate(problem,2,["WW","WW","WW","RR","RR","RR"],partial=True)
        self.assertEqual(verify(problem,grid,allow_shortages=True,max_full_days=5),[])
        before=[helper_demand_roles(problem,d,grid[d]) for d in (1,2)]
        self.assertEqual(before,[(2,0),(0,1)])
        result=improve_jointly(problem,grid,allow_shortages=True,max_full_days=5,seconds=2)
        after=[helper_demand_roles(problem,d,result[d]) for d in (1,2)]
        self.assertEqual(after,[(1,0),(1,1)])
        self.assertEqual(sum(map(sum,before)),sum(map(sum,after)))
        self.assertEqual(verify(problem,result,allow_shortages=True,max_full_days=5),[])
