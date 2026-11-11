# -*- coding: utf-8 -*-
"""生成：检索 → DeepSeek 结构化输出（回答 + 办事清单）→ 出处解析 → 预算记账。

与 P6 的差别：
1. 一次调用同时返回 answer 和 checklist；
2. 所有调用先过预算账本，总预算 ¥2；
3. 同一问题 24h 缓存；
4. 检索判为无资料时直接拒答，不调用模型。
"""
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import retrieve
from .budget import BudgetExceeded, BudgetLedger, estimate_cost
from .cache import ResponseCache, make_key
from .config import (
    CACHE_VERSION,
    DEEPSEEK_MODEL,
    DEEPSEEK_URL,
    LLM_RETRIES,
    LLM_TIMEOUT,
    MAX_OUTPUT_TOKENS,
    REFUSE_TEXT,
    SYSTEM_PROMPT,
    TEMPERATURE,
)

# 全局单例；测试里可以替换成临时路径的实例
ledger = BudgetLedger()
cache = ResponseCache()


class LLMError(RuntimeError):
    """模型调用失败（网络、鉴权、返回格式等）。"""


# ===== 出网守卫：https + 域名白名单 + DNS 全公网 + 禁重定向 =====
ALLOW_HOST = "api.deepseek.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _guard_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != ALLOW_HOST or (p.port not in (None, 443)):
        raise ValueError(f"URL 未通过白名单校验: {url}")
    for info in socket.getaddrinfo(p.hostname, 443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError(f"DNS 解析到非公网地址 {info[4][0]}，拒绝请求")


def _call_deepseek(messages):
    """调用 DeepSeek，返回 (content, usage)。Key 只从环境变量读取。"""
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise LLMError("环境变量 LLM_API_KEY 未设置")

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = None

    for i in range(LLM_RETRIES + 1):
        try:
            _guard_url(DEEPSEEK_URL)
            req = urllib.request.Request(
                DEEPSEEK_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
            with _OPENER.open(req, timeout=LLM_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            usage = data.get("usage") or {}
            if not content.strip():
                raise LLMError("模型返回了空内容")
            return content, usage
        except urllib.error.HTTPError as e:
            last_err = e
            # 鉴权/参数错误重试无意义，直接失败
            if e.code in (400, 401, 403, 404, 422):
                raise LLMError(f"模型接口返回 HTTP {e.code}") from e
        except LLMError as e:
            last_err = e
        except Exception as e:  # 网络抖动/超时
            last_err = e

        if i < LLM_RETRIES:
            time.sleep(2)

    raise LLMError(f"模型调用失败：{type(last_err).__name__}: {last_err}")


def _build_messages(question, hits):
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(f"【资料{i}】栏目：{h['category']}｜文件：{h['title']}\n{h['text']}")
    context = "\n\n".join(blocks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n\n{context}\n\n---\n用户问题：{question}"},
    ]


def _strip_fences(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_structured(text):
    """尽量从模型输出里解析 JSON；解析失败返回 None。"""
    text = _strip_fences(text)
    if not text:
        return None
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for raw in candidates:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("answer"), str):
            return data
    return None


def _salvage_answer(text):
    """JSON 被截断时，至少把 answer 字段抢救出来，避免把半截 JSON 显示给用户。"""
    text = _strip_fences(text)
    m = re.search(r'"answer"\s*:\s*"(.*?)(?<!\\)"', text, re.S)
    if not m:
        m = re.search(r'"answer"\s*:\s*"(.*)$', text, re.S)
    if not m:
        return ""
    raw = m.group(1)
    try:
        return json.loads('"' + raw + '"')
    except Exception:
        return (
            raw.replace("\\n", "\n")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
            .strip()
        )


def _clean_str(value, limit=500):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _clean_list(value, limit=8, item_limit=300):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = _clean_str(item, item_limit)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _normalize_checklist(value):
    if not isinstance(value, dict):
        return None
    item = {
        "title": _clean_str(value.get("title"), 80),
        "steps": _clean_list(value.get("steps")),
        "materials": _clean_list(value.get("materials")),
        "location": _clean_str(value.get("location"), 200),
        "deadline": _clean_str(value.get("deadline"), 200),
        "notes": _clean_list(value.get("notes")),
    }
    if not any([item["title"], item["steps"], item["materials"], item["location"],
                item["deadline"], item["notes"]]):
        return None
    return item


def _checklist_text(checklist):
    if not checklist:
        return ""
    parts = [checklist.get("title", ""), checklist.get("location", ""), checklist.get("deadline", "")]
    parts.extend(checklist.get("steps", []))
    parts.extend(checklist.get("materials", []))
    parts.extend(checklist.get("notes", []))
    return "\n".join(p for p in parts if p)


def _parse_cited(text, hits):
    """从「资料N」提取真正被引用的资料；没标就返回全部（供界面展示）。"""
    idx = {int(n) for n in re.findall(r"资料(\d+)", text or "") if 1 <= int(n) <= len(hits)}
    if not idx:
        return hits
    return [h for i, h in enumerate(hits, 1) if i in idx]


def _dedupe(hits):
    seen, out = set(), []
    for h in hits:
        if h["doc_id"] in seen:
            continue
        seen.add(h["doc_id"])
        out.append(h)
    return out


def _slim(h):
    return {k: h[k] for k in ("doc_id", "title", "category", "url", "score")}


def _base_result(answer_text, checklist, sources, no_hit, model, elapsed):
    return {
        "answer_id": uuid.uuid4().hex[:12],
        "answer": answer_text,
        "checklist": checklist,
        "sources": sources,
        "no_hit": no_hit,
        "model": model,
        "elapsed": round(elapsed, 1),
        "cached": False,
        "cost_cny": 0.0,
    }


def _attach_budget(result):
    result["budget"] = ledger.snapshot()
    return result


def answer(question):
    """主入口：问题 → {answer, checklist, sources, no_hit, cost, budget}。"""
    t0 = time.time()
    q = (question or "").strip()
    if not q:
        raise ValueError("问题不能为空")

    key = make_key(q)
    cached = cache.get(key)
    if cached:
        result = dict(cached)
        result["answer_id"] = uuid.uuid4().hex[:12]
        result["cached"] = True
        result["cost_cny"] = 0.0
        result["elapsed"] = round(time.time() - t0, 1)
        return _attach_budget(result)

    hits = retrieve.search(q)
    if retrieve.no_hit(hits):
        result = _base_result(REFUSE_TEXT, None, [], True, DEEPSEEK_MODEL,
                              time.time() - t0)
        cache.set(key, result)
        return _attach_budget(result)

    messages = _build_messages(q, hits)
    prompt_chars = sum(len(m.get("content", "")) for m in messages)
    estimated = estimate_cost(prompt_chars, MAX_OUTPUT_TOKENS)
    ledger.check(estimated)

    content, usage = _call_deepseek(messages)
    parsed = _parse_structured(content)

    if parsed:
        answer_text = _clean_str(parsed.get("answer"), 4000)
        checklist = _normalize_checklist(parsed.get("checklist"))
        truncated = False
    else:
        # 解析失败时先尝试抢救 answer 字段；抢救不到也不把半截 JSON 当回答
        salvaged = _salvage_answer(content)
        if salvaged:
            answer_text = _clean_str(salvaged, 4000)
            truncated = True
        elif content.lstrip().startswith("{"):
            answer_text = "这次回答生成不完整，请再问一次，或把问题问得更具体一点。"
            truncated = True
        else:
            answer_text = _clean_str(content, 4000)
            truncated = False
        checklist = None

    if not answer_text:
        raise LLMError("模型没有返回可用回答")

    cited_text = answer_text + "\n" + _checklist_text(checklist)
    sources = [_slim(h) for h in _dedupe(_parse_cited(cited_text, hits))]

    # 模型自己明确说“资料里没有”时，统一收口成拒答：
    # 不展示不相关出处，也不展示可能硬凑出来的清单。
    refusal_markers = (
        "知识库中没有找到",
        "没有找到相关资料",
        "没有找到与该问题相关的资料",
        "无法回答",
    )
    no_hit_flag = any(marker in answer_text for marker in refusal_markers)
    if no_hit_flag:
        answer_text = REFUSE_TEXT
        checklist = None
        sources = []

    input_tokens = usage.get("prompt_tokens") or prompt_chars
    output_tokens = usage.get("completion_tokens") or max(1, len(content))
    cost = ledger.record(input_tokens, output_tokens)

    result = _base_result(answer_text, checklist, sources, no_hit_flag, DEEPSEEK_MODEL,
                          time.time() - t0)
    result["cost_cny"] = cost["cost_cny"]
    result["truncated"] = truncated
    result["usage"] = {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
    }
    cache.set(key, {
        "answer": result["answer"],
        "checklist": result["checklist"],
        "sources": result["sources"],
        "no_hit": result["no_hit"],
        "model": result["model"],
    })
    return _attach_budget(result)


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else input("问题：")
    r = answer(q)
    print("\n" + r["answer"])
    if r.get("checklist"):
        print("\n[办事清单]")
        print(json.dumps(r["checklist"], ensure_ascii=False, indent=2))
    print(f"\n—— 出处：{[s['title'] for s in r['sources']]}")
    print(f"—— 本次 ¥{r['cost_cny']:.4f}；预算剩余 ¥{r['budget']['total_remaining_cny']:.4f}")
