"""Management / board profile from the filing's 役員の状況 section (in-lane —
data is in the EDINET filing we already download)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Officer(BaseModel):
    name: str               # as filed (Japanese)
    name_en: str = ""       # romanized, from the officer's XBRL member id
    title: str = ""         # as filed (Japanese)
    title_en: str = ""      # English (term-mapped)
    date_of_birth: str = ""
    age: Optional[int] = None
    term_of_office: str = ""
    shares_held: Optional[float] = None
    career_summary: str = ""
    is_representative: bool = False  # 代表取締役 / Representative Director
    bio: str = ""                    # optional LLM-polished one-paragraph bio


class ManagementProfile(BaseModel):
    company: str
    ticker: str
    fiscal_year: str = ""
    officers: List[Officer] = Field(default_factory=list)

    def representatives(self) -> List[Officer]:
        return [o for o in self.officers if o.is_representative]

    def has_data(self) -> bool:
        return len(self.officers) > 0
