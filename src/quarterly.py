"""Quarterly trend tracking via J-Quants (MVP2 follow-up).

    python -m src.quarterly 8035 --quarters 8

J-Quants reports cumulative (year-to-date) figures per period; we keep those and
also derive single-quarter (3-month) values by differencing within each fiscal
year, which is the more useful view for trend tracking.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .jquants.client import JQuantsClient, JQuantsError
from .models.quarterly import QuarterlySeries, QuarterPoint

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "output" / "quarterly"
_PERIOD_ORDER = {"1Q": 1, "2Q": 2, "3Q": 3, "4Q": 4, "FY": 4}


def _num(v) -> Optional[float]:
    if v in (None, "", "-", "－"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _fy_label(fiscal_year_end: str) -> str:
    return f"FY{fiscal_year_end[:4]}" if fiscal_year_end else "FY?"


def parse_statements(ticker: str, rows: List[dict], max_quarters: int = 8) -> QuarterlySeries:
    # Keep the latest-disclosed row per (fiscal year, period) — handles revisions.
    latest: Dict[tuple, dict] = {}
    for s in rows:
        ptype = s.get("CurPerType")
        if ptype not in _PERIOD_ORDER:
            continue
        if _num(s.get("Sales")) is None:
            continue  # skip forecast-only / empty rows
        fye = s.get("CurFYEn") or s.get("CurPerEn") or ""
        key = (fye, ptype)
        prev = latest.get(key)
        if prev is None or (s.get("DiscDate", "") > prev.get("DiscDate", "")):
            latest[key] = s

    # Build cumulative points.
    points: List[QuarterPoint] = []
    cum_by_fy: Dict[str, Dict[str, dict]] = {}
    for (fye, ptype), s in latest.items():
        p = QuarterPoint(
            label=f"{_fy_label(fye)} {ptype}",
            period_type=ptype,
            fiscal_year_end=fye,
            period_end=s.get("CurPerEn", "") or "",
            disclosed_date=s.get("DiscDate", "") or "",
            revenue=_num(s.get("Sales")),
            operating_profit=_num(s.get("OP")),
            net_income=_num(s.get("NP")),
            eps=_num(s.get("EPS")),
        )
        points.append(p)
        cum_by_fy.setdefault(fye, {})[ptype] = {"revenue": p.revenue, "operating_profit": p.operating_profit}

    # Derive single-quarter (3-month) = cumulative - previous cumulative in the FY.
    for p in points:
        order = _PERIOD_ORDER[p.period_type]
        prev_type = {2: "1Q", 3: "2Q", 4: "3Q"}.get(order)
        if order == 1:  # 1Q cumulative == single quarter
            p.revenue_q, p.operating_profit_q = p.revenue, p.operating_profit
            continue
        prev = cum_by_fy.get(p.fiscal_year_end, {}).get(prev_type)
        if prev:
            if p.revenue is not None and prev["revenue"] is not None:
                p.revenue_q = p.revenue - prev["revenue"]
            if p.operating_profit is not None and prev["operating_profit"] is not None:
                p.operating_profit_q = p.operating_profit - prev["operating_profit"]

    points.sort(key=lambda p: (p.period_end, _PERIOD_ORDER[p.period_type]))
    points = points[-max_quarters:]
    return QuarterlySeries(ticker=ticker, points=points)


def build_quarterly(ticker: str, client: Optional[JQuantsClient] = None, max_quarters: int = 8) -> QuarterlySeries:
    client = client or JQuantsClient()
    rows = client.fetch_statements(ticker)
    return parse_statements(ticker, rows, max_quarters=max_quarters)


def build_chart_html(series: QuarterlySeries, out_path: Path) -> Optional[str]:
    if not series.has_data():
        return None
    import plotly.graph_objects as go

    labels = [p.label for p in series.points]
    rev_q = [(p.revenue_q / 1e9) if p.revenue_q is not None else None for p in series.points]
    op_q = [(p.operating_profit_q / 1e9) if p.operating_profit_q is not None else None for p in series.points]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=rev_q, name="Revenue (¥B, single quarter)",
                         marker_color="#9ecae1", hovertemplate="%{x}<br>Revenue: ¥%{y:.1f}B<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=op_q, name="Operating profit (¥B)", mode="lines+markers",
                             line=dict(color="#fd8d3c", width=3),
                             hovertemplate="%{x}<br>Operating profit: ¥%{y:.1f}B<extra></extra>"))
    fig.update_layout(
        title=f"{series.ticker} — Quarterly trend (single-quarter, from J-Quants)",
        template="plotly_white", hovermode="x unified",
        yaxis_title="¥ billion", height=520,
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
    )
    out_path = Path(out_path)
    fig.write_html(str(out_path), include_plotlyjs=True, full_html=True)
    return str(out_path)


def print_table(series: QuarterlySeries) -> None:
    print(f"\n{'Period':12} {'Rev (cum)':>12} {'Rev (Q)':>11} {'OP (Q)':>11} {'Net (cum)':>12}")
    print("-" * 62)
    for p in series.points:
        def b(v):
            return f"¥{v/1e9:.1f}B" if v is not None else "—"
        print(f"{p.label:12} {b(p.revenue):>12} {b(p.revenue_q):>11} {b(p.operating_profit_q):>11} {b(p.net_income):>12}")


if __name__ == "__main__":
    import argparse
    import sys

    from .config import load_env

    load_env()

    ap = argparse.ArgumentParser(description="Quarterly trend tracking via J-Quants.")
    ap.add_argument("ticker")
    ap.add_argument("--quarters", type=int, default=8)
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    client = JQuantsClient()
    if not client.configured:
        print("error: J-Quants not configured. Add JQUANTS_REFRESH_TOKEN (or "
              "JQUANTS_MAILADDRESS + JQUANTS_PASSWORD) to .env. Register free at "
              "https://jpx-jquants.com/.", file=sys.stderr)
        raise SystemExit(1)

    print(f"Fetching quarterly statements for {args.ticker}…", file=sys.stderr)
    try:
        series = build_quarterly(args.ticker, client=client, max_quarters=args.quarters)
    except JQuantsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print_table(series)
    out_dir = Path(args.output) / args.ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "quarterly.json").write_text(
        json.dumps(series.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_charts:
        path = build_chart_html(series, out_dir / "quarterly.html")
        if path:
            print(f"\nOpen the chart:  open {path}", file=sys.stderr)
