# -*- coding: utf-8 -*-
"""预算账本测试：不调用模型，纯本地。"""
import tempfile
import unittest
from pathlib import Path

from kb.budget import BudgetExceeded, BudgetLedger, estimate_cost


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "budget.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_estimate_positive(self):
        self.assertGreater(estimate_cost(4000, 1100), 0)

    def test_total_cap_blocks(self):
        ledger = BudgetLedger(path=self.path, total_cap=0.01, daily_cap=10)
        ledger.record(1000, 1000)
        with self.assertRaises(BudgetExceeded):
            ledger.check(0.01)

    def test_daily_cap_blocks(self):
        ledger = BudgetLedger(path=self.path, total_cap=10, daily_cap=0.01)
        ledger.record(1000, 1000)
        with self.assertRaises(BudgetExceeded):
            ledger.check(0.01)

    def test_record_persists(self):
        ledger = BudgetLedger(path=self.path, total_cap=10, daily_cap=10)
        info = ledger.record(1000, 500)
        self.assertGreater(info["cost_cny"], 0)
        again = BudgetLedger(path=self.path, total_cap=10, daily_cap=10)
        snap = again.snapshot()
        self.assertEqual(snap["total_calls"], 1)
        self.assertAlmostEqual(snap["total_spent_cny"], info["cost_cny"], places=6)


if __name__ == "__main__":
    unittest.main()
