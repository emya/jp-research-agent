"""Offline tests for MVP2 Track B M2.3 — cash flow + capex."""
from __future__ import annotations

import unittest

from src.edinet.client import EDINETClient
from src.parser.xbrl_parser import XBRLParser

TICKER = "8035"


class TestCashFlow(unittest.TestCase):
    def setUp(self):
        self.filing = EDINETClient().fetch_filing(TICKER)

    def test_cashflow_series_in_history(self):
        h = XBRLParser(self.filing).extract_history()
        for key in ("operating_cf", "investing_cf", "financing_cf", "cash"):
            self.assertIn(key, h.series, f"missing {key}")
            self.assertEqual(len(h.series[key].points), 5)
        # signs: operating positive, investing/financing negative (outflows)
        self.assertGreater(h.series["operating_cf"].points[-1].value, 0)
        self.assertLess(h.series["investing_cf"].points[-1].value, 0)

    def test_free_cash_flow_proxy(self):
        h = XBRLParser(self.filing).extract_history()
        self.assertIn("fcf", h.series)
        ocf = h.series["operating_cf"].points[-1].value
        icf = h.series["investing_cf"].points[-1].value
        self.assertAlmostEqual(h.series["fcf"].points[-1].value, ocf + icf, places=0)

    def test_capex_single_period(self):
        cur = XBRLParser(self.filing).extract_periods()["current"]
        self.assertIsNotNone(cur.get("capex"))
        self.assertEqual(cur.get("capex").source_element, "jppfs_cor:PurchaseOfPropertyPlantAndEquipmentInvCF")
        # capex is NOT one of the 5 coverage metrics
        from src.models.financial_metrics import METRIC_KEYS
        self.assertNotIn("capex", METRIC_KEYS)

    def test_benchmark_cash_flow_checks(self):
        # M2.5: the benchmark validates cash-flow coverage, capex, and the
        # Δcash ≈ operating+investing+financing reconciliation.
        from src.evaluation.benchmark import benchmark_company

        e = benchmark_company(TICKER, judge=False)["extraction"]
        self.assertEqual(e["cash_flow_coverage"], 1.0)
        self.assertTrue(e["capex_present"])
        rec = e["cash_flow_reconciliation"]
        self.assertIsNotNone(rec)
        self.assertTrue(rec["reconciles"], f"residual {rec['residual_pct']:.2%}")


if __name__ == "__main__":
    unittest.main()
