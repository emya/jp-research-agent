"""Multi-year financial history extracted from the filing's 5-year Summary of
Business Results (主要な経営指標等の推移).

Like the single-period metrics, every point keeps its source element + context
for traceability. Derived series (debt, net margin) record their formula.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    fiscal_year: str  # period end date or year label, e.g. "2025-03-31"
    year: int
    value: float
    source_element: str
    context: str = ""


class HistoryDiscrepancy(BaseModel):
    """A flag raised while merging multiple filings into one long history."""

    metric: str
    year: int
    kind: str  # "restatement" | "possible_split"
    note: str
    value_newer: Optional[float] = None
    value_older: Optional[float] = None


class MetricSeries(BaseModel):
    metric: str
    label: str
    unit: str = "JPY"  # "JPY" or "%"
    points: List[HistoryPoint] = Field(default_factory=list)

    @property
    def years(self) -> List[int]:
        return [p.year for p in self.points]

    @property
    def values(self) -> List[float]:
        return [p.value for p in self.points]


class FinancialHistory(BaseModel):
    company: str
    ticker: str
    series: Dict[str, MetricSeries] = Field(default_factory=dict)
    # Populated when merged from multiple filings (MVP2 Track B).
    n_filings: int = 1
    discrepancies: List[HistoryDiscrepancy] = Field(default_factory=list)

    def has_data(self) -> bool:
        return any(s.points for s in self.series.values())

    def year_span(self) -> int:
        years = [p.year for s in self.series.values() for p in s.points]
        return (max(years) - min(years) + 1) if years else 0
