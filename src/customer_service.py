"""智能客服模块 — 基于 DeepSeek 的多轮对话客服"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── 终端编码修复（Windows GBK 兼容） ──────────────────────────
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── 路径 ─────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"
CHAT_HISTORY_FILE = DATA_DIR / "chat_history.json"

# ── DeepSeek 配置（与 optimizer 共享同一套 KEY 和 base_url） ──
DEEPSEEK_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

if not DEEPSEEK_API_KEY:
    raise RuntimeError("OPENAI_API_KEY 未配置，请在 .env 中填写 DeepSeek API Key")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# ── 知识库构建 ───────────────────────────────────────────────

def load_products() -> list[dict]:
    """加载商品数据。"""
    if not PRODUCTS_FILE.exists():
        raise FileNotFoundError(f"商品数据文件不存在: {PRODUCTS_FILE}，请先运行爬虫模块。")
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_knowledge_base(products: list[dict]) -> str:
    """从商品列表生成结构化的知识库文本。

    提取标题、价格、品类、描述等关键信息供 LLM 检索。
    """
    lines = ["【商品知识库】\n"]
    for i, p in enumerate(products, 1):
        title = p.get("title", "未知商品")
        price = p.get("price", 0)
        currency = p.get("currency", "USD")
        category = p.get("category", "未分类")
        description = p.get("description", "")
        stock = p.get("stock_status", "未知")

        # 描述信息：完整保留，供 Agent 提取颜色/材质/尺寸等信息
        if description:
            desc_text = description
        else:
            desc_text = "暂无更详细的颜色/材质信息，建议查看商品详情页"

        lines.append(
            f"{i}. [{category}] {title}\n"
            f"   价格：{price:.2f} {currency}\n"
            f"   库存：{stock}\n"
            f"   描述：{desc_text}\n"
        )
    return "\n".join(lines)


# ── 对话历史管理 ─────────────────────────────────────────────

def load_history() -> list[dict]:
    """读取对话历史。"""
    if CHAT_HISTORY_FILE.exists():
        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history: list[dict]) -> None:
    """保存对话历史到 JSON。"""
    with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def clear_history() -> None:
    """清空对话历史。"""
    save_history([])
    print("[对话历史已清空]")


# ── 工具函数 ─────────────────────────────────────────────────

import re

# 匹配大部分 emoji 的正则（Unicode 扩展）
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc symbols and pictographs
    "\U0001F680-\U0001F6FF"  # Transport and map symbols
    "\U0001F1E0-\U0001F1FF"  # Regional indicators (flags)
    "\U0001F900-\U0001F9FF"  # Supplemental symbols
    "\U0001FA00-\U0001FA6F"  # Chess symbols
    "\U0001FA70-\U0001FAFF"  # Symbols extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "\U00002600-\U000026FF"  # Misc symbols (sun, umbrella, etc.)
    "\U00002B50-\U00002B55"  # Star, etc.
    "\U0001F200-\U0001F2FF"  # Enclosed ideographic supplement
    "]+",
    flags=re.UNICODE,
)

# 兜底话术
FALLBACK_REPLY = "这个我需要帮你确认一下，建议联系人工客服哦～"


def sanitize(text: str) -> str:
    """移除文本中的 emoji，防止 Windows GBK 终端报错。"""
    return _EMOJI_PATTERN.sub("", text).strip()


def safe_print(text: str) -> None:
    """安全打印，防止 GBK 终端因编码问题吞掉输出或报错。"""
    try:
        print(text)
    except UnicodeEncodeError:
        # GBK 终端无法显示中文时，fallback 到纯 ASCII 提示
        text_ascii = text.encode("ascii", errors="replace").decode("ascii")
        print(text_ascii)



# ── 核心对话函数 ─────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个友好的电商客服助手，名叫"小智"。

## 行为规则
1. 只能根据下面提供的【商品知识库】回答用户问题，不得编造商品信息。
2. 如果用户的问题无法从知识库中找到答案，请回复："这个我需要帮你确认一下，建议联系人工客服哦～"
3. 每条回复严格控制在 **80 字以内**，一句话说完，不要多余内容。
4. 语气亲切友好，不要使用任何 emoji 或特殊符号，用纯文字回复。
5. 回答中不要提及你是 AI 或大模型，以"小智"自称。"""


def chat(
    user_message: str,
    chat_history: list[dict] | None = None,
    product_context: str | None = None,
) -> str:
    """调用 DeepSeek API 生成客服回复。

    参数：
        user_message: 用户当前输入
        chat_history: 之前的对话历史（OpenAI 格式）
        product_context: 知识库文本，为 None 时自动构建

    返回：
        AI 回复文本
    """
    if chat_history is None:
        chat_history = []

    # 自动构建知识库（如果未传入）
    if product_context is None:
        products = load_products()
        product_context = build_knowledge_base(products)

    # 构造 messages
    messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{product_context}"},
    ]
    # 添加历史消息（保留最近 10 轮，避免超长上下文）
    messages.extend(chat_history[-20:])
    messages.append({"role": "user", "content": user_message})

    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=200,
        )
        reply = resp.choices[0].message.content

        # 兜底 1：API 返回内容为空或全空白 → 使用固定话术
        if not reply or not reply.strip():
            return FALLBACK_REPLY

        reply = reply.strip()

        # 兜底 2：sanitize 后为空（全是 emoji）→ 使用固定话术
        if not sanitize(reply):
            return FALLBACK_REPLY

        return reply
    except Exception as e:
        return f"抱歉，我现在有点忙不过来，请稍后再试。（错误：{e}）"


# ── Demo 模式 ────────────────────────────────────────────────

def run_demo() -> None:
    """模拟 3 轮用户咨询，展示客服效果。"""
    print("=" * 55)
    print("  [智能客服 Demo — 模拟用户咨询]")
    print("=" * 55)

    products = load_products()
    knowledge = build_knowledge_base(products)

    demo_questions = [
        "你们那个 Fjallraven 背包多少钱？",
        "这个背包是什么材质的？",
        "下单后多久能发货？",
    ]

    history: list[dict] = []

    for i, question in enumerate(demo_questions, 1):
        print(f"\n--- 第 {i} 轮 ---")
        print(f"[用户] {question}")

        reply = chat(question, history, knowledge)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": reply})

        safe_print(f"[小智] {sanitize(reply)}")

    print("\n" + "=" * 55)
    print("  [OK] Demo 结束")
    print("=" * 55)


# ── CLI 交互模式 ─────────────────────────────────────────────

def run_cli() -> None:
    """命令行交互式客服。"""
    print("=" * 50)
    print("  [智能客服小智为您服务]")
    print("  输入问题开始对话，输入 'exit' 退出，'clear' 清空历史")
    print("=" * 50)

    products = load_products()
    knowledge = build_knowledge_base(products)
    history = load_history()

    # 如果历史不为空，提示用户
    if history:
        print(f"  [已载入 {len(history)//2} 轮历史对话]\n")

    while True:
        try:
            user_input = input("\n[你] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n[再见]")
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            print("[感谢您的咨询，再见！]")
            break

        if user_input.lower() == "clear":
            clear_history()
            history = []
            continue

        # 调用 API
        reply = chat(user_input, history, knowledge)
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})

        # 保存到磁盘
        save_history(history)

        safe_print(f"[小智] {sanitize(reply)}")


# ── 入口 ─────────────────────────────────────────────────────

def main():
    """客服模块主入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="智能客服 Agent")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="运行 Demo 模式（模拟 3 轮用户咨询）",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        run_cli()


if __name__ == "__main__":
    main()
