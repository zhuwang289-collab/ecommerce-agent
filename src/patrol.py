#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WooCommerce 巡店模块 (Store Patrol)

调用 WooCommerce REST API 读取商品列表，逐项检查：
  - 价格异常（低于 1 元 或 高于原价 50%）
  - 库存不足（低于 5 件）
  - 商品状态异常（草稿/下架/待审）

将异常结果保存至 data/patrol_result.json，并用 rich 打印彩色巡店报告。

用法:
  python src/patrol.py              # 全量巡店
  python src/patrol.py --quick      # 快速模式（前 5 个商品，测试用）

环境变量（.env）:
  WOOCOMMERCE_URL       - 站点 URL
  WOOCOMMERCE_KEY       - Consumer Key
  WOOCOMMERCE_SECRET    - Consumer Secret
  WOOCOMMERCE_TEST_MODE - True=测试模式（使用本地 demo 数据），False=调用真实 API
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows 终端 UTF-8 修复
if sys.platform == "win32":
    for _s in ("stdout", "stderr"):
        _stream = getattr(sys, _s, None)
        if _stream and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

# 将项目根目录加入 sys.path，确保 from src.xxx 可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.woocommerce_api import get_wcapi, is_test_mode, get_api_url, list_products

load_dotenv()

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

PROJECT_ROOT = _PROJECT_ROOT
DATA_DIR = PROJECT_ROOT / "data"
RESULT_FILE = DATA_DIR / "patrol_result.json"
DEMO_DATA_FILE = PROJECT_ROOT / "demo_products.json"

# ---------------------------------------------------------------------------
# 常量（检查阈值）
# ---------------------------------------------------------------------------

PRICE_FLOOR = 1.0               # 价格低于此值 → 告警
PRICE_CEILING_RATIO = 1.5       # 当前价高于原价 x 此比例 → 告警
STOCK_WARN_THRESHOLD = 5        # 库存低于此值 → 告警

# ---------------------------------------------------------------------------
# 商品获取
# ---------------------------------------------------------------------------


def fetch_products(session: requests.Session | None = None, quick: bool = False) -> list[dict]:
    """
    获取待检查的商品列表。

    - 测试模式：从 demo_products.json 加载
    - 正式模式：从 WooCommerce API 分页拉取
    - quick=True 时只保留前 5 个
    """
    if is_test_mode():
        if not DEMO_DATA_FILE.exists():
            return []
        with open(DEMO_DATA_FILE, "r", encoding="utf-8") as f:
            products = json.load(f)
    else:
        products: list[dict] = []
        page = 1
        while True:
            batch = list_products(page=page, session=session)
            if not batch:
                break
            products.extend(batch)
            if len(batch) < 100:
                break
            page += 1

    # 补全 price 字段
    for p in products:
        if "price" not in p and "regular_price" in p:
            p["price"] = p["regular_price"]

    if quick:
        products = products[:5]

    return products


# ---------------------------------------------------------------------------
# 单项检查
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float:
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def _check_price_low(product: dict, current: float) -> dict | None:
    """价格低于 1 元。"""
    if 0 < current < PRICE_FLOOR:
        return {
            "product_id": product.get("id", "?"),
            "name": product.get("name", "(unnamed)"),
            "type": "price_too_low",
            "severity": "error",
            "detail": f"当前价格 ¥{current:.2f}，低于警戒线 ¥{PRICE_FLOOR:.2f}",
            "current_price": round(current, 2),
            "regular_price": round(_safe_float(product.get("regular_price")), 2),
        }
    return None


def _check_price_high(product: dict, current: float, regular: float) -> dict | None:
    """价格高于原价 50%。"""
    if regular > 0 and current > regular * PRICE_CEILING_RATIO:
        return {
            "product_id": product.get("id", "?"),
            "name": product.get("name", "(unnamed)"),
            "type": "price_too_high",
            "severity": "warning",
            "detail": (
                f"当前价格 ¥{current:.2f}，"
                f"高于原价 ¥{regular:.2f} 的 {PRICE_CEILING_RATIO * 100:.0f}%"
            ),
            "current_price": round(current, 2),
            "regular_price": round(regular, 2),
        }
    return None


def _check_stock(product: dict) -> dict | None:
    """库存不足（低于 5）或未管理。"""
    stock = product.get("stock_quantity")
    pid, name = product.get("id", "?"), product.get("name", "(unnamed)")

    if stock is not None:
        try:
            qty = int(stock)
        except (ValueError, TypeError):
            return None
        if qty < STOCK_WARN_THRESHOLD:
            return {
                "product_id": pid,
                "name": name,
                "type": "stock_low",
                "severity": "warning",
                "detail": f"库存仅剩 {qty} 件，低于警戒线 {STOCK_WARN_THRESHOLD}",
                "stock_quantity": qty,
            }
    else:
        return {
            "product_id": pid,
            "name": name,
            "type": "stock_unmanaged",
            "severity": "info",
            "detail": "未启用库存管理（stock_quantity 为空）",
        }
    return None


def _check_status(product: dict) -> dict | None:
    """商品状态为草稿/待审/私密。"""
    status = product.get("status", "publish")
    if status in ("draft", "pending", "private"):
        label = {"draft": "草稿", "pending": "待审", "private": "私密"}.get(status, status)
        return {
            "product_id": product.get("id", "?"),
            "name": product.get("name", "(unnamed)"),
            "type": "status_alert",
            "severity": "warning",
            "detail": f"商品状态为「{label}」，非发布状态",
            "status": status,
        }
    return None


