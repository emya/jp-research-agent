"""Offline tests for quarterly (J-Quants) parsing — no network."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.jquants.client import JQuantsClient, JQuantsError
from src.quarterly import build_chart_html, parse_statements

# A sample V2 /fins/summary response: 4 periods of one fiscal year (cumulative),
# plus a stale 3Q revision and a forecast-only row that should be ignored.
_ROWS = [
    {"CurPerType": "1Q", "DiscDate": "2024-08-08", "CurFYEn": "2025-03-31",
     "CurPerEn": "2024-06-30", "Sales": "480000000000", "OP": "110000000000",
     "NP": "90000000000", "EPS": "190.0"},
    {"CurPerType": "2Q", "DiscDate": "2024-11-07", "CurFYEn": "2025-03-31",
     "CurPerEn": "2024-09-30", "Sales": "1000000000000", "OP": "240000000000",
     "NP": "190000000000", "EPS": "400.0"},
    {"CurPerType": "3Q", "DiscDate": "2025-02-12", "CurFYEn": "2025-03-31",
     "CurPerEn": "2024-12-31", "Sales": "1600000000000", "OP": "400000000000",
     "NP": "320000000000", "EPS": "680.0"},
    # stale 3Q revision (earlier disclosure, different value) — must be dropped
    {"CurPerType": "3Q", "DiscDate": "2025-01-05", "CurFYEn": "2025-03-31",
     "CurPerEn": "2024-12-31", "Sales": "1500000000000", "OP": "390000000000",
     "NP": "300000000000", "EPS": "600.0"},
    {"CurPerType": "FY", "DiscDate": "2025-05-09", "CurFYEn": "2025-03-31",
     "CurPerEn": "2025-03-31", "Sales": "2431000000000", "OP": "697000000000",
     "NP": "544000000000", "EPS": "1182.0"},
    # forecast-only row, no Sales — must be ignored
    {"CurPerType": "FY", "DiscDate": "2025-05-09", "CurFYEn": "2026-03-31",
     "CurPerEn": "", "Sales": "", "OP": ""},
]


class TestQuarterlyParsing(unittest.TestCase):
    def test_periods_ordered_and_forecast_dropped(self):
        s = parse_statements("8035", _ROWS)
        self.assertEqual([p.period_type for p in s.points], ["1Q", "2Q", "3Q", "FY"])
        self.assertEqual([p.label for p in s.points][0], "FY2025 1Q")

    def test_latest_revision_wins(self):
        s = parse_statements("8035", _ROWS)
        q3 = next(p for p in s.points if p.period_type == "3Q")
        self.assertEqual(q3.revenue, 1.6e12)  # the later-disclosed value, not 1.5e12

    def test_single_quarter_derivation(self):
        s = parse_statements("8035", _ROWS)
        by = {p.period_type: p for p in s.points}
        self.assertEqual(by["1Q"].revenue_q, 480e9)             # 1Q == cumulative
        self.assertEqual(by["2Q"].revenue_q, 1000e9 - 480e9)    # 520B
        self.assertEqual(by["3Q"].revenue_q, 1600e9 - 1000e9)   # 600B
        self.assertEqual(by["FY"].revenue_q, 2431e9 - 1600e9)   # 831B (Q4)
        self.assertEqual(by["FY"].operating_profit_q, 697e9 - 400e9)

    def test_max_quarters(self):
        s = parse_statements("8035", _ROWS, max_quarters=2)
        self.assertEqual(len(s.points), 2)
        self.assertEqual([p.period_type for p in s.points], ["3Q", "FY"])

    def test_chart_html(self):
        s = parse_statements("8035", _ROWS)
        with tempfile.TemporaryDirectory() as tmp:
            out = build_chart_html(s, Path(tmp) / "q.html")
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("Plotly", html)
            self.assertIn("Quarterly trend", html)


class TestClientConfig(unittest.TestCase):
    def test_unconfigured_client_reports_and_raises(self):
        import os
        saved = os.environ.pop("JQUANTS_API_KEY", None)
        try:
            c = JQuantsClient()
            self.assertFalse(c.configured)
            with self.assertRaises(JQuantsError):
                c.fetch_summary("8035")
        finally:
            if saved is not None:
                os.environ["JQUANTS_API_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
