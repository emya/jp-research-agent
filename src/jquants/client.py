"""J-Quants API client (JPX official, **V2**) for quarterly financials.

EDINET no longer carries ongoing quarterly data (quarterly securities reports
were abolished in 2024), so quarterly fundamentals come from J-Quants instead.

V2 auth is an API key (no token refresh): put JQUANTS_API_KEY in the env and it
is sent as the `x-api-key` header. Get the key from the J-Quants dashboard.
Endpoint: GET /v2/fins/summary?code=<4|5-digit>.
"""
from __future__ import annotations

import os
from typing import List, Optional

BASE = "https://api.jquants.com/v2"


class JQuantsError(RuntimeError):
    pass


class JQuantsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("JQUANTS_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def fetch_summary(self, ticker: str) -> List[dict]:
        """Return the /v2/fins/summary 'data' rows for a ticker (4- or 5-digit)."""
        import requests

        if not self.api_key:
            raise JQuantsError(
                "No J-Quants API key. Set JQUANTS_API_KEY in .env (V2 uses an API "
                "key from the dashboard — https://jpx-jquants.com/)."
            )
        code = ticker if len(ticker) == 5 else f"{ticker}0"
        rows: List[dict] = []
        params = {"code": code}
        for _ in range(20):  # follow pagination
            resp = requests.get(
                f"{BASE}/fins/summary",
                params=params,
                headers={"x-api-key": self.api_key},
                timeout=60,
            )
            if resp.status_code != 200:
                raise JQuantsError(f"J-Quants /fins/summary failed ({resp.status_code}): {resp.text[:200]}")
            body = resp.json()
            rows.extend(body.get("data", []) or [])
            key = body.get("pagination_key")
            if not key:
                break
            params = {"code": code, "pagination_key": key}
        return rows

    # Back-compat alias.
    def fetch_statements(self, ticker: str) -> List[dict]:
        return self.fetch_summary(ticker)
