"""Builds a grounded fact pack from structured metrics + filing sections.

Both the offline templates and the LLM prompts consume this, so every memo —
regardless of generation mode — is anchored to the same source-derived facts.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..models.filing import FilingDocument, FilingSections
from ..models.financial_history import FinancialHistory
from ..models.financial_metrics import (
    FLOW_METRICS,
    METRIC_KEYS,
    FinancialMetrics,
    compute_growth,
)

# Latest-year valuation/per-share metrics to surface in the memo, in order.
_VALUATION_ORDER = [
    ("per", "P/E ratio (PER)"),
    ("eps", "EPS (basic)"),
    ("bps", "BPS"),
    ("roe", "ROE"),
    ("payout_ratio", "Payout ratio"),
    ("dps", "Dividend / share"),
]


def _latest_valuation(history: Optional[FinancialHistory]):
    """Return [(label, value_str)] for the most recent year of each valuation
    metric available in the history."""
    out = []
    if history is None:
        return out
    for key, label in _VALUATION_ORDER:
        ser = history.series.get(key)
        if not ser or not ser.points:
            continue
        p = ser.points[-1]
        if ser.unit == "x":
            vs = f"{p.value:.1f}×"
        elif ser.unit == "%":
            vs = f"{p.value:.1f}%"
        elif ser.unit == "JPY/share":
            vs = f"¥{p.value:,.0f}"
        else:
            vs = f"{p.value:,.0f}"
        out.append((f"{label} (FY{p.year})", vs))
    return out

_LABELS = {
    "revenue": "Revenue",
    "operating_income": "Operating income",
    "net_income": "Net income",
    "assets": "Total assets",
    "equity": "Net assets / equity",
}

_SECTION_LABELS = {
    "management_discussion": "Management Discussion & Analysis",
    "business_risks": "Business Risks",
    "future_outlook": "Future Outlook / Business Policy",
}


def format_yen(value: float) -> str:
    a = abs(value)
    if a >= 1e12:
        return f"¥{value / 1e12:.2f}T"
    if a >= 1e9:
        return f"¥{value / 1e9:.1f}B"
    if a >= 1e6:
        return f"¥{value / 1e6:.1f}M"
    return f"¥{value:,.0f}"


def format_pct(fraction: Optional[float]) -> Optional[str]:
    if fraction is None:
        return None
    return f"{fraction * 100:+.1f}%"


def operating_margin(metrics: FinancialMetrics) -> Optional[float]:
    rev = metrics.get("revenue")
    oi = metrics.get("operating_income")
    if rev is None or oi is None or rev.value == 0:
        return None
    return oi.value / rev.value


def build_context(
    filing: FilingDocument,
    current: FinancialMetrics,
    prior: Optional[FinancialMetrics],
    sections: FilingSections,
    history: Optional[FinancialHistory] = None,
) -> Dict:
    growth = compute_growth(current, prior)

    metric_rows: List[Dict] = []
    highlights: List[str] = []
    for key in METRIC_KEYS:
        mv = current.get(key)
        if mv is None:
            continue
        yoy = format_pct(growth.get(key)) if key in FLOW_METRICS else None
        row = {
            "key": key,
            "label": _LABELS[key],
            "value": mv.value,
            "value_str": format_yen(mv.value),
            "yoy": yoy,
            "source_element": mv.source_element,
            "context": mv.context,
        }
        metric_rows.append(row)
        if yoy:
            highlights.append(f"{_LABELS[key]}: {row['value_str']} ({yoy} YoY)")
        else:
            highlights.append(f"{_LABELS[key]}: {row['value_str']}")

    margin = operating_margin(current)
    if margin is not None:
        highlights.append(f"Operating margin: {margin * 100:.1f}%")

    valuation = _latest_valuation(history)
    for label, value_str in valuation:
        highlights.append(f"{label}: {value_str}")

    section_text: Dict[str, str] = {}
    for name, section in sections.present().items():
        section_text[name] = section.text

    return {
        "company_name": filing.company_name,
        "company_name_jp": filing.company_name_jp,
        "ticker": filing.ticker,
        "fiscal_year": current.fiscal_year or filing.fiscal_year,
        "data_kind": filing.data_kind,
        "source_label": filing.source,
        "metric_rows": metric_rows,
        "highlights": highlights,
        "valuation": valuation,
        "growth": growth,
        "operating_margin": margin,
        "sections": section_text,
        "section_labels": _SECTION_LABELS,
    }


def context_as_prompt_block(ctx: Dict, section_char_limit: int = 4000) -> str:
    """Render the fact pack as a compact text block for an LLM prompt."""
    lines: List[str] = []
    lines.append(f"Company: {ctx['company_name']} ({ctx['company_name_jp']})")
    lines.append(f"Ticker (TSE): {ctx['ticker']}")
    lines.append(f"Fiscal year: {ctx['fiscal_year']}")
    lines.append("")
    lines.append("STRUCTURED FINANCIALS (extracted from XBRL — authoritative):")
    for row in ctx["metric_rows"]:
        yoy = f", YoY {row['yoy']}" if row["yoy"] else ""
        lines.append(
            f"  - {row['label']}: {row['value_str']}{yoy} "
            f"[{row['source_element']} @ {row['context']}]"
        )
    if ctx["operating_margin"] is not None:
        lines.append(f"  - Operating margin: {ctx['operating_margin'] * 100:.1f}%")
    if ctx.get("valuation"):
        lines.append("")
        lines.append("VALUATION & PER-SHARE (latest FY, from the XBRL 5-year summary — authoritative):")
        for label, value_str in ctx["valuation"]:
            lines.append(f"  - {label}: {value_str}")
    lines.append("")
    for name, text in ctx["sections"].items():
        label = ctx["section_labels"].get(name, name)
        excerpt = text[:section_char_limit]
        lines.append(f"FILING SECTION — {label}:")
        lines.append(excerpt)
        lines.append("")
    return "\n".join(lines).strip()
