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
from ..models.financial_history import FinancialHistory, HistoryPoint, MetricSeries
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
        "NetSalesIFRS",
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
        "AssetsIFRS",
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
    # Capex (cash flow statement, investing section) — single-period only.
    "capex": [
        "PurchaseOfPropertyPlantAndEquipmentInvCF",
        "PaymentsForPurchaseOfPropertyPlantAndEquipmentIFRS",
        "PurchaseOfPropertyPlantAndEquipment",
    ],
}

# Which contexts feed which period bucket. Durations carry flows; instants carry
# stocks. We merge the duration + instant of the same fiscal year into one record.
_CURRENT_CONTEXTS = {"CurrentYearDuration", "CurrentYearInstant"}
# Real EDINET filings tag the prior-year comparative as Prior1Year*; some use
# PriorYear*. Accept both so YoY extraction works across filers.
_PRIOR_CONTEXTS = {
    "PriorYearDuration", "PriorYearInstant",
    "Prior1YearDuration", "Prior1YearInstant",
}

# Element local-names in the 5-year "Summary of Business Results"
# (主要な経営指標等の推移). These carry one fact per fiscal year, across
# CurrentYear / Prior1Year … Prior4Year contexts.
SUMMARY_CANDIDATES: Dict[str, List[str]] = {
    "revenue": [
        "NetSalesSummaryOfBusinessResults",
        "RevenueIFRSSummaryOfBusinessResults",
        "OperatingRevenue1SummaryOfBusinessResults",
        "NetSalesAndOperatingRevenue2SummaryOfBusinessResults",
        "RevenuesUSGAAPSummaryOfBusinessResults",
    ],
    "ordinary_income": [
        "OrdinaryIncomeLossSummaryOfBusinessResults",
        "ProfitLossBeforeTaxIFRSSummaryOfBusinessResults",
        "IncomeBeforeIncomeTaxesUSGAAPSummaryOfBusinessResults",
    ],
    "net_income": [
        "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
        "NetIncomeLossSummaryOfBusinessResults",
    ],
    "total_assets": [
        "TotalAssetsSummaryOfBusinessResults",
        "TotalAssetsIFRSSummaryOfBusinessResults",
    ],
    "net_assets": [
        "NetAssetsSummaryOfBusinessResults",
        "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
        "EquityIFRSSummaryOfBusinessResults",
    ],
    "equity_ratio": [
        "EquityToAssetRatioSummaryOfBusinessResults",
        "RatioOfOwnersEquityToGrossAssetsIFRSSummaryOfBusinessResults",
    ],
    # Per-share & valuation metrics (also in the 5-year summary).
    "eps": [
        "BasicEarningsLossPerShareSummaryOfBusinessResults",
        "BasicEarningsPerShareSummaryOfBusinessResults",
        "NetIncomeLossPerShareSummaryOfBusinessResults",
        "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
    ],
    "diluted_eps": [
        "DilutedEarningsPerShareSummaryOfBusinessResults",
        "DilutedEarningsLossPerShareSummaryOfBusinessResults",
        "DilutedEarningsLossPerShareIFRSSummaryOfBusinessResults",
    ],
    "bps": [
        "NetAssetsPerShareSummaryOfBusinessResults",
        "EquityToAssetsPerShareIFRSSummaryOfBusinessResults",
    ],
    "per": [
        "PriceEarningsRatioSummaryOfBusinessResults",
        "PriceEarningsRatioIFRSSummaryOfBusinessResults",
    ],
    "roe": [
        "RateOfReturnOnEquitySummaryOfBusinessResults",
        "RateOfReturnOnEquityIFRSSummaryOfBusinessResults",
    ],
    "payout_ratio": [
        "PayoutRatioSummaryOfBusinessResults",
        "PayoutRatioIFRSSummaryOfBusinessResults",
    ],
    "dps": [
        "DividendPaidPerShareSummaryOfBusinessResults",
        "DividendPerShareSummaryOfBusinessResults",
    ],
    # Cash flow (also in the 5-year summary).
    "operating_cf": ["NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults"],
    "investing_cf": [
        "NetCashProvidedByUsedInInvestingActivitiesSummaryOfBusinessResults",
        "NetCashProvidedByUsedInInvestmentActivitiesSummaryOfBusinessResults",
    ],
    "financing_cf": ["NetCashProvidedByUsedInFinancingActivitiesSummaryOfBusinessResults"],
    "cash": ["CashAndCashEquivalentsSummaryOfBusinessResults"],
}

SUMMARY_LABELS = {
    "revenue": "Revenue",
    "ordinary_income": "Ordinary income",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "net_assets": "Net assets",
    "equity_ratio": "Equity ratio",
    "debt": "Debt (total liabilities)",
    "net_margin": "Net margin",
    "eps": "EPS (basic)",
    "diluted_eps": "EPS (diluted)",
    "bps": "BPS (net assets/share)",
    "per": "P/E ratio (PER)",
    "roe": "ROE",
    "payout_ratio": "Payout ratio (parent)",
    "dps": "Dividend / share (parent)",
    "operating_cf": "Operating cash flow",
    "investing_cf": "Investing cash flow",
    "financing_cf": "Financing cash flow",
    "cash": "Cash & equivalents",
    "fcf": "Free cash flow (proxy)",
}

# Unit per metric: "JPY" (¥, large), "JPY/share" (¥ per share), "%", or "x" (ratio).
SUMMARY_UNITS = {
    "equity_ratio": "%", "net_margin": "%", "roe": "%", "payout_ratio": "%",
    "eps": "JPY/share", "diluted_eps": "JPY/share", "bps": "JPY/share", "dps": "JPY/share",
    "per": "x",
}

