"""XBRL financial extraction (MVP Step 2).

Core principle (CLAUDE.md): prefer structured financial data over LLM
extraction. This reads the five core metrics directly from the XBRL instance —
no LLM involved.

Parsing uses the stdlib XML parser and matches facts by their element *local
name* against a prioritized list of candidate EDINET element names, so it works
across JGAAP and IFRS filers without a full taxonomy engine.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from ..models.filing import FilingDocument
from ..models.financial_metrics import (
    FinancialMetrics,
    MetricValue,
)

_XBRLI = "http://www.xbrl.org/2003/instance"

# Candidate element local-names per metric, in priority order. First match per
# (metric, context) wins. Covers common JGAAP (jppfs/jpcrp) and IFRS variants.
CANDIDATES: Dict[str, List[str]] = {
    "revenue": [
        "NetSales",
        "Revenue",
        "RevenueIFRS",
        "NetSalesSummaryOfBusinessResults",
        "OperatingRevenue1",
        "RevenuesUS",
    ],
    "operating_income": [
        "OperatingIncome",
        "OperatingProfitLossIFRS",
        "OperatingIncomeLoss",
        "ProfitLossFromOperatingActivitiesIFRS",
    ],
    "net_income": [
        "ProfitLossAttributableToOwnersOfParent",
        "ProfitLossAttributableToOwnersOfParentIFRS",
        "ProfitLoss",
        "NetIncomeLoss",
    ],
    "assets": [
        "Assets",
        "TotalAssetsIFRS",
        "AssetsSummaryOfBusinessResults",
    ],
    "equity": [
        "NetAssets",
        "EquityAttributableToOwnersOfParent",
        "EquityAttributableToOwnersOfParentIFRS",
        "Equity",
        "ShareholdersEquity",
        "NetAssetsSummaryOfBusinessResults",
    ],
}

# Which contexts feed which period bucket. Durations carry flows; instants carry
# stocks. We merge the duration + instant of the same fiscal year into one record.
_CURRENT_CONTEXTS = {"CurrentYearDuration", "CurrentYearInstant"}
_PRIOR_CONTEXTS = {"PriorYearDuration", "PriorYearInstant"}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _prefixed(tag: str) -> str:
    """Reconstruct a readable 'prefix:LocalName' for provenance from a
    Clark-notation tag, using the taxonomy segment of the namespace URI."""
    if "}" not in tag:
        return tag
    uri, local = tag[1:].split("}", 1)
    seg = uri.rstrip("/").split("/")[-1]  # e.g. jppfs_cor
    prefix = seg if seg else "ns"
    return f"{prefix}:{local}"


class XBRLParser:
    def __init__(self, document: FilingDocument):
        self.document = document
        self.tree = ET.parse(document.xbrl_path)
        self.root = self.tree.getroot()
        self._contexts = self._read_contexts()

    def _read_contexts(self) -> Dict[str, Dict[str, str]]:
        """Map context id -> {end, instant} dates for fiscal-year labelling."""
        contexts: Dict[str, Dict[str, str]] = {}
        for ctx in self.root.findall(f"{{{_XBRLI}}}context"):
            cid = ctx.get("id")
            if not cid:
                continue
            info: Dict[str, str] = {}
            period = ctx.find(f"{{{_XBRLI}}}period")
            if period is not None:
                for child in period:
                    info[_localname(child.tag)] = (child.text or "").strip()
            contexts[cid] = info
        return contexts

    def _fiscal_year_for(self, context_ids) -> str:
        for cid in context_ids:
            info = self._contexts.get(cid, {})
            for key in ("endDate", "instant"):
                if info.get(key):
                    return info[key]
        return ""

    def extract_periods(self) -> Dict[str, FinancialMetrics]:
        """Return {'current': FinancialMetrics, 'prior': FinancialMetrics}.

        A period is only included when at least one metric was found for it.
        """
        # Collect best candidate per (period_bucket, metric).
        # found[bucket][metric] = MetricValue
        found: Dict[str, Dict[str, MetricValue]] = {"current": {}, "prior": {}}
        # Track candidate priority index to keep the highest-priority match.
        rank: Dict[Tuple[str, str], int] = {}

        # Reverse index: local element name -> (metric, priority)
        element_index: Dict[str, Tuple[str, int]] = {}
        for metric, names in CANDIDATES.items():
            for i, name in enumerate(names):
                # Don't overwrite a higher-priority mapping for the same name.
                if name not in element_index:
                    element_index[name] = (metric, i)

        for el in self.root.iter():
            local = _localname(el.tag)
            if local not in element_index:
                continue
            ctx_ref = el.get("contextRef")
            if ctx_ref in _CURRENT_CONTEXTS:
                bucket = "current"
            elif ctx_ref in _PRIOR_CONTEXTS:
                bucket = "prior"
            else:
                continue
            text = (el.text or "").strip()
            if not text:
                continue
            try:
                value = float(text)
            except ValueError:
                continue

            metric, priority = element_index[local]
            key = (bucket, metric)
            if key in rank and rank[key] <= priority:
                continue  # already have a higher- or equal-priority match
            rank[key] = priority
            found[bucket][metric] = MetricValue(
                value=value,
                unit="JPY",
                source_element=_prefixed(el.tag),
                context=ctx_ref,
            )

        periods: Dict[str, FinancialMetrics] = {}
        bucket_contexts = {
            "current": ["CurrentYearInstant", "CurrentYearDuration"],
            "prior": ["PriorYearInstant", "PriorYearDuration"],
        }
        for bucket, metrics in found.items():
            if not metrics:
                continue
            fy = self._fiscal_year_for(bucket_contexts[bucket])
            periods[bucket] = FinancialMetrics(
                fiscal_year=fy or self.document.fiscal_year,
                period_label=f"{bucket.capitalize()} period (FY ending {fy})" if fy else bucket,
                source_document=self.document.xbrl_path,
                **metrics,
            )
        return periods

    def extract(self) -> Optional[FinancialMetrics]:
        """Convenience: the current-period FinancialMetrics (MVP Step 2 output)."""
        return self.extract_periods().get("current")
