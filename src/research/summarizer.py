"""Summarization (MVP Step 4, part 1): executive summary, financial highlights,
and key risks.

LLM mode (when ANTHROPIC_API_KEY is set) uses Claude to synthesize; offline mode
produces deterministic, source-grounded output so the pipeline always runs.
"""
from __future__ import annotations

import re
from typing import Dict, List

from . import llm
from .context import format_pct

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "financial_highlights": {"type": "array", "items": {"type": "string"}},
        "key_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["executive_summary", "financial_highlights", "key_risks"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are an equity research analyst summarizing a Japanese company's annual "
    "securities report for an investor. Use ONLY the structured financials and "
    "filing excerpts provided — do not invent figures. The structured financials "
    "are authoritative; quote them rather than re-deriving them. Be concise, "
    "specific, and balanced. Explain what changed and why where the filing says so. "
    "Write your ENTIRE response in English: the filing excerpts are in Japanese, so "
    "translate and paraphrase them — never output Japanese text."
)


class Summarizer:
    def __init__(self, use_llm=None):
        self.use_llm = llm.llm_available() if use_llm is None else use_llm

    def summarize(self, ctx: Dict) -> Dict:
        if self.use_llm:
            try:
                return self._summarize_llm(ctx)
            except Exception:
                # Fall back rather than fail the pipeline.
                return self._summarize_offline(ctx)
        return self._summarize_offline(ctx)

    # ------------------------------------------------------------------- LLM
    def _summarize_llm(self, ctx: Dict) -> Dict:
        from .context import context_as_prompt_block

        user = (
            context_as_prompt_block(ctx)
            + "\n\nProduce: (1) executive_summary (3-5 sentences), "
            "(2) financial_highlights (4-6 bullet strings, each citing a figure), "
            "(3) key_risks (the most material risks from the filing, 3-6 bullets)."
        )
        out = llm.complete_json(_SYSTEM, user, _SUMMARY_SCHEMA)
        return {
            "executive_summary": out["executive_summary"],
            "financial_highlights": list(out["financial_highlights"]),
            "key_risks": list(out["key_risks"]),
        }

    # --------------------------------------------------------------- offline
    def _summarize_offline(self, ctx: Dict) -> Dict:
        company = ctx["company_name"]
        ticker = ctx["ticker"]
        fy = ctx["fiscal_year"]

        # Executive summary, grounded in the extracted figures + MD&A.
        clauses: List[str] = []
        g = ctx["growth"]
        rev = _row(ctx, "revenue")
        oi = _row(ctx, "operating_income")
        ni = _row(ctx, "net_income")
        if rev:
            clauses.append(f"revenue of {rev['value_str']} ({format_pct(g.get('revenue')) or 'n/a'} YoY)")
        if oi:
            clauses.append(f"operating income of {oi['value_str']} ({format_pct(g.get('operating_income')) or 'n/a'} YoY)")
        if ni:
            clauses.append(f"net income of {ni['value_str']} ({format_pct(g.get('net_income')) or 'n/a'} YoY)")
        figure_sentence = (
            f"{company} (TSE:{ticker}) reported "
            + ", ".join(clauses)
            + f" for the fiscal year ended {fy}."
        ) if clauses else f"{company} (TSE:{ticker}), fiscal year ended {fy}."

        summary = [figure_sentence]
        if ctx["operating_margin"] is not None:
            summary.append(f"Operating margin was {ctx['operating_margin'] * 100:.1f}%.")
        # Offline mode does not splice raw MD&A text (Japanese in real filings) into
        # the summary; the LLM path supplies the English narrative. We keep the
        # deterministic, figure-based sentences only.
        result_summary = " ".join(summary)

        # Key risks: prefer the bulleted structure of the risk section.
        risks = _bullets_or_sentences(ctx["sections"].get("business_risks", ""), limit=5)

        return {
            "executive_summary": result_summary,
            "financial_highlights": list(ctx["highlights"]),
            "key_risks": risks,
        }


def _row(ctx: Dict, key: str):
    for row in ctx["metric_rows"]:
        if row["key"] == key:
            return row
    return None


def _first_sentences(text: str, n: int) -> str:
    flat = " ".join(text.split())
    parts = re.split(r"(?<=[.。])\s+", flat)
    return " ".join(parts[:n]).strip()


def _bullets_or_sentences(text: str, limit: int) -> List[str]:
    if not text:
        return []
    bullets = [
        ln[2:].strip()
        for ln in text.splitlines()
        if ln.strip().startswith("- ") and len(ln.strip()) > 4
    ]
    if bullets:
        return bullets[:limit]
    flat = " ".join(text.split())
    parts = [p.strip() for p in re.split(r"(?<=[.。])\s+", flat) if len(p.strip()) > 20]
    return parts[:limit]
