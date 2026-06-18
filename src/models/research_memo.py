"""The final investor-oriented research memo (MVP Step 4)."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ResearchMemo(BaseModel):
    company_name: str
    ticker: str
    fiscal_year: str

    executive_summary: str
    financial_highlights: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    bull_thesis: str
    bear_thesis: str

    # "llm:claude-opus-4-8" or "offline-template" — makes the provenance of the
    # reasoning explicit to the reader.
    generation_mode: str
    # Source artifacts every conclusion can be traced back to.
    sources: List[str] = Field(default_factory=list)
    # Honest caveat about the data behind the memo (e.g. SAMPLE vs OFFICIAL).
    data_caveat: str = ""
    # Path to the interactive financial-history charts (if generated).
    charts_path: str = ""

    def to_markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"# {self.company_name} ({self.ticker})")
        lines.append("")
        lines.append(f"_Fiscal year: {self.fiscal_year}_")
        lines.append("")
        if self.data_caveat:
            lines.append(f"> ⚠️ {self.data_caveat}")
            lines.append("")
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(self.executive_summary)
        lines.append("")
        lines.append("## Financial Highlights")
        lines.append("")
        for h in self.financial_highlights:
            lines.append(f"- {h}")
        lines.append("")
        lines.append("## Key Risks")
        lines.append("")
        for r in self.key_risks:
            lines.append(f"- {r}")
        lines.append("")
        lines.append("## Bull Thesis")
        lines.append("")
        lines.append(self.bull_thesis)
        lines.append("")
        lines.append("## Bear Thesis")
        lines.append("")
        lines.append(self.bear_thesis)
        lines.append("")
        if self.charts_path:
            lines.append("## Financial History")
            lines.append("")
            lines.append(f"Interactive 5-year charts (revenue, earnings, assets, debt, ratios): "
                         f"[{self.charts_path}]({self.charts_path})")
            lines.append("")
        lines.append("---")
        lines.append(f"_Generation mode: {self.generation_mode}_")
        if self.sources:
            lines.append("")
            lines.append("**Sources**")
            for s in self.sources:
                lines.append(f"- {s}")
        return "\n".join(lines)