# ---------------------------------------------------------------------------
# 巡店核心
# ---------------------------------------------------------------------------


def patrol(session: requests.Session | None = None, quick: bool = False) -> dict:
    """
    执行巡店检查，返回结构化结果。

    Args:
        session: WooCommerce OAuth1 session（正式模式需要）
        quick:   只检查前 5 个商品

    Returns:
        dict: { patrol_time, total_checked, anomalies, summary }
    """
    products = fetch_products(session=session, quick=quick)
    total_checked = len(products)
    anomalies: list[dict[str, Any]] = []

    for prod in products:
        regular = _safe_float(prod.get("regular_price"))
        current = _safe_float(prod.get("price", prod.get("regular_price")))

        for check in (
            lambda: _check_price_low(prod, current),
            lambda: _check_price_high(prod, current, regular),
            lambda: _check_stock(prod),
            lambda: _check_status(prod),
        ):
            result = check()
            if result is not None:
                anomalies.append(result)

    types = [a["type"] for a in anomalies]
    summary = {
        "total": len(anomalies),
        "price_too_low": types.count("price_too_low"),
        "price_too_high": types.count("price_too_high"),
        "stock_low": types.count("stock_low"),
        "stock_unmanaged": types.count("stock_unmanaged"),
        "status_alert": types.count("status_alert"),
    }

    return {
        "patrol_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_checked": total_checked,
        "anomalies": anomalies,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def save_result(result: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return RESULT_FILE


def print_report(result: dict) -> None:
    console = Console()

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]~~ WooCommerce Store Patrol Report ~~[/]",
            border_style="cyan",
        )
    )
    console.print(f"  巡店时间:  {result['patrol_time']}")
    console.print(f"  检查商品:  [bold]{result['total_checked']}[/] 个")
    console.print(f"  发现异常:  [bold]{result['summary']['total']}[/] 项")
    console.print()

    anomalies = result["anomalies"]
    if not anomalies:
        console.print("[bold green][OK] 一切正常，未发现异常！[/]")
        console.print()
        return

    type_meta = {
        "price_too_low": ("价格过低", "red"),
        "price_too_high": ("价格过高", "yellow"),
        "stock_low": ("库存不足", "yellow"),
        "stock_unmanaged": ("库存未管理", "blue"),
        "status_alert": ("状态异常", "magenta"),
    }
    sev_style = {"error": "bold white on red", "warning": "bold black on yellow", "info": "blue"}

    table = Table(
        title="异常明细",
        box=box.ROUNDED,
        header_style="bold white",
        title_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("商品", max_width=40)
    table.add_column("类型", width=12)
    table.add_column("严重度", width=8)
    table.add_column("详情", max_width=60)

    for i, a in enumerate(anomalies, 1):
        label, color = type_meta.get(a["type"], (a["type"], "white"))
        table.add_row(
            str(i),
            Text(a["name"], style="bold"),
            Text(label, style=color),
            Text(a["severity"].upper(), style=sev_style.get(a["severity"], "white")),
            a["detail"],
        )

    console.print(table)
    console.print()

    s = result["summary"]
    st = Table(box=box.SIMPLE, show_header=False)
    st.add_column("项目", style="bold")
    st.add_column("数量", justify="right")
    for label, key in [
        ("[red]价格过低[/]", "price_too_low"),
        ("[yellow]价格过高[/]", "price_too_high"),
        ("[yellow]库存不足[/]", "stock_low"),
        ("[blue]未管理库存[/]", "stock_unmanaged"),
        ("[magenta]状态异常[/]", "status_alert"),
    ]:
        st.add_row(label, str(s[key]))
    st.add_row("[bold]--- 总计异常[/]", f"[bold]{s['total']}[/]")

    console.print(Panel(st, title="[bold]汇总统计[/]", border_style="cyan"))
    console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WooCommerce 巡店工具 — 检查商品价格、库存、状态异常",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python src/patrol.py              全量巡店\n"
            "  python src/patrol.py --quick      快速巡店（前 5 个商品）\n\n"
            "环境变量:\n"
            "  WOOCOMMERCE_TEST_MODE=True  启用测试模式（使用本地 demo 数据）\n"
        ),
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式：只检查前 5 个商品（用于测试验证）",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    console = Console()

    mode_tag = "[yellow][TEST MODE][/]" if is_test_mode() else "[green][LIVE][/]"
    label = "快速巡店" if args.quick else "全量巡店"
    console.print(f"{mode_tag}  [bold cyan]~~ 开始 {label} ...[/]")
    console.print()

    # 正式模式需要 OAuth1 session
    wc_session = None
    if not is_test_mode():
        try:
            wc_session = get_wcapi()
        except ValueError as e:
            console.print(f"[bold red]错误: {e}[/]")
            sys.exit(1)

    result = patrol(session=wc_session, quick=args.quick)

    path = save_result(result)
    console.print(f"[dim]结果已保存至 {path}[/]")
    console.print()

    print_report(result)

    sys.exit(1 if result["summary"]["total"] > 0 else 0)


if __name__ == "__main__":
    main()
