# -*- coding: utf-8 -*-
"""简单的回答缓存：同一问题 24 小时内不重复调用模型。

单进程使用；写入用临时文件 + replace，避免半截 JSON。
"""
import hashlib
import json
import threading
import time
from pathlib import Path

from .config import CACHE_FILE, CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS, CACHE_VERSION


_lock = threading.Lock()


def make_key(question):
    text = " ".join((question or "").strip().lower().split())
    raw = f"{CACHE_VERSION}|{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ResponseCache:
    def __init__(self, path=None, ttl=None, max_entries=None):
        self.path = Path(path or CACHE_FILE)
        self.ttl = int(ttl if ttl is not None else CACHE_TTL_SECONDS)
        self.max_entries = int(max_entries if max_entries is not None else CACHE_MAX_ENTRIES)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self, data):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key):
        now = time.time()
        with _lock:
            data = self._load()
            item = data.get(key)
            if not item:
                return None
            if now - float(item.get("ts", 0)) > self.ttl:
                data.pop(key, None)
                self._save(data)
                return None
            result = item.get("result")
            return result if isinstance(result, dict) else None

    def set(self, key, result):
        now = time.time()
        with _lock:
            data = self._load()
            # 清过期
            data = {
                k: v
                for k, v in data.items()
                if now - float(v.get("ts", 0)) <= self.ttl
            }
            data[key] = {"ts": now, "result": result}
            if len(data) > self.max_entries:
                keep = sorted(data.items(), key=lambda kv: kv[1].get("ts", 0))[-self.max_entries:]
                data = dict(keep)
            self._save(data)
