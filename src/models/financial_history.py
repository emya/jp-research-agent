"""Multi-year financial history extracted from the filing's 5-year Summary of
Business Results (主要な経営指標等の推移).

Like the single-period metrics, every point keeps its source element + context
for traceability. Derived series (debt, net margin) record their formula.
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    fiscal_year: str  # period end date or year label, e.g. "2025-03-31"
    year: int
    value: float
    source_element: str
    context: str = ""


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

    def has_data(self) -> bool:
        return any(s.points for s in self.series.values())
