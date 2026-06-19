"""Peer-comparison dashboard (MVP2 Track A) — Plotly -> standalone HTML.

Latest-FY snapshot bars (one bar per company) + multi-company trend lines over
the 5-year history. Each company keeps a consistent color across panels.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models.comparison import PeerComparison
from .models.financial_history import FinancialHistory

_YEN_T = 1e12
_PALETTE = ["#3182bd", "#e6550d", "#31a354", "#756bb1", "#d62728",
            "#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b"]

# (title, axis, format-key, metric)
_SNAPSHOT = [
    ("Revenue (latest FY)", "¥ trillion", "yen_t", "revenue"),
    ("Operating margin (latest FY)", "%", "pct", "operating_margin"),
    ("ROE (latest FY)", "%", "pct", "roe"),
    ("P/E ratio (latest FY)", "×", "ratio", "per"),
]
_TRENDS = [
    ("Revenue trend", "¥ trillion", "yen_t", "revenue"),
    ("P/E ratio trend", "×", "ratio", "per"),
    ("ROE trend", "%", "pct", "roe"),
]


def _conv(fmt: str, values):
    if fmt == "yen_t":
        return [v / _YEN_T for v in values], "¥%{y:.2f}T"
    if fmt == "ratio":
        return list(values), "%{y:.1f}×"
    return list(values), "%{y:.1f}%"  # pct


def build_comparison_html(
    comparison: PeerComparison,
    histories: Dict[str, FinancialHistory],
    out_path: Path,
) -> Optional[str]:
    if not comparison.rows:
        return None

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    tickers = [r.ticker for r in comparison.rows]
    name = {r.ticker: r.company for r in comparison.rows}
    color = {t: _PALETTE[i % len(_PALETTE)] for i, t in enumerate(tickers)}

    snap = [p for p in _SNAPSHOT if any(r.get(p[3]) for r in comparison.rows)]
    trend = [
        p for p in _TRENDS
        if any(
            histories.get(t) and histories[t].series.get(p[3]) and histories[t].series[p[3]].points
            for t in tickers
        )
    ]
    panels: List[Tuple[str, Tuple]] = [("snap", p) for p in snap] + [("trend", p) for p in trend]
    if not panels:
        return None

    fig = make_subplots(
        rows=len(panels), cols=1, vertical_spacing=0.06,
        subplot_titles=[f"{p[0]} ({p[1]})" for _kind, p in panels],
    )

    first_trend = True
    for row, (kind, (_title, axis, fmt, metric)) in enumerate(panels, start=1):
        if kind == "snap":
            xs, ys, colors, hovers = [], [], [], []
            for r in comparison.rows:
                m = r.get(metric)
                if not m:
                    continue
                (val,), _ = _conv(fmt, [m.value])
                xs.append(r.ticker)
                ys.append(val)
                colors.append(color[r.ticker])
                hovers.append(name[r.ticker])
            _, hy = _conv(fmt, [0])
            fig.add_trace(
                go.Bar(x=xs, y=ys, marker_color=colors, customdata=hovers, showlegend=False,
                       hovertemplate="<b>%{customdata}</b><br>" + hy + "<extra></extra>"),
                row=row, col=1,
            )
        else:  # trend
            for t in tickers:
                ser = histories.get(t) and histories[t].series.get(metric)
                if not ser or not ser.points:
                    continue
                ys, hy = _conv(fmt, ser.values)
                fig.add_trace(
                    go.Scatter(
                        x=ser.years, y=ys, name=name[t], legendgroup=t,
                        showlegend=first_trend, mode="lines+markers",
                        line=dict(color=color[t], width=2.5),
                        hovertemplate=f"<b>{name[t]}</b><br>%{{x}}: " + hy + "<extra></extra>",
                    ),
                    row=row, col=1,
                )
            first_trend = False
            fig.update_xaxes(dtick=1, row=row, col=1)
        fig.update_yaxes(title_text=axis, row=row, col=1)

    sample = any(r.data_kind == "SAMPLE" for r in comparison.rows)
    caveat = "Includes SAMPLE data" if sample else "Source: official EDINET XBRL"
    fig.update_layout(
        title=dict(
            text=f"{comparison.sector} — Peer Comparison"
                 f"<br><span style='font-size:12px;color:#888'>as of {comparison.as_of} — {caveat}</span>",
            x=0.01, xanchor="left", y=0.99, yanchor="top", font=dict(size=20),
        ),
        height=300 * len(panels) + 130,
        template="plotly_white",
        barmode="group",
        legend=dict(orientation="v", x=1.005, xanchor="left", y=1, yanchor="top", font=dict(size=11)),
        margin=dict(t=100, r=210, l=70, b=40),
    )

    out_path = Path(out_path)
    fig.write_html(str(out_path), include_plotlyjs=True, full_html=True)
    return str(out_path)
