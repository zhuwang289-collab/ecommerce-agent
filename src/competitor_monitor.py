#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞品监控模块 (Competitor Monitor)

使用 Playwright 依次访问竞品链接，提取商品信息，
与上一次快照对比变动，生成报告。

用法:
  python src/competitor_monitor.py              # 全量监控
  python src/competitor_monitor.py --quick      # 只检查前 2 个竞品
  python src/competitor_monitor.py --headless   # 无头模式
"""

import argparse
import json
import os
import random
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

# Windows 终端 UTF-8 修复
if sys.platform == "win32":
    for _s in ("stdout", "stderr"):
        _stream = getattr(sys, _s, None)
        if _stream and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

from playwright.sync_api import sync_playwright, Page, Browser
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
URLS_FILE = DATA_DIR / "competitor_urls.json"
LATEST_FILE = DATA_DIR / "competitor_latest.json"
CHANGES_FILE = DATA_DIR / "competitor_changes.json"

# ---------------------------------------------------------------------------
# 默认选择器（当 JSON 中未定义时使用）
# ---------------------------------------------------------------------------

DEFAULT_SELECTORS = {
    "product_container": ".product_pod",
    "title": "h3 a",
    "title_attr": "title",
    "price": ".price_color",
    "stock": ".instock",
    "dropshipping": ".dropship-badge, [class*=dropship], [class*=dropshipping]",
    "link": "h3 a",
    "link_attr": "href",
    "image": ".image_container img",
    "image_attr": "src",
}

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]


def _random_delay(min_s: float = 2.0, max_s: float = 4.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _safe_text(els: list, idx: int = 0) -> str:
    """安全获取元素文本。"""
    try:
        return els[idx].inner_text().strip() if els and len(els) > idx else ""
    except Exception:
        return ""


def _safe_attr(els: list, attr: str, idx: int = 0) -> str:
    """安全获取元素属性。"""
    try:
        return els[idx].get_attribute(attr) or "" if els and len(els) > idx else ""
    except Exception:
        return ""


def _parse_price(text: str) -> float | None:
    """从文本中提取数字价格。"""
    import re
    nums = re.findall(r"[\d.]+", text.replace(",", ""))
    if nums:
        try:
            return float(nums[0])
        except ValueError:
            return None
    return None


def _normalize_url(base: str, link: str) -> str:
    """拼接完整 URL。"""
    if link.startswith("http"):
        return link
    return urljoin(base, link)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------


def load_competitor_urls() -> list[dict]:
    if not URLS_FILE.exists():
        raise FileNotFoundError(
            f"找不到 {URLS_FILE}，请先创建竞品列表文件。"
        )
    with open(URLS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def load_latest_snapshot() -> dict | None:
    if LATEST_FILE.exists():
        with open(LATEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_snapshot(products_by_competitor: dict[str, Any]) -> Path:
    """保存时间戳快照 + 覆盖 latest。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_file = DATA_DIR / f"competitor_snapshot_{timestamp}.json"

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "competitors": products_by_competitor,
    }

    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return snapshot_file


# ---------------------------------------------------------------------------
# Playwright 页面设置
# ---------------------------------------------------------------------------


