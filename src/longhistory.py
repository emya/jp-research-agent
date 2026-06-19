"""Long-history builder (MVP2 Track B, M2.1 + M2.2).

Fetches several of a company's most recent annual reports, extracts each one's
5-year summary, and merges them into one long FinancialHistory (10-15 yr),
reconciling overlaps with a restatement policy. Reuses the existing chart
renderer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from .charts import build_charts_html
from .edinet.client import EDINETClient, EDINETError
from .models.filing import FilingDocument
from .models.financial_history import FinancialHistory
from .parser.history_merger import merge_histories
from .parser.xbrl_parser import XBRLParser

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "output" / "longhistory"


def build_long_history(
    ticker: str, max_reports: int = 3, client: Optional[EDINETClient] = None
) -> Tuple[FinancialHistory, List[FilingDocument]]:
    client = client or EDINETClient()
    filings = client.fetch_annual_reports(ticker, max_reports=max_reports)
    histories = [XBRLParser(f).extract_history() for f in filings]
    merged = merge_histories(histories)
    if not merged.company and filings:
        merged.company = filings[0].company_name
        merged.ticker = ticker
    return merged, filings


def _persist(out_root: Path, ticker: str, history: FinancialHistory, charts_path: str) -> dict:
    out_dir = Path(out_root) / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    hj = out_dir / "long_history.json"
    hj.write_text(json.dumps(history.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = {"long_history_json": str(hj)}
    if charts_path:
        artifacts["charts_html"] = charts_path
    return artifacts


if __name__ == "__main__":
    import argparse
    import sys

    from .config import load_env

    load_env()

    ap = argparse.ArgumentParser(description="Build a long (multi-filing) financial history.")
    ap.add_argument("ticker")
    ap.add_argument("--years", type=int, default=3, help="Max annual reports to chain (default 3)")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    print(f"Building long history for {args.ticker} from up to {args.years} filings…", file=sys.stderr)
    try:
        history, filings = build_long_history(args.ticker, max_reports=args.years)
    except EDINETError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    rev = history.series.get("revenue")
    span_years = sorted({p.year for s in history.series.values() for p in s.points})
    print(f"\n{history.company} ({history.ticker})")
    print(f"  filings merged: {history.n_filings}")
    print(f"  year span: {min(span_years)}–{max(span_years)} ({len(span_years)} years)" if span_years else "  no data")
    if rev:
        print("  revenue: " + "  ".join(f"{p.year}:¥{p.value/1e12:.2f}T" for p in rev.points))
    if history.discrepancies:
        print(f"\n  ⚠️ {len(history.discrepancies)} discrepancy flag(s):")
        for d in history.discrepancies:
            print(f"    - [{d.kind}] {d.note}")

    charts_path = ""
    if not args.no_charts and filings:
        out_dir = Path(args.output) / args.ticker
        out_dir.mkdir(parents=True, exist_ok=True)
        charts_path = build_charts_html(history, filings[0], out_dir / "charts.html") or ""

    artifacts = _persist(Path(args.output), args.ticker, history, charts_path)
    print("\nArtifacts:", file=sys.stderr)
    for k, v in artifacts.items():
        print(f"  {k}: {v}", file=sys.stderr)
    if charts_path:
        print(f"\nOpen the chart:  open {charts_path}", file=sys.stderr)
