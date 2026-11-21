"""加载原始资料与结构化登记，并做形状校验。

读取原始 JSON 时与 corpus 保持同一约定（UTF-8、记录数组、原样文字）。
parses / confirmations 是新增的结构化层，读取时校验关键字段，
避免把缺字段的坏登记悄悄当成“未填写”。
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import (
    Confirmation,
    Direction,
    Learner,
    Manuscript,
    ParsedDocument,
    ParsedStep,
    RecheckNote,
    Sample,
    StockItem,
    Substitution,
    TermSense,
)

REQUIRED_PARSE_STEP_FIELDS = {
    "id", "原句", "操作", "宾语", "承接", "可省", "重复", "需老师",
    "前置条件", "效果特征", "需资源", "工位", "离台前完成",
}
REQUIRED_CONFIRMATION_FIELDS = {
    "id", "状态", "来源", "来稿版本", "来步骤", "去稿版本", "去步骤",
    "共同接续点", "适用原句", "说明",
}


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _split_skills(text: str) -> tuple[str, ...]:
    text = (text or "").strip()
    if not text or text == "无":
        return ()
    return tuple(part.strip() for part in text.replace("，", "、").split("、") if part.strip())


def _split_slots(text: str) -> tuple[str, ...]:
    text = (text or "").strip()
    if not text:
        return ()
    return tuple(part.strip() for part in text.replace("和", "、").split("、") if part.strip())


class WorkshopData:
    """一次工作坊所用全部资料的只读视图。"""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.manuscripts = self._load_manuscripts()
        self.stock = self._load_stock()
        self.learners = self._load_learners()
        self.samples = self._load_samples()
        self.directions = self._load_directions()
        self.documents = self._load_parses()
        self.confirmations, self.substitutions, self.rechecks = self._load_confirmations()

    def _rows(self, name: str) -> list[dict]:
        rows = read_json(self.directory / f"{name}.json")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"{name}.json 应为记录对象的数组")
        return rows

    def _load_manuscripts(self) -> dict[tuple[str, int], Manuscript]:
        result = {}
        for row in self._rows("manuscripts"):
            item = Manuscript(row["id"], int(row["版本"]), row["师傅"], row["来源"], row["内容"])
            result[(item.id, item.版本)] = item
        return result

    def _load_stock(self) -> list[StockItem]:
        return [
            StockItem(row["id"], row["工位"], row["资源"], int(row["数量"]), row["里侧"], row["时段"])
            for row in self._rows("stock")
        ]

    def _load_learners(self) -> dict[str, Learner]:
        result = {}
        for row in self._rows("learners"):
            item = Learner(
                row["id"], row["学员"],
                _split_skills(row["可做"]),
                _split_skills(row["需老师"]),
                _split_slots(row["时段"]),
            )
            result[item.id] = item
        return result

    def _load_samples(self) -> dict[str, Sample]:
        result = {}
        for row in self._rows("samples"):
            feature_text = row["特征"].strip()
            features = () if feature_text in ("", "无") else tuple(
                part.strip() for part in feature_text.replace("，", "、").split("、") if part.strip()
            )
            item = Sample(
                row["id"], row["学员"], row["状态"], row["台位"],
                features, row["本次要求"], row["原始指令"] or None,
            )
            result[item.id] = item
        return result

    def _load_directions(self) -> dict[str, Direction]:
        return {
            row["id"]: Direction(row["id"], row["文稿"], int(row["版本"]), row["状态"], row["说明"])
            for row in self._rows("directions")
        }

    def _load_parses(self) -> dict[tuple[str, int], ParsedDocument]:
        rows = read_json(self.directory / "parses.json")
        if not isinstance(rows, list):
            raise ValueError("parses.json 应为数组")
        result: dict[tuple[str, int], ParsedDocument] = {}
        for row in rows:
            key = (row["文稿"], int(row["版本"]))
            if key not in self.manuscripts:
                raise ValueError(f"解析 {key} 没有对应原稿")
            terms = tuple(
                TermSense(t["词形"], t["操作"], t["所指"], t.get("承接"))
                for t in row.get("术语表", [])
            )
            steps = []
            for raw in row["步骤"]:
                missing = REQUIRED_PARSE_STEP_FIELDS - set(raw)
                if missing:
                    raise ValueError(f"解析步骤 {raw.get('id')} 缺字段：{sorted(missing)}")
                steps.append(ParsedStep(
                    id=raw["id"], 文稿=key[0], 版本=key[1],
                    原句=raw["原句"], 操作=raw["操作"], 宾语=raw["宾语"],
                    承接=raw["承接"], 可省=bool(raw["可省"]),
                    重复=int(raw["重复"]), 需老师=bool(raw["需老师"]),
                    前置条件=raw["前置条件"],
                    效果特征=tuple(raw["效果特征"]),
                    需资源=tuple(raw["需资源"]),
                    工位=raw["工位"],
                    离台前完成=raw["离台前完成"],
                    停手条件=raw.get("停手条件"),
                ))
            doc = ParsedDocument(
                key[0], key[1], row["师傅"], row.get("解析备注", ""), terms, tuple(steps)
            )
            if key in result:
                raise ValueError(f"解析重复登记：{key}")
            result[key] = doc
        return result

    def _load_confirmations(self):
        raw = read_json(self.directory / "confirmations.json")
        if not isinstance(raw, dict):
            raise ValueError("confirmations.json 应为对象")
        confirmations: list[Confirmation] = []
        for row in raw.get("接续确认", []):
            missing = REQUIRED_CONFIRMATION_FIELDS - set(row)
            if missing:
                raise ValueError(f"接续确认 {row.get('id')} 缺字段：{sorted(missing)}")
            confirmations.append(Confirmation(
                row["id"], row["状态"], row["来源"],
                tuple(row["来稿版本"]), row["来步骤"],
                tuple(row["去稿版本"]), row["去步骤"],
                row["共同接续点"], row["适用原句"], row["说明"],
            ))
        substitutions = [
            Substitution(
                row["id"], row["状态"], row["来源"], row["缺料"], row.get("替代料"),
                row.get("适用工序"), row.get("前置条件"), row.get("满足效果"), row["说明"],
            )
            for row in raw.get("材料替代", [])
        ]
        rechecks = [
            RecheckNote(
                row["id"], tuple(row["新供稿"]), tuple(row["被补充原句"]),
                tuple(row["待查解释"]), row["状态"], row["说明"],
            )
            for row in raw.get("解释复核", [])
        ]
        return confirmations, substitutions, rechecks

    # ---- 便捷查询 ----
    def document(self, doc_id: str, version: int) -> ParsedDocument:
        return self.documents[(doc_id, version)]

    def learner_for_sample(self, sample: Sample) -> Learner:
        return self.learners[sample.学员]

    def direction(self, direction_id: str | None) -> Direction | None:
        if not direction_id:
            return None
        return self.directions.get(direction_id)

    def manuscript_text(self, doc_id: str, version: int) -> str:
        return self.manuscripts[(doc_id, version)].内容
