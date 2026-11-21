"""前置条件求值。

条件是结构化谓词，不执行任何原文里的文字：
- {"特征": "短边夹已上"}  当前在制样件已形成该特征
- {"工位": "西台"}        当前工位
- {"时段": "下午"}        当前可用时段
- {"资源": "竹梭"}        资源在本工位可领（留台/可借规则在库存层处理）
- {"恒真": true}
- {"且": [...]} / {"或": [...]} / {"非": {...}} 组合
空字符串、缺登记一律不视为成立，必须回到教师处确认。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ConditionContext:
    特征: frozenset[str]
    工位: str
    时段: tuple[str, ...]
    资源可用: Callable[[str], bool]

    def holds(self, predicate: dict[str, Any]) -> bool:
        return evaluate(predicate, self)


def evaluate(predicate: dict[str, Any], ctx: ConditionContext) -> bool:
    if not isinstance(predicate, dict) or len(predicate) != 1:
        raise ValueError(f"无法识别的条件谓词：{predicate!r}")
    (key, value), = predicate.items()
    if key == "恒真":
        return bool(value)
    if key == "特征":
        return value in ctx.特征
    if key == "工位":
        return ctx.工位 == value
    if key == "时段":
        return value in ctx.时段
    if key == "资源":
        return ctx.资源可用(value)
    if key == "且":
        return all(evaluate(part, ctx) for part in value)
    if key == "或":
        return any(evaluate(part, ctx) for part in value)
    if key == "非":
        return not evaluate(value, ctx)
    raise ValueError(f"未知条件键：{key}")


def missing_features(predicate: dict[str, Any], features: frozenset[str]) -> tuple[str, ...]:
    """列出条件里要求、但样件还没有形成的特征（用于交回老师的清单）。"""
    found: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        (key, value), = node.items()
        if key == "特征" and value not in features:
            found.append(value)
        elif key == "且":
            for part in value:
                walk(part)
        elif key == "或":
            for part in value:
                walk(part)
        elif key == "非":
            walk(value)

    walk(predicate)
    return tuple(found)
