"""Merge several per-filing FinancialHistory objects into one long history
(MVP2 Track B).

Each annual report carries a 5-year summary; chaining consecutive reports
extends coverage. Overlapping years are reconciled with a **restatement
policy**: prefer the value from the most recent filing (it reflects the latest
accounting), and flag material differences. A heuristic also flags likely
per-share split boundaries (BPS/DPS), which EDINET does not always restate.
"""
from __future__ import annotations

from typing import Dict, List

from ..models.financial_history import (
    FinancialHistory,
    HistoryDiscrepancy,
    MetricSeries,
)

_REL_TOL = 0.01  # >1% difference on an overlapping year = restatement
_SPLIT_METRICS = {"bps", "dps"}  # smooth per-share series; a big jump implies a split
_SPLIT_RATIO = 2.5


def _recency(h: FinancialHistory) -> int:
    years = [p.year for s in h.series.values() for p in s.points]
    return max(years) if years else -1


def merge_histories(histories: List[FinancialHistory]) -> FinancialHistory:
    """Merge into one history, newest filing winning on overlapping years."""
    histories = [h for h in histories if h.has_data()]
    if not histories:
        return FinancialHistory(company="", ticker="", n_filings=0)

    histories = sorted(histories, key=_recency, reverse=True)  # newest first
    company, ticker = histories[0].company, histories[0].ticker
    discrepancies: List[HistoryDiscrepancy] = []

    merged: Dict[str, Dict[int, object]] = {}  # metric -> year -> HistoryPoint
    units: Dict[str, str] = {}
    labels: Dict[str, str] = {}

    for h in histories:  # newest first — first to set a year wins
        for mkey, s in h.series.items():
            units.setdefault(mkey, s.unit)
            labels.setdefault(mkey, s.label)
            year_map = merged.setdefault(mkey, {})
            for p in s.points:
                if p.year in year_map:
                    existing = year_map[p.year]
                    if existing.value != 0 and abs(existing.value - p.value) / abs(existing.value) > _REL_TOL:
                        discrepancies.append(HistoryDiscrepancy(
                            metric=mkey, year=p.year, kind="restatement",
                            note=(f"{labels[mkey]} {p.year} differs across filings "
                                  f"({existing.value:g} vs {p.value:g}); using most-recent filing"),
                            value_newer=existing.value, value_older=p.value,
                        ))
                    # keep the newer value already in place
                else:
                    year_map[p.year] = p

    series: Dict[str, MetricSeries] = {}
    for mkey, year_map in merged.items():
        pts = sorted(year_map.values(), key=lambda p: p.year)
        series[mkey] = MetricSeries(metric=mkey, label=labels[mkey], unit=units[mkey], points=pts)

    # Heuristic: flag likely per-share split boundaries (BPS/DPS shouldn't jump).
    for mkey in _SPLIT_METRICS:
        s = series.get(mkey)
        if not s or len(s.points) < 2:
            continue
        for a, b in zip(s.points, s.points[1:]):
            if a.value > 0 and b.value > 0:
                ratio = b.value / a.value
                if ratio >= _SPLIT_RATIO or ratio <= 1 / _SPLIT_RATIO:
                    discrepancies.append(HistoryDiscrepancy(
                        metric=mkey, year=b.year, kind="possible_split",
                        note=(f"{s.label} jumps {a.year}->{b.year} (×{ratio:.1f}); "
                              "possible stock split / non-split-adjusted figure across filings"),
                        value_newer=b.value, value_older=a.value,
                    ))

    return FinancialHistory(
        company=company, ticker=ticker, series=series,
        n_filings=len(histories), discrepancies=discrepancies,
    )
