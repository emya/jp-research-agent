"""Officer / management extraction from the 役員の状況 section (MVP2 follow-up).

Each officer is a member of `DirectorsAndOtherOfficersAxis`; their name, title,
birth date, career, term, and shareholding are tagged as values against that
member's context. We collect the *current* officers (not the AGM "Proposal"
candidates) and flag representative directors.
"""
from __future__ import annotations

import datetime as _dt
import re
import xml.etree.ElementTree as ET
from typing import Dict, Optional

from ..models.filing import FilingDocument
from ..models.management import ManagementProfile, Officer

_XBRLI = "http://www.xbrl.org/2003/instance"
_OFFICER_AXIS = "DirectorsAndOtherOfficersAxis"

# Current-officer field elements (the non-"Proposal" variants).
_FIELD_MAP = {
    "NameInformationAboutDirectorsAndCorporateAuditors": "name",
    "OfficialTitleOrPositionInformationAboutDirectorsAndCorporateAuditors": "title",
    "DateOfBirthInformationAboutDirectorsAndCorporateAuditors": "date_of_birth",
    "TermOfOfficeInformationAboutDirectorsAndCorporateAuditors": "term_of_office",
    "NumberOfSharesHeldOrdinarySharesInformationAboutDirectorsAndCorporateAuditors": "shares_held",
    "CareerSummaryInformationAboutDirectorsAndCorporateAuditorsTextBlock": "career_summary",
}
_REP_MARKERS = ("代表取締役", "Representative Director")

# Japanese officer-title vocabulary -> English. Ordered longest-first so compound
# titles match before their parts (代表取締役社長 before 代表取締役 / 社長).
_TITLE_TERMS = [
    ("代表取締役会長", "Representative Director & Chairman"),
    ("代表取締役社長", "Representative Director & President"),
    ("代表取締役副社長", "Representative Director & Vice President"),
    ("代表執行役社長", "Representative Executive Officer & President"),
    ("代表取締役", "Representative Director"),
    ("取締役会長", "Chairman"),
    ("副社長執行役員", "Executive Vice President"),
    ("専務執行役員", "Senior Managing Executive Officer"),
    ("常務執行役員", "Managing Executive Officer"),
    ("専務取締役", "Senior Managing Director"),
    ("常務取締役", "Managing Director"),
    ("社外取締役", "Outside Director"),
    ("常勤監査役", "Standing Corporate Auditor"),
    ("社外監査役", "Outside Corporate Auditor"),
    ("執行役員", "Executive Officer"),
    ("コーポレートオフィサー", "Corporate Officer"),
    ("副社長", "Vice President"),
    ("社長", "President"),
    ("専務", "Senior Managing Director"),
    ("常務", "Managing Director"),
    ("会長", "Chairman"),
    ("取締役", "Director"),
    ("監査役", "Corporate Auditor"),
    ("議長", "Chairperson"),
]


def _translate_title(jp: str) -> str:
    """Greedy longest-match translation of a Japanese officer title to English."""
    if not jp:
        return ""
    out: list = []
    i, s = 0, jp
    while i < len(s):
        if s[i] in "　 、,／/・\t":
            i += 1
            continue
        for term, en in _TITLE_TERMS:
            if s.startswith(term, i):
                out.append(en)
                i += len(term)
                break
        else:  # no Japanese term matched — keep ASCII runs (CEO/COO/CFO) verbatim
            m = re.match(r"[A-Za-z0-9&.]+", s[i:])
            if m:
                out.append(m.group(0))
                i += len(m.group(0))
            else:
                i += 1
    dedup: list = []
    for t in out:
        if not dedup or dedup[-1] != t:
            dedup.append(t)
    return ", ".join(dedup)


def _name_from_member(member: str) -> str:
    """Romanized name from the officer's XBRL member id (e.g. KawaiToshikiMember
    -> 'Kawai Toshiki'). Empty if the member is a generic placeholder."""
    local = re.sub(r"Member$", "", member.split(":")[-1])
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local).strip()
    if not name or re.search(r"\d", name) or name.lower() in ("officer", "director", "unnamed"):
        return ""
    return name


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _clean(text: str) -> str:
    # EDINET pads Japanese names with full-width spaces.
    return re.sub(r"[　\s]+", " ", (text or "").strip()).strip()


def _age_from(dob: str) -> Optional[int]:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", dob or "")
    if not m:
        return None
    born = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    today = _dt.date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _strip_html(text: str) -> str:
    from .filing_parser import html_to_text
    return html_to_text(text) if "<" in (text or "") else _clean(text)


def extract_officers(document: FilingDocument) -> ManagementProfile:
    root = ET.parse(document.xbrl_path).getroot()

    # context id -> officer member QName
    ctx_member: Dict[str, str] = {}
    for ctx in root.findall(f"{{{_XBRLI}}}context"):
        cid = ctx.get("id") or ""
        for m in ctx.iter():
            if _localname(m.tag) == "explicitMember" and m.get("dimension", "").endswith(_OFFICER_AXIS):
                ctx_member[cid] = (m.text or "").strip()

    by_member: Dict[str, Dict[str, str]] = {}
    for el in root.iter():
        field = _FIELD_MAP.get(_localname(el.tag))
        if not field:
            continue
        cref = el.get("contextRef")
        member = ctx_member.get(cref)
        if not member:
            continue
        text = "".join(el.itertext()).strip() if field == "career_summary" else (el.text or "").strip()
        if text:
            by_member.setdefault(member, {})[field] = text

    officers = []
    for member, fields in by_member.items():
        name = _clean(fields.get("name", ""))
        if not name:
            continue
        title = _clean(fields.get("title", ""))
        shares = None
        if fields.get("shares_held"):
            try:
                shares = float(fields["shares_held"])
            except ValueError:
                shares = None
        officers.append(Officer(
            name=name,
            name_en=_name_from_member(member),
            title=title,
            title_en=_translate_title(title),
            date_of_birth=_clean(fields.get("date_of_birth", "")),
            age=_age_from(fields.get("date_of_birth", "")),
            term_of_office=_clean(fields.get("term_of_office", "")),
            shares_held=shares,
            career_summary=_strip_html(fields.get("career_summary", "")),
            is_representative=any(mk in title for mk in _REP_MARKERS),
        ))

    # Representatives first, then by shareholding.
    officers.sort(key=lambda o: (not o.is_representative, -(o.shares_held or 0)))

    return ManagementProfile(
        company=document.company_name or document.ticker,
        ticker=document.ticker,
        fiscal_year=document.fiscal_year,
        officers=officers,
    )
