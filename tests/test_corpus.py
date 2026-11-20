"""交接资料格式和原文完整性测试。"""
from pathlib import Path
import json
import subprocess
import sys
import unittest

from corpus import read_collection

ROOT = Path(__file__).resolve().parents[1]


def records(name):
    return read_collection(ROOT / "data" / (name + ".json"))


class MaterialTests(unittest.TestCase):
    def test_collections_are_utf8_record_arrays(self):
        for name, fields in FIELDS.items():
            with self.subTest(collection=name):
                rows = records(name)
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(set(row), set(fields))
                    self.assertIsInstance(row["id"], str)
                    self.assertTrue(row["id"])

    def test_reader_retains_exact_text_and_order(self):
        result = subprocess.check_output(
            [sys.executable, "-m", "corpus", PRIMARY, "--id", LINE_ID],
            cwd=ROOT, text=True, encoding="utf-8",
        )
        original = [row for row in records(PRIMARY) if row["id"] == LINE_ID]
        self.assertTrue(original)
        self.assertEqual(json.loads(result), original)

    def test_in_process_work_has_original_instructions(self):
        directions = {row["id"]: row for row in records("directions")}
        manuscripts = {(row["id"], row["版本"]) for row in records("manuscripts")}
        for sample in records("samples"):
            if sample["原始指令"]:
                source = directions[sample["原始指令"]]
                self.assertIn((source["文稿"], source["版本"]), manuscripts)
        self.assertEqual({"东台", "西台", "北台"}, {row["工位"] for row in records("stock")})


PRIMARY = 'manuscripts'
LINE_ID = 'W1'
FIELDS = {
    "manuscripts": [
        "id",
        "版本",
        "师傅",
        "来源",
        "内容"
    ],
    "stock": [
        "id",
        "工位",
        "资源",
        "数量",
        "里侧",
        "时段"
    ],
    "learners": [
        "id",
        "学员",
        "可做",
        "需老师",
        "时段"
    ],
    "samples": [
        "id",
        "学员",
        "状态",
        "台位",
        "特征",
        "本次要求",
        "原始指令"
    ],
    "directions": [
        "id",
        "文稿",
        "版本",
        "状态",
        "说明"
    ],
    "handoff": [
        "id",
        "来自",
        "到达",
        "适用",
        "文字"
    ]
}
