"""工位库存与领用规则。

规则来自 stock.json 的登记字段与 handoff.json 的补充文字：
- “留台”器具只能在登记工位使用，不得借离；“可借”资源可在有余额时跨工位领用。
- 时段不同（上午/下午）的库存视为不同批次，当前时段无登记即不可领。
- handoff 对具体资源的占用说明（如 X5：西台一只短边夹已被 S3 占用）
  落成“预占”，在制样件继续用自己占用的那件不受影响。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import StockItem


@dataclass
class Reservation:
    样件: str
    资源: str
    工位: str
    数量: int
    说明: str


# 交接单中已经说清楚的实物占用，按 (资源, 工位) 登记预占数量。
HANDOFF_RESERVATIONS = (
    Reservation("S3", "短边夹", "西台", 1, "X5：第二只短边夹为S3正在使用，卸下会散灰边"),
)


@dataclass
class StockBook:
    items: tuple[StockItem, ...]
    reservations: tuple[Reservation, ...] = HANDOFF_RESERVATIONS
    _used: dict[str, int] = field(default_factory=dict)

    def _matching(self, resource: str, station: str, slots: tuple[str, ...]) -> list[StockItem]:
        return [
            item for item in self.items
            if item.资源 == resource and item.时段 in slots
            and (item.工位 == station or item.里侧 == "可借")
        ]

    def available(self, resource: str, station: str, slots: tuple[str, ...],
                  sample_id: str | None = None) -> int:
        """当前样件在该工位、该时段可领的净数量。"""
        total = 0
        for item in self._matching(resource, station, slots):
            quantity = item.数量
            for reservation in self.reservations:
                if (reservation.资源 == resource
                        and reservation.工位 == item.工位
                        and reservation.样件 != sample_id):
                    quantity -= reservation.数量
            total += max(quantity, 0)
        used = self._used.get((resource, station, sample_id), 0) if sample_id else 0
        return max(total - used, 0)

    def can_use(self, resource: str, station: str, slots: tuple[str, ...],
                sample_id: str | None = None) -> bool:
        return self.available(resource, station, slots, sample_id) >= 1

    def take(self, resource: str, station: str, slots: tuple[str, ...],
             sample_id: str, quantity: int = 1) -> tuple[bool, str]:
        if self.available(resource, station, slots, sample_id) < quantity:
            return False, f"{station}在{ '/'.join(slots) }没有可领的{resource}（含留台/预占限制）"
        key = (resource, station, sample_id)
        self._used[key] = self._used.get(key, 0) + quantity
        source = self._matching(resource, station, slots)[0]
        note = f"领{resource}×{quantity}（{source.工位}库存{source.id}，{source.里侧}）"
        if source.工位 != station:
            note += f"，可借至{station}"
        return True, note

    def borrowing_violations(self, station: str, resources: tuple[str, ...],
                             slots: tuple[str, ...]) -> tuple[str, ...]:
        """留台器具被要求借离登记工位时的违规说明。"""
        violations = []
        for resource in resources:
            for item in self.items:
                if (item.资源 == resource and item.时段 in slots
                        and item.工位 != station and item.里侧 == "留台"):
                    violations.append(
                        f"{resource}是{item.工位}留台器具（{item.id}），不能借到{station}"
                    )
        return tuple(violations)
