"""把结构化解析与现场状态编成试样计划。

核心纪律：
1. 步骤只来自登记过的解析稿；跨版本衔接只接受状态为“成立”的教师确认，
   文字相似、产物同名都不能衔接。
2. 在制样件按“已形成特征”定位进度，只允许把剩余步骤接到实际半成品上；
   接不上就交回老师，不许改掉已经形成的特征。
3. 材料替代必须满足同一工序的前后条件（替代登记 + 条件求值同时成立）。
4. 学员说明只保留本次可执行支路，可选步骤条件不成立时明确跳过，
   并保留重复次数、前置准备、停手条件。
"""
from __future__ import annotations

from dataclasses import dataclass

from .conditions import ConditionContext, evaluate, missing_features
from .inventory import StockBook
from .loader import WorkshopData
from .models import (
    Confirmation,
    ParsedDocument,
    ParsedStep,
    Plan,
    PlannedStep,
    Sample,
    Substitution,
)

# 本次要求里的纹样词 -> 步骤效果特征里必须出现的特征。
PATTERN_FEATURES = {
    "菱": "菱纹可辨",
    "菱纹": "菱纹可辨",
    "菱目": "菱纹可辨",
}


@dataclass
class PlanRequest:
    样件: str
    时段: tuple[str, ...]
    起始稿: tuple[str, int] | None = None  # 未做样件由老师指定走哪一版
    指定纹样: str | None = None


