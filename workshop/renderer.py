"""把计划渲染成给学员的可执行说明和给老师的回溯视图。"""
from __future__ import annotations

from .models import Plan, PlannedStep

EXECUTABLE_STATES = ("可执行", "已完成", "跳过(可选)")
BLOCKED_STATES = ("待解阻断", "条件未满足")


def render_learner_instruction(plan: Plan) -> str:
    """学员说明：只写本次可执行支路，含重复次数、前置准备、停手条件。"""
    lines = [
        f"试样说明（样件 {plan.样件.id}，结论：{plan.结论}）",
        f"样件状态：{plan.样件.状态}；台位：{plan.样件.台位}",
        f"已形成特征：{'、'.join(plan.已形成特征) or '无'}",
        f"本次要求：{plan.样件.本次要求}",
        "",
    ]
    if plan.结论 == "交回老师":
        executable = [item for item in plan.步骤
                      if item.状态 in EXECUTABLE_STATES + ("待解阻断",)]
        if executable:
            lines.append("以下为本次支路；标注【待解阻断】的步骤须先解阻再做：")
            lines.extend(_render_executable(executable))
            lines.append("")
        lines.append("交回老师的问题：")
        for problem in plan.问题:
            lines.append(f"  - {problem}")
        blocked = [item for item in plan.步骤 if item.状态 in BLOCKED_STATES]
        if blocked:
            lines.append("")
            lines.append("暂不能执行的步骤：")
            for item in blocked:
                lines.append(f"  - {item.step.操作}（{item.step.宾语 or ''}）：{'；'.join(item.问题) or item.状态}")
        if plan.停手条件:
            lines.append("")
            lines.append("停手条件：")
            for condition in dict.fromkeys(plan.停手条件):
                lines.append(f"  - {condition}")
        return "\n".join(lines)

    lines.append("本次可执行支路：")
    lines.extend(_render_executable(plan.步骤))

    if plan.停手条件:
        lines.append("")
        lines.append("停手条件：")
        for condition in dict.fromkeys(plan.停手条件):
            lines.append(f"  - {condition}")
    lines.append("")
    lines.append(f"路由版本：{' → '.join(f'{d}v{v}' for d, v in plan.路由)}")
    return "\n".join(lines)


def _render_executable(items) -> list[str]:
    lines: list[str] = []
    index = 1
    for item in items:
        if item.状态 not in EXECUTABLE_STATES + ("待解阻断",):
            continue
        if item.状态 == "已完成":
            lines.append(f"{index}. 【已完成】{item.step.操作}（{item.step.宾语 or ''}）")
            index += 1
            continue
        if item.状态 == "跳过(可选)":
            lines.append(f"{index}. 【可选，本次跳过】{item.step.操作}：条件未出现（{item.step.原句}）")
            index += 1
            continue
        if item.状态 == "待解阻断":
            repeat = f"，重复 {item.重复} 次" if item.重复 > 1 else ""
            lines.append(
                f"{index}. 【待解阻断】{item.step.操作}（{item.step.宾语 or ''}）{repeat}｜{item.step.原句}"
            )
            for note in item.资源处置:
                lines.append(f"   领用：{note}")
            for problem in item.问题:
                lines.append(f"   阻断原因：{problem}")
            index += 1
            continue
        repeat = f"，重复 {item.重复} 次" if item.重复 > 1 else ""
        lines.append(
            f"{index}. {item.step.操作}（{item.step.宾语 or ''}）{repeat}｜{item.step.原句}"
        )
        if item.step.承接:
            lines.append(f"   承接：{item.step.承接}")
        for note in item.资源处置:
            lines.append(f"   领用：{note}")
        if item.接续确认:
            lines.append(f"   跨稿衔接：经确认 {item.接续确认.id}（{item.接续确认.来源}）")
        index += 1
    return lines


def render_teacher_trace(plan: Plan) -> str:
    """教师视图：每个工序都能回到原句，并标注版本、确认与替代。"""
    lines = [
        f"教师回溯（样件 {plan.样件.id}，结论：{plan.结论}）",
        f"路由版本：{' → '.join(f'{d}v{v}' for d, v in plan.路由) or '未成路由'}",
        f"原始指令：{plan.样件.原始指令 or '无'}",
        "",
    ]
    for item in plan.步骤:
        step = item.step
        lines.append(f"[{step.id}] {item.状态} ×{item.重复}")
        lines.append(f"  操作：{step.操作}（{step.宾语 or '无宾语'}）")
        lines.append(f"  原句：{step.原句}")
        lines.append(f"  出处：{step.文稿} 第{step.版本}版")
        if step.承接:
            lines.append(f"  承接前指：{step.承接}")
        if item.接续确认:
            c = item.接续确认
            lines.append(f"  接续确认：{c.id}（{c.状态}，{c.来源}）→ {c.去稿版本[0]}v{c.去稿版本[1]}/{c.去步骤}")
        if item.替代:
            s = item.替代
            lines.append(f"  材料替代：{s.id}（{s.状态}，{s.来源}）{s.缺料}→{s.替代料}")
        for problem in item.问题:
            lines.append(f"  问题：{problem}")
        lines.append("")
    if plan.问题:
        lines.append("交回老师的问题清单：")
        for problem in plan.问题:
            lines.append(f"  - {problem}")
    return "\n".join(lines)


def render_version_lookup(data, direction_id: str) -> str:
    """查某份已发给工位的说明用了哪个版本、哪里采用了确认过的替代。"""
    direction = data.directions.get(direction_id)
    if direction is None:
        return f"找不到领用/工位指示：{direction_id}"
    lines = [
        f"说明 {direction.id}（状态：{direction.状态}）",
        f"原话：{direction.说明}",
        f"采用版本：{direction.文稿} 第{direction.版本}版",
    ]
    manuscript = data.manuscripts.get((direction.文稿, direction.版本))
    if manuscript:
        lines.append(f"原稿全文：{manuscript.内容}")
    related = [c for c in data.confirmations
               if tuple(c.来稿版本) == (direction.文稿, direction.版本)
               or tuple(c.去稿版本) == (direction.文稿, direction.版本)]
    if related:
        lines.append("相关教师确认（否定/待复核登记同样不得绕开）：")
        for c in related:
            lines.append(
                f"  - {c.id}【{c.状态}】{c.来稿版本[0]}v{c.来稿版本[1]}"
                f"→{c.去稿版本[0]}v{c.去稿版本[1]}：{c.说明}"
            )
    subs = [s for s in data.substitutions if s.状态 == "成立"]
    if subs:
        lines.append("登记过的材料替代（仅在条件满足时适用）：")
        for s in subs:
            lines.append(f"  - {s.id}：{s.缺料}→{s.替代料}，条件 {s.前置条件}")
    return "\n".join(lines)
