"""Interactive financial-history charts (Plotly -> standalone HTML).

Presentation only — depends on the history model + Plotly, not on EDINET or the
LLM. Produces a single self-contained .html (Plotly inlined, opens offline).

Panel-driven: each panel groups metrics that share a y-axis unit (¥ trillion,
¥/share, P/E ratio ×, or %). Empty panels are skipped.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .models.filing import FilingDocument
from .models.financial_history import FinancialHistory

_YEN_T = 1e12

# (panel title, y-axis title, value-format key, [(metric, trace kind)])
_PANELS: List[Tuple[str, str, str, List[Tuple[str, str]]]] = [
    ("Income statement", "¥ trillion", "yen_t",
     [("revenue", "bar"), ("ordinary_income", "line"), ("net_income", "line")]),
    ("Balance sheet", "¥ trillion", "yen_t",
     [("total_assets", "line"), ("net_assets", "line"), ("debt", "line")]),
    ("Per-share value", "¥ / share", "yen",
     [("eps", "line"), ("bps", "line")]),
    ("Valuation — P/E ratio (PER)", "× (times)", "ratio",
     [("per", "line")]),
    ("Returns & ratios", "%", "pct",
     [("net_margin", "line"), ("roe", "line"), ("equity_ratio", "line"), ("payout_ratio", "line")]),
]

_COLORS = {
    "revenue": "#9ecae1", "ordinary_income": "#fd8d3c", "net_income": "#31a354",
    "total_assets": "#3182bd", "net_assets": "#756bb1", "debt": "#e6550d",
    "eps": "#31a354", "bps": "#756bb1",
    "per": "#d62728",
    "net_margin": "#31a354", "roe": "#e6550d", "equity_ratio": "#756bb1", "payout_ratio": "#3182bd",
}


def _format(kind: str, values):
    if kind == "yen_t":
        return [v / _YEN_T for v in values], "¥%{y:.2f}T"
    if kind == "yen":
        return list(values), "¥%{y:,.0f}"
    if kind == "ratio":
        return list(values), "%{y:.1f}×"
    return list(values), "%{y:.1f}%"  # pct


def build_charts_html(
    history: FinancialHistory, filing: FilingDocument, out_path: Path
) -> Optional[str]:
    """Write an interactive HTML dashboard. Returns the path, or None if there's
    no history to plot."""
    if not history.has_data():
        return None

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    s = history.series
    # Keep only panels that have at least one populated metric.
    active = [
        p for p in _PANELS
        if any(s.get(m) and s[m].points for m, _kind in p[3])
    ]
    if not active:
        return None

    fig = make_subplots(
        rows=len(active), cols=1, vertical_spacing=0.075,
        subplot_titles=[title for title, _axis, _f, _m in active],
    )

    # Each panel gets its own legend (Plotly multi-legend), so traces are grouped
    # by panel instead of one giant 14-item legend overlapping the title.
    for row, (_title, _axis, fmt, metrics) in enumerate(active, start=1):
        legend_id = "legend" if row == 1 else f"legend{row}"
        for metric, kind in metrics:
            ser = s.get(metric)
            if not ser or not ser.points:
                continue
            ys, hy = _format(fmt, ser.values)
            ht = "<b>%{x}</b><br>" + ser.label + ": " + hy + "<extra></extra>"
            color = _COLORS.get(metric)
            common = dict(x=ser.years, y=ys, name=ser.label, hovertemplate=ht, legend=legend_id)
            if kind == "bar":
                fig.add_trace(go.Bar(marker_color=color, **common), row=row, col=1)
            else:
                fig.add_trace(
                    go.Scatter(mode="lines+markers", line=dict(color=color, width=3), **common),
                    row=row, col=1,
                )
        fig.update_yaxes(title_text=_axis, row=row, col=1)

    # Pin each panel's legend to the right of that panel's y-domain.
    legends = {}
    for row in range(1, len(active) + 1):
        axis = fig.layout["yaxis" if row == 1 else f"yaxis{row}"]
        low, high = axis.domain
        legend_id = "legend" if row == 1 else f"legend{row}"
        legends[legend_id] = dict(
            x=1.005, xanchor="left", y=high, yanchor="top",
            orientation="v", font=dict(size=11),
            bgcolor="rgba(255,255,255,0.65)", bordercolor="#dddddd", borderwidth=1,
        )

    fig.update_xaxes(dtick=1)
    caveat = (
        "Illustrative SAMPLE data — not official"
        if filing.data_kind == "SAMPLE"
        else "Source: official EDINET XBRL — figures as reported in the filing"
    )
    fig.update_layout(
        title=dict(
            text=(
                f"{history.company} ({history.ticker}) — Financial History"
                f"<br><span style='font-size:12px;color:#888888'>{caveat}</span>"
            ),
            x=0.01, xanchor="left", y=0.985, yanchor="top", font=dict(size=20),
        ),
        height=320 * len(active) + 110,
        hovermode="x unified",
        template="plotly_white",
        margin=dict(t=95, r=260, l=70, b=50),
        **legends,
    )

    out_path = Path(out_path)
    fig.write_html(str(out_path), include_plotlyjs=True, full_html=True)
    return str(out_path)
