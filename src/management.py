"""Management / board profile (MVP2 follow-up).

    python -m src.management 8035          # representative directors
    python -m src.management 8035 --all    # full board
    python -m src.management 8035 --bio     # LLM-polished English career bios (reps)

Extracts the 役員の状況 section from the EDINET filing — structured, in-lane.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from .edinet.client import EDINETClient, EDINETError
from .models.management import ManagementProfile, Officer
from .parser.officer_parser import extract_officers
from .research import llm

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "output" / "management"

_BIO_SYSTEM = (
    "Write a factual English professional bio (2-4 sentences) from the officer's "
    "Japanese career summary. Trace their career progression — prior companies and "
    "roles with the years given — and end with their current position. Translate "
    "company and role names to English. State ONLY what's in the text: no "
    "embellishment, no opinion, no invented dates or employers."
)
_BIO_SCHEMA = {
    "type": "object",
    "properties": {"bio": {"type": "string"}},
    "required": ["bio"],
    "additionalProperties": False,
}


def build_profile(ticker: str, client: Optional[EDINETClient] = None) -> ManagementProfile:
    client = client or EDINETClient()
    return extract_officers(client.fetch_filing(ticker))


def add_bios(officers: List[Officer]) -> None:
    """Best-effort LLM-polished bios for the given officers (in place)."""
    for o in officers:
        if not o.career_summary:
            continue
        try:
            out = llm.complete_json(
                _BIO_SYSTEM,
                f"Officer: {o.name}\nTitle: {o.title}\nCareer summary:\n{o.career_summary}",
                _BIO_SCHEMA, max_tokens=600,
            )
            o.bio = out.get("bio", "")
        except Exception:
            pass


def render(profile: ManagementProfile, show_all: bool) -> str:
    chosen = profile.officers if show_all else (profile.representatives() or profile.officers)
    lines = [f"# Management — {profile.company} ({profile.ticker})", ""]
    lines.append(f"_{len(profile.officers)} officers, {len(profile.representatives())} representative director(s)_")
    lines.append("")
    for o in chosen:
        tag = " ⭐ (Representative)" if o.is_representative else ""
        heading = o.name_en or o.name
        jp = f"  ({o.name})" if o.name_en and o.name else ""
        lines.append(f"## {heading}{jp}{tag}")
        title = o.title_en or o.title
        title_jp = f"  ({o.title})" if o.title_en and o.title else ""
        lines.append(f"- **Title:** {title}{title_jp}")
        if o.age is not None:
            lines.append(f"- **Age:** {o.age}  (DOB {o.date_of_birth})")
        if o.shares_held is not None:
            lines.append(f"- **Shares held:** {o.shares_held:,.0f}")
        if o.term_of_office:
            lines.append(f"- **Term:** {o.term_of_office}")
        if o.bio:
            lines.append(f"- **Bio:** {o.bio}")
        elif o.career_summary:
            career = " ".join(o.career_summary.split())
            lines.append(f"- **Career:** {career[:240]}…")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys

    from .config import load_env

    load_env()

    ap = argparse.ArgumentParser(description="Management / board profile from the EDINET filing.")
    ap.add_argument("ticker")
    ap.add_argument("--all", action="store_true", help="Show the full board (default: representatives)")
    ap.add_argument("--bio", action="store_true", help="Add LLM-polished English career bios (needs a provider key)")
    ap.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    args = ap.parse_args()

    try:
        profile = build_profile(args.ticker)
    except EDINETError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if not profile.has_data():
        print(f"No officer data found for {args.ticker}.", file=sys.stderr)
        raise SystemExit(1)

    if args.bio:
        if not llm.llm_available():
            print("note: --bio needs ANTHROPIC_API_KEY or OPENAI_API_KEY; skipping bios.", file=sys.stderr)
        else:
            add_bios(profile.representatives())

    out_dir = Path(args.output) / args.ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "management.json").write_text(
        json.dumps(profile.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    md = render(profile, show_all=args.all)
    (out_dir / "management.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nArtifacts: {out_dir}", file=sys.stderr)
