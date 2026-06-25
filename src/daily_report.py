#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运营日报模块 (Daily Report)

读取巡店结果 + 竞品变动，调用 DeepSeek 生成中文运营日报，
输出 Markdown 文件 + rich 终端打印。

用法:
  python src/daily_report.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows 终端 UTF-8 修复
if sys.platform == "win32":
    for _s in ("stdout", "stderr"):
        _stream = getattr(sys, _s, None)
        if _stream and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich import box

load_dotenv()

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PATROL_FILE = DATA_DIR / "patrol_result.json"
COMPETITOR_CHANGES_FILE = DATA_DIR / "competitor_changes.json"

# ---------------------------------------------------------------------------
# DeepSeek 配置
# ---------------------------------------------------------------------------

DEEPSEEK_API_KEY = os.getenv("OPENAI_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

if not DEEPSEEK_API_KEY:
    raise RuntimeError("OPENAI_API_KEY 未配置，请在 .env 中填写 DeepSeek API Key")

AI_CLIENT = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# ---------------------------------------------------------------------------
# 数据加载（容错：文件不存在或格式异常时返回空结构）
# ---------------------------------------------------------------------------


def _safe_timestamp_str(data: dict, key: str) -> str:
    """安全提取时间戳。"""
    val = data.get(key, "")
    return val if val and isinstance(val, str) else "未知"


def load_patrol_data() -> dict:
    """
    加载巡店结果。
    返回 {"found": bool, "time": str, "checked": int,
           "summary": dict, "anomalies": list}
    """
    if not PATROL_FILE.exists():
        return {"found": False, "time": "", "checked": 0, "summary": {}, "anomalies": []}

    try:
        with open(PATROL_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, Exception):
        return {"found": False, "time": "", "checked": 0, "summary": {}, "anomalies": []}

    return {
        "found": True,
        "time": _safe_timestamp_str(raw, "patrol_time"),
        "checked": raw.get("total_checked", 0),
        "summary": raw.get("summary", {}),
        "anomalies": raw.get("anomalies", []),
    }


def load_competitor_data() -> dict:
    """
    加载竞品变动。
    返回 {"found": bool, "time": str, "prev_time": str,
           "competitors": { "竞品名": {...} }, "has_any_change": bool}
    """
    if not COMPETITOR_CHANGES_FILE.exists():
        return {"found": False, "time": "", "prev_time": "",
                "competitors": {}, "has_any_change": False}

    try:
        with open(COMPETITOR_CHANGES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, Exception):
        return {"found": False, "time": "", "prev_time": "",
                "competitors": {}, "has_any_change": False}

    competitors = raw.get("competitors", {})
    has_change = any(
        c.get("price_changes") or c.get("new_products")
        or c.get("removed_products") or c.get("stock_changes")
        or c.get("title_changes")
        for c in competitors.values()
    )

    return {
        "found": True,
        "time": _safe_timestamp_str(raw, "timestamp"),
        "prev_time": _safe_timestamp_str(raw, "previous_timestamp"),
        "competitors": competitors,
        "has_any_change": has_change,
    }


# ---------------------------------------------------------------------------
# Prompt 构建
# ---------------------------------------------------------------------------


def build_prompt(patrol: dict, competitor: dict) -> str:
    """构建发送给 DeepSeek 的系统 + 用户提示词。"""
    today = datetime.now().strftime("%Y-%m-%d")

    # ---- 巡店部分 ----
    patrol_section = ""
    if patrol["found"] and patrol["anomalies"]:
        lines = []
        for a in patrol["anomalies"]:
            sev = "🔥" if a["severity"] == "error" else "⚠️"
            lines.append(f"- {sev} **{a['name']}**: {a['detail']}")
        patrol_section = f"""### 今日巡店异常 ({patrol['time']})
共检查 {patrol['checked']} 个商品，发现 {len(patrol['anomalies'])} 项异常。

""" + "\n".join(lines)
    else:
        patrol_section = "### 今日巡店异常\n本日无异常。✅"

    # ---- 竞品部分 ----
    comp_section = ""
    if competitor["found"] and competitor["has_any_change"]:
        comp_lines = []
        for comp_name, comp_data in competitor["competitors"].items():
            items = []
            for pc in comp_data.get("price_changes", []):
                d = "📈" if pc["direction"] == "up" else "📉"
                items.append(f"  {d} 「{pc['title']}」 ¥{pc['old_price']:.2f} → ¥{pc['new_price']:.2f} ({pc['change_pct']:+.1f}%)")
            for np_ in comp_data.get("new_products", []):
                items.append(f"  🆕 「{np_['title']}」 ¥{np_.get('price', 0):.2f}")
            for rp in comp_data.get("removed_products", []):
                items.append(f"  🚫 「{rp['title']}」 已下架")
            for sc in comp_data.get("stock_changes", []):
                items.append(f"  📦 「{sc['title']}」 库存: {sc['from']} → {sc['to']}")
            for tc in comp_data.get("title_changes", []):
                items.append(f"  ✏️ 「{tc['old_title']}」 → 「{tc['new_title']}」")

            if items:
                comp_lines.append(f"- **{comp_name}**")
                comp_lines.extend(items)

        comp_section = "### 竞品价格变动\n" + "\n".join(comp_lines)
    else:
        comp_section = "### 竞品价格变动\n本日无变动。📊"

    # ---- 完整提示词 ----
    prompt = f"""你是一位资深电商运营经理，请根据以下今日数据，生成一份简洁专业的 {today} 运营日报。

日报格式如下（Markdown）：

# 📊 运营日报 {today}

---
## 一、巡店异常汇总
<在此列出巡店发现的核心问题，按严重程度排序>

## 二、竞品动态
<分析竞品价格变动、新品上架、下架等趋势，判断是否有需要跟进的>

## 三、建议行动
<基于上述数据给出3~5条可执行建议，每条一行，带优先级标签 🔴 🟡 🟢>

---
*本报告由 AI 自动生成，请结合实际情况核实。*

---

以下是今日的原始数据：

{patrol_section}

---

{comp_section}

---

请严格按照上述 Markdown 模板生成日报，不要额外发挥。建议行动要具体、可执行。"""
    return prompt


# ---------------------------------------------------------------------------
# DeepSeek API 调用
# ---------------------------------------------------------------------------


def call_deepseek(prompt: str, max_retries: int = 3) -> str:
    """调用 DeepSeek API 生成日报，含自动重试。"""
    for attempt in range(1, max_retries + 1):
        try:
            resp = AI_CLIENT.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位资深电商运营经理，专业、简洁、数据驱动。"
                            "请严格按照用户给定的模板格式输出，不要添加无关内容。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=1500,
                timeout=60,
            )
            content = resp.choices[0].message.content or ""
            # 清理可能的思考前缀
            if "---" in content:
                # 保留第一个 --- 之后的内容（跳过可能的思考过程）
                pass
            return content.strip()

        except Exception as e:
            print(f"  [WARN] DeepSeek API 调用失败 (第 {attempt} 次): {e}")
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"    等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"DeepSeek API 调用失败: {e}")

    raise RuntimeError("DeepSeek API 重试耗尽")


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def save_report(content: str) -> Path:
    """保存日报为 Markdown 文件。"""
    today = datetime.now().strftime("%Y%m%d")
    report_file = DATA_DIR / f"daily_report_{today}.md"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(content)

    return report_file