def _stealth_page(page: Page) -> None:
    """对页面应用 stealth 伪装。"""
    # 覆盖 navigator.webdriver
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
        // 覆盖 Chrome 检测
        window.chrome = { runtime: {} };
        // 覆盖权限查询
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (params) => (
            params.name === 'notifications'
                ? Promise.resolve({ state: 'denied' })
                : originalQuery(params)
        );
    """)


def _create_browser(playwright, headless: bool) -> Browser:
    """创建配置好的浏览器实例。"""
    ua = random.choice(USER_AGENTS)
    vp = random.choice(VIEWPORTS)

    browser = playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    return browser


def _create_context(browser: Browser) -> Any:
    """创建带随机配置的浏览器上下文。"""
    ua = random.choice(USER_AGENTS)
    vp = random.choice(VIEWPORTS)

    context = browser.new_context(
        user_agent=ua,
        viewport=vp,
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        geolocation={"latitude": 31.2304, "longitude": 121.4737},
        permissions=[],
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    return context


# ---------------------------------------------------------------------------
# 页面抓取
# ---------------------------------------------------------------------------


def scrape_competitor(page: Page, competitor: dict) -> dict:
    """
    抓取一个竞品链接下的所有商品。

    Args:
        page: Playwright Page 对象
        competitor: {"name":..., "url":..., "selectors": {...}}

    Returns:
        {"competitor_name": ..., "url": ..., "products": [...], "error": ...}
    """
    name = competitor.get("name", "(unnamed)")
    url = competitor.get("url", "")
    sel = {**DEFAULT_SELECTORS, **(competitor.get("selectors") or {})}

    result: dict[str, Any] = {
        "competitor_name": name,
        "url": url,
        "products": [],
        "error": None,
        "scraped_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        print(f"    Navigate: {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)
        _random_delay(1.5, 3.0)

        # 等待商品容器出现
        try:
            page.wait_for_selector(sel["product_container"], timeout=10000)
        except Exception:
            result["error"] = f"未找到容器选择器: {sel['product_container']}"
            return result

        containers = page.query_selector_all(sel["product_container"])
        print(f"    Found {len(containers)} products")

        for container in containers:
            try:
                title_els = container.query_selector_all(sel["title"])
                title = _safe_attr(title_els, sel.get("title_attr", "title")) or _safe_text(title_els)

                price_els = container.query_selector_all(sel["price"])
                price_raw = _safe_text(price_els)
                price = _parse_price(price_raw)

                stock_els = container.query_selector_all(sel["stock"])
                stock_text = _safe_text(stock_els)
                in_stock = "in stock" in stock_text.lower() if stock_text else True

                # 一件代发标签
                dropship_els = container.query_selector_all(sel.get("dropshipping", ""))
                dropship = len(dropship_els) > 0

                # 商品链接
                link_els = container.query_selector_all(sel.get("link", sel["title"]))
                link_raw = _safe_attr(link_els, sel.get("link_attr", "href"))
                link = _normalize_url(url, link_raw) if link_raw else ""

                # 商品图片
                img_els = container.query_selector_all(sel.get("image", ".image_container img"))
                img_raw = _safe_attr(img_els, sel.get("image_attr", "src"))
                image_url = _normalize_url(url, img_raw) if img_raw else ""

                # 额外：星级（books.toscrape 特有）
                star_els = container.query_selector_all(".star-rating")
                star_cls = ""
                if star_els:
                    cls_str = star_els[0].get_attribute("class") or ""
                    for s in ["One", "Two", "Three", "Four", "Five"]:
                        if s in cls_str:
                            star_cls = s
                            break

                product = {
                    "title": title,
                    "price": price,
                    "price_raw": price_raw,
                    "image_url": image_url,
                    "in_stock": in_stock,
                    "stock_text": stock_text,
                    "dropshipping": dropship,
                    "link": link,
                }
                if star_cls:
                    product["rating"] = star_cls

                result["products"].append(product)

            except Exception as e:
                # 单商品解析失败不中断整体
                result["products"].append({
                    "title": f"<parse error: {e}>",
                    "price": None,
                    "in_stock": False,
                })

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 变动对比
# ---------------------------------------------------------------------------


def compute_changes(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    将本次抓取结果与上一次快照对比，识别变动。

    Returns:
        {"competitors": { "竞品名": {"price_changes": [...], "new_products": [...],
                            "removed_products": [...], "title_changes": [...]} },
         "timestamp": ..., "previous_timestamp": ...}
    """
    changes: dict = {
        "timestamp": current.get("timestamp", ""),
        "previous_timestamp": previous.get("timestamp", "") if previous else None,
        "competitors": {},
    }

    current_comps = {c["competitor_name"]: c for c in current.get("competitors", [])}
    prev_comps = {c["competitor_name"]: c for c in previous.get("competitors", [])} if previous else {}

    for comp_name, cur_comp in current_comps.items():
        comp_change: dict[str, Any] = {
            "url": cur_comp.get("url", ""),
            "price_changes": [],
            "stock_changes": [],
            "new_products": [],
            "removed_products": [],
            "title_changes": [],
            "has_error": cur_comp.get("error") is not None,
        }

        prev_comp = prev_comps.get(comp_name)
        if not prev_comp:
            # 全新竞品——所有商品算新增
            for p in cur_comp.get("products", []):
                comp_change["new_products"].append({
                    "title": p.get("title", ""),
                    "price": p.get("price"),
                })
            changes["competitors"][comp_name] = comp_change
            continue

        # 按标题建立索引（简单去重）
        prev_by_title = {}
        for p in prev_comp.get("products", []):
            t = p.get("title", "").strip()
            if t:
                prev_by_title[t] = p

        cur_by_title = {}
        for p in cur_comp.get("products", []):
            t = p.get("title", "").strip()
            if t:
                cur_by_title[t] = p

        # 找出新 / 下架商品
        prev_titles = set(prev_by_title.keys())
        cur_titles = set(cur_by_title.keys())

        new_titles = cur_titles - prev_titles
        removed_titles = prev_titles - cur_titles
        common_titles = cur_titles & prev_titles

        for t in sorted(new_titles):
            p = cur_by_title[t]
            comp_change["new_products"].append({
                "title": t,
                "price": p.get("price"),
                "link": p.get("link", ""),
            })

        for t in sorted(removed_titles):
            p = prev_by_title[t]
            comp_change["removed_products"].append({
                "title": t,
                "price": p.get("price"),
            })

        # 对比共有商品：价格 / 标题 / 库存
        for t in sorted(common_titles):
            cur_p = cur_by_title[t]
            prev_p = prev_by_title[t]

            # 价格变动
            cur_price = cur_p.get("price")
            prev_price = prev_p.get("price")
            if cur_price is not None and prev_price is not None and cur_price != prev_price:
                pct = ((cur_price - prev_price) / prev_price) * 100 if prev_price else 0
                comp_change["price_changes"].append({
                    "title": t,
                    "old_price": prev_price,
                    "new_price": cur_price,
                    "change_pct": round(pct, 2),
                    "direction": "up" if pct > 0 else "down",
                })

            # 库存变动
            cur_stock = cur_p.get("in_stock", True)
            prev_stock = prev_p.get("in_stock", True)
            if cur_stock != prev_stock:
                comp_change["stock_changes"].append({
                    "title": t,
                    "from": "in_stock" if prev_stock else "out_of_stock",
                    "to": "in_stock" if cur_stock else "out_of_stock",
                })

            # 标题变动
            cur_title = cur_p.get("title", "")
            prev_title = prev_p.get("title", "")
            if cur_title != prev_title and cur_title and prev_title:
                comp_change["title_changes"].append({
                    "old_title": prev_title,
                    "new_title": cur_title,
                })

        changes["competitors"][comp_name] = comp_change

    return changes


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def save_changes(changes: dict) -> Path:
    with open(CHANGES_FILE, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)
    return CHANGES_FILE


