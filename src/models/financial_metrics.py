"""Typed financial artifacts.

These models are the structured output of XBRL extraction (MVP Step 2). Every
numeric value carries provenance (the XBRL element it came from and the context
it was reported in) so any downstream conclusion is traceable to the filing.
"""
from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field

# Canonical metric keys used throughout the pipeline.
METRIC_KEYS = ("revenue", "operating_income", "net_income", "assets", "equity")

# Flow metrics are period-over-period comparable (income statement); stock
# metrics are point-in-time (balance sheet). YoY growth is only meaningful for
# flows.
FLOW_METRICS = ("revenue", "operating_income", "net_income")
STOCK_METRICS = ("assets", "equity")


class MetricValue(BaseModel):
    """A single extracted figure with full provenance."""

    value: float
    unit: str = "JPY"
    # The XBRL element this came from, e.g. "jppfs_cor:NetSales".
    source_element: str
    # The XBRL context, e.g. "CurrentYearDuration".
    context: str


class FinancialMetrics(BaseModel):
    """The five core metrics for a single reporting period (MVP Step 2)."""

    fiscal_year: str
    period_label: str = ""

    revenue: Optional[MetricValue] = None
    operating_income: Optional[MetricValue] = None
    net_income: Optional[MetricValue] = None
    assets: Optional[MetricValue] = None
    equity: Optional[MetricValue] = None
    # Capex (cash flow statement) — extra single-period field, not one of the
    # five core METRIC_KEYS (so coverage scoring is unaffected).
    capex: Optional[MetricValue] = None

    source_document: str = Field(
        default="",
        description="Path to the XBRL instance these values were extracted from.",
    )

    def get(self, key: str) -> Optional[MetricValue]:
        return getattr(self, key, None)


def compute_growth(
    current: FinancialMetrics, prior: Optional[FinancialMetrics]
) -> Dict[str, Optional[float]]:
    """Year-over-year growth (as a fraction) for flow metrics.

    Returns None for a metric when either period is missing it or the prior
    value is zero. Deterministic and source-grounded — no estimation.
    """
    growth: Dict[str, Optional[float]] = {}
    for key in FLOW_METRICS:
        cur = current.get(key)
        if prior is None:
            growth[key] = None
            continue
        pri = prior.get(key)
        if cur is None or pri is None or pri.value == 0:
            growth[key] = None
        else:
            growth[key] = (cur.value - pri.value) / abs(pri.value)
    return growth
