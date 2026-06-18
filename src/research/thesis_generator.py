"""Investment thesis generation (MVP Step 4, part 2): bull and bear cases.

LLM mode synthesizes balanced theses with Claude; offline mode builds grounded
theses from the extracted financials, operating margin, growth, and the filing's
outlook and risk sections.
"""
from __future__ import annotations

import re
from typing import Dict, List

from . import llm
from .context import format_pct

_THESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "bull_thesis": {"type": "string"},
        "bear_thesis": {"type": "string"},
    },
    "required": ["bull_thesis", "bear_thesis"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are an equity research analyst. From the structured financials and "
    "filing excerpts provided, write a balanced bull thesis and bear thesis for "
    "the company. Ground every claim in the provided data or the filing's own "
    "outlook/risk language. Do not invent figures or make a buy/sell "
    "recommendation — these are analytical arguments, not advice."
)


class ThesisGenerator:
    def __init__(self, use_llm=None):
        self.use_llm = llm.llm_available() if use_llm is None else use_llm

    def generate(self, ctx: Dict) -> Dict:
        if self.use_llm:
            try:
                return self._generate_llm(ctx)
            except Exception:
                return self._generate_offline(ctx)
        return self._generate_offline(ctx)

    # ------------------------------------------------------------------- LLM
    def _generate_llm(self, ctx: Dict) -> Dict:
        from .context import context_as_prompt_block

        user = (
            context_as_prompt_block(ctx)
            + "\n\nProduce a bull_thesis (one focused paragraph) and a bear_thesis "
            "(one focused paragraph). Each should reference specific figures and the "
            "filing's outlook/risk language."
        )
        out = llm.complete_json(_SYSTEM, user, _THESIS_SCHEMA)
        return {"bull_thesis": out["bull_thesis"], "bear_thesis": out["bear_thesis"]}

    # --------------------------------------------------------------- offline
    def _generate_offline(self, ctx: Dict) -> Dict:
        g = ctx["growth"]
        margin = ctx["operating_margin"]
        outlook = ctx["sections"].get("future_outlook", "")
        risks = ctx["sections"].get("business_risks", "")

        bull_parts: List[str] = []
        if outlook:
            bull_parts.append(_first_sentences(outlook, 2))
        if margin is not None:
            bull_parts.append(
                f"The company sustained an operating margin of {margin * 100:.1f}%, "
                "indicating pricing power and cost discipline."
            )
        equity = _row(ctx, "equity")
        if equity:
            bull_parts.append(
                f"A solid balance sheet (net assets {equity['value_str']}) supports "
                "continued R&D investment and shareholder returns."
            )
        if not bull_parts:
            bull_parts.append(
                "Structured financials indicate an established, profitable franchise."
            )
        bull = " ".join(bull_parts)

        bear_parts: List[str] = []
        decl = []
        for key, label in (("revenue", "revenue"), ("operating_income", "operating income"), ("net_income", "net income")):
            pct = g.get(key)
            if pct is not None and pct < 0:
                decl.append(f"{label} {format_pct(pct)}")
        if decl:
            bear_parts.append(
                "Year-over-year declines (" + ", ".join(decl) + ") underscore the "
                "cyclicality of the business."
            )
        first_risk = _first_bullet(risks)
        if first_risk:
            bear_parts.append("The filing's own risk factors flag: " + first_risk)
        if not bear_parts:
            bear_parts.append(
                "Cyclical demand and the risk factors disclosed in the filing could "
                "pressure results."
            )
        bear = " ".join(bear_parts)

        return {"bull_thesis": bull, "bear_thesis": bear}


def _row(ctx: Dict, key: str):
    for row in ctx["metric_rows"]:
        if row["key"] == key:
            return row
    return None


def _first_sentences(text: str, n: int) -> str:
    flat = " ".join(text.split())
    parts = re.split(r"(?<=[.。])\s+", flat)
    return " ".join(parts[:n]).strip()


def _first_bullet(text: str) -> str:
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("- ") and len(s) > 4:
            return s[2:].strip()
    return _first_sentences(text, 1) if text else ""
