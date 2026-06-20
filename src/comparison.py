"""Peer / sector comparison engine (MVP2 Track A).

Runs the per-company extraction across a peer set, aligns the latest-year
metrics, ranks them, and produces a relative-analysis memo + dashboard.

Stays within the project's Non-Goals: the memo makes *relative observations*
("X trades at a lower P/E than peers"), never recommendations or signals.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .edinet.client import EDINETClient, EDINETError
from .models.comparison import (
    METRIC_LABEL,
    METRIC_ORDER,
    METRIC_UNIT,
    PeerComparison,
    PeerMetric,
    PeerRow,
    assign_ranks,
)
from .models.financial_history import FinancialHistory
from .models.financial_metrics import compute_growth
from .pipeline import PipelineError, run
from .research import llm
from .research.context import format_yen, operating_margin

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SECTORS_PATH = _REPO_ROOT / "sectors.json"
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "output" / "comparison"


def load_sector(name: str) -> Optional[List[str]]:
    if not _SECTORS_PATH.exists():
        return None
    return json.loads(_SECTORS_PATH.read_text(encoding="utf-8")).get(name)


def _hist_latest(history: FinancialHistory, key: str) -> Optional[float]:
    s = history.series.get(key)
    return s.points[-1].value if s and s.points else None


def _company_metrics(result: Dict) -> Dict[str, PeerMetric]:
    current = result["periods"]["current"]
    prior = result["periods"].get("prior")
    history = result["history"]
    growth = compute_growth(current, prior)

    raw: Dict[str, Optional[float]] = {}
    rev = current.get("revenue")
    raw["revenue"] = rev.value if rev else None
    raw["revenue_growth"] = (growth.get("revenue") * 100) if growth.get("revenue") is not None else None
    om = operating_margin(current)
    raw["operating_margin"] = (om * 100) if om is not None else None
    raw["net_margin"] = _hist_latest(history, "net_margin")
    raw["roe"] = _hist_latest(history, "roe")
    raw["per"] = _hist_latest(history, "per")
    raw["eps"] = _hist_latest(history, "eps")
    raw["payout_ratio"] = _hist_latest(history, "payout_ratio")

    return {
        k: PeerMetric(value=v, unit=METRIC_UNIT[k])
        for k, v in raw.items()
        if v is not None
    }


def build_comparison(
    tickers: List[str],
    sector: str = "custom",
    client: Optional[EDINETClient] = None,
    on_progress=None,
) -> Tuple[PeerComparison, Dict[str, FinancialHistory], List[Dict]]:
    """Returns (comparison, histories, errors). Per-company extraction uses
    offline-template memos (no LLM) — only the final comparison memo uses an LLM."""
    rows: List[PeerRow] = []
    histories: Dict[str, FinancialHistory] = {}
    errors: List[Dict] = []

    for t in tickers:
        if on_progress:
            on_progress(t)
        try:
            result = run(t, client=client, use_llm=False, write=False, make_charts=False)
        except (EDINETError, PipelineError) as exc:
            errors.append({"ticker": t, "error": str(exc)})
            continue
        rows.append(PeerRow(
            ticker=t,
            company=result["filing"].company_name,
            fiscal_year=result["periods"]["current"].fiscal_year,
            data_kind=result["filing"].data_kind,
            metrics=_company_metrics(result),
        ))
        histories[t] = result["history"]

    comparison = PeerComparison(
        sector=sector,
        as_of=_dt.date.today().isoformat(),
        metric_order=list(METRIC_ORDER),
        rows=rows,
    )
    assign_ranks(comparison)

    fys = {r.fiscal_year for r in rows}
    if len(fys) > 1:
        comparison.fiscal_year_warning = (
            "Peers do not share a fiscal year-end (" + ", ".join(sorted(fys)) +
            ") — latest-FY comparison is approximate."
        )
    return comparison, histories, errors


# ---------------------------------------------------------------- formatting
def fmt_metric(m: PeerMetric) -> str:
    if m.unit == "JPY":
        return format_yen(m.value)
    if m.unit == "%":
        return f"{m.value:.1f}%"
    if m.unit == "x":
        return f"{m.value:.1f}×"
    if m.unit == "JPY/share":
        return f"¥{m.value:,.0f}"
    return f"{m.value:,.2f}"


def _leader(comparison: PeerComparison, key: str) -> Optional[PeerRow]:
    for r in comparison.rows:
        m = r.get(key)
        if m and m.rank == 1:
            return r
    return None


# ----------------------------------------------------------------- the memo
_MEMO_SCHEMA = {
    "type": "object",
    "properties": {
        "valuation": {"type": "string"},
        "growth_and_profitability": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["valuation", "growth_and_profitability", "summary"],
    "additionalProperties": False,
}
_MEMO_SYSTEM = (
    "You are an equity analyst writing a RELATIVE comparison across peer "
    "companies, using only the provided figures (extracted from XBRL filings). "
    "Make comparative observations (who is cheaper on P/E, who grows faster, who "
    "is more profitable) and explain them with the numbers. Do NOT make buy/sell "
    "recommendations or predict prices — relative analysis only. "
    "Write your ENTIRE response in English."
)


def _comparison_table_text(comparison: PeerComparison) -> str:
    lines = [f"Sector: {comparison.sector}  (as of {comparison.as_of})"]
    if comparison.fiscal_year_warning:
        lines.append("NOTE: " + comparison.fiscal_year_warning)
    for r in comparison.rows:
        parts = [f"{r.company} ({r.ticker}, FY{r.fiscal_year})"]
        for key in comparison.metric_order:
            m = r.get(key)
            if m:
                rank = f" [#{m.rank}]" if m.rank else ""
                parts.append(f"{METRIC_LABEL[key]}={fmt_metric(m)}{rank}")
        lines.append("  - " + "; ".join(parts))
    return "\n".join(lines)


def comparison_memo(comparison: PeerComparison) -> Tuple[str, str]:
    """Return (markdown, mode). LLM relative analysis when available, else a
    deterministic ranking summary."""
    if llm.llm_available():
        try:
            out = llm.complete_json(
                _MEMO_SYSTEM,
                _comparison_table_text(comparison) +
                "\n\nWrite: valuation (relative P/E positioning), "
                "growth_and_profitability, and a short summary.",
                _MEMO_SCHEMA,
            )
            md = (
                f"## Valuation\n\n{out['valuation']}\n\n"
                f"## Growth & Profitability\n\n{out['growth_and_profitability']}\n\n"
                f"## Summary\n\n{out['summary']}\n"
            )
            return md, f"llm:{llm.active_model_label()}"
        except Exception:
            pass
    return _offline_memo(comparison), "offline-template"


def _offline_memo(comparison: PeerComparison) -> str:
    parts: List[str] = []
    leaders = {
        "revenue": "largest by revenue",
        "revenue_growth": "fastest revenue growth",
        "operating_margin": "highest operating margin",
        "roe": "highest ROE",
        "per": "lowest P/E (cheapest on earnings)",
    }
    bullets = []
    for key, desc in leaders.items():
        r = _leader(comparison, key)
        if r:
            bullets.append(f"- **{desc}:** {r.company} ({r.ticker}) — {fmt_metric(r.get(key))}")
    parts.append("## Relative positioning\n")
    parts.append("\n".join(bullets) if bullets else "_Insufficient data._")
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------- table out
def print_table(comparison: PeerComparison) -> None:
    cols = [k for k in comparison.metric_order]
    header = f"{'Ticker':7} {'Company':24} " + " ".join(f"{METRIC_LABEL[k][:10]:>11}" for k in cols)
    print(header)
    print("-" * len(header))
    for r in comparison.rows:
        cells = []
        for k in cols:
            m = r.get(k)
            cells.append(f"{fmt_metric(m):>11}" if m else f"{'—':>11}")
        print(f"{r.ticker:7} {r.company[:24]:24} " + " ".join(cells))
    if comparison.fiscal_year_warning:
        print("\n⚠️ " + comparison.fiscal_year_warning)


def _persist(out_root: Path, comparison: PeerComparison, memo_md: str, charts_path: str) -> Dict[str, str]:
    out_dir = Path(out_root) / comparison.sector
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    cj = out_dir / "comparison.json"
    cj.write_text(json.dumps(comparison.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts["comparison_json"] = str(cj)
    mm = out_dir / "comparison_memo.md"
    mm.write_text(f"# {comparison.sector} — peer comparison\n\n_as of {comparison.as_of}_\n\n" + memo_md, encoding="utf-8")
    artifacts["comparison_memo"] = str(mm)
    if charts_path:
        artifacts["comparison_html"] = charts_path
    return artifacts


if __name__ == "__main__":
    import argparse
    import sys

    from .charts_compare import build_comparison_html
    from .config import load_env

    load_env()

    ap = argparse.ArgumentParser(description="Peer / sector comparison.")
    ap.add_argument("target", nargs="+", help="A sector name from sectors.json, or explicit tickers")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    if len(args.target) == 1 and load_sector(args.target[0]) is not None:
        sector = args.target[0]
        tickers = load_sector(sector)
    else:
        sector = "custom"
        tickers = args.target

    print(f"Comparing {sector}: {', '.join(tickers)}", file=sys.stderr)
    comparison, histories, errors = build_comparison(
        tickers, sector=sector, on_progress=lambda t: print(f"  fetching {t}…", file=sys.stderr)
    )
    for e in errors:
        print(f"  ! {e['ticker']}: {e['error'][:70]}", file=sys.stderr)

    print()
    print_table(comparison)

    memo_md, memo_mode = comparison_memo(comparison)
    charts_path = ""
    if not args.no_charts:
        out_dir = Path(args.output) / sector
        out_dir.mkdir(parents=True, exist_ok=True)
        charts_path = build_comparison_html(comparison, histories, out_dir / "comparison.html") or ""

    artifacts = _persist(Path(args.output), comparison, memo_md, charts_path)
    print(f"\nMemo ({memo_mode}):\n", file=sys.stderr)
    print(memo_md)
    print("Artifacts:", file=sys.stderr)
    for k, v in artifacts.items():
        print(f"  {k}: {v}", file=sys.stderr)
    if charts_path:
        print(f"\nOpen the dashboard:  open {charts_path}", file=sys.stderr)
