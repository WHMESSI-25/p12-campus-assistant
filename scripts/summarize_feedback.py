# -*- coding: utf-8 -*-
"""汇总反馈：读 runtime/feedback.jsonl，输出 Markdown 摘要。

用法：
    .venv/Scripts/python.exe scripts/summarize_feedback.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kb.config import FEEDBACK_FILE  # noqa: E402


def main():
    if not FEEDBACK_FILE.exists():
        print("还没有反馈记录。")
        return

    rows = []
    for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    if not rows:
        print("还没有反馈记录。")
        return

    counts = Counter(r.get("rating") for r in rows)
    print("# 反馈汇总\n")
    print(f"- 总反馈：{len(rows)} 条")
    print(f"- 有用：{counts.get(1, 0)} 条")
    print(f"- 没用：{counts.get(-1, 0)} 条\n")

    negatives = [r for r in rows if r.get("rating") == -1]
    if negatives:
        print("## 没用反馈\n")
        for r in negatives[-20:]:
            print(f"- `{r.get('ts', '')}` {r.get('question', '')}")
            if r.get("comment"):
                print(f"  - 用户说：{r['comment']}")
        print()


if __name__ == "__main__":
    main()
