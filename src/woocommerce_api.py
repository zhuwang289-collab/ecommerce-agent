#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WooCommerce API 共享模块

从 .env 读取配置，返回 OAuth1 认证的 requests.Session。
所有需要调 WooCommerce REST API 的模块统一从这里获取连接。

用法:
    from src.woocommerce_api import get_wcapi

    session = get_wcapi()
    resp = session.get("...wp-json/wc/v3/products")
"""

import os
from typing import Any

import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

load_dotenv()


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

WOOC_URL = os.getenv("WOOCOMMERCE_URL", "").rstrip("/")
WOOC_KEY = os.getenv("WOOCOMMERCE_KEY", "")
WOOC_SECRET = os.getenv("WOOCOMMERCE_SECRET", "")
WOOC_TEST_MODE = os.getenv("WOOCOMMERCE_TEST_MODE", "").lower() in (
    "true", "1", "yes",
)

API_VERSION = "wc/v3"


# ---------------------------------------------------------------------------
# 公共函数
# ---------------------------------------------------------------------------


def get_wcapi() -> requests.Session:
    """
    返回一个配置好 OAuth1 认证的 requests.Session。

    Raises:
        ValueError: 缺少必要配置时抛出。
    """
    missing = [
        name
        for name, val in [
            ("WOOCOMMERCE_URL", WOOC_URL),
            ("WOOCOMMERCE_KEY", WOOC_KEY),
            ("WOOCOMMERCE_SECRET", WOOC_SECRET),
        ]
        if not val
    ]
    if missing:
        raise ValueError(
            f"缺少 WooCommerce 配置: {', '.join(missing)}。请在 .env 中设置。"
        )

    session = requests.Session()
    session.auth = OAuth1(WOOC_KEY, WOOC_SECRET, signature_method="HMAC-SHA1")
    session.headers.update({
        "User-Agent": "ecommerce-agent/1.0",
        "Accept": "application/json",
    })
    return session


def is_test_mode() -> bool:
    """当前是否为测试模式。"""
    return WOOC_TEST_MODE


def get_api_url(path: str) -> str:
    """拼接完整的 API URL。"""
    path = path.lstrip("/")
    return f"{WOOC_URL}/wp-json/{API_VERSION}/{path}"


def request(method: str, path: str, session: requests.Session | None = None, **kwargs: Any) -> requests.Response:
    """
    便捷函数：对 WooCommerce API 发起一次请求。

    Args:
        method: HTTP 方法 (GET, POST, PUT, DELETE)
        path:   API 路径，如 "products", "products/123"
        session: 可复用 session，不传则新建
        **kwargs: 传给 session.request() 的额外参数 (json, params, timeout 等)

    Returns:
        requests.Response
    """
    if session is None:
        session = get_wcapi()
    url = get_api_url(path)
    kwargs.setdefault("timeout", 30)
    return session.request(method.upper(), url, **kwargs)


# ---------------------------------------------------------------------------
# 快捷列表（供测试 / 巡店使用）
# ---------------------------------------------------------------------------


def list_products(
    page: int = 1,
    per_page: int = 100,
    session: requests.Session | None = None,
) -> list[dict]:
    """
    分页获取商品列表。

    在测试模式下返回空列表（由 patrol 等模块自行切换 demo 数据）。
    """
    if WOOC_TEST_MODE:
        return []

    resp = request("GET", f"products?per_page={per_page}&page={page}", session=session)
    if resp.status_code != 200:
        raise RuntimeError(
            f"WooCommerce API 返回 {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 简单自测
# ---------------------------------------------------------------------------


def main():
    import sys

    if WOOC_TEST_MODE:
        print("[woocommerce_api] 测试模式 — 跳过真实 API 调用")
        sys.exit(0)

    print(f"[woocommerce_api] 连接: {WOOC_URL}")
    print(f"[woocommerce_api] Key:    {WOOC_KEY[:12]}...")

    try:
        session = get_wcapi()
        resp = session.get(get_api_url("products?per_page=5"), timeout=15)
        print(f"[woocommerce_api] HTTP {resp.status_code}")

        if resp.status_code == 200:
            products = resp.json()
            print(f"[woocommerce_api] 商品数: {len(products)}")
            for p in products[:3]:
                print(f"  - #{p['id']} {p['name'][:45]}  ${p['price']}")
            if len(products) > 3:
                print(f"  ... 及另外 {len(products) - 3} 个")
        else:
            print(f"[woocommerce_api] 错误: {resp.text[:200]}")
            sys.exit(1)

    except Exception as e:
        print(f"[woocommerce_api] 异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
