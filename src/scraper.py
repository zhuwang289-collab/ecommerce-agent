"""爬虫模块 — 从 FakeStore API 获取商品数据"""

import json
import os
from pathlib import Path

import requests

API_URL = "https://fakestoreapi.com/products"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"

_SESSION = requests.Session()
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


def fetch_all_products() -> list[dict]:
    """
    调用 FakeStore API 获取所有商品。
    API 返回 JSON 数组，直接映射为我们需要的格式。
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _SESSION.get(API_URL, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            raw = resp.json()
            break
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                import time
                time.sleep(2**attempt)
            else:
                raise RuntimeError(f"FakeStore API 请求失败: {e}")

    products = []
    for item in raw:
        products.append(
            {
                "title": item["title"],
                "price": float(item["price"]),
                "currency": "USD",
                "image_url": item.get("image", ""),
                "detail_url": f"https://fakestoreapi.com/products/{item['id']}",
                "description": item.get("description", ""),
                "stock_status": "In stock",
                "upc": str(item["id"]),
                "category": item.get("category", "Unknown"),
            }
        )

    return products


def save_products(products: list[dict]) -> Path:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    return PRODUCTS_FILE


def run() -> list[dict]:
    """模块入口：获取数据 → 保存 → 返回商品列表。"""
    print(f"  → 从 FakeStore API 获取商品数据 ...")
    products = fetch_all_products()
    path = save_products(products)

    categories = sorted(set(p["category"] for p in products))
    prices = [p["price"] for p in products]
    print(f"  ✓ 获取 {len(products)} 个商品，"
          f"{len(categories)} 个品类: {', '.join(categories)}")
    print(f"  ✓ 已保存到 {path}")
    return products
