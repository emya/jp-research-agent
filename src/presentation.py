"""IR / earnings-presentation analysis (MVP2 Track B, M2.6).

    python -m src.presentation IR/8035.pdf --ticker 8035

Reads an IR-deck PDF with Claude's native PDF support and produces a structured
summary, cross-referenced against the XBRL-extracted financials. Requires
ANTHROPIC_API_KEY (clean PDF input is a Claude feature).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from .edinet.client import EDINETClient, EDINETError
from .models.presentation import PresentationAnalysis
from .pipeline import PipelineError, run
from .research import llm
from .research.context import build_context, context_as_prompt_block

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "output" / "presentation"

_SYSTEM = (
    "You are an equity analyst reading a company's investor-relations / earnings "
    "presentation (a PDF, possibly in Japanese). Summarize it for an investor: the "
    "core summary, key messages, forward guidance and medium-term targets, risks "
    "management emphasizes, and notable figures or chart takeaways. Be faithful to "
    "the deck — do not invent numbers. When official filing financials are "
    "provided, compare the deck's headline figures to them and report alignment or "
    "discrepancies. This is summarization, not investment advice — no buy/sell calls."
)

_FIELDS = ["summary", "key_messages", "guidance_and_targets", "highlighted_risks",
           "notable_figures", "consistency_with_filing"]
_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_messages": {"type": "array", "items": {"type": "string"}},
        "guidance_and_targets": {"type": "array", "items": {"type": "string"}},
        "highlighted_risks": {"type": "array", "items": {"type": "string"}},
        "notable_figures": {"type": "array", "items": {"type": "string"}},
        "consistency_with_filing": {"type": "string"},
    },
    "required": _FIELDS,
    "additionalProperties": False,
}


def _filing_facts(ticker: str, client: Optional[EDINETClient]) -> str:
    """XBRL-extracted facts block for cross-referencing the deck (best-effort)."""
    try:
        result = run(ticker, client=client, use_llm=False, write=False, make_charts=False)
    except (EDINETError, PipelineError):
        return ""
    ctx = build_context(
        result["filing"], result["periods"]["current"], result["periods"].get("prior"),
        result["sections"], result["history"],
    )
    return context_as_prompt_block(ctx)


def analyze_presentation(
    pdf_path: str, ticker: Optional[str] = None, client: Optional[EDINETClient] = None
) -> PresentationAnalysis:
    pdf_bytes = Path(pdf_path).read_bytes()

    user = "Analyze the attached investor-relations / earnings presentation PDF."
    facts = _filing_facts(ticker, client) if ticker else ""
    if facts:
        user += (
            "\n\nCROSS-REFERENCE — official XBRL-extracted financials (authoritative):\n"
            + facts
            + "\n\nIn 'consistency_with_filing', state whether the deck's headline "
            "figures align with these official numbers, and flag any discrepancy."
        )
    else:
        user += " No filing financials were provided; set 'consistency_with_filing' to 'Not assessed'."

    out: Dict = llm.analyze_pdf_json(_SYSTEM, user, pdf_bytes, _SCHEMA)
    return PresentationAnalysis(
        pdf_path=str(pdf_path),
        ticker=ticker or "",
        generation_mode=f"llm:{llm.active_model_label()}",
        **out,
    )


if __name__ == "__main__":
    import argparse
    import sys

    from .config import load_env

    load_env()

    ap = argparse.ArgumentParser(description="Analyze an IR / earnings-presentation PDF.")
    ap.add_argument("pdf", help="Path to the IR-deck PDF")
    ap.add_argument("--ticker", default=None, help="Cross-reference against this company's filing")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    args = ap.parse_args()

    if not llm.anthropic_available():
        print("error: PDF analysis requires ANTHROPIC_API_KEY (Claude native PDF support).", file=sys.stderr)
        raise SystemExit(1)
    if not Path(args.pdf).exists():
        print(f"error: file not found: {args.pdf}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Analyzing {args.pdf} with {llm.active_model_label()}…", file=sys.stderr)
    analysis = analyze_presentation(args.pdf, ticker=args.ticker)

    key = args.ticker or Path(args.pdf).stem
    out_dir = Path(args.output) / key
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "presentation_analysis.json").write_text(
        json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_dir / "presentation_analysis.md"
    md_path.write_text(analysis.to_markdown(), encoding="utf-8")

    print(f"\nArtifacts: {out_dir}", file=sys.stderr)
    print(analysis.to_markdown())
