"""Offline tests for MVP2 Track B — long-history merge."""
from __future__ import annotations

import os
import unittest

from src.longhistory import build_long_history
from src.models.financial_history import FinancialHistory, HistoryPoint, MetricSeries
from src.parser.history_merger import merge_histories


def _series(metric, unit, pairs):
    pts = [HistoryPoint(fiscal_year=f"{y}-03-31", year=y, value=v, source_element="x") for y, v in pairs]
    return MetricSeries(metric=metric, label=metric, unit=unit, points=pts)


def _history(company, ticker, **series):
    return FinancialHistory(company=company, ticker=ticker, series=series)


class TestMerge(unittest.TestCase):
    def test_union_and_newer_wins_with_restatement_flag(self):
        newer = _history("Co", "1234", revenue=_series("revenue", "JPY", [
            (2021, 1000), (2022, 1100), (2023, 1200), (2024, 1300), (2025, 1400)]))
        older = _history("Co", "1234", revenue=_series("revenue", "JPY", [
            (2018, 700), (2019, 800), (2020, 900), (2021, 1000), (2022, 1190)]))  # 2022 restated

        merged = merge_histories([older, newer])  # unordered input
        self.assertEqual(merged.n_filings, 2)
        rev = merged.series["revenue"]
        self.assertEqual(rev.years, list(range(2018, 2026)))  # 8-year union
        # 2022 uses the newer filing's value (1100), not the older (1190)
        v2022 = next(p.value for p in rev.points if p.year == 2022)
        self.assertEqual(v2022, 1100)
        # restatement flagged for 2022
        flags = [d for d in merged.discrepancies if d.kind == "restatement" and d.year == 2022]
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].value_newer, 1100)
        self.assertEqual(flags[0].value_older, 1190)

    def test_no_flag_when_overlap_agrees(self):
        a = _history("Co", "1", revenue=_series("revenue", "JPY", [(2023, 100), (2024, 110)]))
        b = _history("Co", "1", revenue=_series("revenue", "JPY", [(2022, 90), (2023, 100)]))
        merged = merge_histories([a, b])
        self.assertEqual([p.year for p in merged.series["revenue"].points], [2022, 2023, 2024])
        self.assertEqual(merged.discrepancies, [])

    def test_possible_split_flag_on_bps(self):
        newer = _history("Co", "1", bps=_series("bps", "JPY/share", [(2023, 3000), (2024, 3300), (2025, 3600)]))
        older = _history("Co", "1", bps=_series("bps", "JPY/share", [(2021, 8500), (2022, 9000), (2023, 3000)]))
        merged = merge_histories([older, newer])
        splits = [d for d in merged.discrepancies if d.kind == "possible_split"]
        self.assertTrue(splits, "expected a possible_split flag at the 2022->2023 boundary")

    def test_build_long_history_offline_single_filing(self):
        # No EDINET key -> fixture path -> single filing -> still a valid history.
        saved = os.environ.pop("EDINET_API_KEY", None)
        try:
            history, filings = build_long_history("8035", max_reports=3)
        finally:
            if saved is not None:
                os.environ["EDINET_API_KEY"] = saved
        self.assertEqual(history.n_filings, 1)
        self.assertTrue(history.has_data())
        self.assertEqual(len(filings), 1)
        self.assertEqual(history.series["revenue"].years, [2020, 2021, 2022, 2023, 2024])


if __name__ == "__main__":
    unittest.main()
