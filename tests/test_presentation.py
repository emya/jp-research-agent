"""Offline tests for MVP2 Track B M2.6 — IR presentation analysis scaffolding.

The actual multimodal LLM call is live-only; these cover the non-LLM pieces.
"""
from __future__ import annotations

import os
import unittest

from src.models.presentation import PresentationAnalysis
from src.research import llm


class TestPresentationScaffolding(unittest.TestCase):
    def test_pdf_analysis_requires_anthropic(self):
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            self.assertFalse(llm.anthropic_available())
            with self.assertRaises(RuntimeError):
                llm.analyze_pdf_json("sys", "user", b"%PDF-1.4 fake", {"type": "object"})
        finally:
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved

    def test_markdown_render(self):
        a = PresentationAnalysis(
            pdf_path="IR/8035.pdf", ticker="8035",
            summary="Strong year driven by AI demand.",
            key_messages=["Record revenue", "Margin expansion"],
            guidance_and_targets=["¥3T revenue by FY2027"],
            highlighted_risks=["Memory cycle volatility"],
            notable_figures=["Revenue +33% YoY"],
            consistency_with_filing="Deck figures match the filing.",
            generation_mode="llm:anthropic:claude-opus-4-8",
        )
        md = a.to_markdown()
        self.assertIn("IR Presentation Analysis", md)
        self.assertIn("Guidance & Medium-term Targets", md)
        self.assertIn("¥3T revenue by FY2027", md)
        self.assertIn("Consistency with the Official Filing", md)


if __name__ == "__main__":
    unittest.main()
