"""结构化记录的数据模型。原稿（manuscripts 等）仍由 corpus 原样读取。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TermSense:
    """同一词形在某一稿版本中的具体所指（同名异义登记）。"""

    词形: str
    操作: str
    所指: str
    承接: str | None = None


@dataclass(frozen=True)
class ParsedStep:
    """原稿一句话解析出的工序步骤。"""

    id: str
    文稿: str
    版本: int
    原句: str
    操作: str
    宾语: str | None
    承接: str | None
    可省: bool
    重复: int
    需老师: bool
    前置条件: dict[str, Any]
    效果特征: tuple[str, ...]
    需资源: tuple[str, ...]
    工位: str | None
    离台前完成: str | None
    停手条件: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    文稿: str
    版本: int
    师傅: str
    解析备注: str
    术语表: tuple[TermSense, ...]
    步骤: tuple[ParsedStep, ...]

    def step(self, step_id: str) -> ParsedStep:
        for step in self.步骤:
            if step.id == step_id:
                return step
        raise KeyError(step_id)


@dataclass(frozen=True)
class Confirmation:
    """教师对跨版本接续点的确认。只有“成立”可用于衔接。"""

    id: str
    状态: str  # 成立 / 不成立 / 待复核
    来源: str
    来稿版本: tuple[str, int]
    来步骤: str | None
    去稿版本: tuple[str, int]
    去步骤: str | None
    共同接续点: dict[str, Any] | None
    适用原句: str
    说明: str


@dataclass(frozen=True)
class Substitution:
    """材料替代登记。成立与否取决于工序前后条件，不看名称相似。"""

    id: str
    状态: str
    来源: str
    缺料: str
    替代料: str | None
    适用工序: str | None
    前置条件: dict[str, Any] | None
    满足效果: str | None
    说明: str


@dataclass(frozen=True)
class RecheckNote:
    """新供稿补出省略文字后，需要教师复核的旧解释。"""

    id: str
    新供稿: tuple[str, int]
    被补充原句: tuple[Any, ...]
    待查解释: tuple[str, ...]
    状态: str
    说明: str


@dataclass(frozen=True)
class StockItem:
    id: str
    工位: str
    资源: str
    数量: int
    里侧: str  # 可借 / 留台
    时段: str


@dataclass(frozen=True)
class Learner:
    id: str
    学员: str
    可做: tuple[str, ...]
    需老师: tuple[str, ...]
    时段: tuple[str, ...]


@dataclass(frozen=True)
class Sample:
    id: str
    学员: str
    状态: str  # 未做 / 在制
    台位: str
    特征: tuple[str, ...]
    本次要求: str
    原始指令: str | None


@dataclass(frozen=True)
class Direction:
    id: str
    文稿: str
    版本: int
    状态: str
    说明: str


@dataclass(frozen=True)
class Manuscript:
    id: str
    版本: int
    师傅: str
    来源: str
    内容: str


@dataclass(frozen=True)
class PlannedStep:
    """计划里一条可执行或被拦截的步骤。"""

    step: ParsedStep
    状态: str  # 可执行 / 条件未满足 / 跳过(可选) / 拦截
    重复: int
    资源处置: tuple[str, ...] = field(default_factory=tuple)
    替代: Substitution | None = None
    问题: tuple[str, ...] = field(default_factory=tuple)
    接续确认: Confirmation | None = None


@dataclass(frozen=True)
class Plan:
    样件: Sample
    结论: str  # 可执行 / 交回老师
    路由: tuple[tuple[str, int], ...]
    已形成特征: tuple[str, ...]
    步骤: tuple[PlannedStep, ...]
    问题: tuple[str, ...]
    停手条件: tuple[str, ...]
    依据: dict[str, Any]
