#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WooCommerce 商品上架工具

从 data/optimized_products.json 读取优化后的商品，
通过 WooCommerce REST API (OAuth1) 创建到店铺。
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# 将项目根目录加入 sys.path，确保 from src.xxx 可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.woocommerce_api import get_wcapi, get_api_url, is_test_mode

load_dotenv()

PROJECT_ROOT = _PROJECT_ROOT
DATA_DIR = PROJECT_ROOT / "data"
OPTIMIZED_FILE = DATA_DIR / "optimized_products.json"
RESULT_FILE = DATA_DIR / "wc_upload_result.json"


# ---------------------------------------------------------------------------
# 商品操作
# ---------------------------------------------------------------------------


def create_product(session: requests.Session, product: dict) -> dict:
    """创建一个 WooCommerce 商品。"""
    wc_data = {
        "name": product.get("optimized_title", product["title"])[:120],
        "type": "simple",
        "regular_price": str(product.get("suggested_price", product["price"])),
        "description": product.get("description", ""),
        "short_description": product.get("short_description", ""),
        "sku": str(product.get("upc", "")),
        "manage_stock": True,
        "stock_quantity": 100,
        "status": "publish",
    }

    category = product.get("category", "")
    if category and category != "Unknown":
        wc_data["categories"] = [{"name": category}]

    img_url = product.get("image_url", "")
    if img_url:
        wc_data["images"] = [{"src": img_url, "position": 0}]

    url = get_api_url("products")
    resp = session.post(url, json=wc_data, timeout=30)

    if resp.status_code in (200, 201):
        data = resp.json()
        return {
            "wc_id": data["id"],
            "name": data["name"],
            "price": data["price"],
            "status": "success",
            "sku": data.get("sku", ""),
        }
    else:
        return {
            "wc_id": None,
            "name": wc_data["name"],
            "price": wc_data["regular_price"],
            "status": "failed",
            "error": resp.text[:300],
        }


def list_all_products(session: requests.Session) -> list[dict]:
    """列出所有商品（分页）。"""
    all_products = []
    page = 1
    while True:
        url = get_api_url(f"products?per_page=100&page={page}")
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            break
        batch = resp.json()
        if not batch:
            break
        all_products.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return all_products


def load_optimized_products() -> list[dict]:
    if not OPTIMIZED_FILE.exists():
        fallback = PROJECT_ROOT / "data" / "products.json"
        if fallback.exists():
            print("  [WARN] optimized_products.json 不存在，使用原始 products.json")
            with open(fallback, encoding="utf-8") as f:
                return json.load(f)
        raise FileNotFoundError(f"找不到 {OPTIMIZED_FILE}")
    with open(OPTIMIZED_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    if is_test_mode():
        print("[wc_upload] 测试模式 — 跳过实际上架")
        return

    base_url = os.getenv("WOOCOMMERCE_URL", "http://localhost:8080/ecommerce-agent")
    print(f"[WooCommerce] 连接: {base_url}")

    # OAuth1 认证
    try:
        session = get_wcapi()
    except ValueError as e:
        print(f"[ERROR] 配置错误: {e}")
        sys.exit(1)

    # 验证连接
    print("[Auth] OAuth1 认证...")
    try:
        resp = session.get(get_api_url("products?per_page=1"), timeout=15)
        if resp.status_code == 200:
            print(f"[Auth] 认证成功 (HTTP {resp.status_code})")
        else:
            print(f"[Auth] 认证失败 (HTTP {resp.status_code}): {resp.text[:150]}")
            sys.exit(1)
    except Exception as e:
        print(f"[Auth] 连接异常: {e}")
        sys.exit(1)

    print()

    # 加载商品
    products = load_optimized_products()
    total = len(products)
    print(f"[Data] 加载 {total} 个商品")

    # 上传
    results = []
    success = 0
    fail = 0

    print()
    print("=" * 60)
    print(f"开始上架 {total} 个商品到 WooCommerce ...")
    print("=" * 60)

    for i, prod in enumerate(products, 1):
        name = prod.get("optimized_title", prod.get("title", "?"))
        price = prod.get("suggested_price", prod.get("price", "?"))

        result = create_product(session, prod)
        results.append(result)

        if result["status"] == "success":
            success += 1
            print(f"  [{i}/{total}] OK  #{result['wc_id']}  {name[:45]:45s}  ${price}")
        else:
            fail += 1
            print(f"  [{i}/{total}] FAIL  {name[:40]:40s}  {result.get('error','')[:80]}")

        if i < total:
            time.sleep(0.3)

    # 保存结果
    summary = {
        "total": total,
        "success": success,
        "failed": fail,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": results,
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print(f"上架完成: 成功 {success} / 失败 {fail}")
    print(f"结果已保存到 {RESULT_FILE}")

    # 验证
    print()
    print("[Verify] 从 WooCommerce 拉取商品列表确认...")
    time.sleep(1)
    online = list_all_products(session)
    print(f"[Verify] WooCommerce 中现有 {len(online)} 个商品")
    for p in online:
        print(f"  - #{p['id']} {p['name'][:50]:50s}  ${p['price']}  [{p['status']}]")

    return success, fail


if __name__ == "__main__":
    ok, fail = main()
    sys.exit(0 if fail == 0 else 1)