class Planner:
    def __init__(self, data: WorkshopData):
        self.data = data
        self.stock = StockBook(tuple(data.stock))

    # ---------- 对外入口 ----------
    def plan(self, request: PlanRequest) -> Plan:
        sample = self.data.samples[request.样件]
        if sample.状态 == "在制":
            return self._plan_in_process(sample, request)
        return self._plan_fresh(sample, request)

    # ---------- 未做样件 ----------
    def _plan_fresh(self, sample: Sample, request: PlanRequest) -> Plan:
        if request.起始稿 is None:
            raise ValueError(f"未做样件 {sample.id} 须由老师指定起始稿版本")
        doc = self.data.document(*request.起始稿)
        learner = self.data.learner_for_sample(sample)
        features = frozenset(sample.特征)
        planned: list[PlannedStep] = []
        problems: list[str] = []
        for step in doc.步骤:
            planned.append(self._evaluate_step(step, sample, learner, features, request.时段, set()))
        route = [(doc.文稿, doc.版本)]
        problems.extend(p for item in planned for p in item.问题)
        problems.extend(self._pattern_problems(sample, request, planned, route))
        problems.extend(self._exit_problems(doc, planned))
        return self._build_plan(sample, tuple(route), features, planned, problems, request)

    # ---------- 在制样件 ----------
    def _plan_in_process(self, sample: Sample, request: PlanRequest) -> Plan:
        direction = self.data.direction(sample.原始指令)
        if direction is None:
            return self._dead_end(sample, request, ["在制样件没有可追溯的原始指令，无法判定版本归属"])
        route_doc = self.data.document(direction.文稿, direction.版本)
        learner = self.data.learner_for_sample(sample)
        features = frozenset(sample.特征)
        formed: set[str] = set(features)
        planned: list[PlannedStep] = []
        completed_steps: list[ParsedStep] = []
        remaining_steps: list[ParsedStep] = []

        for step in route_doc.步骤:
            if step.效果特征 and all(effect in formed for effect in step.效果特征):
                planned.append(PlannedStep(step, "已完成", step.重复, (), None, (), None))
                completed_steps.append(step)
            else:
                remaining_steps.append(step)

        if not completed_steps:
            return self._dead_end(
                sample, request,
                [f"实际半成品特征{list(formed)}与{route_doc.文稿}v{route_doc.版本}任一工序效果都对不上，须重新起样"],
            )

        # 剩余步骤逐个接。可选步骤条件不成立则跳过。
        # “硬阻断”指工序本身与实际半成品接不上（前置条件缺特征），
        # 此时任何改单都不允许；资格/库存类问题不阻断已确认的接续尝试。
        pending: list[ParsedStep] = []
        hard_block = False
        for step in remaining_steps:
            result = self._evaluate_step(step, sample, learner, frozenset(formed), request.时段, formed)
            planned.append(result)
            if result.状态 == "条件未满足":
                hard_block = True
                pending.append(step)
                break
            if result.状态 == "跳过(可选)":
                continue
            # 可执行与“待解阻断”都说明工序与半成品相容；阻断步不再下探，
            # 但保留在支路里等老师解阻，特征按工序效果登记以便接续判定。
            formed.update(step.效果特征)
            if result.状态 == "待解阻断":
                pending.append(step)
                break

        problems = [p for item in planned for p in item.问题]
        route = [(route_doc.文稿, route_doc.版本)]

        # 没有硬阻断时，允许尝试教师确认过的跨版本接续（如W2夹短边夹后接W4菱目）。
        # 接续成功后，被现场问题阻断的同版本步骤不再挂“待接”，因为学员本次
        # 拿到的支路只保留可执行部分；问题仍随计划交回老师。
        if not hard_block:
            splice = self._try_splice(sample, learner, request, route_doc, planned, formed)
            if splice is not None:
                planned.extend(splice.added)
                route.extend(splice.route)
                problems.extend(splice.problems)
                if not splice.problems:
                    pending = []
        if pending:
            blockers = "；".join(sorted({p for item in planned for p in item.问题}))
            problems.append(
                "原做法剩余步骤接不上实际半成品，已保住特征"
                f"{sorted(features)}；缺的准备：{self._missing_preparation(pending, frozenset(formed))}"
                + (f"；现场阻断：{blockers}" if blockers else "")
            )
        problems.extend(self._recheck_problems(route_doc))
        problems.extend(self._pattern_problems(sample, request, planned, route))
        problems.extend(self._exit_problems(route_doc, planned))
        # 展示层只认实际已形成的特征；formed 里可能含阻断步的预期效果，仅用于接续判定。
        return self._build_plan(sample, tuple(route), features, planned, problems, request)

    # ---------- 单步评估 ----------
    def _evaluate_step(self, step: ParsedStep, sample: Sample, learner,
                       features: frozenset[str], slots: tuple[str, ...],
                       formed: set[str]) -> PlannedStep:
        problems: list[str] = []
        resource_notes: list[str] = []
        substitution: Substitution | None = None
        station = step.工位 or sample.台位

        if step.操作 == "停手约束":
            return PlannedStep(step, "可执行", step.重复, (), None, (), None)

        # 特征/工位/时段类前置：决定工序本身与现场、半成品是否相容，
        # 不成立即硬阻断。资源类前置剥离后交给库存与替代规则，避免
        # “缺货”被误当成“半成品接不上”。
        structural = self._strip_resource_predicates(step.前置条件)
        structural_context = ConditionContext(
            特征=features, 工位=station, 时段=slots, 资源可用=lambda name: True,
        )
        if not evaluate(structural, structural_context):
            missing = missing_features(structural, features)
            if missing:
                detail = f"前置条件不成立（缺特征：{list(missing)}）"
            else:
                detail = f"前置条件不成立（工位/时段不匹配：{structural}）"
            if step.可省:
                return PlannedStep(step, "跳过(可选)", step.重复, (), None, (), None)
            # 即使工序本身做不下去，也把现场资源缺口一并报给老师，
            # 便于领用单一次改齐；这些问题不改变“条件未满足”的硬阻断定性。
            _, resource_problems, _ = self._resource_problems(
                step, station, slots, features, sample.id
            )
            return PlannedStep(
                step, "条件未满足", step.重复, (), None,
                (detail, *resource_problems), None,
            )

        # 学员资格（停手约束与离台是纪律性步骤，不需要工序资格）
        if step.操作 not in ("停手约束", "离台") and step.操作 not in learner.可做:
            problems.append(f"学员{learner.学员}无‘{step.操作}’资格")
        if step.需老师:
            problems.append(f"‘{step.操作}’须老师在场")

        # 资源与替代。时段/工位条件在这里通过库存可领性再次生效：
        # 当前时段没有登记库存即不可领，不能因剥离资源谓词而放行。
        resource_notes, resource_problems, substitution = self._resource_problems(
            step, station, slots, features, sample.id, collect_notes=True
        )
        problems.extend(resource_problems)

        # 留台器具借离检查
        for violation in self.stock.borrowing_violations(station, step.需资源, slots):
            problems.append(violation)

        status = "待解阻断" if problems else "可执行"
        return PlannedStep(step, status, step.重复, tuple(resource_notes), substitution, tuple(problems), None)

    def _resource_problems(self, step: ParsedStep, station: str, slots: tuple[str, ...],
                           features: frozenset[str], sample_id: str,
                           collect_notes: bool = False):
        notes: list[str] = []
        problems: list[str] = []
        substitution: Substitution | None = None
        for resource in step.需资源:
            if self.stock.can_use(resource, station, slots, sample_id):
                if collect_notes:
                    ok, note = self.stock.take(resource, station, slots, sample_id)
                    if ok:
                        notes.append(note)
                    else:
                        problems.append(note)
                continue
            sub = self._find_substitution(step, resource, station, slots, features)
            if sub is None:
                problems.append(
                    f"{resource}在{station}{'/'.join(slots)}无可用库存，且无满足本工序前后条件的替代"
                )
            else:
                substitution = sub
                if collect_notes:
                    notes.append(
                        f"替代：{resource}→{sub.替代料}（{sub.来源}，效果‘{sub.满足效果}’）"
                    )
        return notes, problems, substitution

    @staticmethod
    def _strip_resource_predicates(predicate: dict) -> dict:
        """把条件里的资源谓词换成恒真，只保留特征/工位/时段等结构性条件。"""
        key, value = next(iter(predicate.items()))
        if key == "资源":
            return {"恒真": True}
        if key == "且":
            kept = [Planner._strip_resource_predicates(part) for part in value]
            kept = [part for part in kept if part != {"恒真": True}]
            return {"且": kept} if kept else {"恒真": True}
        if key == "或":
            kept = [Planner._strip_resource_predicates(part) for part in value]
            return {"或": kept}
        if key == "非":
            return {"非": Planner._strip_resource_predicates(value)}
        return predicate

    def _find_substitution(self, step: ParsedStep, missing: str, station: str,
                           slots: tuple[str, ...], features: frozenset[str]) -> Substitution | None:
        for sub in self.data.substitutions:
            if sub.状态 != "成立" or sub.缺料 != missing:
                continue
            applicable = sub.适用工序
            if applicable is not None:
                applicable = (applicable,) if isinstance(applicable, str) else tuple(applicable)
                if step.id not in applicable:
                    continue
            if sub.满足效果 not in step.效果特征:
                continue  # 替代必须满足同一工序的效果（前后条件的“后”）
            ctx = ConditionContext(
                特征=features, 工位=station, 时段=slots,
                资源可用=lambda name: self.stock.can_use(name, station, slots),
            )
            if sub.前置条件 and not evaluate(sub.前置条件, ctx):
                continue
            return sub
        return None

    # ---------- 跨版本接续 ----------
    def _try_splice(self, sample: Sample, learner, request: PlanRequest,
                    route_doc: ParsedDocument, planned: list[PlannedStep],
                    formed: set[str]):
        @dataclass
        class SpliceResult:
            added: list[PlannedStep]
            route: list[tuple[str, int]]
            problems: list[str]

        added: list[PlannedStep] = []
        route: list[tuple[str, int]] = []
        problems: list[str] = []
        # 接续点挂在来源稿某一步之后。允许锚点已推进到该步之后，
        # 只要确认的来步骤确实在本稿已相容的步骤序列里；不允许倒接。
        # 学员资格这类阻断不改变半成品物理状态，阻断步仍计入相容序列；
        # 但跨稿步骤本身仍会重新过资格与资源校验。
        made = [item.step for item in planned
                if item.状态 in ("已完成", "可执行", "待解阻断")]
        made_ids = [step.id for step in made]
        for confirmation in self.data.confirmations:
            if tuple(confirmation.来稿版本) != (route_doc.文稿, route_doc.版本):
                continue
            if confirmation.来步骤 is not None and confirmation.来步骤 not in made_ids:
                continue
            if confirmation.状态 != "成立":
                problems.append(
                    f"接续登记{confirmation.id}状态为‘{confirmation.状态}’，"
                    f"不得据此衔接（{confirmation.说明}）"
                )
                continue
            target_doc = self.data.document(*confirmation.去稿版本)
            target_step = target_doc.step(confirmation.去步骤)
            ctx = ConditionContext(
                特征=frozenset(formed), 工位=target_step.工位 or sample.台位,
                时段=request.时段,
                资源可用=lambda name: self.stock.can_use(
                    name, target_step.工位 or sample.台位, request.时段, sample.id),
            )
            if confirmation.共同接续点 and not evaluate(confirmation.共同接续点, ctx):
                problems.append(
                    f"确认{confirmation.id}的共同接续点未满足："
                    f"{missing_features(confirmation.共同接续点, frozenset(formed))}"
                )
                continue
            evaluated = self._evaluate_step(
                target_step, sample, learner, frozenset(formed), request.时段, formed
            )
            added.append(PlannedStep(
                evaluated.step, evaluated.状态, evaluated.重复,
                evaluated.资源处置, evaluated.替代, evaluated.问题, confirmation,
            ))
            route.append((target_doc.文稿, target_doc.版本))
            if evaluated.状态 == "可执行":
                formed.update(target_step.效果特征)
            elif evaluated.状态 != "跳过(可选)":
                # 接续后的首步都没做成，后续步骤不再下探，问题交回老师。
                return SpliceResult(added, route, problems)
            # 接上之后，目标稿后续步骤也按同一纪律接。
            target_steps = list(target_doc.步骤)
            start = target_steps.index(target_step) + 1
            for nxt in target_steps[start:]:
                extra = self._evaluate_step(
                    nxt, sample, learner, frozenset(formed), request.时段, formed
                )
                added.append(extra)
                if extra.状态 == "可执行":
                    formed.update(nxt.效果特征)
                elif extra.状态 == "跳过(可选)":
                    continue
                else:
                    break
            return SpliceResult(added, route, problems)
        return None

    # ---------- 复核、纹样、离台与汇总 ----------
    def _recheck_problems(self, route_doc: ParsedDocument) -> list[str]:
        problems = []
        for note in self.data.rechecks:
            if note.状态 != "待复核":
                continue
            if note.新供稿 == (route_doc.文稿, route_doc.版本) or \
                   (note.被补充原句 and note.被补充原句[0] == route_doc.文稿):
                problems.append(
                    f"解释复核{note.id}待办：{note.说明}（待查：{list(note.待查解释)}）"
                )
        return problems

    def _pattern_problems(self, sample: Sample, request: PlanRequest,
                          planned: list[PlannedStep], route: list[tuple[str, int]]) -> list[str]:
        wanted = request.指定纹样 or self._pattern_from_requirement(sample.本次要求)
        if not wanted:
            return []
        needed = PATTERN_FEATURES.get(wanted)
        if needed is None:
            return [f"纹样‘{wanted}’没有登记对应效果特征，请老师确认"]
        # 只有真正做成（在制件已完成，或本次评估可执行）的步骤才算产出纹样；
        # 待解阻断/条件未满足的步骤效果尚未形成，不能用来满足本次要求。
        produced = {effect for item in planned if item.状态 in ("可执行", "已完成")
                    for effect in item.step.效果特征}
        if needed in produced:
            return []
        return [
            f"本次要求展示‘{wanted}’（需特征{needed}），但路由"
            f"{route}没有任何能做成且形成该纹样的步骤；不得凭名称相似自行接稿"
        ]

    @staticmethod
    def _pattern_from_requirement(text: str) -> str | None:
        for word in PATTERN_FEATURES:
            if word in text:
                return word
        return None

    def _exit_problems(self, doc: ParsedDocument, planned: list[PlannedStep]) -> list[str]:
        problems = []
        by_station: dict[str, list[str]] = {}
        for item in planned:
            if item.step.离台前完成:
                by_station.setdefault(item.step.工位 or "", []).append(item.step.离台前完成)
        for station, tasks in by_station.items():
            blocked = [item for item in planned
                       if item.状态 in ("待解阻断", "条件未满足") and (item.step.工位 or "") == station]
            if blocked:
                problems.append(
                    f"{station}有步骤未做成，离台整理‘{sorted(set(tasks))}’的前提不成立，样件不得离台"
                )
        return problems

    @staticmethod
    def _missing_preparation(remaining: list[ParsedStep], features: frozenset[str]) -> list[str]:
        missing: list[str] = []
        for step in remaining:
            missing.extend(missing_features(step.前置条件, features))
        return sorted(set(missing))

    def _dead_end(self, sample: Sample, request: PlanRequest, problems: list[str]) -> Plan:
        return self._build_plan(sample, (), frozenset(sample.特征), (), problems, request)

    def _build_plan(self, sample: Sample, route, features, planned, problems,
                    request: PlanRequest) -> Plan:
        stop_conditions = tuple(
            item.step.停手条件 for item in planned if item.step.停手条件
        )
        evidence = self._evidence(planned, request)
        conclusion = "交回老师" if problems else "可执行"
        return Plan(
            样件=sample, 结论=conclusion, 路由=tuple(route),
            已形成特征=tuple(sorted(features)), 步骤=tuple(planned),
            问题=tuple(dict.fromkeys(problems)), 停手条件=stop_conditions, 依据=evidence,
        )

    @staticmethod
    def _evidence(planned: list[PlannedStep], request: PlanRequest) -> dict:
        steps = []
        for item in planned:
            record = {
                "步骤": item.step.id,
                "原句": item.step.原句,
                "文稿版本": [item.step.文稿, item.step.版本],
                "承接": item.step.承接,
            }
            if item.接续确认:
                record["接续确认"] = item.接续确认.id
            if item.替代:
                record["材料替代"] = item.替代.id
            steps.append(record)
        return {"时段": list(request.时段), "步骤溯源": steps}
