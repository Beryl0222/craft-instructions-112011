"""试样说明编制器的纪律性测试。

覆盖：同名异义、省略宾语与前指、可选/重复/条件、教师确认接续、
材料替代的前后条件、未做/在制样件区分、留台器具、离台整理、
新供稿导致的解释复核，以及原句回溯。
"""
from pathlib import Path
import unittest

from workshop.conditions import ConditionContext, evaluate, missing_features
from workshop.inventory import StockBook
from workshop.loader import WorkshopData
from workshop.planner import PlanRequest, Planner
from workshop.renderer import render_learner_instruction, render_teacher_trace, render_version_lookup

ROOT = Path(__file__).resolve().parents[1]


def data() -> WorkshopData:
    return WorkshopData(ROOT / "data")


def plan(sample_id: str, slots=("上午",), start=None, pattern=None):
    return Planner(data()).plan(PlanRequest(sample_id, slots, start, pattern))


class TermSenseTests(unittest.TestCase):
    def test_same_word_has_different_senses_across_masters(self):
        d = data()
        w1 = d.document("W1", 1)
        w2 = d.document("W2", 1)
        sense_w1 = next(t for t in w1.术语表 if t.词形 == "回穿两道")
        sense_w2 = next(t for t in w2.术语表 if t.词形 == "回穿两道")
        self.assertEqual(sense_w1.操作, "经面回穿")
        self.assertEqual(sense_w2.操作, "边线回穿")
        self.assertNotEqual(sense_w1.所指, sense_w2.所指)
        self.assertIn("同一层经线", sense_w1.承接)
        self.assertIn("未收的边线", sense_w2.承接)

    def test_ellided_object_is_recorded_with_anaphora_link(self):
        d = data()
        step = d.document("W1", 1).step("W1v1-2")
        self.assertEqual(step.宾语, "同一层经线")
        self.assertIn("W1v1-1", step.承接)
        self.assertEqual(step.重复, 2)

    def test_v2_makes_v1_ellipsis_explicit_and_triggers_recheck(self):
        d = data()
        v2 = d.document("W1", 2).step("W1v2-2")
        self.assertIn("同一层经线", v2.原句)
        recheck = next(n for n in d.rechecks if n.新供稿 == ("W1", 2))
        self.assertEqual(recheck.状态, "待复核")
        self.assertTrue(any("省略" in text for text in recheck.待查解释))


class ConditionTests(unittest.TestCase):
    def test_predicate_evaluation(self):
        ctx = ConditionContext(
            frozenset({"短边夹已上"}), "西台", ("上午",), lambda name: name == "短边夹"
        )
        self.assertTrue(evaluate({"特征": "短边夹已上"}, ctx))
        self.assertFalse(evaluate({"特征": "灰边已备"}, ctx))
        self.assertTrue(evaluate({"且": [{"特征": "短边夹已上"}, {"工位": "西台"}]}, ctx))
        self.assertFalse(evaluate({"时段": "下午"}, ctx))
        self.assertTrue(evaluate({"资源": "短边夹"}, ctx))
        self.assertFalse(evaluate({"资源": "长夹"}, ctx))

    def test_missing_features_lists_only_absent_ones(self):
        predicate = {"且": [{"特征": "短边夹已上"}, {"特征": "灰边已备"}]}
        self.assertEqual(
            missing_features(predicate, frozenset({"短边夹已上"})), ("灰边已备",)
        )

    def test_unknown_predicate_is_rejected_not_defaulted(self):
        ctx = ConditionContext(frozenset(), "西台", ("上午",), lambda name: False)
        with self.assertRaises(ValueError):
            evaluate({"随便写的键": 1}, ctx)


class InventoryTests(unittest.TestCase):
    def test_station_bound_tool_cannot_leave_its_station(self):
        d = data()
        book = StockBook(tuple(d.stock))
        # 经夹是东台留台器具，西台上午领不到。
        self.assertFalse(book.can_use("经夹", "西台", ("上午",)))
        self.assertTrue(book.can_use("经夹", "东台", ("上午",)))
        violations = book.borrowing_violations("西台", ("经夹",), ("上午",))
        self.assertTrue(violations)
        self.assertIn("留台", violations[0])

    def test_borrowable_resource_crosses_stations(self):
        d = data()
        book = StockBook(tuple(d.stock))
        self.assertTrue(book.can_use("竹梭", "西台", ("上午",)))

    def test_handoff_reservation_reduces_available_count(self):
        d = data()
        book = StockBook(tuple(d.stock))
        # K3 有两只短边夹，X5 预占一只给 S3；其他样件只剩一只。
        self.assertEqual(book.available("短边夹", "西台", ("上午",), "S2"), 1)
        # S3 自己继续用不受预占影响。
        self.assertEqual(book.available("短边夹", "西台", ("上午",), "S3"), 2)

    def test_afternoon_slot_is_a_separate_batch(self):
        d = data()
        book = StockBook(tuple(d.stock))
        self.assertFalse(book.can_use("长夹", "北台", ("上午",)))
        self.assertTrue(book.can_use("长夹", "北台", ("下午",)))


