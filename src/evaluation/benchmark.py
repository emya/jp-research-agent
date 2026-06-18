"""Evaluation harness (stretch goal).

Runs the extraction pipeline across multiple companies and reports how complete
the structured extraction was — a proxy for the "compare extracted metrics
against XBRL ground truth" metric in CLAUDE.md. Memo generation is skipped here
(write=False, use_llm=False) so the benchmark is fast and deterministic.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..edinet.client import EDINETClient, EDINETError
from ..models.financial_metrics import METRIC_KEYS
from ..pipeline import PipelineError, run


def extraction_coverage(ticker: str, client: Optional[EDINETClient] = None) -> Dict:
    """Return extraction coverage for one ticker (fraction of the 5 core
    metrics found in the current period)."""
    try:
        result = run(ticker, client=client, use_llm=False, write=False)
    except (EDINETError, PipelineError) as exc:
        return {"ticker": ticker, "ok": False, "error": str(exc)}

    current = result["periods"].get("current")
    found = [k for k in METRIC_KEYS if current and current.get(k) is not None]
    sections = result["sections"].present()
    return {
        "ticker": ticker,
        "ok": True,
        "company_name": result["filing"].company_name,
        "metrics_found": found,
        "metrics_coverage": len(found) / len(METRIC_KEYS),
        "sections_found": sorted(sections.keys()),
        "has_prior_period": "prior" in result["periods"],
    }


def run_benchmark(tickers: List[str], client: Optional[EDINETClient] = None) -> List[Dict]:
    return [extraction_coverage(t, client=client) for t in tickers]


if __name__ == "__main__":
    import json
    import sys

    tickers = sys.argv[1:] or ["8035"]
    print(json.dumps(run_benchmark(tickers), ensure_ascii=False, indent=2))
