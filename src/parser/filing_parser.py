"""Filing section retrieval (MVP Step 3).

Reads narrative iXBRL text-block elements from the filing and strips them to
plain text. Like the XBRL parser, sections are matched by element local-name
against candidate EDINET element names — deterministic, no LLM.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Dict, List, Optional

from ..models.filing import FilingDocument, FilingSection, FilingSections

# Section -> candidate iXBRL text-block element local-names (priority order).
SECTION_CANDIDATES: Dict[str, List[str]] = {
    "management_discussion": [
        "ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock",
        "BusinessResultsOfGroupTextBlock",
        "ManagementDiscussionAndAnalysisTextBlock",
        "OverviewOfOperatingResultsTextBlock",
    ],
    "business_risks": [
        "BusinessRisksTextBlock",
        "RisksRelatingToBusinessTextBlock",
    ],
    "future_outlook": [
        "BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock",
        "BusinessPolicyBusinessEnvironmentAndIssuesToBeAddressedTextBlock",
        "OutlookOfBusinessTextBlock",
        "ManagementPolicyTextBlock",
    ],
}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _prefixed(tag: str) -> str:
    if "}" not in tag:
        return tag
    uri, local = tag[1:].split("}", 1)
    seg = uri.rstrip("/").split("/")[-1]
    return f"{seg or 'ns'}:{local}"


class _TextExtractor(HTMLParser):
    """Collapse HTML to readable plain text, treating block tags as breaks."""

    _BLOCK = {"p", "br", "li", "div", "tr", "table", "ul", "ol", "h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCK:
            self._parts.append("\n")
        if tag == "li":
            self._parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        return "\n".join(ln for ln in lines if ln).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html or "")
    return parser.text()


class FilingParser:
    def __init__(self, document: FilingDocument):
        self.document = document
        self.root = ET.parse(document.xbrl_path).getroot()

    def extract(self) -> FilingSections:
        # element local-name -> (section, priority)
        element_index: Dict[str, tuple] = {}
        for section, names in SECTION_CANDIDATES.items():
            for i, name in enumerate(names):
                element_index.setdefault(name, (section, i))

        best: Dict[str, tuple] = {}  # section -> (priority, FilingSection)
        for el in self.root.iter():
            local = _localname(el.tag)
            if local not in element_index:
                continue
            section, priority = element_index[local]
            raw = "".join(el.itertext())
            text = html_to_text(raw)
            if not text:
                continue
            if section in best and best[section][0] <= priority:
                continue
            best[section] = (
                priority,
                FilingSection(
                    name=section,
                    source_element=_prefixed(el.tag),
                    text=text,
                ),
            )

        return FilingSections(
            management_discussion=best.get("management_discussion", (0, None))[1],
            business_risks=best.get("business_risks", (0, None))[1],
            future_outlook=best.get("future_outlook", (0, None))[1],
        )
