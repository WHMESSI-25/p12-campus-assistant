# -*- coding: utf-8 -*-
"""生成层测试：用假数据与假模型，不消耗 token。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb import generate
from kb.budget import BudgetLedger
from kb.cache import ResponseCache


HITS = [{
    "doc_id": "doc-1",
    "title": "测试办事指南",
    "category": "学生工作",
    "url": "https://example.com/1",
    "chunk_no": 1,
    "text": "这是测试资料。每周不超过8小时。",
    "score": 0.9,
    "fused": 0.1,
}]


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_ledger = generate.ledger
        self.old_cache = generate.cache
        generate.ledger = BudgetLedger(path=self.root / "budget.json",
                                       total_cap=2.0, daily_cap=2.0)
        generate.cache = ResponseCache(path=self.root / "cache.json", ttl=3600,
                                       max_entries=20)

    def tearDown(self):
        generate.ledger = self.old_ledger
        generate.cache = self.old_cache
        self.tmp.cleanup()

    def test_parse_structured_with_fence(self):
        raw = '```json\n{"answer":"测试回答（资料1）","checklist":{"title":"测试","steps":["第一步（资料1）"],"materials":[],"location":"","deadline":"","notes":[]}}\n```'
        data = generate._parse_structured(raw)
        self.assertEqual(data["answer"], "测试回答（资料1）")
        self.assertEqual(data["checklist"]["steps"], ["第一步（资料1）"])

    def test_salvage_truncated_answer(self):
        raw = '{"answer":"这是被截断的回答（资料1）","checklist":{"title":"测试"'
        self.assertEqual(generate._salvage_answer(raw), "这是被截断的回答（资料1）")

    def test_no_hit_does_not_call_model(self):
        with patch.object(generate.retrieve, "search", return_value=[]), \
             patch.object(generate.retrieve, "no_hit", return_value=True), \
             patch.object(generate, "_call_deepseek") as call:
            result = generate.answer("无关问题")
        self.assertTrue(result["no_hit"])
        self.assertIsNone(result["checklist"])
        self.assertEqual(result["cost_cny"], 0.0)
        call.assert_not_called()

    def test_structured_answer_and_cache(self):
        model_json = json.dumps({
            "answer": "测试回答（资料1）",
            "checklist": {
                "title": "测试事项",
                "steps": ["第一步（资料1）"],
                "materials": ["身份证（资料1）"],
                "location": "测试地点",
                "deadline": "",
                "notes": [],
            },
        }, ensure_ascii=False)
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        with patch.object(generate.retrieve, "search", return_value=HITS), \
             patch.object(generate.retrieve, "no_hit", return_value=False), \
             patch.object(generate, "_call_deepseek", return_value=(model_json, usage)) as call:
            first = generate.answer("测试问题")
            second = generate.answer("测试问题")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["answer"], "测试回答（资料1）")
        self.assertEqual(first["checklist"]["title"], "测试事项")
        self.assertEqual(first["sources"][0]["title"], "测试办事指南")
        self.assertGreater(first["cost_cny"], 0)
        self.assertEqual(second["cost_cny"], 0.0)
        self.assertEqual(call.call_count, 1)

    def test_truncated_json_does_not_leak_raw(self):
        raw = '{"answer":"这是被截断的回答（资料1）","checklist":{"title":"测试"'
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        with patch.object(generate.retrieve, "search", return_value=HITS), \
             patch.object(generate.retrieve, "no_hit", return_value=False), \
             patch.object(generate, "_call_deepseek", return_value=(raw, usage)):
            result = generate.answer("测试问题")
        self.assertEqual(result["answer"], "这是被截断的回答（资料1）")
        self.assertTrue(result["truncated"])
        self.assertIsNone(result["checklist"])


if __name__ == "__main__":
    unittest.main()
