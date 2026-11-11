# -*- coding: utf-8 -*-
"""Web 接口测试：不调用模型。"""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.feedback = Path(self.tmp.name) / "feedback.jsonl"
        self.old_feedback = app_module.FEEDBACK_FILE
        app_module.FEEDBACK_FILE = self.feedback
        self.client = TestClient(app_module.app)

    def tearDown(self):
        app_module.FEEDBACK_FILE = self.old_feedback
        self.tmp.cleanup()

    def test_index(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("汕大办事助手", resp.text)

    def test_favicon(self):
        self.assertEqual(self.client.get("/favicon.ico").status_code, 204)

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_question_too_long(self):
        resp = self.client.post("/api/ask", json={"question": "问" * 201})
        self.assertEqual(resp.status_code, 400)

    def test_feedback_written(self):
        resp = self.client.post("/api/feedback", json={
            "answer_id": "abc123",
            "rating": -1,
            "comment": "没看懂",
            "question": "测试问题",
            "session_id": "s1",
        })
        self.assertEqual(resp.status_code, 200)
        lines = self.feedback.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        item = json.loads(lines[0])
        self.assertEqual(item["rating"], -1)
        self.assertEqual(item["comment"], "没看懂")

    def test_feedback_bad_rating(self):
        resp = self.client.post("/api/feedback", json={
            "answer_id": "abc", "rating": 0
        })
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
