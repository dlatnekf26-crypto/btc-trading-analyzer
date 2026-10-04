"""Plotly price, indicator, trade, performance and simulation visualizations."""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from btc_analyzer.strategy.signal_engine import Analysis
from btc_analyzer.candles import candle_shift


def style_chart(fig: go.Figure, height: int = 540) -> go.Figure:
    fig.update_layout(
        height=height,
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#ffffff",
        colorway=["#3182f6", "#dd9b24", "#08a878", "#8c65da", "#e94b65"],
        font={"family": "Inter, Arial, sans-serif", "color": "#53647b", "size": 11},
        margin={"t": 55, "b": 40, "l": 8, "r": 8},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.04, "x": 0, "font": {"size": 11}},
        hoverlabel={"bgcolor": "#ffffff", "font_color": "#191f28"},
        modebar={"bgcolor": "rgba(255,255,255,0.95)", "color": "#66758b", "activecolor": "#3182f6"},
    )
    fig.update_xaxes(gridcolor="#edf1f7", zeroline=False)
    fig.update_yaxes(gridcolor="#edf1f7", zeroline=False, tickformat=",.0f")
    return fig


def add_ichimoku(fig: go.Figure, df: pd.DataFrame, frame: pd.DataFrame, timezone: str, detail: bool) -> None:
    """Plot shifted geometry only; no backward-shifted close enters features."""
    displacement = int(df.attrs.get("ichimoku_displacement", 26))
    timeframe = df.attrs.get("timeframe", "1h")
    recent = df.tail(min(displacement, int(df.bars_since_gap.iloc[-1])))
    projected = candle_shift(recent.index, timeframe, displacement)
    future = projected > frame.index[-1]
    cloud = pd.DataFrame({"a": frame.ichimoku_cloud_a, "b": frame.ichimoku_cloud_b})
    ahead = pd.DataFrame(
        {"a": recent.ichimoku_span_a.to_numpy()[future], "b": recent.ichimoku_span_b.to_numpy()[future]},
        index=projected[future],
    )
    cloud = pd.concat([cloud, ahead]).sort_index()
    valid = cloud.notna().all(axis=1)
    show_legend = True
    for bullish in (True, False):
        mask = valid & ((cloud.a >= cloud.b) == bullish)
        groups = mask.ne(mask.shift()).cumsum()
        for _, selected in mask[mask].groupby(groups).groups.items():
            part = cloud.loc[selected]
            x = part.index.tz_convert(timezone)
            color = "rgba(16,168,119,0.15)" if bullish else "rgba(233,75,101,0.13)"
            edge = "rgba(16,168,119,0.45)" if bullish else "rgba(233,75,101,0.4)"
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=part.a,
                    name="일목 구름",
                    mode="lines",
                    legendgroup="ichimoku-cloud",
                    showlegend=show_legend,
                    line={"color": edge, "width": 1},
                    hoverinfo="skip",
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=part.b,
                    name="일목 구름",
                    mode="lines",
                    legendgroup="ichimoku-cloud",
                    showlegend=False,
                    fill="tonexty",
                    fillcolor=color,
                    line={"color": edge, "width": 1},
                    hoverinfo="skip",
                ),
                row=1,
                col=1,
            )
            show_legend = False
    if detail:
        for key, label, color in (
            ("ichimoku_tenkan", "전환선", "#3182f6"),
            ("ichimoku_kijun", "기준선", "#dd9b24"),
        ):
            fig.add_trace(
                go.Scatter(
                    x=frame.index.tz_convert(timezone),
                    y=frame[key],
                    name=label,
                    line={"color": color, "width": 1.5},
                ),
                row=1,
                col=1,
            )
        lag_x = candle_shift(df.index, timeframe, -displacement)
        visible = lag_x >= frame.index[0]
        fig.add_trace(
            go.Scatter(
                x=lag_x[visible].tz_convert(timezone),
                y=df.close.to_numpy()[visible],
                name="후행스팬",
                line={"color": "#8c65da", "width": 1, "dash": "dot"},
                hovertemplate="%{x}<br>"
                + str(displacement)
                + "봉 과거에 표시한 종가 %{y:,.2f}<extra>후행스팬</extra>",
            ),
            row=1,
            col=1,
        )


