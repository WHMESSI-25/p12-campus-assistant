# -*- coding: utf-8 -*-
"""核心 10 题验收：真实调用模型，结果落 eval/results/。

用法：
    .venv/Scripts/python.exe scripts/check_core10.py --execute
不传 --execute 只打印题目与预算，不调用模型。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kb.budget import BudgetExceeded  # noqa: E402
from kb.generate import LLMError, answer, ledger  # noqa: E402

QUESTIONS = ROOT / "eval" / "core10.jsonl"
OUT_DIR = ROOT / "eval" / "results"


def normalize(text):
    return re.sub(r"[\s，。；：、（）()《》\"'“”‘’·,.;:!?！？-]", "", text or "")


def check_points(answer_text, key_points):
    text = normalize(answer_text)
    missing = [p for p in key_points if normalize(p) not in text]
    return missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="真正调用模型")
    args = parser.parse_args()

    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not args.execute:
        print(f"共 {len(rows)} 题；当前预算：{ledger.snapshot()}")
        for row in rows:
            print(f"{row['id']} {row['question']}")
        print("\n加 --execute 才会真正调用模型。")
        return

    results, total_cost = [], 0.0
    passed = 0
    for row in rows:
        t0 = time.time()
        try:
            result = answer(row["question"])
            cost = float(result.get("cost_cny", 0.0))
            total_cost += cost
            missing = [] if row.get("expect_no_hit") else check_points(result.get("answer", ""), row.get("key_points", []))
            no_hit_ok = bool(result.get("no_hit")) == bool(row.get("expect_no_hit"))
            ok = no_hit_ok and not missing
            if ok:
                passed += 1
            item = {
                "id": row["id"],
                "question": row["question"],
                "ok": ok,
                "no_hit_expected": bool(row.get("expect_no_hit")),
                "no_hit_actual": bool(result.get("no_hit")),
                "missing_key_points": missing,
                "answer": result.get("answer"),
                "checklist": result.get("checklist"),
                "sources": result.get("sources"),
                "cost_cny": cost,
                "elapsed": result.get("elapsed"),
                "truncated": result.get("truncated", False),
            }
            results.append(item)
            print(f"[{row['id']}] {'PASS' if ok else 'FAIL'} "
                  f"no_hit={result.get('no_hit')} cost=¥{cost:.4f} "
                  f"missing={missing}")
        except (BudgetExceeded, LLMError) as e:
            results.append({"id": row["id"], "question": row["question"], "ok": False, "error": str(e)})
            print(f"[{row['id']}] ERROR {e}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"core10_{time.strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "passed": passed,
        "total": len(rows),
        "total_cost_cny": round(total_cost, 6),
        "budget": ledger.snapshot(),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n结果：{passed}/{len(rows)} 通过；本次花费 ¥{total_cost:.4f}")
    print(f"预算：{ledger.snapshot()}")
    print(f"明细：{out}")


if __name__ == "__main__":
    main()
