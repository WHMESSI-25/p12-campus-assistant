# -*- coding: utf-8 -*-
"""P12 汕大办事助手 Web 服务（FastAPI）。

本地运行：
    .venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8012
"""
import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from kb import retrieve
from kb.budget import BudgetExceeded
from kb.config import (
    DEEPSEEK_MODEL,
    FEEDBACK_FILE,
    RATE_LIMIT_PER_IP,
    RATE_LIMIT_PER_SESSION,
)
from kb.generate import LLMError, answer, ledger

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="汕大办事助手")


@app.on_event("startup")
def _startup():
    """后台预热检索链路；测试环境可用 P12_PRELOAD=0 关闭。"""
    if os.environ.get("P12_PRELOAD", "1") == "1":
        threading.Thread(target=retrieve.warmup, daemon=True).start()

# ===== 简单进程内限流（单进程 uvicorn 足够；多 worker 需换 Redis）=====
_rate_lock = threading.Lock()
_rate_hits = defaultdict(deque)


def _client_ip(request: Request):
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow(session_id, ip):
    now = time.time()
    window = 24 * 3600
    keys = [
        (f"s:{session_id}", RATE_LIMIT_PER_SESSION),
        (f"i:{ip}", RATE_LIMIT_PER_IP),
    ]
    with _rate_lock:
        for key, limit in keys:
            dq = _rate_hits[key]
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= limit:
                return False
        for key, _ in keys:
            _rate_hits[key].append(now)
    return True


class AskIn(BaseModel):
    question: str
    session_id: str | None = None


class FeedbackIn(BaseModel):
    answer_id: str
    rating: int
    comment: str = ""
    question: str = ""
    session_id: str = ""


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "model": DEEPSEEK_MODEL,
        "budget": ledger.snapshot(),
    }


@app.post("/api/ask")
def ask(inp: AskIn, request: Request):
    q = (inp.question or "").strip()
    if not q or len(q) > 200:
        return JSONResponse({"error": "请输入 1-200 字的问题"}, status_code=400)

    session_id = (inp.session_id or "").strip()[:80] or "anonymous"
    ip = _client_ip(request)
    if not _allow(session_id, ip):
        return JSONResponse(
            {
                "error": "今天的试用次数已用完。这个版本额度有限，明天再来试试。",
                "code": "rate_limited",
            },
            status_code=429,
        )

    try:
        return answer(q)
    except BudgetExceeded as e:
        return JSONResponse(
            {
                "error": str(e),
                "code": "budget_exceeded",
                "budget": ledger.snapshot(),
            },
            status_code=429,
        )
    except LLMError as e:
        return JSONResponse(
            {
                "error": "模型服务暂时不可用，请稍后再试。",
                "code": "llm_error",
                "detail": str(e)[:200],
            },
            status_code=503,
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": "服务内部错误，请稍后再试。",
                "code": "internal_error",
                "detail": type(e).__name__,
            },
            status_code=500,
        )


@app.post("/api/feedback")
def feedback(inp: FeedbackIn):
    if inp.rating not in (1, -1):
        return JSONResponse({"error": "rating 只能是 1 或 -1"}, status_code=400)

    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "answer_id": (inp.answer_id or "")[:32],
        "rating": inp.rating,
        "comment": (inp.comment or "").strip()[:300],
        "question": (inp.question or "").strip()[:200],
        "session": hashlib.sha256((inp.session_id or "").encode("utf-8")).hexdigest()[:12],
    }
    with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


@app.get("/api/stats")
def stats():
    """只返回聚合数字，不暴露用户问题原文。"""
    total = {"up": 0, "down": 0}
    if FEEDBACK_FILE.exists():
        for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("rating") == 1:
                total["up"] += 1
            elif item.get("rating") == -1:
                total["down"] += 1
    return {"feedback": total, "budget": ledger.snapshot()}
