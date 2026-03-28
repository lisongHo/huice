from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go


def _ensure_frame(frame: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    return pd.DataFrame(frame)


def _empty_figure(title: str, message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        title=title,
        annotations=[
            dict(
                text=message,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=14, color="#666"),
            )
        ],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=24, r=24, t=56, b=24),
    )
    return fig


def equity_curve_figure(frame: pd.DataFrame | list[dict[str, Any]]) -> go.Figure:
    df = _ensure_frame(frame)
    if df.empty:
        return _empty_figure("Equity Curve", "No equity curve is available for this run yet.")

    df = df.sort_values(df.columns[0])
    x_col = "trade_date" if "trade_date" in df.columns else df.columns[0]
    y_col = "equity" if "equity" in df.columns else df.columns[-1]

    fig = go.Figure(
        go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="lines",
            line=dict(width=2.5, color="#1f77b4"),
            name="Equity",
        )
    )
    fig.update_layout(
        template="plotly_white",
        title="Equity Curve",
        margin=dict(l=24, r=24, t=56, b=24),
        xaxis_title="Trade Date",
        yaxis_title="Equity",
        hovermode="x unified",
    )
    fig.update_yaxes(tickprefix="¥", separatethousands=True)
    return fig


def drawdown_figure(frame: pd.DataFrame | list[dict[str, Any]]) -> go.Figure:
    df = _ensure_frame(frame)
    if df.empty:
        return _empty_figure("Drawdown", "No drawdown curve is available for this run yet.")

    x_col = "trade_date" if "trade_date" in df.columns else df.columns[0]
    y_col = "drawdown" if "drawdown" in df.columns else df.columns[-1]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df[x_col],
            y=df[y_col],
            fill="tozeroy",
            mode="lines",
            line=dict(width=2, color="#d62728"),
            name="Drawdown",
        )
    )
    fig.update_layout(
        template="plotly_white",
        title="Drawdown Curve",
        margin=dict(l=24, r=24, t=56, b=24),
        xaxis_title="Trade Date",
        yaxis_title="Drawdown",
        hovermode="x unified",
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def annual_returns_figure(frame: pd.DataFrame | list[dict[str, Any]]) -> go.Figure:
    df = _ensure_frame(frame)
    if df.empty:
        return _empty_figure("Annual Returns", "No annual return breakdown is available for this run yet.")

    year_col = "year" if "year" in df.columns else df.columns[0]
    return_col = "return_pct" if "return_pct" in df.columns else df.columns[1]
    color = ["#2ca02c" if value >= 0 else "#d62728" for value in df[return_col]]

    fig = go.Figure(
        go.Bar(
            x=df[year_col],
            y=df[return_col],
            marker_color=color,
            name="Annual Return",
        )
    )
    fig.update_layout(
        template="plotly_white",
        title="Annual Returns",
        margin=dict(l=24, r=24, t=56, b=24),
        xaxis_title="Year",
        yaxis_title="Return",
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def scan_comparison_figure(frame: pd.DataFrame | list[dict[str, Any]]) -> go.Figure:
    df = _ensure_frame(frame)
    if df.empty:
        return _empty_figure("Scan Comparison", "No persisted scan runs are available for this batch yet.")

    x_col = "max_drawdown_pct" if "max_drawdown_pct" in df.columns else df.columns[0]
    y_col = "total_return_pct" if "total_return_pct" in df.columns else df.columns[-1]
    hover_name = "run_id" if "run_id" in df.columns else None
    marker_size = pd.to_numeric(df["trade_count"], errors="coerce").fillna(1) if "trade_count" in df.columns else pd.Series([10] * len(df))

    fig = go.Figure(
        go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="markers+text",
            text=df[hover_name] if hover_name else None,
            textposition="top center",
            marker=dict(
                size=(marker_size.clip(lower=1) * 2).tolist(),
                color=df[y_col],
                colorscale="RdYlGn",
                showscale=True,
            ),
            hovertemplate="<b>%{text}</b><br>drawdown=%{x:.2%}<br>return=%{y:.2%}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_white",
        title="Scan Comparison",
        margin=dict(l=24, r=24, t=56, b=24),
        xaxis_title="Max Drawdown",
        yaxis_title="Total Return",
    )
    fig.update_xaxes(tickformat=".1%")
    fig.update_yaxes(tickformat=".1%")
    return fig


def event_window_figure(
    frame: pd.DataFrame | list[dict[str, Any]],
    *,
    event_date: Any | None = None,
    title: str = "Event Window",
) -> go.Figure:
    df = _ensure_frame(frame)
    if df.empty:
        return _empty_figure(title, "No persisted time-series points are available for this diagnostic yet.")

    x_col = "trade_date" if "trade_date" in df.columns else df.columns[0]
    y_col = "equity" if "equity" in df.columns else df.columns[-1]
    fig = go.Figure(
        go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="lines+markers",
            line=dict(width=2.5, color="#0f766e"),
            name=y_col,
        )
    )
    if event_date is not None:
        fig.add_vline(x=event_date, line_width=2, line_dash="dash", line_color="#dc2626")
    fig.update_layout(
        template="plotly_white",
        title=title,
        margin=dict(l=24, r=24, t=56, b=24),
        xaxis_title="Trade Date",
        yaxis_title=y_col.replace("_", " ").title(),
        hovermode="x unified",
    )
    return fig


def trade_table_frame(frame: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    df = _ensure_frame(frame)
    if df.empty:
        return df

    preferred = [
        "trade_date",
        "symbol",
        "side",
        "shares",
        "price",
        "amount",
        "fees",
        "execution_mode",
        "notes",
    ]
    columns = [column for column in preferred if column in df.columns]
    columns.extend(column for column in df.columns if column not in columns)
    view = df.loc[:, columns].copy()
    if "trade_date" in view.columns:
        view["trade_date"] = pd.to_datetime(view["trade_date"]).dt.date
    if "side" in view.columns:
        view["side"] = view["side"].astype(str).str.upper()
    for column in ("price", "amount", "fees"):
        if column in view.columns:
            view[column] = pd.to_numeric(view[column], errors="coerce").round(2)
    if "shares" in view.columns:
        view["shares"] = pd.to_numeric(view["shares"], errors="coerce").astype("Int64")
    return view.sort_values(by=[column for column in ("trade_date", "symbol") if column in view.columns], ascending=True)


def trade_table_figure(frame: pd.DataFrame | list[dict[str, Any]]) -> go.Figure:
    df = trade_table_frame(frame)
    if df.empty:
        return _empty_figure("Trade Ledger", "No trades were recorded for this run yet.")

    display = df.copy()
    for column in display.columns:
        display[column] = display[column].astype(str)
    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=[f"<b>{column}</b>" for column in display.columns],
                    fill_color="#1f2937",
                    font=dict(color="white", size=12),
                    align="left",
                ),
                cells=dict(
                    values=[display[column].tolist() for column in display.columns],
                    fill_color=[["#f8fafc", "#ffffff"] * (len(display) // 2 + 1)],
                    align="left",
                ),
            )
        ]
    )
    fig.update_layout(
        title="Trade Ledger",
        margin=dict(l=0, r=0, t=48, b=0),
        height=max(320, 36 * len(display) + 160),
        template="plotly_white",
    )
    return fig
