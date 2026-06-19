"""Peer-comparison artifacts (MVP2 Track A).

A PeerComparison aligns the latest-year metrics across a set of companies and
ranks them per metric. Every value comes from the per-company XBRL extraction,
so the comparison stays traceable.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

# Metric metadata: order of display, label, unit, and ranking direction.
# direction: "desc" = higher is rank 1, "asc" = lower is rank 1, None = no rank.
METRIC_META = [
    ("revenue", "Revenue", "JPY", "desc"),
    ("revenue_growth", "Revenue YoY", "%", "desc"),
    ("operating_margin", "Operating margin", "%", "desc"),
    ("net_margin", "Net margin", "%", "desc"),
    ("roe", "ROE", "%", "desc"),
    ("per", "P/E (PER)", "x", "asc"),
    ("eps", "EPS", "JPY/share", "desc"),
    ("payout_ratio", "Payout ratio", "%", None),
]
METRIC_ORDER = [m[0] for m in METRIC_META]
METRIC_LABEL = {m[0]: m[1] for m in METRIC_META}
METRIC_UNIT = {m[0]: m[2] for m in METRIC_META}
METRIC_DIRECTION = {m[0]: m[3] for m in METRIC_META}


class PeerMetric(BaseModel):
    value: float
    unit: str
    rank: Optional[int] = None  # 1 = best per the metric's direction


class PeerRow(BaseModel):
    ticker: str
    company: str
    fiscal_year: str
    data_kind: str = "OFFICIAL"
    metrics: Dict[str, PeerMetric] = Field(default_factory=dict)

    def get(self, key: str) -> Optional[PeerMetric]:
        return self.metrics.get(key)


class PeerComparison(BaseModel):
    sector: str
    as_of: str = ""
    metric_order: List[str] = Field(default_factory=lambda: list(METRIC_ORDER))
    rows: List[PeerRow] = Field(default_factory=list)
    fiscal_year_warning: str = ""  # set when peers don't share a fiscal year-end


def assign_ranks(comparison: PeerComparison) -> None:
    """Populate each PeerMetric.rank within its metric, per METRIC_DIRECTION."""
    for key in comparison.metric_order:
        direction = METRIC_DIRECTION.get(key)
        if direction is None:
            continue
        scored = [(r.metrics[key].value, r) for r in comparison.rows if key in r.metrics]
        if not scored:
            continue
        scored.sort(key=lambda t: t[0], reverse=(direction == "desc"))
        for i, (_value, row) in enumerate(scored, start=1):
            row.metrics[key].rank = i