def print_report(content: str, patrol: dict, competitor: dict) -> None:
    """用 rich 打印日报到终端。"""
    console = Console()

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]📊 运营日报[/]",
            border_style="cyan",
        )
    )
    console.print(f"  日期: {datetime.now().strftime('%Y-%m-%d')}")
    console.print()

    # 数据摘要
    info_table = Table(box=box.SIMPLE, show_header=False)
    info_table.add_column("项目", style="bold")
    info_table.add_column("内容")

    if patrol["found"]:
        info_table.add_row(
            "🔍 巡店",
            f"检查 {patrol['checked']} 个商品，"
            f"异常 {patrol.get('summary', {}).get('total', 0)} 项"
        )
    else:
        info_table.add_row("🔍 巡店", "[dim]无数据[/]")

    if competitor["found"]:
        comp_count = len(competitor["competitors"])
        change_count = sum(
            len(c.get("price_changes", []))
            + len(c.get("new_products", []))
            + len(c.get("removed_products", []))
            + len(c.get("stock_changes", []))
            + len(c.get("title_changes", []))
            for c in competitor["competitors"].values()
        )
        info_table.add_row(
            "👀 竞品",
            f"监控 {comp_count} 个竞品，变动 {change_count} 项"
        )
    else:
        info_table.add_row("👀 竞品", "[dim]无数据[/]")

    console.print(info_table)
    console.print()

    # Markdown 正文
    console.print(Panel.fit("[bold]日报正文[/]", border_style="green"))
    console.print()
    try:
        md = Markdown(content)
        console.print(md)
    except Exception:
        # 如果 rich Markdown 渲染有问题，直接输出文本
        console.print(content[:2000])
    console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    console = Console()

    # 1. 加载数据
    print("📂 加载巡店数据...")
    patrol = load_patrol_data()
    if patrol["found"]:
        print(f"   ✓ {patrol['checked']} 个商品, {len(patrol['anomalies'])} 项异常")
    else:
        print("   - 无巡店数据")

    print("📂 加载竞品数据...")
    competitor = load_competitor_data()
    if competitor["found"]:
        total_changes = sum(
            len(c.get("price_changes", []))
            + len(c.get("new_products", []))
            + len(c.get("removed_products", []))
            + len(c.get("stock_changes", []))
            + len(c.get("title_changes", []))
            for c in competitor["competitors"].values()
        )
        print(f"   ✓ {len(competitor['competitors'])} 个竞品, {total_changes} 项变动")
    else:
        print("   - 无竞品数据")

    print()

    # 2. 调用 AI
    print("🤖 调用 DeepSeek 生成日报...")
    prompt = build_prompt(patrol, competitor)

    try:
        content = call_deepseek(prompt)
    except RuntimeError as e:
        console.print(f"[bold red]❌ 日报生成失败: {e}[/]")
        sys.exit(1)

    print(f"   ✓ 生成 {len(content)} 字符")
    print()

    # 3. 保存
    report_file = save_report(content)
    print(f"💾 日报已保存: {report_file}")
    print()

    # 4. 打印
    print_report(content, patrol, competitor)

    print(f"\n[dim]📁 {report_file}[/]")
    sys.exit(0)


if __name__ == "__main__":
    main()
