# -*- coding: utf-8 -*-
"""P12 汕大办事助手：全局配置

所有可调参数集中在这里；预算、模型、检索参数都不散落在业务代码里。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# HuggingFace 缓存放 D 盘 + 大陆镜像（必须在 import transformers 前设置）
os.environ.setdefault("HF_HOME", str(ROOT / ".hf_cache"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "15")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# ===== 向量模型与检索参数（沿用 P6 的调优结果）=====
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
MODEL_DIR = ROOT / "models" / "bge-small-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
TOP_K = 8
NO_HIT_THRESHOLD = 0.55
MIN_DOC_CHARS = 20

# ===== 存储 =====
STORE = ROOT / "kb" / "store"
EXTRACTED = ROOT / "data" / "extracted"
RUNTIME = ROOT / "runtime"
BUDGET_FILE = RUNTIME / "budget.json"
CACHE_FILE = RUNTIME / "cache.json"
FEEDBACK_FILE = RUNTIME / "feedback.jsonl"
DATA_MANIFEST = ROOT / "data_manifest.json"

# ===== DeepSeek 生成端 =====
# deepseek-chat 当前实测映射到非思考模式，避免 reasoning token 浪费；
# 模型名允许用环境变量覆盖，接口变更时不用改代码。
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = os.environ.get("P12_MODEL", "deepseek-chat")
LLM_TIMEOUT = 60
LLM_RETRIES = 2
MAX_OUTPUT_TOKENS = int(os.environ.get("P12_MAX_OUTPUT_TOKENS", "1100"))
TEMPERATURE = 0.2

# ===== 预算（总预算 ¥2，用户 2026-11-11 拍板）=====
TOTAL_BUDGET_CNY = float(os.environ.get("P12_TOTAL_BUDGET_CNY", "2.0"))
DAILY_BUDGET_CNY = float(os.environ.get("P12_DAILY_BUDGET_CNY", "0.8"))

# 保守估价：按较高价位估算，宁可提前停，不超支。
# 单位：人民币元 / 百万 tokens。
INPUT_PRICE_PER_M_CNY = float(os.environ.get("P12_INPUT_PRICE_PER_M", "4.0"))
OUTPUT_PRICE_PER_M_CNY = float(os.environ.get("P12_OUTPUT_PRICE_PER_M", "8.0"))

# ===== 缓存与限额 =====
CACHE_TTL_SECONDS = 24 * 3600
CACHE_MAX_ENTRIES = 300
CACHE_VERSION = "p12-v4"
RATE_LIMIT_PER_SESSION = int(os.environ.get("P12_RATE_LIMIT_PER_SESSION", "30"))
RATE_LIMIT_PER_IP = int(os.environ.get("P12_RATE_LIMIT_PER_IP", "200"))

# ===== 产品文案 =====
REFUSE_TEXT = (
    "办事指南知识库中没有找到与该问题相关的资料，无法回答。"
    "建议到汕头大学信息公开网（info.stu.edu.cn）查询，"
    "或直接咨询学校相关职能部门。"
)

SYSTEM_PROMPT = """你是「汕大办事助手」，只依据【资料】回答汕头大学办事问题。

严格输出 JSON，不要 Markdown 代码块，不要输出 JSON 之外的任何文字：
{
  "answer": "用简体中文回答；关键事实后用（资料N）标注出处",
  "checklist": {
    "title": "事项名称；资料中没有明确事项就填空字符串",
    "steps": ["步骤，关键处标（资料N）"],
    "materials": ["需要准备的材料，标（资料N）"],
    "location": "办理地点；没有就填空字符串",
    "deadline": "办理时限或截止时间；没有就填空字符串",
    "notes": ["注意事项，标（资料N）"]
  }
}

规则：
1. 只依据【资料】中的内容回答；资料里没有的信息一律不得编造。
2. 用简体中文，条理清晰；涉及流程时按步骤列出。
3. 关键事实后用（资料N）标注出处编号。
4. 与问题相关的要点必须逐条列全：金额、时限、材料、审批人等细节，只要资料里有且与问题相关，都要提到。
5. 金额、数量、边界条件必须逐字照抄原文表述（例如「3000元及以上」「不超过40小时」），不得改写或自行推断边界归属。
6. 回答限定在与问题直接相关的流程上：不同流程、不同表格的资料不要互相混合，引用某流程时不要夹带其他流程的环节。
7. 只有当用户明确询问「怎么办理 / 流程 / 需要什么材料 / 去哪里办 / 要办什么手续」时，才填写 checklist；如果用户只问规定、金额、时限、条件、区别，checklist 的 title/steps/materials/location/deadline/notes 全部留空。
8. 流程类问题：answer 只用 2-4 句话概括关键结论和入口，详细步骤放进 checklist，避免两处重复；checklist 的 steps 最多 6 条、materials 最多 6 条、notes 最多 4 条，每条不超过 80 字。
9. 办事清单必须与用户问题直接对应，不要把其他事项的流程塞进来；只从资料抽取，没有依据的字段留空字符串或空数组，绝对不要猜。
10. 如果资料不足以回答，answer 明确说「办事指南知识库中没有找到相关资料」，checklist 的所有字段留空。
11. 与办事咨询无关的请求（写文章、闲聊、外部资讯等），说明不在本知识库服务范围，不展开回答。
12. 不要输出 JSON 之外的任何字符。"""
