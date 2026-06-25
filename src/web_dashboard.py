#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Web 面板 — 电商运营中心

启动:
  streamlit run src/web_dashboard.py
"""

import json
import os
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from glob import glob

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCRIPTS_DIR = PROJECT_ROOT / "src"

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="电商运营中心",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# 数据加载函数
# ---------------------------------------------------------------------------


@st.cache_data(ttl=10)
def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_products() -> list[dict]:
    data = load_json(DATA_DIR / "optimized_products.json")
    return data if isinstance(data, list) else []


def load_patrol() -> dict:
    data = load_json(DATA_DIR / "patrol_result.json")
    return data if isinstance(data, dict) else {}


def load_competitor_latest() -> dict:
    data = load_json(DATA_DIR / "competitor_latest.json")
    return data if isinstance(data, dict) else {}


def load_competitor_changes() -> dict:
    data = load_json(DATA_DIR / "competitor_changes.json")
    return data if isinstance(data, dict) else {}


def load_latest_report_md() -> str | None:
    files = sorted(DATA_DIR.glob("daily_report_*.md"), reverse=True)
    if not files:
        return None
    try:
        return files[0].read_text(encoding="utf-8")
    except Exception:
        return None


def get_latest_report_date() -> str:
    files = sorted(DATA_DIR.glob("daily_report_*.md"), reverse=True)
    if not files:
        return "无"
    m = re.search(r"daily_report_(\d{8})\.md", files[0].name)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return files[0].name


def count_competitor_changes(changes: dict) -> int:
    total = 0
    for comp in changes.get("competitors", {}).values():
        for key in ("price_changes", "new_products", "removed_products",
                     "stock_changes", "title_changes"):
            total += len(comp.get(key, []))
    return total


# ---------------------------------------------------------------------------
# 脚本执行
# ---------------------------------------------------------------------------


def run_script(script_name: str, args: list[str] | None = None) -> tuple[int, str]:
    """通过 subprocess 启动脚本，捕获 stdout + stderr。

    Windows 下系统编码为 GBK，但 rich 输出 UTF-8 字符，
    因此显式指定 encoding=utf-8 并容错替换，避免解码失败导致 None。
    """
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name)]
    if args:
        cmd.extend(args)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # 让子进程也使用 UTF-8 输出（rich 依赖）
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        # 即使 reader thread 失败，stdout/stderr 也可能为 None，做安全保护
        stdout = result.stdout if result.stdout is not None else ""
        stderr = result.stderr if result.stderr is not None else ""
        output = stdout + stderr
        return result.returncode, output[:4000]
    except subprocess.TimeoutExpired:
        return -1, "执行超时 (600s)"
    except Exception as e:
        return -1, str(e)


# ---------------------------------------------------------------------------
# 概览指标
# ---------------------------------------------------------------------------


def render_overview():
    products = load_products()
    patrol = load_patrol()
    changes = load_competitor_changes()
    report_date = get_latest_report_date()

    cols = st.columns(4)
    with cols[0]:
        st.metric(
            "📦 商品总数",
            len(products),
            help="optimized_products.json 中的商品数量",
        )
    with cols[1]:
        anomaly_count = patrol.get("summary", {}).get("total", 0)
        st.metric(
            "🔍 巡店异常",
            anomaly_count,
            delta=f"{patrol.get('total_checked', 0)} 个已检查",
            delta_color="off" if anomaly_count == 0 else "inverse",
            help="patrol_result.json 中的异常数",
        )
    with cols[2]:
        change_count = count_competitor_changes(changes)
        st.metric(
            "📊 竞品变动",
            change_count,
            help="competitor_changes.json 中的变动总数",
        )
    with cols[3]:
        st.metric(
            "📅 最新日报",
            report_date,
            help="最新 daily_report_*.md 的日期",
        )


# ---------------------------------------------------------------------------
# Tab: 商品管理
# ---------------------------------------------------------------------------


def render_products_tab():
    products = load_products()
    if not products:
        st.info("暂无商品数据 (data/optimized_products.json)")
        return

    df = pd.DataFrame(products)

    # 标准化列名
    col_map = {
        "title": "原标题",
        "optimized_title": "优化标题",
        "category": "品类",
        "price": "原价(USD)",
        "suggested_price": "建议售价(USD)",
        "currency": "货币",
        "stock_status": "库存状态",
    }
    display_cols = [k for k in col_map if k in df.columns]
    df_display = df[display_cols].rename(columns=col_map)

    # 筛选器
    col1, col2 = st.columns(2)
    categories = sorted(df["category"].dropna().unique()) if "category" in df.columns else []
    with col1:
        sel_cat = st.multiselect("按品类筛选", options=categories, default=[])

    with col2:
        price_max = df["suggested_price"].max() if "suggested_price" in df.columns else 1000
        price_range = st.slider(
            "建议售价区间 (USD)",
            0.0, float(price_max) * 1.1, (0.0, float(price_max) * 1.1),
        )

    # 应用筛选
    mask = pd.Series([True] * len(df_display))
    if sel_cat:
        mask &= df["category"].isin(sel_cat)
    if "suggested_price" in df.columns:
        mask &= df["suggested_price"].between(price_range[0], price_range[1])

    filtered = df_display[mask]
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.caption(f"共 {len(filtered)} 条 (已筛选) / {len(df_display)} 条 (总计)")


# ---------------------------------------------------------------------------
# Tab: 巡店报告
# ---------------------------------------------------------------------------


def render_patrol_tab():
    patrol = load_patrol()
    anomalies = patrol.get("anomalies", [])

    if not anomalies:
        st.success("✅ 本日巡店无异常")
        return

    # 表格
    df = pd.DataFrame(anomalies)
    col_map = {
        "product_id": "商品ID",
        "name": "商品名",
        "type": "异常类型",
        "severity": "严重度",
        "detail": "详情",
        "current_price": "当前价",
        "regular_price": "原价",
        "stock_quantity": "库存",
    }
    display_cols = [k for k in col_map if k in df.columns]
    st.dataframe(df[display_cols].rename(columns=col_map), use_container_width=True, hide_index=True)

    # 饼图：异常类型分布
    st.subheader("异常类型分布")
    type_counts = df["type"].value_counts().reset_index()
    type_counts.columns = ["type", "count"]

    type_labels = {
        "price_too_low": "价格过低",
        "price_too_high": "价格过高",
        "stock_low": "库存不足",
        "stock_unmanaged": "未管理库存",
        "status_alert": "状态异常",
    }
    type_counts["label"] = type_counts["type"].map(type_labels).fillna(type_counts["type"])

    colors = {
        "price_too_low": "#ef4444",
        "price_too_high": "#f59e0b",
        "stock_low": "#eab308",
        "stock_unmanaged": "#3b82f6",
        "status_alert": "#a855f7",
    }
    pie_colors = [colors.get(t, "#6b7280") for t in type_counts["type"]]

    fig = px.pie(
        type_counts,
        values="count",
        names="label",
        title="异常类型占比",
        color_discrete_sequence=pie_colors,
        hole=0.4,
    )
    fig.update_traces(textposition="inside", textinfo="label+percent")
    st.plotly_chart(fig, use_container_width=True)

    # 严重度分布柱状图
    sev_counts = df["severity"].value_counts().reset_index()
    sev_counts.columns = ["severity", "count"]
    fig2 = px.bar(
        sev_counts, x="severity", y="count",
        title="严重度分布",
        color="severity",
        color_discrete_map={"error": "#ef4444", "warning": "#f59e0b", "info": "#3b82f6"},
        text_auto=True,
    )
    st.plotly_chart(fig2, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab: 竞品监控
# ---------------------------------------------------------------------------


def render_competitor_tab():
    latest = load_competitor_latest()
    changes = load_competitor_changes()
    competitors = latest.get("competitors", [])

    if not competitors:
        st.info("暂无竞品数据")
        return

    for comp in competitors:
        name = comp.get("competitor_name", "(无名)")
        scraped_at = comp.get("scraped_at", "")
        products = comp.get("products", [])
        error = comp.get("error")

        with st.expander(f"📌 {name}  —  {len(products)} 个商品  ({scraped_at})", expanded=True):
            if error:
                st.error(f"抓取错误: {error}")

            if products:
                df = pd.DataFrame(products)
                col_map = {
                    "title": "标题",
                    "price": "价格",
                    "price_raw": "原始价格",
                    "in_stock": "有货",
                    "stock_text": "库存状态",
                    "dropshipping": "一件代发",
                    "rating": "评分",
                    "link": "链接",
                }
                display_cols = [k for k in col_map if k in df.columns]
                df_display = df[display_cols].rename(columns=col_map)
                # 转换 bool 列
                if "in_stock" in df.columns:
                    df_display["有货"] = df["in_stock"].map({True: "✅", False: "❌"})
                if "dropshipping" in df.columns:
                    df_display["一件代发"] = df["dropshipping"].map({True: "✅", False: "—"})
                st.dataframe(df_display, use_container_width=True, hide_index=True)

    # 竞品变动历史
    st.subheader("📊 竞品变动历史")
    change_comps = changes.get("competitors", {})
    if change_comps:
        has_any = any(
            c.get("price_changes") or c.get("new_products") or c.get("removed_products")
            for c in change_comps.values()
        )
        if has_any:
            for comp_name, comp_data in change_comps.items():
                sections = []
                if comp_data.get("price_changes"):
                    sections.append("价格变动")
                if comp_data.get("new_products"):
                    sections.append("新增商品")
                if comp_data.get("removed_products"):
                    sections.append("下架商品")
                if comp_data.get("stock_changes"):
                    sections.append("库存变动")
                if comp_data.get("title_changes"):
                    sections.append("标题变动")
                st.write(f"**{comp_name}**: {', '.join(sections)}")
        else:
            st.info("本日无竞品变动")


# ---------------------------------------------------------------------------
# Tab: 日报
# ---------------------------------------------------------------------------


def render_report_tab():
    md_content = load_latest_report_md()
    if md_content is None:
        st.info("暂无日报 (data/daily_report_*.md)")
        return

    # 显示原始 Markdown 渲染
    st.markdown(md_content)

    # 显示文件列表
    st.divider()
    st.caption("📁 历史日报:")
    report_files = sorted(DATA_DIR.glob("daily_report_*.md"), reverse=True)
    for f in report_files:
        st.caption(f"  {f.name}")


# ---------------------------------------------------------------------------
# 操作区
# ---------------------------------------------------------------------------


def render_actions():
    st.divider()
    st.subheader("⚡ 快速操作")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🔍 执行巡店", use_container_width=True, type="secondary"):
            with st.spinner("正在巡店..."):
                rc, out = run_script("patrol.py", ["--quick"])
            if rc == 0 or rc == 1:  # 0=无异常 1=有异常（都算成功）
                st.success("巡店完成")
            else:
                st.error(f"巡店失败 (code={rc})")
            with st.expander("查看输出"):
                st.code(out)

    with col2:
        if st.button("👀 抓取竞品", use_container_width=True, type="secondary"):
            with st.spinner("正在抓取竞品..."):
                rc, out = run_script("competitor_monitor.py", ["--quick", "--headless"])
            if rc == 0 or rc == 1:
                st.success("竞品抓取完成")
            else:
                st.error(f"抓取失败 (code={rc})")
            with st.expander("查看输出"):
                st.code(out)

    with col3:
        if st.button("📊 生成日报", use_container_width=True, type="primary"):
            with st.spinner("正在调用 AI 生成日报..."):
                rc, out = run_script("daily_report.py")
            if rc == 0:
                st.success("日报生成完成")
            else:
                st.error(f"日报生成失败 (code={rc})")
            with st.expander("查看输出"):
                st.code(out)

    with col4:
        if st.button("🔄 刷新数据", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


# ---------------------------------------------------------------------------
# 主布局
# ---------------------------------------------------------------------------


def main():
    st.title("📊 电商运营中心")
    st.caption(f"项目: {PROJECT_ROOT}  |  数据目录: {DATA_DIR}")

    render_overview()
    render_actions()

    tabs = st.tabs(["📦 商品管理", "🔍 巡店报告", "👀 竞品监控", "📅 日报"])

    with tabs[0]:
        render_products_tab()
    with tabs[1]:
        render_patrol_tab()
    with tabs[2]:
        render_competitor_tab()
    with tabs[3]:
        render_report_tab()

    st.divider()
    st.caption(f"🕐 最后刷新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
