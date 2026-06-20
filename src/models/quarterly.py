"""Quarterly financials (from J-Quants) for recent-trend tracking."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class QuarterPoint(BaseModel):
    label: str               # e.g. "FY2025 Q3"
    period_type: str         # "1Q" | "2Q" | "3Q" | "FY"
    fiscal_year_end: str
    period_end: str
    disclosed_date: str = ""

    # As reported by J-Quants — cumulative (year-to-date) within the fiscal year.
    revenue: Optional[float] = None
    operating_profit: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None

    # Derived single-quarter (3-month) figures, where consecutive periods allow.
    revenue_q: Optional[float] = None
    operating_profit_q: Optional[float] = None


class QuarterlySeries(BaseModel):
    ticker: str
    company: str = ""
    points: List[QuarterPoint] = Field(default_factory=list)

    def has_data(self) -> bool:
        return len(self.points) > 0
