"""End-to-end MVP pipeline: EDINET -> XBRL metrics -> sections -> research memo.

Wires the four MVP steps together and persists every artifact so generated
memos sit alongside the extracted source data (reproducibility / traceability).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .charts import build_charts_html
from .edinet.client import EDINETClient
from .models.filing import FilingDocument, FilingSections
from .models.financial_history import FinancialHistory
from .models.financial_metrics import FinancialMetrics
from .models.research_memo import ResearchMemo
from .parser.filing_parser import FilingParser
from .parser.xbrl_parser import XBRLParser
from .research import llm
from .research.context import build_context
from .research.summarizer import Summarizer
from .research.thesis_generator import ThesisGenerator

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "output"


class PipelineError(RuntimeError):
    pass


def _memo_sources(
    filing: FilingDocument, current: FinancialMetrics, sections: FilingSections
) -> List[str]:
    sources = [
        f"EDINET filing: {filing.form_type} (doc {filing.doc_id}, {filing.source})",
        f"XBRL instance: {filing.xbrl_path}",
    ]
    elements = []
    for key in ("revenue", "operating_income", "net_income", "assets", "equity"):
        mv = current.get(key)
        if mv is not None:
            elements.append(f"{key}={mv.source_element}@{mv.context}")
    if elements:
        sources.append("Extracted XBRL facts: " + ", ".join(elements))
    for name, section in sections.present().items():
        sources.append(f"Section '{name}': {section.source_element}")
    return sources


def _data_caveat(filing: FilingDocument) -> str:
    if filing.data_kind == "SAMPLE":
        return (
            "Generated from a BUNDLED SAMPLE filing with illustrative figures — "
            "NOT an official EDINET disclosure. Set EDINET_API_KEY to run against "
            "live EDINET data."
        )
    return "Financials extracted from the official EDINET XBRL filing."


def _output_dir(output_root: Path, filing: FilingDocument, fiscal_year: str) -> Path:
    safe_fy = (fiscal_year or filing.fiscal_year or "unknown").replace("/", "-")
    return Path(output_root) / filing.ticker / safe_fy


def run(
    ticker: str,
    client: Optional[EDINETClient] = None,
    use_llm: Optional[bool] = None,
    output_root: Optional[Path] = None,
    write: bool = True,
    make_charts: bool = True,
) -> Dict:
    client = client or EDINETClient()

    # Step 1 — ingest filing.
    filing = client.fetch_filing(ticker)

    # Step 2 — structured financial extraction (current/prior + 5-year history).
    parser = XBRLParser(filing)
    periods = parser.extract_periods()
    current = periods.get("current")
    if current is None:
        raise PipelineError(
            f"No current-period financials could be extracted from {filing.xbrl_path}."
        )
    prior = periods.get("prior")
    history = parser.extract_history()

    # Step 3 — textual sections.
    sections = FilingParser(filing).extract()

    # Step 4 — research memo.
    ctx = build_context(filing, current, prior, sections, history)
    summarizer = Summarizer(use_llm=use_llm)
    thesis_gen = ThesisGenerator(use_llm=use_llm)
    summary = summarizer.summarize(ctx)
    theses = thesis_gen.generate(ctx)
    mode = f"llm:{llm.active_model_label()}" if summarizer.use_llm else "offline-template"

    # Charts are an artifact on disk, so they're only produced when writing.
    out_dir = None
    charts_path = ""
    if write:
        out_dir = _output_dir(output_root or _DEFAULT_OUTPUT, filing, current.fiscal_year)
        out_dir.mkdir(parents=True, exist_ok=True)
        if make_charts:
            charts_path = build_charts_html(history, filing, out_dir / "charts.html") or ""

    memo = ResearchMemo(
        company_name=filing.company_name,
        ticker=filing.ticker,
        fiscal_year=current.fiscal_year or filing.fiscal_year,
        executive_summary=summary["executive_summary"],
        financial_highlights=summary["financial_highlights"],
        key_risks=summary["key_risks"],
        bull_thesis=theses["bull_thesis"],
        bear_thesis=theses["bear_thesis"],
        generation_mode=mode,
        sources=_memo_sources(filing, current, sections),
        data_caveat=_data_caveat(filing),
        charts_path=charts_path,
    )

    result = {
        "filing": filing,
        "periods": periods,
        "history": history,
        "sections": sections,
        "memo": memo,
        "artifacts": {},
    }

    if write:
        result["artifacts"] = _persist(
            out_dir, filing, periods, history, sections, memo, charts_path
        )
    return result


def _persist(
    out_dir: Path,
    filing: FilingDocument,
    periods: Dict[str, FinancialMetrics],
    history: FinancialHistory,
    sections: FilingSections,
    memo: ResearchMemo,
    charts_path: str,
) -> Dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(name: str, payload) -> str:
        path = out_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(path)

    artifacts = {
        "filing": dump("filing.json", filing.model_dump()),
        "financial_metrics": dump(
            "financial_metrics.json",
            {k: v.model_dump() for k, v in periods.items()},
        ),
        "financial_history": dump("financial_history.json", history.model_dump()),
        "filing_sections": dump("filing_sections.json", sections.model_dump()),
        "research_memo_json": dump("research_memo.json", memo.model_dump()),
    }
    md_path = out_dir / "research_memo.md"
    md_path.write_text(memo.to_markdown(), encoding="utf-8")
    artifacts["research_memo_md"] = str(md_path)
    if charts_path:
        artifacts["charts_html"] = charts_path
    return artifacts
