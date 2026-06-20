"""EDINET ingestion (MVP Step 1).

Produces a :class:`FilingDocument`. By default it loads a bundled SAMPLE filing
so the pipeline runs offline. If ``EDINET_API_KEY`` is set, it fetches the real
annual securities report from the EDINET API v2.

This module deliberately has no dependency on the LLM / research code — EDINET
ingestion must stand alone (see CLAUDE.md engineering constraints).
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Optional

from ..models.filing import FilingDocument

EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
# Annual securities report (有価証券報告書).
ANNUAL_REPORT_DOC_TYPE = "120"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROOT = _REPO_ROOT / "data" / "fixtures"


class EDINETError(RuntimeError):
    pass


_AUTH_HELP = (
    "EDINET rejected the key as invalid/inactive ({detail}). The request format is "
    "correct, so this is the key itself. Check: (1) the key in .env has no stray "
    "spaces/newlines and is the full ~32-char value; (2) your EDINET registration "
    "is fully completed (email + SMS verification); (3) try regenerating the key on "
    "the EDINET API key screen. Run `--diagnose` to see the key fingerprint."
)


def _sec_matches(doc: dict, sec_code: str) -> bool:
    """Match a filing to a ticker by the first 4 digits of its securities code.

    Robust to whether EDINET returns the 5-digit secCode ("80350") or 4-digit
    ("8035"), and tolerates None.
    """
    code = (doc.get("secCode") or "").strip()
    return bool(code) and code[:4] == sec_code[:4]


class EDINETClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        fixture_root: Optional[Path] = None,
        download_dir: Optional[Path] = None,
        verbose: bool = True,
        lookback_days: Optional[int] = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("EDINET_API_KEY")
        self.fixture_root = Path(fixture_root) if fixture_root else _FIXTURE_ROOT
        self.download_dir = Path(download_dir) if download_dir else (_REPO_ROOT / "data" / "downloads")
        self.verbose = verbose
        env_lookback = os.environ.get("EDINET_LOOKBACK_DAYS")
        # Default window must reach last year's filing: a March fiscal-year-end
        # company files its annual report in June (~360 days back).
        self.lookback_days = lookback_days or (int(env_lookback) if env_lookback else 460)
        self._filing_cache: dict = {}

    @property
    def live(self) -> bool:
        return bool(self.api_key)

    def fetch_filing(self, ticker: str) -> FilingDocument:
        """Return the latest annual report filing for a ticker (cached per client,
        so reusing one client for several analyses avoids repeat index scans)."""
        if ticker in self._filing_cache:
            return self._filing_cache[ticker]
        doc = self._fetch_live(ticker) if self.live else self._load_fixture(ticker)
        self._filing_cache[ticker] = doc
        return doc

    # ------------------------------------------------------------------ fixture
    def _load_fixture(self, ticker: str) -> FilingDocument:
        base = self.fixture_root / ticker
        meta_path = base / "filing.json"
        if not meta_path.exists():
            raise EDINETError(
                f"No EDINET_API_KEY set and no bundled sample filing for ticker {ticker} "
                f"(expected {meta_path}). Set EDINET_API_KEY to fetch live data."
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        xbrl_path = base / meta["xbrl_relpath"]
        if not xbrl_path.exists():
            raise EDINETError(f"Sample XBRL instance missing: {xbrl_path}")
        return FilingDocument(
            ticker=meta["ticker"],
            company_name=meta["company_name"],
            company_name_jp=meta.get("company_name_jp", ""),
            edinet_code=meta.get("edinet_code", ""),
            doc_id=meta["doc_id"],
            form_type=meta["form_type"],
            fiscal_year=meta["fiscal_year"],
            submitted_date=meta.get("submitted_date", ""),
            source="fixture",
            data_kind=meta.get("data_kind", "SAMPLE"),
            xbrl_path=str(xbrl_path),
            note=meta.get("note", ""),
        )

    # --------------------------------------------------------------------- live
    def _fetch_live(self, ticker: str) -> FilingDocument:
        import requests  # local import keeps the module importable without requests

        sec_code = f"{ticker}0"  # EDINET securities codes are the 4-digit ticker + a trailing digit
        doc = self._find_latest_annual_report(requests, sec_code)
        if doc is None:
            raise EDINETError(
                f"Could not locate an annual securities report (docTypeCode "
                f"{ANNUAL_REPORT_DOC_TYPE}) for ticker {ticker} (secCode {sec_code}) "
                f"in the last {self.lookback_days} days of the EDINET index. "
                f"Try a larger window via EDINET_LOOKBACK_DAYS, or confirm the ticker."
            )

        doc_id = doc["docID"]
        target_dir = self.download_dir / ticker / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        xbrl_path = self._download_xbrl(requests, doc_id, target_dir)

        return FilingDocument(
            ticker=ticker,
            company_name=(doc.get("filerName") or "").strip(),
            edinet_code=doc.get("edinetCode", "") or "",
            doc_id=doc_id,
            form_type=doc.get("docDescription", "Annual Securities Report"),
            fiscal_year=doc.get("periodEnd", "") or "",
            submitted_date=doc.get("submitDateTime", "") or "",
            source="edinet-live",
            data_kind="OFFICIAL",
            xbrl_path=str(xbrl_path),
            note="Fetched from EDINET API v2.",
        )

    def _find_latest_annual_report(self, requests, sec_code: str):
        """Scan the EDINET document index day-by-day (newest first) for the
        company's latest annual securities report.

        EDINET v2 has no search-by-company endpoint, so we must walk the daily
        index. Annual reports are filed on a single day, so the scan must be
        daily (not sampled) or it will skip the filing. Returns the first
        (most recent) match, or None.
        """
        import sys

        today = _dt.date.today()
        for offset in range(0, self.lookback_days + 1):
            day = today - _dt.timedelta(days=offset)
            params = {"date": day.isoformat(), "type": 2, "Subscription-Key": self.api_key}
            try:
                resp = requests.get(f"{EDINET_API_BASE}/documents.json", params=params, timeout=30)
            except Exception:
                continue  # transient network issue on one day — keep scanning

            if resp.status_code in (401, 403):
                raise EDINETError(_AUTH_HELP.format(detail=f"HTTP {resp.status_code}"))
            if resp.status_code != 200:
                continue

            data = resp.json()
            # EDINET's Azure gateway wraps an invalid-key error in a 200 body.
            if isinstance(data, dict) and str(data.get("StatusCode")) in ("401", "403"):
                raise EDINETError(_AUTH_HELP.format(detail=data.get("message", "invalid subscription key")))

            for d in data.get("results", []) or []:
                if _sec_matches(d, sec_code) and str(d.get("docTypeCode")) == ANNUAL_REPORT_DOC_TYPE:
                    if self.verbose:
                        print(
                            f"  found: {d.get('filerName')} — {d.get('docDescription')} "
                            f"(docID {d.get('docID')}, submitted {d.get('submitDateTime')})",
                            file=sys.stderr,
                        )
                    return d

            if self.verbose and offset and offset % 30 == 0:
                print(f"  …scanned {offset}/{self.lookback_days} days back ({day.isoformat()})…", file=sys.stderr)
        return None

    def _index_results(self, requests, day):
        """One day's EDINET index results (raises on auth failure; None on a
        transient error so the caller keeps scanning)."""
        params = {"date": day.isoformat(), "type": 2, "Subscription-Key": self.api_key}
        try:
            resp = requests.get(f"{EDINET_API_BASE}/documents.json", params=params, timeout=30)
        except Exception:
            return None
        if resp.status_code in (401, 403):
            raise EDINETError(_AUTH_HELP.format(detail=f"HTTP {resp.status_code}"))
        if resp.status_code != 200:
            return []
        data = resp.json()
        if isinstance(data, dict) and str(data.get("StatusCode")) in ("401", "403"):
            raise EDINETError(_AUTH_HELP.format(detail=data.get("message", "invalid subscription key")))
        return data.get("results", []) or []

    def _find_annual_reports(self, requests, sec_code: str, max_reports: int):
        """Collect up to ``max_reports`` annual reports (newest first). After
        each hit, jump ~300 days back (reports are yearly) to bound requests."""
        import sys

        today = _dt.date.today()
        found, offset = [], 0
        max_offset = self.lookback_days * max_reports + 120
        while offset <= max_offset and len(found) < max_reports:
            day = today - _dt.timedelta(days=offset)
            results = self._index_results(requests, day)
            match = None
            for d in results or []:
                if _sec_matches(d, sec_code) and str(d.get("docTypeCode")) == ANNUAL_REPORT_DOC_TYPE:
                    match = d
                    break
            if match:
                found.append(match)
                if self.verbose:
                    print(f"  found [{len(found)}/{max_reports}]: {match.get('docDescription')} "
                          f"(docID {match.get('docID')}, {match.get('submitDateTime')})", file=sys.stderr)
                offset += 300
                continue
            if self.verbose and offset and offset % 60 == 0:
                print(f"  …scanned {offset} days back ({day.isoformat()}), {len(found)} found…", file=sys.stderr)
            offset += 1
        return found

    def _build_live_filing(self, ticker: str, doc: dict, xbrl_path) -> FilingDocument:
        return FilingDocument(
            ticker=ticker,
            company_name=(doc.get("filerName") or "").strip(),
            edinet_code=doc.get("edinetCode", "") or "",
            doc_id=doc["docID"],
            form_type=doc.get("docDescription", "Annual Securities Report"),
            fiscal_year=doc.get("periodEnd", "") or "",
            submitted_date=doc.get("submitDateTime", "") or "",
            source="edinet-live",
            data_kind="OFFICIAL",
            xbrl_path=str(xbrl_path),
            note="Fetched from EDINET API v2.",
        )

    def fetch_annual_reports(self, ticker: str, max_reports: int = 3):
        """Return up to ``max_reports`` of the company's most recent annual
        reports (newest first) for building a long history. Offline mode returns
        only the single bundled sample."""
        if not self.live:
            return [self._load_fixture(ticker)]
        import requests

        sec_code = f"{ticker}0"
        docs = self._find_annual_reports(requests, sec_code, max_reports)
        if not docs:
            raise EDINETError(
                f"No annual securities reports found for ticker {ticker} (secCode {sec_code})."
            )
        filings = []
        for doc in docs:
            target_dir = self.download_dir / ticker / doc["docID"]
            target_dir.mkdir(parents=True, exist_ok=True)
            xbrl_path = self._download_xbrl(requests, doc["docID"], target_dir)
            filings.append(self._build_live_filing(ticker, doc, xbrl_path))
        return filings

    def diagnostic_dates(self):
        """A curated set of dates likely to reveal the problem fast: the last few
        days (is the API returning data at all?) and last year's late-June
        annual-report season for March fiscal-year-end issuers."""
        today = _dt.date.today()
        dates = [today - _dt.timedelta(days=i) for i in range(0, 3)]
        for d in range(20, 31):
            try:
                dates.append(_dt.date(today.year - 1, 6, d))
            except ValueError:
                pass
        return sorted(set(dates), reverse=True)

    def _key_fingerprint(self) -> dict:
        """Safe metadata about the key (no secret leak) to catch .env mangling."""
        k = self.api_key or ""
        return {
            "length": len(k),
            "has_whitespace": any(c.isspace() for c in k),
            "preview": (k[:2] + "…" + k[-2:]) if len(k) >= 4 else "(too short)",
        }

    def probe(self, ticker: str, dates=None):
        """Probe specific dates with full transparency. Returns a dict with the
        key fingerprint, per-date results (incl. EDINET's own metadata block and
        a raw body sample), and a header-auth comparison."""
        import requests

        if not self.live:
            raise EDINETError("probe() requires EDINET_API_KEY (live mode).")

        sec_code = f"{ticker}0"
        dates = dates or self.diagnostic_dates()
        url = f"{EDINET_API_BASE}/documents.json"
        report = []
        raw_first = None
        for i, day in enumerate(dates):
            params = {"date": day.isoformat(), "type": 2, "Subscription-Key": self.api_key}
            entry = {
                "date": day.isoformat(),
                "status": None,
                "n_results": 0,
                "metadata": None,
                "matches": [],
                "error": None,
            }
            try:
                resp = requests.get(url, params=params, timeout=30)
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"request failed: {exc}"
                report.append(entry)
                continue
            entry["status"] = resp.status_code
            if i == 0:
                raw_first = resp.text[:800]
            if resp.status_code != 200:
                entry["error"] = resp.text[:300]
                report.append(entry)
                continue
            data = resp.json()
            entry["metadata"] = data.get("metadata")
            results = data.get("results") or []
            entry["n_results"] = len(results)
            for d in results:
                if _sec_matches(d, sec_code):
                    entry["matches"].append(
                        {
                            "docID": d.get("docID"),
                            "secCode": d.get("secCode"),
                            "edinetCode": d.get("edinetCode"),
                            "filerName": d.get("filerName"),
                            "docTypeCode": d.get("docTypeCode"),
                            "docDescription": d.get("docDescription"),
                        }
                    )
            report.append(entry)

        # Fallback test: send the key as a header instead of a query param.
        header_test = {"n_results": None, "status": None, "error": None}
        try:
            probe_day = dates[0].isoformat()
            resp = requests.get(
                url,
                params={"date": probe_day, "type": 2},
                headers={"Ocp-Apim-Subscription-Key": self.api_key or ""},
                timeout=30,
            )
            header_test["status"] = resp.status_code
            header_test["date"] = probe_day
            if resp.status_code == 200:
                header_test["n_results"] = len(resp.json().get("results") or [])
            else:
                header_test["error"] = resp.text[:200]
        except Exception as exc:  # noqa: BLE001
            header_test["error"] = str(exc)

        return {
            "key": self._key_fingerprint(),
            "dates": report,
            "raw_first": raw_first,
            "header_test": header_test,
        }

    def _download_xbrl(self, requests, doc_id: str, target_dir: Path) -> Path:
        # Cache: if this filing was already downloaded, reuse it (no refetch).
        cached = self._select_xbrl(target_dir)
        if cached is not None:
            return cached
        params = {"type": 1, "Subscription-Key": self.api_key}  # type=1 => ZIP with XBRL
        resp = requests.get(f"{EDINET_API_BASE}/documents/{doc_id}", params=params, timeout=120)
        if resp.status_code != 200:
            raise EDINETError(f"EDINET document download failed ({resp.status_code}) for {doc_id}")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(target_dir)
        chosen = self._select_xbrl(target_dir)
        if chosen is None:
            raise EDINETError(f"No .xbrl instance found in EDINET download for {doc_id}")
        return chosen

    @staticmethod
    def _select_xbrl(target_dir: Path) -> Optional[Path]:
        """Pick the audited financial instance (PublicDoc *.xbrl) if present."""
        candidates = sorted(target_dir.rglob("*.xbrl"))
        public = [p for p in candidates if "PublicDoc" in str(p)]
        chosen = public or candidates
        return chosen[0] if chosen else None
