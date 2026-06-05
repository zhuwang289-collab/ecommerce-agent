"""抖店上架模块 — 商品创建与价格更新

功能模式：
  - 测试模式 (DOUYIN_TEST_MODE=True)：仅打印模拟日志，不调用真实 API
  - 正式模式：使用抖店开放 API 进行真实上架（框架已预留，填入真实 key 后启用）

API 文档参考：抖店开放平台 — 商品创建 / 价格更新
"""

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()

# ── 日志 ─────────────────────────────────────────────────
logger = logging.getLogger("douyin")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "  [DOUYIN] %(message)s"
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ── 配置 ──────────────────────────────────────────────────
DOUYIN_APP_KEY = os.getenv("DOUYIN_APP_KEY", "")
DOUYIN_APP_SECRET = os.getenv("DOUYIN_APP_SECRET", "")
DOUYIN_TEST_MODE = os.getenv("DOUYIN_TEST_MODE", "True").lower() in ("true", "1", "yes")

# 抖店 API 基础地址（正式）
API_BASE = "https://open-api.jinritemai.com"

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds, exponential backoff


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class UploadResult:
    """单个商品上架结果。"""
    index: int
    title: str
    product_id: str
    status: str        # "成功" | "失败"
    message: str = ""


# ── 正式模式 — Token 管理（框架） ────────────────────────

class TokenManager:
    """
    抖店 API 授权 token 管理。
    正式模式下需填入真实 app_key / app_secret 并调用 get_token()。
    """
    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token: Optional[str] = None
        self.expires_at: float = 0

    def get_token(self) -> str:
        """获取 access_token（含缓存和自动续期）。"""
        if self.access_token and time.time() < self.expires_at - 300:
            return self.access_token
        # TODO: 调用抖店 oauth/token 接口
        # resp = requests.post(f"{API_BASE}/oauth/token", json={...})
        # self.access_token = resp.json()["data"]["access_token"]
        # self.expires_at = time.time() + resp.json()["data"]["expires_in"]
        raise NotImplementedError("正式模式：请配置 DOUYIN_APP_KEY / DOUYIN_APP_SECRET 并实现 token 获取")


# ── 正式模式 — 签名生成（框架） ──────────────────────────

def _generate_sign(method: str, path: str, params: dict, app_secret: str) -> str:
    """
    抖店 API 签名算法（HMAC-SHA256）。
    参数按字典序拼接 → 用 app_secret 做 HMAC 签名。
    """
    sorted_params = sorted(params.items())
    raw = f"{method}{path}{urlencode(sorted_params)}"
    return hmac.new(
        app_secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ── 测试模式 — 模拟上架 ─────────────────────────────────

def _mock_upload(product: dict, idx: int) -> UploadResult:
    """模拟上架一个商品，仅打印日志。"""
    title = product.get("optimized_title") or product.get("title", "")
    category = product.get("category", "Unknown")
    price = product.get("suggested_price") or product.get("price", 0)

    logger.info(
        "🔼 [模拟] 上架商品 #%d | 标题: %s | 类别: %s | 售价: ¥%.2f",
        idx, title[:50], category, price,
    )
    # 模拟处理延迟
    time.sleep(0.02)
    return UploadResult(
        index=idx,
        title=title[:50],
        product_id=f"mock_{idx:04d}",
        status="成功",
        message="模拟上架成功（测试模式）",
    )


def _mock_update_price(product_id: str, new_price: float) -> UploadResult:
    """模拟更新价格。"""
    logger.info("💰 [模拟] 更新价格 %s → ¥%.2f", product_id, new_price)
    return UploadResult(
        index=0,
        title="",
        product_id=product_id,
        status="成功",
        message="模拟价格更新成功",
    )


# ── 正式模式 — 商品创建 API（框架） ──────────────────────

def _real_upload_product(product: dict, token_mgr: TokenManager) -> UploadResult:
    """
    真实上架商品（待实现）。
    """
    # TODO: 调用抖店 /product/createProduct 接口
    # 1. 构建商品参数（标题、类别ID、售价、图片等）
    # 2. 生成签名
    # 3. 发送请求
    # 4. 解析响应
    raise NotImplementedError("正式模式待实现")


# ── 重试装饰器 ────────────────────────────────────────────

def _with_retry(fn, *args, **kwargs):
    """带指数退避重试的调用包装。"""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY * (2 ** (attempt - 1))
                logger.warning("⚠ 失败 (第 %d 次), %.1fs 后重试: %s", attempt, delay, e)
                time.sleep(delay)
    raise RuntimeError(f"操作失败，已达最大重试次数 {MAX_RETRIES}") from last_exc


# ── 公开接口 ──────────────────────────────────────────────

def upload_product(product: dict, idx: int = 0) -> UploadResult:
    """
    上架单个商品。
    测试模式下模拟上架；正式模式下调用真实 API。
    """
    if DOUYIN_TEST_MODE:
        return _mock_upload(product, idx)
    else:
        token_mgr = TokenManager(DOUYIN_APP_KEY, DOUYIN_APP_SECRET)
        return _with_retry(_real_upload_product, product, token_mgr)


def update_price(product_id: str, new_price: float) -> UploadResult:
    """更新商品售价。"""
    if DOUYIN_TEST_MODE:
        return _mock_update_price(product_id, new_price)
    else:
        raise NotImplementedError("正式模式：update_price 待实现")


def batch_upload(products: list[dict]) -> list[UploadResult]:
    """
    批量上架商品。
    返回每个商品的上架状态列表（与 products 顺序一致）。
    """
    total = len(products)
    results: list[UploadResult] = []

    logger.info("=" * 50)
    logger.info("开始批量上架 %d 个商品 | 模式: %s", total, "测试" if DOUYIN_TEST_MODE else "正式")
    logger.info("=" * 50)

    for idx, prod in enumerate(products, 1):
        result = upload_product(prod, idx)
        results.append(result)
        if idx % 100 == 0 or idx == total:
            ok = sum(1 for r in results if r.status == "成功")
            logger.info("进度: [%d/%d] 成功: %d", idx, total, ok)

    success = sum(1 for r in results if r.status == "成功")
    fail = total - success
    logger.info("=" * 50)
    logger.info("批量上架完成 | 总计: %d | 成功: %d | 失败: %d", total, success, fail)
    logger.info("=" * 50)

    return results


def run(products: list[dict]) -> list[UploadResult]:
    """
    模块入口：接收优化后的商品列表 → 批量上架 → 返回上架状态。
    """
    return batch_upload(products)
