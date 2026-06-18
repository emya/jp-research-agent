#!/usr/bin/env python3
"""JP Research Agent — MVP CLI.

    python main.py --ticker 8035

Generates an investor-oriented research memo from a Japanese company's EDINET
annual securities report. Runs offline against a bundled sample filing by
default; set EDINET_API_KEY for live filings and ANTHROPIC_API_KEY for
LLM-generated memos.
"""
from __future__ import annotations

import argparse
import sys
import warnings

# Cosmetic: macOS system Python links LibreSSL, which urllib3 v2 warns about.
warnings.filterwarnings("ignore", message=r".*OpenSSL 1\.1\.1.*")

from src.config import load_env
from src.edinet.client import EDINETError
from src.pipeline import PipelineError, run
from src.research import llm

# Load EDINET_API_KEY / ANTHROPIC_API_KEY from a .env file if present (shell
# exports take precedence).
load_env()


def _diagnose(ticker: str) -> int:
    import os

    from src.edinet.client import EDINETClient

    if not os.environ.get("EDINET_API_KEY"):
        print("error: --diagnose requires EDINET_API_KEY to be set.", file=sys.stderr)
        return 1
    print(f"Probing EDINET for ticker {ticker} on a few key dates…\n", file=sys.stderr)
    try:
        out = EDINETClient().probe(ticker)
    except EDINETError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    k = out["key"]
    print(f"Key fingerprint: length={k['length']}  has_whitespace={k['has_whitespace']}  preview={k['preview']}")
    if k["has_whitespace"]:
        print("  ⚠️ The key contains whitespace/newline — likely a copy-paste artifact in .env.")
    print("")

    any_results = False
    any_match = False
    for e in out["dates"]:
        if e["error"] and e["status"] != 200:
            print(f"  {e['date']}: HTTP {e['status']}  ERROR  {e['error']!r}")
            continue
        meta = e.get("metadata") or {}
        rs = (meta.get("resultset") or {}).get("count")
        any_results = any_results or e["n_results"] > 0
        print(
            f"  {e['date']}: HTTP {e['status']}  results={e['n_results']}  "
            f"resultset.count={rs}  meta.status={meta.get('status')}  meta.message={meta.get('message')!r}"
        )
        for m in e["matches"]:
            any_match = True
            print(
                f"      -> docType={m['docTypeCode']}  secCode={m['secCode']}  "
                f"edinet={m['edinetCode']}  {m['filerName']} | {m['docDescription']}"
            )

    ht = out["header_test"]
    print(f"\nHeader-auth test ({ht.get('date')}): HTTP {ht['status']}  results={ht['n_results']}  err={ht.get('error')!r}")

    print("\nRaw response sample (first probed date):")
    print("  " + (out["raw_first"] or "(none)").replace("\n", "\n  "))

    print("")
    if any_match:
        print("Diagnosis: matches found. docTypeCode 120 = annual securities report. The normal run should work.")
    elif any_results:
        print(f"Diagnosis: data returned but no secCode {ticker} match — see records above.")
    elif ht.get("n_results"):
        print("Diagnosis: query-param key returns 0 but HEADER auth returns data — fix is to send the key as the "
              "'Ocp-Apim-Subscription-Key' header. Tell me and I'll switch the client.")
    else:
        print("Diagnosis: 0 results everywhere. Read meta.message and the raw sample above — that's EDINET's own "
              "explanation (e.g. invalid key, bad parameter, or rate limit).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate a research memo for a Japanese listed company.")
    parser.add_argument("--ticker", required=True, help="4-digit TSE ticker, e.g. 8035")
    parser.add_argument("--no-llm", action="store_true", help="Force offline (template) memo generation")
    parser.add_argument("--output", default=None, help="Output root directory (default: data/output)")
    parser.add_argument("--quiet", action="store_true", help="Don't print the memo to stdout")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="List every EDINET filing found for the ticker (any type) and exit",
    )
    args = parser.parse_args(argv)

    if args.diagnose:
        return _diagnose(args.ticker)

    use_llm = False if args.no_llm else None  # None => auto-detect provider key

    import os

    if os.environ.get("EDINET_API_KEY"):
        print(
            "Live EDINET mode: scanning the daily document index for the latest "
            "annual report (this can take a minute)…",
            file=sys.stderr,
        )

    try:
        result = run(args.ticker, use_llm=use_llm, output_root=args.output)
    except (EDINETError, PipelineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    filing = result["filing"]
    memo = result["memo"]

    if memo.generation_mode.startswith("llm"):
        mode_note = memo.generation_mode  # e.g. llm:anthropic:claude-opus-4-8
    else:
        mode_note = "offline templates"
        if not args.no_llm and not llm.llm_available():
            mode_note += " (no ANTHROPIC_API_KEY or OPENAI_API_KEY set)"

    print(f"Source: {filing.source} ({filing.data_kind})  |  Memo generation: {mode_note}", file=sys.stderr)
    print("Artifacts written:", file=sys.stderr)
    for name, path in result["artifacts"].items():
        print(f"  {name}: {path}", file=sys.stderr)
    print("", file=sys.stderr)

    if not args.quiet:
        print(memo.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
