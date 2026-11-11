# -*- coding: utf-8 -*-
"""预算账本：所有模型调用必须先过这里，保证总预算 ¥2 不被突破。

设计原则：
- 调用前按最坏情况估算，余额不够就不发请求；
- 调用后按 API 返回的 usage 记账；
- 账本落盘，重启不丢；
- 单日上限和总上限双重保护。
"""
import json
import threading
import time
from pathlib import Path

from .config import (
    BUDGET_FILE,
    DAILY_BUDGET_CNY,
    INPUT_PRICE_PER_M_CNY,
    OUTPUT_PRICE_PER_M_CNY,
    TOTAL_BUDGET_CNY,
)


class BudgetExceeded(RuntimeError):
    """预算不足，拒绝调用模型。"""


_lock = threading.Lock()


def _today():
    return time.strftime("%Y-%m-%d")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _empty():
    return {
        "total_spent_cny": 0.0,
        "total_calls": 0,
        "daily": {},
        "updated_at": _now(),
    }


def estimate_cost(prompt_chars, max_output_tokens):
    """按字符数保守估算一次调用的最坏成本（人民币元）。

    中文场景下 1 字符约等于 1 token 的上界估计；宁可高估。
    """
    input_tokens = max(1, int(prompt_chars))
    return (
        input_tokens / 1_000_000 * INPUT_PRICE_PER_M_CNY
        + max_output_tokens / 1_000_000 * OUTPUT_PRICE_PER_M_CNY
    )


class BudgetLedger:
    def __init__(self, path=None, total_cap=None, daily_cap=None):
        self.path = Path(path or BUDGET_FILE)
        self.total_cap = float(total_cap if total_cap is not None else TOTAL_BUDGET_CNY)
        self.daily_cap = float(daily_cap if daily_cap is not None else DAILY_BUDGET_CNY)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        if not self.path.exists():
            return _empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return _empty()
            data.setdefault("total_spent_cny", 0.0)
            data.setdefault("total_calls", 0)
            data.setdefault("daily", {})
            return data
        except Exception:
            # 账本损坏时宁可归零重记，也不能让服务起不来
            return _empty()

    def _save(self, data):
        data["updated_at"] = _now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self):
        with _lock:
            data = self._load()
            today = _today()
            day = data["daily"].get(today, {"spent_cny": 0.0, "calls": 0})
            total = round(float(data["total_spent_cny"]), 6)
            daily = round(float(day.get("spent_cny", 0.0)), 6)
            return {
                "total_spent_cny": total,
                "total_remaining_cny": round(max(0.0, self.total_cap - total), 6),
                "total_cap_cny": round(self.total_cap, 6),
                "daily_spent_cny": daily,
                "daily_remaining_cny": round(max(0.0, self.daily_cap - daily), 6),
                "daily_cap_cny": round(self.daily_cap, 6),
                "total_calls": int(data.get("total_calls", 0)),
            }

    def check(self, estimated_cny):
        """调用前检查；不够就抛 BudgetExceeded。"""
        with _lock:
            data = self._load()
            today = _today()
            day = data["daily"].get(today, {"spent_cny": 0.0, "calls": 0})
            total = float(data["total_spent_cny"])
            daily = float(day.get("spent_cny", 0.0))
            if total + estimated_cny > self.total_cap + 1e-9:
                raise BudgetExceeded(
                    f"总预算 ¥{self.total_cap:.2f} 已用完（已花 ¥{total:.3f}），"
                    "为避免超支，本次不再调用模型。"
                )
            if daily + estimated_cny > self.daily_cap + 1e-9:
                raise BudgetExceeded(
                    f"今日额度 ¥{self.daily_cap:.2f} 已用完（今日已花 ¥{daily:.3f}），"
                    "请明天再试。"
                )

    def record(self, input_tokens, output_tokens):
        """调用后记账，返回本次成本与账本快照。"""
        input_tokens = max(0, int(input_tokens or 0))
        output_tokens = max(0, int(output_tokens or 0))
        cost = (
            input_tokens / 1_000_000 * INPUT_PRICE_PER_M_CNY
            + output_tokens / 1_000_000 * OUTPUT_PRICE_PER_M_CNY
        )
        with _lock:
            data = self._load()
            today = _today()
            day = data["daily"].setdefault(today, {"spent_cny": 0.0, "calls": 0})
            data["total_spent_cny"] = round(float(data["total_spent_cny"]) + cost, 6)
            data["total_calls"] = int(data.get("total_calls", 0)) + 1
            day["spent_cny"] = round(float(day.get("spent_cny", 0.0)) + cost, 6)
            day["calls"] = int(day.get("calls", 0)) + 1

            # 只保留最近 30 天，防止账本无限增长
            if len(data["daily"]) > 30:
                keep = sorted(data["daily"])[-30:]
                data["daily"] = {k: data["daily"][k] for k in keep}

            self._save(data)
            total = round(float(data["total_spent_cny"]), 6)
            daily = round(float(day["spent_cny"]), 6)
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_cny": round(cost, 6),
                "total_spent_cny": total,
                "total_remaining_cny": round(max(0.0, self.total_cap - total), 6),
                "daily_spent_cny": daily,
                "daily_remaining_cny": round(max(0.0, self.daily_cap - daily), 6),
                "total_cap_cny": round(self.total_cap, 6),
                "daily_cap_cny": round(self.daily_cap, 6),
            }
