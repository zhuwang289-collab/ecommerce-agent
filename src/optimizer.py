"""优化模块 — 调用 DeepSeek API 同时优化标题与定价"""

import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OPTIMIZED_FILE = DATA_DIR / "optimized_products.json"

# DeepSeek 配置（OpenAI 兼容接口）
DEEPSEEK_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

if not DEEPSEEK_API_KEY:
    raise RuntimeError("OPENAI_API_KEY 未配置，请在 .env 中填写 DeepSeek API Key")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def load_products() -> list[dict]:
    """读取爬虫输出的 products.json。"""
    path = DATA_DIR / "products.json"
    if not path.exists():
        raise FileNotFoundError(f"请先运行爬虫模块生成 {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _optimize_single(product: dict, max_retries: int = 3) -> dict:
    """
    对单个商品调用 DeepSeek API，一次请求完成两件事：
      1. 标题优化（≤60 字，SEO 友好）
      2. 定价建议：根据商品类别、市场行情，综合 20% 利润率给出数字建议价
    返回结构化字段 optimized_title / category / suggested_price。
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an e-commerce expert across all product "
                            "categories (electronics, clothing, jewelry, etc.).\n\n"
                            "For each product:\n"
                            "1. Identify its category from the title and current category\n"
                            "2. Generate an SEO-optimized title ≤60 characters "
                            "that highlights key features and appeal\n"
                            "3. Act as a retail pricing specialist. The current "
                            "price is the wholesale cost. Set a suggested retail "
                            "price that:\n"
                            "   - Is HIGHER than the current price (add ~20% margin)\n"
                            "   - Is competitive for its product category\n"
                            "   - Is a realistic retail price ending in .99, .95 or .00\n\n"
                            "Return ONLY this format:\n"
                            "TITLE: <optimized title>\n"
                            "CATEGORY: <book genre/category>\n"
                            "PRICE: <number only, no currency symbol>"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Title: {product['title']}\n"
                            f"Category: {product.get('category', 'General')}\n"
                            f"Wholesale cost: {product['price']} {product.get('currency', 'USD')}\n"
                            "Provide optimized title, refined category, and suggested retail price:"
                        ),
                    },
                ],
                temperature=0.7,
                max_tokens=150,
                timeout=30,
            )

            raw = resp.choices[0].message.content or ""

            # 从结构化输出中提取字段
            title_match = re.search(r"^TITLE:\s*(.+)", raw, re.MULTILINE)
            price_match = re.search(r"^PRICE:\s*([\d.]+)", raw, re.MULTILINE)
            category_match = re.search(r"^CATEGORY:\s*(.+)", raw, re.MULTILINE)

            optimized_title = (title_match.group(1).strip()[:60]
                               if title_match else product["title"])
            suggested_price = (round(float(price_match.group(1)), 2)
                               if price_match else product["price"])
            category = (category_match.group(1).strip()
                        if category_match else "Unknown")

            # 安全校验：建议价不能低于原价（模型有时会抽风）
            if suggested_price < product["price"]:
                suggested_price = product["price"]

            return {
                **product,
                "category": category,
                "optimized_title": optimized_title,
                "suggested_price": suggested_price,
            }

        except Exception as e:
            print(f"    ⚠ API 调用失败 (第 {attempt} 次): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                # 三次都失败 → 保留原标题，建议价 = 原价（不退化为随机）
                print(f"    ⚠ 已降级，使用原价: {product['title'][:40]}...")
                return {
                    **product,
                    "category": "Unknown",
                    "optimized_title": product["title"],
                    "suggested_price": product["price"],
                }

    # 不应到达这里，但满足类型检查
    return {**product, "category": "Unknown",
            "optimized_title": product["title"],
            "suggested_price": product["price"]}


def run(max_workers: int = 5) -> list[dict]:
    """
    模块入口：读取商品 → 并发调用 DeepSeek API → 保存。
    max_workers — 并行线程数（DeepSeek 免费版建议 ≤3，付费版可用 5）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    products = load_products()
    total = len(products)
    results: list[dict] = [None] * total  # 按原序占位

    print(f"  → 共 {total} 个商品，并发 ({max_workers} 线程) 调用 DeepSeek API ...")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_optimize_single, prod): idx
            for idx, prod in enumerate(products)
        }
        done = 0
        for future in as_completed(future_map):
            idx = future_map[future]
            results[idx] = future.result()
            done += 1
            if done % 20 == 0 or done == total:
                short = results[idx]["title"][:40]
                print(f"  [{done}/{total}] {short}...")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OPTIMIZED_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 已保存 {len(results)} 个优化结果到 {OPTIMIZED_FILE}")
    return results
