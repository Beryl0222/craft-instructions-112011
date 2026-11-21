"""命令行入口：编制试样计划、回溯工序、查已发说明的版本与替代。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loader import WorkshopData
from .planner import PlanRequest, Planner
from .renderer import render_learner_instruction, render_teacher_trace, render_version_lookup

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data"


def _parse_doc_version(text: str) -> tuple[str, int]:
    doc, version = text.split(":", 1)
    return doc, int(version)


def _parse_slots(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.replace("和", "、").split("、") if part.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="织造试样说明编制器")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="为一个样件编制试样说明")
    p_plan.add_argument("样件")
    p_plan.add_argument("--时段", default="上午", help="如 上午 / 下午 / 上午、下午")
    p_plan.add_argument("--起始稿", help="未做样件必填，形如 W2:1")
    p_plan.add_argument("--纹样", help="老师指定本次要展示的纹样，如 菱")
    p_plan.add_argument("--视图", choices=("学员", "教师", "json"), default="学员")
    p_plan.add_argument("--数据目录", default=str(DEFAULT_DATA))

    p_trace = sub.add_parser("trace", help="从工序回到原句（教师视图）")
    p_trace.add_argument("样件")
    p_trace.add_argument("--时段", default="上午")
    p_trace.add_argument("--起始稿", help="未做样件必填")
    p_trace.add_argument("--纹样")
    p_trace.add_argument("--数据目录", default=str(DEFAULT_DATA))

    p_lookup = sub.add_parser("lookup", help="查已发说明采用的版本与确认替代")
    p_lookup.add_argument("说明编号")
    p_lookup.add_argument("--数据目录", default=str(DEFAULT_DATA))
    return parser


def _make_request(args) -> PlanRequest:
    return PlanRequest(
        样件=args.样件,
        时段=_parse_slots(args.时段),
        起始稿=_parse_doc_version(args.起始稿) if args.起始稿 else None,
        指定纹样=args.纹样,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data = WorkshopData(Path(args.数据目录))

    if args.command == "lookup":
        print(render_version_lookup(data, args.说明编号))
        return 0

    planner = Planner(data)
    plan = planner.plan(_make_request(args))

    if args.command == "trace":
        print(render_teacher_trace(plan))
        return 0

    if args.视图 == "json":
        payload = {
            "样件": plan.样件.id,
            "结论": plan.结论,
            "路由": [list(part) for part in plan.路由],
            "已形成特征": list(plan.已形成特征),
            "停手条件": list(plan.停手条件),
            "问题": list(plan.问题),
            "依据": plan.依据,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.视图 == "教师":
        print(render_teacher_trace(plan))
    else:
        print(render_learner_instruction(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
