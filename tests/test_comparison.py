"""Offline tests for MVP2 Track A — peer comparison.

Run: .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.charts_compare import build_comparison_html
from src.comparison import build_comparison, comparison_memo
from src.models.comparison import PeerComparison, PeerMetric, PeerRow, assign_ranks

TICKER = "8035"


class TestRanking(unittest.TestCase):
    def test_assign_ranks_direction(self):
        rows = [
            PeerRow(ticker="A", company="A", fiscal_year="2025-03-31", metrics={
                "per": PeerMetric(value=30.0, unit="x"),
                "roe": PeerMetric(value=10.0, unit="%"),
            }),
            PeerRow(ticker="B", company="B", fiscal_year="2025-03-31", metrics={
                "per": PeerMetric(value=15.0, unit="x"),
                "roe": PeerMetric(value=25.0, unit="%"),
            }),
        ]
        comp = PeerComparison(sector="x", rows=rows)
        assign_ranks(comp)
        # per is "asc" -> lower PER ranks #1 (B)
        self.assertEqual(rows[1].metrics["per"].rank, 1)
        self.assertEqual(rows[0].metrics["per"].rank, 2)
        # roe is "desc" -> higher ROE ranks #1 (B)
        self.assertEqual(rows[1].metrics["roe"].rank, 1)


class TestComparisonOffline(unittest.TestCase):
    def setUp(self):
        # Force offline / no-LLM for deterministic results.
        self._saved = {k: os.environ.get(k) for k in
                       ("EDINET_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_build_comparison_from_fixture(self):
        comp, histories, errors = build_comparison([TICKER], sector="test")
        self.assertEqual(errors, [])
        self.assertEqual(len(comp.rows), 1)
        row = comp.rows[0]
        # core comparison metrics present from the fixture
        for k in ("revenue", "revenue_growth", "operating_margin", "roe", "per", "eps"):
            self.assertIn(k, row.metrics, f"missing {k}")
        # single company -> rank 1 on ranked metrics
        self.assertEqual(row.metrics["per"].rank, 1)
        self.assertIn(TICKER, histories)

    def test_offline_memo(self):
        comp, _h, _e = build_comparison([TICKER], sector="test")
        md, mode = comparison_memo(comp)
        self.assertEqual(mode, "offline-template")
        self.assertIn("Relative positioning", md)

    def test_dashboard_html(self):
        comp, histories, _e = build_comparison([TICKER], sector="test")
        with tempfile.TemporaryDirectory() as tmp:
            out = build_comparison_html(comp, histories, Path(tmp) / "c.html")
            self.assertIsNotNone(out)
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("Plotly", html)
            self.assertIn("Peer Comparison", html)


if __name__ == "__main__":
    unittest.main()
