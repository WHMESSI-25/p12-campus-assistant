# -*- coding: utf-8 -*-
"""线上启动入口：监听平台注入的 PORT，绑定 0.0.0.0。"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8012"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
