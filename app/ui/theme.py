from __future__ import annotations

from html import escape

import streamlit as st


_THEME_CSS = """
<style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(196, 92, 55, 0.12), transparent 28%),
            radial-gradient(circle at top right, rgba(26, 84, 72, 0.10), transparent 24%),
            linear-gradient(180deg, #f7f1e8 0%, #f3eee6 45%, #efe7dc 100%);
        color: #201815;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f2ede5 0%, #ece4d8 100%);
        border-right: 1px solid rgba(32, 24, 21, 0.08);
    }
    [data-testid="stSidebar"] * {
        color: #2b211d !important;
    }
    .quantlab-hero {
        position: relative;
        overflow: hidden;
        padding: 1.4rem 1.4rem 1.1rem 1.4rem;
        margin: 0 0 1.2rem 0;
        border: 1px solid rgba(83, 54, 45, 0.12);
        border-radius: 24px;
        background: linear-gradient(145deg, rgba(255,255,255,0.76), rgba(250,244,236,0.94));
        box-shadow: 0 18px 40px rgba(65, 40, 29, 0.08);
    }
    .quantlab-hero::after {
        content: "";
        position: absolute;
        inset: auto -4rem -5rem auto;
        width: 12rem;
        height: 12rem;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(196, 92, 55, 0.18), transparent 68%);
        pointer-events: none;
    }
    .quantlab-kicker {
        margin: 0 0 0.45rem 0;
        font-size: 0.8rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #9a5b43;
        font-weight: 700;
    }
    .quantlab-title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
    }
    .quantlab-title {
        margin: 0;
        font-size: 2.1rem;
        line-height: 1.1;
        color: #1f1713;
        font-weight: 800;
    }
    .quantlab-badge {
        white-space: nowrap;
        padding: 0.45rem 0.8rem;
        border-radius: 999px;
        background: rgba(31, 23, 19, 0.06);
        border: 1px solid rgba(31, 23, 19, 0.08);
        color: #5e4237;
        font-size: 0.84rem;
        font-weight: 700;
    }
    .quantlab-description {
        margin: 0.8rem 0 0 0;
        max-width: 52rem;
        color: #5a4840;
        font-size: 1rem;
        line-height: 1.7;
    }
    .quantlab-section-label {
        margin: 0.2rem 0 0.6rem 0;
        color: #8d5d49;
        font-size: 0.82rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-weight: 700;
    }
    .quantlab-card {
        padding: 1rem 1rem 0.9rem 1rem;
        border-radius: 18px;
        border: 1px solid rgba(83, 54, 45, 0.10);
        background: rgba(255,255,255,0.72);
        box-shadow: 0 10px 24px rgba(65, 40, 29, 0.05);
        min-height: 110px;
    }
    .quantlab-card-label {
        font-size: 0.82rem;
        color: #8a6656;
        margin-bottom: 0.55rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 700;
    }
    .quantlab-card-value {
        font-size: 1.9rem;
        font-weight: 800;
        color: #1f1713;
        line-height: 1.05;
        margin-bottom: 0.35rem;
    }
    .quantlab-card-note {
        color: #68534a;
        font-size: 0.92rem;
        line-height: 1.45;
    }
    div[data-testid="stMetric"] {
        padding: 0.9rem 1rem 0.8rem 1rem;
        border-radius: 18px;
        border: 1px solid rgba(83, 54, 45, 0.10);
        background: rgba(255,255,255,0.72);
        box-shadow: 0 10px 24px rgba(65, 40, 29, 0.05);
    }
    .stButton button {
        border-radius: 999px;
        border: 1px solid rgba(39, 29, 24, 0.12);
        box-shadow: none;
    }
</style>
"""


def apply_workbench_theme(page_title: str) -> None:
    st.set_page_config(page_title=page_title, layout="wide")
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def render_page_header(
    *,
    kicker: str,
    title: str,
    description: str,
    badge: str | None = None,
) -> None:
    badge_html = f'<div class="quantlab-badge">{escape(badge)}</div>' if badge else ""
    st.markdown(
        (
            '<section class="quantlab-hero">'
            f'<div class="quantlab-kicker">{escape(kicker)}</div>'
            '<div class="quantlab-title-row">'
            f'<h1 class="quantlab-title">{escape(title)}</h1>'
            f"{badge_html}"
            "</div>"
            f'<p class="quantlab-description">{escape(description)}</p>'
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_section_label(text: str) -> None:
    st.markdown(f'<div class="quantlab-section-label">{escape(text)}</div>', unsafe_allow_html=True)


def render_card(*, label: str, value: str, note: str) -> None:
    st.markdown(
        (
            '<section class="quantlab-card">'
            f'<div class="quantlab-card-label">{escape(label)}</div>'
            f'<div class="quantlab-card-value">{escape(value)}</div>'
            f'<div class="quantlab-card-note">{escape(note)}</div>'
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def execution_mode_label(mode: str) -> str:
    mapping = {
        "close_proxy": "收盘代理 close_proxy",
        "last_5m_vwap": "尾盘五分钟均价 last_5m_vwap",
        "next_open_control": "次日开盘控制 next_open_control",
    }
    return mapping.get(mode, mode)


def workflow_label(workflow: str) -> str:
    mapping = {
        "backfill": "历史回填 backfill",
        "daily-refresh": "日常刷新 daily-refresh",
        "weekly-maintenance": "周维护 weekly-maintenance",
    }
    return mapping.get(workflow, workflow)


def source_label(source: str) -> str:
    mapping = {
        "app": "本地 app",
        "shared": "共享 shared",
        "missing": "缺失 missing",
    }
    return mapping.get(source, source)


def run_status_label(status: str) -> str:
    mapping = {
        "created": "已创建 created",
        "completed": "已完成 completed",
        "failed": "失败 failed",
    }
    return mapping.get(status.lower(), status)