def price_chart(
    df: pd.DataFrame,
    analysis: Analysis,
    timezone: str = "Asia/Seoul",
    averages: tuple[str, ...] = ("ema_20", "ema_50", "ema_200"),
    bands: bool = True,
    trades: pd.DataFrame | None = None,
    quote: str = "USDT",
    ichimoku: bool = False,
    ichimoku_detail: bool = True,
    zones_visible: bool = True,
    levels_visible: bool = True,
    bars: int = 300,
) -> go.Figure:
    """Display time in the selected timezone; analysis/storage timestamps remain UTC."""
    frame = df.tail(bars)
    x = frame.index.tz_convert(timezone)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=frame.open,
            high=frame.high,
            low=frame.low,
            close=frame.close,
            name="가격",
            increasing_line_color="#10a878",
            decreasing_line_color="#e94b65",
        ),
        row=1,
        col=1,
    )
    if ichimoku:
        add_ichimoku(fig, df, frame, timezone, ichimoku_detail)
    average_colors = {"ema_20": "#dd9b24", "ema_50": "#3182f6", "ema_200": "#8c65da"}
    for key in averages:
        if key in frame and frame[key].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=frame[key],
                    name=key.upper().replace("_", " "),
                    line={"width": 1.5, "color": average_colors.get(key, "#91a8c8")},
                ),
                row=1,
                col=1,
            )
    if bands:
        for key in ("bb_upper", "bb_middle", "bb_lower"):
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=frame[key],
                    name="볼린저 밴드",
                    legendgroup="bands",
                    showlegend=key == "bb_upper",
                    line={"width": 1, "color": "#6682a6", "dash": "dot"},
                ),
                row=1,
                col=1,
            )
    fig.add_trace(
        go.Bar(
            x=x,
            y=frame.volume,
            name="거래량",
            showlegend=False,
            marker_color=["#34d399" if c >= o else "#fb7185" for c, o in zip(frame.close, frame.open)],
        ),
        row=2,
        col=1,
    )
    for zone in analysis.zones if zones_visible else []:
        fig.add_hrect(
            y0=zone.low,
            y1=zone.high,
            fillcolor="#34d399" if zone.kind == "Support" else "#fb7185",
            opacity=0.12,
            line_width=0,
            row=1,
            col=1,
        )
    if analysis.plan and levels_visible:
        p = analysis.plan
        fig.add_hrect(y0=p.entry_low, y1=p.entry_high, fillcolor="#60a5fa", opacity=0.2, row=1, col=1)
        fig.add_hline(y=p.stop, line_dash="dash", line_color="#ef4444", annotation_text="Stop", row=1, col=1)
        for i, tp in enumerate(p.targets):
            fig.add_hline(
                y=tp, line_dash="dash", line_color="#a78bfa", annotation_text=f"TP{i + 1}", row=1, col=1
            )
    if trades is not None and not trades.empty:
        for column, time_column, marker, name in [
            ("entry", "entry_time", "triangle-up", "Entry"),
            ("exit", "exit_time", "circle", "Exit (weighted)"),
        ]:
            times = pd.to_datetime(trades[time_column], utc=True)
            mask = (times >= frame.index[0]) & (times <= frame.index[-1] + pd.Timedelta(days=1))
            selected = trades.loc[mask]
            fig.add_trace(
                go.Scatter(
                    x=times[mask].dt.tz_convert(timezone),
                    y=selected[column],
                    mode="markers",
                    name=name,
                    marker={
                        "symbol": marker,
                        "size": 10,
                        "color": ["#34d399" if p > 0 else "#fb7185" for p in selected.pnl],
                    },
                ),
                row=1,
                col=1,
            )
    fig.update_layout(xaxis_rangeslider_visible=False, uirevision=f"btc-{df.attrs.get('timeframe', '1h')}")
    fig.update_xaxes(title_text=f"{timezone} · 봉 시작 시각", row=2, col=1)
    fig.update_yaxes(title_text=quote, row=1, col=1)
    return style_chart(fig, 550)


def indicator_chart(df: pd.DataFrame, timezone: str = "Asia/Seoul") -> go.Figure:
    frame = df.tail(300)
    x = frame.index.tz_convert(timezone)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, subplot_titles=["RSI", "MACD", "ATR% / BB width%"])
    fig.add_trace(go.Scatter(x=x, y=frame.rsi, name="RSI"), row=1, col=1)
    for level in (30, 70):
        fig.add_hline(y=level, line_dash="dot", row=1, col=1)
    for key in ("macd", "macd_signal"):
        fig.add_trace(go.Scatter(x=x, y=frame[key], name=key), row=2, col=1)
    fig.add_trace(go.Bar(x=x, y=frame.macd_hist, name="Histogram"), row=2, col=1)
    fig.add_trace(go.Scatter(x=x, y=frame.atr_pct, name="ATR%"), row=3, col=1)
    fig.add_trace(go.Scatter(x=x, y=frame.bb_width * 100, name="BB width%"), row=3, col=1)
    return style_chart(fig, 640)


def equity_chart(equity: pd.DataFrame, quote: str = "USDT") -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
    for key, name in (("equity", "Strategy"), ("buy_hold", "Buy & Hold (net costs)")):
        fig.add_trace(go.Scatter(x=equity.index, y=equity[key], name=name), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=equity.index, y=equity.drawdown * 100, fill="tozeroy", name="Drawdown%"), row=2, col=1
    )
    fig.update_yaxes(title_text=quote, row=1, col=1)
    return style_chart(fig, 500)


def monte_chart(bands: pd.DataFrame, quote: str = "USDT") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bands.index, y=bands.p95, name="95th percentile", line={"width": 0}))
    fig.add_trace(
        go.Scatter(x=bands.index, y=bands.p05, name="5th percentile", fill="tonexty", line={"width": 0})
    )
    fig.add_trace(go.Scatter(x=bands.index, y=bands["median"], name="Median"))
    fig.update_layout(xaxis_title="거래 횟수", yaxis_title=f"모의 자산 · {quote}")
    return style_chart(fig, 430)
