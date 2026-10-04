"""Plotly price, indicator, trade, performance and simulation visualizations."""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from btc_analyzer.strategy.signal_engine import Analysis


def price_chart(
    df: pd.DataFrame,
    analysis: Analysis,
    timezone: str = "Asia/Seoul",
    averages: tuple[str, ...] = ("ema_20", "ema_50", "ema_200"),
    bands: bool = True,
    trades: pd.DataFrame | None = None,
) -> go.Figure:
    """Display time in the selected timezone; analysis/storage timestamps remain UTC."""
    frame = df.tail(300)
    x = frame.index.tz_convert(timezone)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    fig.add_trace(
        go.Candlestick(x=x, open=frame.open, high=frame.high, low=frame.low, close=frame.close, name="OHLCV"),
        row=1,
        col=1,
    )
    for key in averages:
        if key in frame:
            fig.add_trace(go.Scatter(x=x, y=frame[key], name=key.upper(), line={"width": 1.3}), row=1, col=1)
    if bands:
        for key in ("bb_upper", "bb_middle", "bb_lower"):
            fig.add_trace(
                go.Scatter(x=x, y=frame[key], name=key, line={"width": 1, "dash": "dot"}), row=1, col=1
            )
    fig.add_trace(
        go.Bar(
            x=x,
            y=frame.volume,
            name="Volume",
            marker_color=["#34d399" if c >= o else "#fb7185" for c, o in zip(frame.close, frame.open)],
        ),
        row=2,
        col=1,
    )
    for zone in analysis.zones:
        fig.add_hrect(
            y0=zone.low,
            y1=zone.high,
            fillcolor="#34d399" if zone.kind == "Support" else "#fb7185",
            opacity=0.12,
            line_width=0,
            row=1,
            col=1,
        )
    if analysis.plan:
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
    fig.update_layout(
        height=650,
        template="plotly_dark",
        margin={"t": 30, "b": 20},
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h"},
    )
    fig.update_xaxes(title_text=f"{timezone} · Candle open", row=2, col=1)
    return fig


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
    fig.update_layout(height=650, template="plotly_dark")
    return fig


def equity_chart(equity: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
    for key, name in (("equity", "Strategy"), ("buy_hold", "Buy & Hold (net costs)")):
        fig.add_trace(go.Scatter(x=equity.index, y=equity[key], name=name), row=1, col=1)
    fig.add_trace(
        go.Scatter(x=equity.index, y=equity.drawdown * 100, fill="tozeroy", name="Drawdown%"), row=2, col=1
    )
    fig.update_layout(height=500, template="plotly_dark")
    return fig


def monte_chart(bands: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bands.index, y=bands.p95, name="95th percentile", line={"width": 0}))
    fig.add_trace(
        go.Scatter(x=bands.index, y=bands.p05, name="5th percentile", fill="tonexty", line={"width": 0})
    )
    fig.add_trace(go.Scatter(x=bands.index, y=bands["median"], name="Median"))
    fig.update_layout(template="plotly_dark", xaxis_title="Trade count", yaxis_title="Simulated equity")
    return fig
