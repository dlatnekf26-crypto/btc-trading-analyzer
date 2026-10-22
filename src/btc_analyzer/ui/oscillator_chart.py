"""Small shared oscillator panels; reuse the chart's already computed features."""

import numpy as np
import plotly.graph_objects as go

PANELS = (
    {"axis": "yaxis3", "label": "RSI", "fields": ["rsi"], "fixed": [0, 100]},
    {"axis": "yaxis4", "label": "MACD", "fields": ["macd", "macd_signal", "macd_hist"]},
)


def macd_range(frame):
    values = frame[["macd", "macd_signal", "macd_hist"]].to_numpy(dtype=float)
    valid = values[np.isfinite(values)]
    low, high = (min(0.0, float(valid.min())), max(0.0, float(valid.max()))) if valid.size else (-1.0, 1.0)
    pad = max(high - low, abs(high), abs(low), 1e-8) * 0.12
    return [low - pad, high + pad]


def add_oscillators(fig, frame, x):
    for key, label, color, row in (
        ("rsi", "RSI", "#ef3f50", 3),
        ("macd", "MACD", "#3182f6", 4),
        ("macd_signal", "MACD 시그널", "#dd9b24", 4),
    ):
        fig.add_trace(
            go.Scatter(
                x=x,
                y=frame[key],
                name=label,
                mode="lines",
                showlegend=False,
                line={"width": 1.4, "color": color},
                connectgaps=False,
            ),
            row=row,
            col=1,
        )
    fig.add_trace(
        go.Bar(
            x=x,
            y=frame.macd_hist,
            name="MACD 히스토그램",
            showlegend=False,
            marker_color=["#10a878" if n >= 0 else "#e94b65" for n in frame.macd_hist],
        ),
        row=4,
        col=1,
    )
    for level in (30, 70):
        fig.add_hline(y=level, line_width=1, line_dash="dot", line_color="#c6ceda", row=3, col=1)
    fig.add_hrect(y0=30, y1=70, line_width=0, fillcolor="rgba(140,101,218,.045)", row=3, col=1)
    fig.add_hline(y=0, line_width=1, line_color="#c6ceda", row=4, col=1)
    for row, label in (
        (2, "거래량"),
        (3, "RSI 14 · 기준 30 / 70"),
        (4, "MACD 12·26·9 · 파랑 MACD / 주황 시그널"),
    ):
        fig.add_annotation(
            x=0,
            y=1,
            xref=f"x{row} domain",
            yref=f"y{row} domain",
            text=label,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font={"size": 10, "color": "#6b7684"},
        )