def print_report(
    results: list[dict],
    changes: dict[str, Any],
    snapshot_file: Path,
    elapsed: float,
) -> None:
    console = Console()

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]~~ Competitor Monitor Report ~~[/]",
            border_style="cyan",
        )
    )
    console.print(f"  扫描时间:  {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}")
    console.print(f"  耗时:      {elapsed:.1f}s")
    console.print(f"  竞品数量:  [bold]{len(results)}[/]")
    console.print(f"  快照文件:  {snapshot_file.name}")
    console.print()

    # ---- 各竞品摘要 ----
    for comp in results:
        name = comp.get("competitor_name", "(unnamed)")
        products = comp.get("products", [])
        error = comp.get("error")
        count = len(products)

        if error:
            console.print(f"  [bold red]!! {name}[/]  —  ERROR: {error}")
            continue

        console.print(f"  [bold]{name}[/]  ({count} 个商品)")

        # 该竞品的变动
        comp_change = changes.get("competitors", {}).get(name, {})

        n_new = len(comp_change.get("new_products", []))
        n_removed = len(comp_change.get("removed_products", []))
        n_price = len(comp_change.get("price_changes", []))
        n_stock = len(comp_change.get("stock_changes", []))
        n_title = len(comp_change.get("title_changes", []))

        tags = []
        if n_new:
            tags.append(f"[green]+{n_new} 新增[/]")
        if n_removed:
            tags.append(f"[red]-{n_removed} 下架[/]")
        if n_price:
            tags.append(f"[yellow]${n_price} 调价[/]")
        if n_stock:
            tags.append(f"[magenta]{n_stock} 库存变动[/]")
        if n_title:
            tags.append(f"[blue]{n_title} 标题变动[/]")
        if not tags:
            tags.append("[dim]无变化[/]")

        console.print(f"       变动: {', '.join(tags)}")

        # 展示前 5 个商品
        if products:
            for p in products[:5]:
                title = p.get("title", "?")
                price = p.get("price")
                stock = p.get("in_stock", True)
                price_str = f"${price:.2f}" if price is not None else "?"
                stock_mark = "[green]V[/]" if stock else "[red]X[/]"
                console.print(f"         {stock_mark} {price_str:>8s}  {title[:55]}")
            if len(products) > 5:
                console.print(f"         ...及另外 {len(products) - 5} 个")

        console.print()

    # ---- 变动明细表 ----
    has_changes = any(
        comp_change.get("price_changes")
        or comp_change.get("new_products")
        or comp_change.get("removed_products")
        or comp_change.get("stock_changes")
        or comp_change.get("title_changes")
        for comp_change in changes.get("competitors", {}).values()
    )

    if has_changes:
        console.print(
            Panel.fit(
                "[bold yellow]~~ 变动详情 ~~[/]",
                border_style="yellow",
            )
        )
        console.print()

        for comp_name, comp_change in changes.get("competitors", {}).items():
            sections = []

            # 调价
            if comp_change.get("price_changes"):
                t = Table(
                    title=f"{comp_name} - 价格变动",
                    box=box.ROUNDED,
                    header_style="bold yellow",
                )
                t.add_column("商品", max_width=40)
                t.add_column("原价", justify="right", width=10)
                t.add_column("现价", justify="right", width=10)
                t.add_column("变动", justify="right", width=10)

                for pc in comp_change["price_changes"]:
                    direction = pc.get("direction", "")
                    pct = pc.get("change_pct", 0)
                    sign = "+" if direction == "up" else ""
                    color = "red" if direction == "up" else "green"
                    t.add_row(
                        pc["title"][:40],
                        f"${pc['old_price']:.2f}",
                        f"${pc['new_price']:.2f}",
                        f"[{color}]{sign}{pct:.1f}%[/]",
                    )
                sections.append(t)

            # 新增
            if comp_change.get("new_products"):
                t = Table(
                    title=f"{comp_name} - 新增商品",
                    box=box.ROUNDED,
                    header_style="bold green",
                )
                t.add_column("商品", max_width=50)
                t.add_column("价格", justify="right", width=10)
                for np_ in comp_change["new_products"]:
                    p_str = f"${np_['price']:.2f}" if np_.get("price") is not None else "?"
                    t.add_row(np_["title"][:50], p_str)
                sections.append(t)

            # 下架
            if comp_change.get("removed_products"):
                t = Table(
                    title=f"{comp_name} - 下架商品",
                    box=box.ROUNDED,
                    header_style="bold red",
                )
                t.add_column("商品", max_width=50)
                t.add_column("原价", justify="right", width=10)
                for rp in comp_change["removed_products"]:
                    p_str = f"${rp['price']:.2f}" if rp.get("price") is not None else "?"
                    t.add_row(rp["title"][:50], p_str)
                sections.append(t)

            # 库存变动
            if comp_change.get("stock_changes"):
                t = Table(
                    title=f"{comp_name} - 库存变动",
                    box=box.ROUNDED,
                    header_style="bold magenta",
                )
                t.add_column("商品", max_width=50)
                t.add_column("原状态", width=14)
                t.add_column("现状态", width=14)
                for sc in comp_change["stock_changes"]:
                    from_clr = "red" if sc["from"] == "out_of_stock" else "green"
                    to_clr = "red" if sc["to"] == "out_of_stock" else "green"
                    t.add_row(
                        sc["title"][:50],
                        f"[{from_clr}]{sc['from']}[/]",
                        f"[{to_clr}]{sc['to']}[/]",
                    )
                sections.append(t)

            for section in sections:
                console.print(section)
                console.print()

    else:
        console.print("[bold green][OK] 所有竞品无变动[/]")
        console.print()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(
    competitors: list[dict],
    headless: bool = True,
    quick: bool = False,
) -> tuple[list[dict], dict, Path]:
    """
    执行竞品监控。

    Returns:
        (results, changes, snapshot_file)
    """
    if quick:
        competitors = competitors[:2]
        print(f"[Quick Mode] 只检查前 {len(competitors)} 个竞品")

    total = len(competitors)
    results: list[dict] = []

    with sync_playwright() as pw:
        browser = _create_browser(pw, headless=headless)
        context = _create_context(browser)
        page = context.new_page()
        _stealth_page(page)

        for i, comp in enumerate(competitors, 1):
            name = comp.get("name", "(unnamed)")
            print(f"\n[{i}/{total}] Scraping: {name}")
            result = scrape_competitor(page, comp)
            results.append(result)

            if i < total:
                delay = random.uniform(2.0, 4.0)
                print(f"    Waiting {delay:.1f}s before next...")
                time.sleep(delay)

        context.close()
        browser.close()

    total_products = sum(len(r.get("products", [])) for r in results)
    print(f"\n[Data] 共抓取 {total_products} 个商品，来自 {total} 个竞品")

    # 保存快照
    products_by_competitor = [
        {
            "competitor_name": r["competitor_name"],
            "url": r["url"],
            "error": r.get("error"),
            "scraped_at": r.get("scraped_at", ""),
            "products": r.get("products", []),
        }
        for r in results
    ]
    snapshot_file = save_snapshot(products_by_competitor)
    print(f"[Data] 快照已保存: {snapshot_file.name}")

    # 计算变动
    previous = load_latest_snapshot()
    # 排除刚刚保存的 latest（需要前一次的快照）
    # 我们寻找之前的时间戳快照
    prev_snapshot = _find_previous_snapshot()
    changes = compute_changes(
        {"timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "competitors": products_by_competitor},
        prev_snapshot,
    )
    changes_path = save_changes(changes)
    print(f"[Data] 变动已保存: {changes_path.name}")

    return results, changes, snapshot_file


def _find_previous_snapshot() -> dict | None:
    """在 competitor_snapshot_*.json 中找到上一个快照（除最新外）。"""
    snapshots = sorted(DATA_DIR.glob("competitor_snapshot_*.json"))
    if len(snapshots) >= 2:
        # 取倒数第二个（最新的 latest 不算）
        with open(snapshots[-2], "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="竞品监控工具 — 定时抓取竞品页面，追踪价格/库存/标题变动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python src/competitor_monitor.py             全量抓取\n"
            "  python src/competitor_monitor.py --quick     只抓前 2 个竞品\n"
            "  python src/competitor_monitor.py --headless  无头模式（默认）\n"
            "  python src/competitor_monitor.py --no-headless  有头模式\n"
        ),
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式：只检查前 2 个竞品",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="无头模式（默认启用），--no-headless 可打开浏览器窗口",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    console = Console()

    # 加载竞品列表
    try:
        competitors = load_competitor_urls()
    except FileNotFoundError as e:
        console.print(f"[bold red]错误: {e}[/]")
        sys.exit(1)

    if not competitors:
        console.print("[bold red]错误: 竞品列表为空[/]")
        sys.exit(1)

    mode_tag = "[yellow][QUICK][/]" if args.quick else "[green][FULL][/]"
    head_tag = "[dim]headless[/]" if args.headless else "[dim]headed[/]"
    console.print(f"{mode_tag}  [bold cyan]~~ 开始竞品监控 ({head_tag}) ...[/]")
    console.print(f"  竞品总数: {len(competitors)}")

    t0 = time.time()
    results, changes, snapshot_file = run(
        competitors,
        headless=args.headless,
        quick=args.quick,
    )
    elapsed = time.time() - t0

    print()
    print_report(results, changes, snapshot_file, elapsed)

    total_changes = sum(
        len(c.get("price_changes", []))
        + len(c.get("new_products", []))
        + len(c.get("removed_products", []))
        + len(c.get("stock_changes", []))
        + len(c.get("title_changes", []))
        for c in changes.get("competitors", {}).values()
    )
    sys.exit(1 if total_changes > 0 else 0)


if __name__ == "__main__":
    main()
