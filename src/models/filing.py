"""Filing-level artifacts: the downloaded document (Step 1) and its extracted
textual sections (Step 3)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FilingDocument(BaseModel):
    """A retrieved EDINET filing (MVP Step 1).

    Points at on-disk artifacts rather than holding bytes, so the extracted
    source data stays alongside generated outputs for reproducibility.
    """

    ticker: str
    company_name: str
    company_name_jp: str = ""
    edinet_code: str = ""
    doc_id: str
    form_type: str
    fiscal_year: str
    submitted_date: str = ""

    # "edinet-live" when fetched from the EDINET API, "fixture" when loaded
    # from a bundled sample. Surfaced in the memo for transparency.
    source: str = "fixture"
    # "SAMPLE" for synthetic illustrative data, "OFFICIAL" for live EDINET data.
    data_kind: str = "SAMPLE"

    xbrl_path: str
    note: str = ""


class FilingSection(BaseModel):
    name: str
    # XBRL/iXBRL element the narrative was read from, e.g.
    # "jpcrp_cor:BusinessRisksTextBlock".
    source_element: str
    text: str


class FilingSections(BaseModel):
    """Narrative sections extracted from the filing (MVP Step 3)."""

    management_discussion: Optional[FilingSection] = None
    business_risks: Optional[FilingSection] = None
    future_outlook: Optional[FilingSection] = None

    def present(self) -> dict:
        out = {}
        for name in ("management_discussion", "business_risks", "future_outlook"):
            section = getattr(self, name)
            if section is not None:
                out[name] = section
        return out
