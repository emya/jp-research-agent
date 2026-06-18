"""Offline tests for the MVP pipeline (stdlib unittest — no pytest needed).

Run: .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.edinet.client import EDINETClient
from src.models.financial_metrics import compute_growth
from src.parser.filing_parser import FilingParser, html_to_text
from src.parser.xbrl_parser import XBRLParser
from src.pipeline import run
from src.research.context import build_context
from src.research.summarizer import Summarizer
from src.research.thesis_generator import ThesisGenerator

TICKER = "8035"


class FixtureMixin(unittest.TestCase):
    def setUp(self):
        self.client = EDINETClient()  # no key -> fixture mode
        self.filing = self.client.fetch_filing(TICKER)


class TestEdinetClient(FixtureMixin):
    def test_loads_sample_filing(self):
        self.assertEqual(self.filing.ticker, TICKER)
        self.assertEqual(self.filing.source, "fixture")
        self.assertEqual(self.filing.data_kind, "SAMPLE")
        self.assertTrue(Path(self.filing.xbrl_path).exists())

    def test_unknown_ticker_raises(self):
        from src.edinet.client import EDINETError

        with self.assertRaises(EDINETError):
            self.client.fetch_filing("0000")


class TestXBRLParser(FixtureMixin):
    def test_extracts_five_metrics_for_current_period(self):
        periods = XBRLParser(self.filing).extract_periods()
        self.assertIn("current", periods)
        self.assertIn("prior", periods)
        cur = periods["current"]
        for key in ("revenue", "operating_income", "net_income", "assets", "equity"):
            self.assertIsNotNone(cur.get(key), f"missing {key}")

    def test_values_and_provenance(self):
        cur = XBRLParser(self.filing).extract_periods()["current"]
        self.assertEqual(cur.revenue.value, 1830899000000.0)
        self.assertEqual(cur.revenue.source_element, "jppfs_cor:NetSales")
        self.assertEqual(cur.revenue.context, "CurrentYearDuration")
        self.assertEqual(cur.assets.context, "CurrentYearInstant")

    def test_yoy_growth_is_negative_this_cycle(self):
        periods = XBRLParser(self.filing).extract_periods()
        g = compute_growth(periods["current"], periods["prior"])
        self.assertLess(g["revenue"], 0)
        # 1,830,899 vs 2,209,025 -> about -17.1%
        self.assertAlmostEqual(g["revenue"], -0.1712, places=3)


class TestFilingParser(FixtureMixin):
    def test_extracts_three_sections(self):
        sections = FilingParser(self.filing).extract()
        present = sections.present()
        self.assertIn("management_discussion", present)
        self.assertIn("business_risks", present)
        self.assertIn("future_outlook", present)
        self.assertIn("cyclicality", present["business_risks"].text.lower())

    def test_html_to_text_strips_markup_and_keeps_bullets(self):
        out = html_to_text("<ul><li>One risk</li><li>Two risk</li></ul>")
        self.assertIn("- One risk", out)
        self.assertNotIn("<li>", out)


class TestMemoGeneration(FixtureMixin):
    def test_offline_memo_has_all_fields_and_is_traceable(self):
        periods = XBRLParser(self.filing).extract_periods()
        sections = FilingParser(self.filing).extract()
        ctx = build_context(self.filing, periods["current"], periods.get("prior"), sections)

        summary = Summarizer(use_llm=False).summarize(ctx)
        theses = ThesisGenerator(use_llm=False).generate(ctx)

        self.assertTrue(summary["executive_summary"])
        self.assertGreaterEqual(len(summary["financial_highlights"]), 5)
        self.assertGreaterEqual(len(summary["key_risks"]), 3)
        self.assertTrue(theses["bull_thesis"])
        self.assertTrue(theses["bear_thesis"])
        # Grounding: a real figure appears in the highlights.
        self.assertTrue(any("¥" in h for h in summary["financial_highlights"]))


class TestProviderSelection(unittest.TestCase):
    def setUp(self):
        import os

        self._saved = {
            k: os.environ.get(k)
            for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER")
        }
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        import os

        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _set(self, **kv):
        import os

        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER"):
            os.environ.pop(k, None)
        os.environ.update(kv)

    def test_selection_matrix(self):
        from src.research import llm

        self._set()
        self.assertIsNone(llm.active_provider())
        self.assertFalse(llm.llm_available())

        self._set(ANTHROPIC_API_KEY="a")
        self.assertEqual(llm.active_provider(), "anthropic")

        self._set(OPENAI_API_KEY="o")
        self.assertEqual(llm.active_provider(), "openai")

        # Both set: Anthropic preferred by default.
        self._set(ANTHROPIC_API_KEY="a", OPENAI_API_KEY="o")
        self.assertEqual(llm.active_provider(), "anthropic")

        # LLM_PROVIDER forces the choice.
        self._set(ANTHROPIC_API_KEY="a", OPENAI_API_KEY="o", LLM_PROVIDER="openai")
        self.assertEqual(llm.active_provider(), "openai")

        # Forcing a provider whose key is absent -> none.
        self._set(OPENAI_API_KEY="o", LLM_PROVIDER="anthropic")
        self.assertIsNone(llm.active_provider())


class TestEndToEnd(unittest.TestCase):
    def test_run_writes_artifacts_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(TICKER, use_llm=False, output_root=Path(tmp))
            memo = result["memo"]
            self.assertEqual(memo.generation_mode, "offline-template")
            self.assertEqual(memo.ticker, TICKER)
            self.assertTrue(memo.sources)
            for path in result["artifacts"].values():
                self.assertTrue(Path(path).exists(), path)
            md = Path(result["artifacts"]["research_memo_md"]).read_text(encoding="utf-8")
            self.assertIn("Bull Thesis", md)
            self.assertIn("Bear Thesis", md)


if __name__ == "__main__":
    unittest.main()
