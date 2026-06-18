"""LLM helper for the research layer — provider-agnostic.

Used for reasoning/summarization only, never for extracting figures that XBRL
already provides (CLAUDE.md core principle).

Provider selection:
  * ANTHROPIC_API_KEY set -> Claude (default preference)
  * else OPENAI_API_KEY set -> OpenAI
  * neither -> offline templates (callers fall back)
Set LLM_PROVIDER=anthropic|openai to force one when both keys are present.
Override models with ANTHROPIC_MODEL / OPENAI_MODEL.

The two SDKs are kept fully separate — no OpenAI-compatible shims.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OPENAI_MODEL = "gpt-4.1"


def _anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)


def _openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def active_provider() -> Optional[str]:
    """Return 'anthropic', 'openai', or None based on keys and LLM_PROVIDER."""
    forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if forced == "anthropic":
        return "anthropic" if has_anthropic else None
    if forced == "openai":
        return "openai" if has_openai else None

    # Default preference: Anthropic, then OpenAI.
    if has_anthropic:
        return "anthropic"
    if has_openai:
        return "openai"
    return None


def llm_available() -> bool:
    return active_provider() is not None


def active_model_label() -> str:
    provider = active_provider()
    if provider == "anthropic":
        return f"anthropic:{_anthropic_model()}"
    if provider == "openai":
        return f"openai:{_openai_model()}"
    return "offline-template"


def complete_json(system: str, user: str, schema: Dict, max_tokens: int = 6000) -> Dict:
    """Call the active provider and return JSON validated against ``schema``.

    Raises if no provider is available or the response can't be parsed; callers
    decide whether to fall back to offline generation.
    """
    provider = active_provider()
    if provider == "anthropic":
        return _complete_anthropic(system, user, schema, max_tokens)
    if provider == "openai":
        return _complete_openai(system, user, schema, max_tokens)
    raise RuntimeError("No LLM provider available (set ANTHROPIC_API_KEY or OPENAI_API_KEY).")


def _complete_anthropic(system: str, user: str, schema: Dict, max_tokens: int) -> Dict:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=_anthropic_model(),
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


def _complete_openai(system: str, user: str, schema: Dict, max_tokens: int) -> Dict:
    from openai import OpenAI

    client = OpenAI()
    resp = client.chat.completions.create(
        model=_openai_model(),
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "research_output", "schema": schema, "strict": True},
        },
    )
    return json.loads(resp.choices[0].message.content)
