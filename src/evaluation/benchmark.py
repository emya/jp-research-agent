"""Research benchmark (stretch goal).

Evaluates the pipeline across multiple companies on the three CLAUDE.md
dimensions:

  1. Extraction  — objective, no LLM. Coverage of the 5 core metrics, a
     cross-source consistency check (current-period value vs the latest year of
     the 5-year summary — two independent XBRL locations that should agree), and
     sanity checks. This is our closest thing to "ground truth".
  2. Research quality — optional LLM-as-judge scoring a rubric (explains the
     earnings change, identifies key risks, theses grounded, faithful to the
     figures, usefulness).
  3. Summarization quality — folded into the same judge call.

Run:  .venv/bin/python -m src.evaluation.benchmark 8035 6857 6920
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..edinet.client import EDINETClient, EDINETError
from ..models.financial_metrics import METRIC_KEYS
from ..pipeline import PipelineError, run
from ..research import llm
from ..research.context import build_context, context_as_prompt_block

# Semiconductor supply-chain names from the README.
DEFAULT_TICKERS = ["8035", "6857", "6920", "7735", "6146"]

# Metrics present in BOTH the main statements and the 5-year summary, so the two
# independent extractions can be cross-checked. Pairs are (history_key,
# current_metric_key) — the two layers name total assets / net assets
# differently (history: total_assets/net_assets; current: assets/equity).
_CONSISTENCY_PAIRS = [
    ("revenue", "revenue"),
    ("net_income", "net_income"),
    ("total_assets", "assets"),
    ("net_assets", "equity"),
]
_REL_TOL = 0.005  # 0.5% — allows for rounding differences

_JUDGE_SYSTEM = (
    "You are a rigorous equity-research reviewer. You are given GROUND-TRUTH "
    "financials extracted from a company's XBRL filing (authoritative) and a "
    "research memo generated about that filing. Score the memo on each criterion "
    "from 1 (poor) to 5 (excellent). Penalize any quantitative claim that "
    "contradicts the ground-truth figures. Be critical and specific."
)

_CRIT = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "comment": {"type": "string"},
    },
    "required": ["score", "comment"],
    "additionalProperties": False,
}
_CRITERIA = [
    "explains_earnings_change",
    "identifies_key_risks",
    "theses_plausible_grounded",
    "faithful_to_figures",
    "overall_usefulness",
]
_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {c: _CRIT for c in _CRITERIA},
    "required": _CRITERIA,
    "additionalProperties": False,
}


def _extraction_report(result: Dict) -> Dict:
    current = result["periods"].get("current")
    history = result["history"]

    found = [k for k in METRIC_KEYS if current and current.get(k) is not None]
    coverage = len(found) / len(METRIC_KEYS)

    checks: List[Dict] = []
    for hist_key, cur_key in _CONSISTENCY_PAIRS:
        cur = current.get(cur_key) if current else None
        ser = history.series.get(hist_key)
        if cur is None or not ser or not ser.points:
            continue
        latest = ser.points[-1].value
        rel = abs(cur.value - latest) / max(abs(latest), 1.0)
        checks.append({
            "metric": hist_key,
            "current": cur.value,
            "history_latest": latest,
            "rel_diff": rel,
            "match": rel < _REL_TOL,
        })
    matches = sum(1 for c in checks if c["match"])
    consistency = (matches / len(checks)) if checks else None

    sanity: Dict[str, bool] = {}
    debt = history.series.get("debt")
    if debt and debt.points:
        sanity["debt_nonneg"] = all(p.value >= 0 for p in debt.points)
    eq = history.series.get("equity_ratio")
    if eq and eq.points:
        sanity["equity_ratio_in_range"] = all(0 <= p.value <= 100 for p in eq.points)
    per = history.series.get("per")
    if per and per.points:
        sanity["per_positive"] = all(p.value > 0 for p in per.points)
    sanity_pass = all(sanity.values()) if sanity else None

    history_years = max((len(s.points) for s in history.series.values()), default=0)

    return {
        "coverage": coverage,
        "metrics_found": found,
        "consistency": consistency,
        "consistency_checks": checks,
        "sanity_pass": sanity_pass,
        "sanity": sanity,
        "history_years": history_years,
        "history_series": sorted(history.series.keys()),
    }


def _research_judge(result: Dict) -> Dict:
    filing = result["filing"]
    periods = result["periods"]
    ctx = build_context(
        filing, periods["current"], periods.get("prior"),
        result["sections"], result["history"],
    )
    facts = context_as_prompt_block(ctx)
    memo_text = result["memo"].to_markdown()
    user = (
        "GROUND-TRUTH FACTS (from XBRL — authoritative):\n"
        f"{facts}\n\n"
        "RESEARCH MEMO TO EVALUATE:\n"
        f"{memo_text}\n\n"
        "Score each criterion 1-5 with a one-sentence justification."
    )
    out = llm.complete_json(_JUDGE_SYSTEM, user, _JUDGE_SCHEMA, max_tokens=3000)
    scores = [out[c]["score"] for c in _CRITERIA]
    out["_mean_score"] = sum(scores) / len(scores)
    return out


def benchmark_company(
    ticker: str,
    client: Optional[EDINETClient] = None,
    use_llm: Optional[bool] = None,
    judge: Optional[bool] = None,
) -> Dict:
    """Run the full pipeline for one ticker and score it. ``judge`` defaults to
    whether an LLM provider is configured."""
    judge = llm.llm_available() if judge is None else judge
    try:
        result = run(ticker, client=client, use_llm=use_llm, write=False, make_charts=False)
    except (EDINETError, PipelineError) as exc:
        return {"ticker": ticker, "ok": False, "error": str(exc)}

    report = {
        "ticker": ticker,
        "ok": True,
        "company": result["filing"].company_name,
        "data_kind": result["filing"].data_kind,
        "fiscal_year": result["periods"]["current"].fiscal_year,
        "memo_mode": result["memo"].generation_mode,
        "extraction": _extraction_report(result),
    }
    if judge:
        try:
            report["research"] = _research_judge(result)
        except Exception as exc:  # noqa: BLE001 — judging is best-effort
            report["research_error"] = str(exc)
    return report


def run_benchmark(
    tickers: List[str],
    client: Optional[EDINETClient] = None,
    use_llm: Optional[bool] = None,
    judge: Optional[bool] = None,
    on_progress=None,
) -> List[Dict]:
    reports = []
    for t in tickers:
        if on_progress:
            on_progress(t)
        reports.append(benchmark_company(t, client=client, use_llm=use_llm, judge=judge))
    return reports


def aggregate(reports: List[Dict]) -> Dict:
    ok = [r for r in reports if r.get("ok")]
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None
    return {
        "companies": len(reports),
        "succeeded": len(ok),
        "mean_coverage": mean([r["extraction"]["coverage"] for r in ok]),
        "mean_consistency": mean([r["extraction"]["consistency"] for r in ok]),
        "mean_research_score": mean(
            [r["research"]["_mean_score"] for r in ok if "research" in r]
        ),
    }


def _print_table(reports: List[Dict]) -> None:
    print(f"\n{'Ticker':7} {'Company':26} {'Cov':>4} {'Consist':>7} {'Sanity':>6} {'Yrs':>3} {'Research':>8}")
    print("-" * 70)
    for r in reports:
        if not r.get("ok"):
            print(f"{r['ticker']:7} {'(failed)':26} {r['error'][:40]}")
            continue
        e = r["extraction"]
        research = f"{r['research']['_mean_score']:.2f}/5" if "research" in r else "—"
        sanity = "pass" if e["sanity_pass"] else ("fail" if e["sanity_pass"] is False else "—")
        consist = f"{e['consistency']*100:.0f}%" if e["consistency"] is not None else "—"
        print(
            f"{r['ticker']:7} {r['company'][:26]:26} {e['coverage']*100:>3.0f}% "
            f"{consist:>7} {sanity:>6} {e['history_years']:>3} {research:>8}"
        )


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    from ..config import load_env

    load_env()  # pick up EDINET/provider keys from .env

    ap = argparse.ArgumentParser(description="Research benchmark across companies.")
    ap.add_argument("tickers", nargs="*", default=DEFAULT_TICKERS, help="TSE tickers (default: semi names)")
    ap.add_argument("--no-judge", action="store_true", help="Skip the LLM research-quality judge")
    ap.add_argument("--offline-memos", action="store_true", help="Benchmark template memos instead of LLM memos")
    ap.add_argument("--output", default="data/output/benchmark_report.json", help="Where to write the JSON report")
    args = ap.parse_args()

    tickers = args.tickers or DEFAULT_TICKERS
    judge = False if args.no_judge else None
    use_llm = False if args.offline_memos else None

    if not llm.llm_available() and judge is None:
        print("note: no ANTHROPIC_API_KEY/OPENAI_API_KEY — running extraction-only (no judge).", file=sys.stderr)

    reports = run_benchmark(
        tickers, use_llm=use_llm, judge=judge,
        on_progress=lambda t: print(f"benchmarking {t}…", file=sys.stderr),
    )
    _print_table(reports)
    agg = aggregate(reports)
    print("\nAggregate:", json.dumps(agg, indent=2))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"reports": reports, "aggregate": agg}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written: {out}", file=sys.stderr)
