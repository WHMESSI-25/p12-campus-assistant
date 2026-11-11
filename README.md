# 汕大办事助手（P12）

把 P6 的校园办事 RAG 升级成给真实用户用的小产品：**回答带原文出处，流程类问题附一张可勾选的办事清单。**

- 产品形态：移动端优先的单页 Web 应用
- 底座：P6 的 112 篇去重语料、415 个检索块、向量 + BM25 混合检索
- 目标：5 个真实用户、5 条反馈、至少 1 轮迭代
- 预算：**总计 ¥2**（含开发测试与试用）

## 它和 P6 的区别

| | P6 | P12 |
|---|---|---|
| 定位 | RAG 技术验证 | 给真实用户用的产品 |
| 成功标准 | 40 题评估 91.2% | 5 个真实用户 + 反馈 + 迭代 |
| 交互 | 聊天问答 | 问答 + 办事清单 + 快捷问题 + 反馈 |
| 成本 | 无产品级限额 | 总预算 ¥2、每日 ¥0.8、输出上限、缓存 |
| 交付 | 能跑的 Demo | URL + 仓库 + README + 复盘 + 迭代记录 |

## 功能

- 单轮办事问答，关键事实后标「资料N」
- 回答下方列出原文出处链接
- 流程类问题生成办事清单：步骤 / 材料 / 地点 / 时限 / 注意事项
- 知识库没有的内容明确拒答，不编造
- 每条回答可点「有用 / 没用」并留言
- 匿名会话限频、每日预算熔断、24 小时回答缓存

## 架构

```
用户提问
  ↓
FastAPI /api/ask
  ↓
kb/retrieve.py   向量 + BM25 RRF 混合检索 Top8
  ↓
相似度闸门 0.55 ── 无相关内容 → 直接拒答（不调用模型）
  ↓
预算检查（总 ¥2 / 每日 ¥0.8）
  ↓
DeepSeek deepseek-chat（非思考模式）
  ↓
JSON 解析：answer + checklist
  ↓
出处解析、拒答收口、预算记账、24h 缓存
  ↓
前端渲染：回答 + 办事清单 + 出处 + 反馈
```

## 本地运行

要求 Python 3.12。

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt

# 向量模型：从 P6 复制，或让 retrieve.py 走魔搭源下载
# 默认路径：models/bge-small-zh-v1.5

# DeepSeek Key 只放环境变量，不写文件
set LLM_API_KEY=你的Key

.venv/Scripts/python -m uvicorn app:app --host 127.0.0.1 --port 8012
```

打开 <http://127.0.0.1:8012>。

线上/沙箱启动用 `run_site.py`，它读取平台注入的 `PORT` 并绑定 `0.0.0.0`：

```bash
python run_site.py
```

## 预算与成本

- 总预算：`P12_TOTAL_BUDGET_CNY=2.0`
- 每日预算：`P12_DAILY_BUDGET_CNY=0.8`
- 单次输出上限：`P12_MAX_OUTPUT_TOKENS=1100`
- 账本：`runtime/budget.json`（重启不丢）
- 缓存：`runtime/cache.json`，同一问题 24h 内不重复调用
- 拒答：不调用模型，成本 0
- 实测单次问答约 **¥0.011–0.017**

预算不够时接口返回 429 和中文提示，不会继续扣费。

## 测试

```bash
# 15 个单元/接口测试，全部使用假模型，不消耗 token
.venv/Scripts/python -m unittest discover -s tests -v

# 核心 10 题真实验收（会消耗预算，默认不执行）
.venv/Scripts/python scripts/check_core10.py
.venv/Scripts/python scripts/check_core10.py --execute
```

核心 10 题覆盖：事实题、流程题、对比题、拒答题。结果写入 `eval/results/`。

## 目录

```
app.py                 FastAPI 服务与反馈接口
kb/config.py           参数、提示词、预算配置
kb/retrieve.py         混合检索与预热
kb/generate.py         结构化生成、预算、缓存、拒答收口
kb/budget.py           ¥2 预算账本
kb/cache.py            24h 回答缓存
kb/store/              chunks.json + vectors.dat
models/                本地向量模型（不入 Git）
web/index.html         移动端单页界面
tests/                 15 个单元/接口测试
eval/core10.jsonl      核心 10 题
scripts/check_core10.py 验收入口
docs/任务书.md         P12 任务书 v1.0
```

## 已知限制

- 单轮问答，不做多轮上下文；
- 不做登录与跨设备历史；
- 只覆盖 P6 已抓取的学校公开办事指南，不包含实时通知、校历、食堂营业时间等；
- `deepseek-chat` 当前映射到非思考模式；如接口变更，用 `P12_MODEL` 环境变量切换；
- 部署方式待 M3 完成（优先 WorkBuddy Sites，魔搭备选）。

## 数据来源

汕头大学信息公开网「学校办事指南」栏目。P6 的抓取、PDF 文字抽取、去重与切块流程见 P6 仓库；本项目直接复用其 `kb/store` 运行数据。