# Metrics EDINET reports as a fraction (0.30) that we normalize to a percent.
_FRACTION_TO_PCT = ("equity_ratio", "roe", "payout_ratio")


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
        """Map context id -> period dates + whether it carries dimension members.

        ``__members__`` is True when the context has explicit/typed dimension
        members (e.g. non-consolidated or per-segment); the consolidated 5-year
        series uses the member-free contexts.
        """
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
            has_members = any(
                _localname(d.tag) in ("explicitMember", "typedMember") for d in ctx.iter()
            )
            info["__members__"] = has_members  # type: ignore[assignment]
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
            "prior": ["Prior1YearInstant", "Prior1YearDuration", "PriorYearInstant", "PriorYearDuration"],
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

    def extract_history(self) -> FinancialHistory:
        """Extract the multi-year series from the Summary of Business Results.

        Uses member-free (consolidated, non-segment) contexts and keys facts by
        the fiscal year of their context's end/instant date. Adds derived series
        (debt = total assets - net assets; net margin) and normalizes the equity
        ratio to a percentage.
        """
        element_index: Dict[str, Tuple[str, int]] = {}
        for metric, names in SUMMARY_CANDIDATES.items():
            for i, name in enumerate(names):
                element_index.setdefault(name, (metric, i))

        # (metric, year) -> (rank, HistoryPoint), rank = (tier, candidate_priority).
        # tier 0 = consolidated (member-free); tier 1 = parent-only
        # (NonConsolidatedMember) — used as a fallback for metrics like dividend
        # and payout ratio that EDINET reports only at the parent level.
        best: Dict[Tuple[str, int], Tuple[Tuple[int, int], HistoryPoint]] = {}
        for el in self.root.iter():
            local = _localname(el.tag)
            if local not in element_index:
                continue
            ctx_ref = el.get("contextRef") or ""
            cinfo = self._contexts.get(ctx_ref, {})
            if not cinfo.get("__members__"):
                tier = 0
            elif ctx_ref.endswith("_NonConsolidatedMember"):
                tier = 1
            else:
                continue  # per-segment or other dimensional fact — skip
            date = cinfo.get("endDate") or cinfo.get("instant")
            if not date:
                continue
            try:
                year = int(date[:4])
            except ValueError:
                continue
            text = (el.text or "").strip()
            if not text:
                continue
            try:
                value = float(text)
            except ValueError:
                continue
            metric, priority = element_index[local]
            key = (metric, year)
            rank = (tier, priority)
            if key in best and best[key][0] <= rank:
                continue
            best[key] = (
                rank,
                HistoryPoint(
                    fiscal_year=date, year=year, value=value,
                    source_element=_prefixed(el.tag), context=ctx_ref,
                ),
            )

        by_metric: Dict[str, List[HistoryPoint]] = {}
        for (metric, _year), (_rank, point) in best.items():
            by_metric.setdefault(metric, []).append(point)

        series: Dict[str, MetricSeries] = {}
        for metric, points in by_metric.items():
            points.sort(key=lambda p: p.year)
            series[metric] = MetricSeries(
                metric=metric,
                label=SUMMARY_LABELS.get(metric, metric),
                unit=SUMMARY_UNITS.get(metric, "JPY"),
                points=points,
            )

        self._add_derived_series(series)

        return FinancialHistory(
            company=self.document.company_name or self.document.ticker,
            ticker=self.document.ticker,
            series=series,
        )

    @staticmethod
    def _add_derived_series(series: Dict[str, MetricSeries]) -> None:
        def by_year(name: str) -> Dict[int, HistoryPoint]:
            return {p.year: p for p in series[name].points} if name in series else {}

        assets = by_year("total_assets")
        equity = by_year("net_assets")
        debt_points = [
            HistoryPoint(
                fiscal_year=assets[y].fiscal_year,
                year=y,
                value=assets[y].value - equity[y].value,
                source_element="derived: total_assets - net_assets",
            )
            for y in sorted(set(assets) & set(equity))
        ]
        if debt_points:
            series["debt"] = MetricSeries(
                metric="debt", label=SUMMARY_LABELS["debt"], unit="JPY", points=debt_points
            )

        revenue = by_year("revenue")
        net_income = by_year("net_income")
        margin_points = [
            HistoryPoint(
                fiscal_year=revenue[y].fiscal_year,
                year=y,
                value=net_income[y].value / revenue[y].value * 100.0,
                source_element="derived: net_income / revenue * 100",
            )
            for y in sorted(set(revenue) & set(net_income))
            if revenue[y].value
        ]
        # Free cash flow proxy = operating CF + investing CF (investing CF is a
        # cash outflow, so this approximates OCF - capex). Labelled a proxy.
        ocf = by_year("operating_cf")
        icf = by_year("investing_cf")
        fcf_points = [
            HistoryPoint(
                fiscal_year=ocf[y].fiscal_year,
                year=y,
                value=ocf[y].value + icf[y].value,
                source_element="derived: operating_cf + investing_cf",
            )
            for y in sorted(set(ocf) & set(icf))
        ]
        if fcf_points:
            series["fcf"] = MetricSeries(
                metric="fcf", label=SUMMARY_LABELS["fcf"], unit="JPY", points=fcf_points
            )

        if margin_points:
            series["net_margin"] = MetricSeries(
                metric="net_margin", label=SUMMARY_LABELS["net_margin"], unit="%", points=margin_points
            )

        # Equity ratio / ROE / payout are often reported as fractions (0.30);
        # normalize each to a percentage when the values look like fractions.
        for name in _FRACTION_TO_PCT:
            if name in series:
                pts = series[name].points
                if pts and max(p.value for p in pts) <= 1.5:
                    for p in pts:
                        p.value *= 100.0