class FreshSampleTests(unittest.TestCase):
    def test_fresh_sample_requires_teacher_chosen_version(self):
        with self.assertRaises(ValueError):
            plan("S2")

    def test_missing_material_blocks_without_substitution_in_morning(self):
        result = plan("S4", ("上午",), ("W5", 1))
        self.assertEqual(result.结论, "交回老师")
        blocked = [i for i in result.步骤 if i.step.id == "W5v1-1"][0]
        self.assertEqual(blocked.状态, "条件未满足")
        # 上午时段替代（M1要求下午）不成立，问题须点明时段不匹配与纸绳缺货。
        self.assertTrue(any("时段" in p for p in result.问题))
        self.assertTrue(any("纸绳" in p for p in result.问题))

    def test_substitution_holds_only_when_pre_post_conditions_match(self):
        result = plan("S4", ("下午",), ("W5", 1))
        self.assertEqual(result.结论, "可执行")
        step = [i for i in result.步骤 if i.step.id == "W5v1-1"][0]
        self.assertEqual(step.状态, "可执行")
        self.assertIsNotNone(step.替代)
        self.assertEqual(step.替代.id, "M1")
        # 替代登记必须指向同一工序效果。
        self.assertIn(step.替代.满足效果, step.step.效果特征)

    def test_rejected_substitution_route_is_not_offered_to_learner(self):
        d = data()
        m2 = next(s for s in d.substitutions if s.id == "M2")
        self.assertEqual(m2.状态, "不成立")
        result = plan("S2", ("上午",), ("W2", 1))
        self.assertFalse(any(i.替代 is not None for i in result.步骤))


class InProcessSampleTests(unittest.TestCase):
    def test_progress_is_located_from_formed_features(self):
        result = plan("S1", ("上午",), pattern="菱")
        done = [i.step.id for i in result.步骤 if i.状态 == "已完成"]
        self.assertEqual(done, ["W1v1-1"])
        # 实际半成品没有“同层经面回穿完成”，该步不得算作已完成。
        self.assertNotIn("同层经面回穿完成", result.已形成特征)

    def test_formed_features_are_preserved_when_original_route_stalls(self):
        result = plan("S1", ("上午",), pattern="菱")
        self.assertEqual(result.结论, "交回老师")
        for feature in ("经面已平码", "灰边未收"):
            self.assertIn(feature, result.已形成特征)
        # 缺红标导致收经做不下去，必须列出缺的准备。
        self.assertTrue(any("已到红标" in p for p in result.问题))

    def test_pattern_request_cannot_be_satisfied_by_name_similarity(self):
        # S1 走 W1（经面回穿），C2 明确不确认经面回穿后直接接菱目。
        result = plan("S1", ("上午",), pattern="菱")
        self.assertTrue(any("菱" in p and "名称相似" in p for p in result.问题))
        self.assertEqual(result.路由, (("W1", 1),))

    def test_confirmed_splice_is_allowed_but_target_preconditions_still_checked(self):
        result = plan("S3", ("上午",))
        self.assertEqual(result.路由, (("W2", 1), ("W4", 1)))
        splice_step = [i for i in result.步骤 if i.接续确认 is not None]
        self.assertEqual(len(splice_step), 1)
        self.assertEqual(splice_step[0].接续确认.id, "C1")
        # W4 自身要求灰边已备，S3 没有，目标步仍被拦。
        target = [i for i in result.步骤 if i.step.id == "W4v1-2"][0]
        self.assertEqual(target.状态, "条件未满足")
        self.assertTrue(any("灰边已备" in p for p in target.问题))

    def test_unconfirmed_confirmation_status_never_joins(self):
        d = data()
        c2 = next(c for c in d.confirmations if c.id == "C2")
        self.assertEqual(c2.状态, "不成立")
        result = plan("S1", ("上午",), pattern="菱")
        self.assertNotIn(("W4", 1), result.路由)

    def test_recheck_note_is_raised_for_new_supplement(self):
        result = plan("S1", ("上午",))
        self.assertTrue(any("R1" in p for p in result.问题))

    def test_stop_conditions_are_kept_in_instruction(self):
        result = plan("S3", ("上午",))
        self.assertTrue(any("停手" in c for c in result.停手条件))
        text = render_learner_instruction(result)
        self.assertIn("停手条件", text)


class RepeatsAndOptionalTests(unittest.TestCase):
    def test_repeat_count_is_retained(self):
        result = plan("S1", ("上午",))
        back = [i for i in result.步骤 if i.step.id == "W1v1-2"][0]
        self.assertEqual(back.重复, 2)
        text = render_learner_instruction(result)
        self.assertIn("重复 2 次", text)

    def test_optional_step_is_skipped_when_condition_absent(self):
        result = plan("S1", ("上午",))
        optional = [i for i in result.步骤 if i.step.id == "W1v1-3"][0]
        self.assertEqual(optional.状态, "跳过(可选)")
        self.assertIn("可选，本次跳过", render_learner_instruction(result))


class ExitAndTraceTests(unittest.TestCase):
    def test_exit_finishing_blocked_when_station_work_incomplete(self):
        result = plan("S1", ("上午",), pattern="菱")
        self.assertTrue(any("离台" in p for p in result.问题))

    def test_teacher_trace_returns_every_step_to_original_sentence(self):
        result = plan("S3", ("上午",))
        text = render_teacher_trace(result)
        for item in result.步骤:
            self.assertIn(item.step.原句, text)
            self.assertIn(f"{item.step.文稿} 第{item.step.版本}版", text)

    def test_lookup_shows_version_and_confirmation_records(self):
        d = data()
        text = render_version_lookup(d, "I2")
        self.assertIn("W2 第1版", text)
        self.assertIn("C1", text)
        # I4 同时登记了成立与不成立两条，否定结论也要可查。
        text_i4 = render_version_lookup(d, "I4")
        self.assertIn("C1", text_i4)
        self.assertIn("C2", text_i4)
        self.assertIn("不成立", text_i4)

    def test_learner_view_contains_only_executable_branch_and_trace_contains_all(self):
        result = plan("S1", ("上午",), pattern="菱")
        learner = render_learner_instruction(result)
        teacher = render_teacher_trace(result)
        self.assertNotIn("W1v1-4", learner)  # 做不下去的收经不进学员支路编号
        self.assertIn("W1v1-4", teacher)


if __name__ == "__main__":
    unittest.main()
