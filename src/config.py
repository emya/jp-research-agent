"""Minimal .env loader (no external dependency).

Reads KEY=VALUE lines from a .env file at the repo root and sets them in the
process environment *without* overriding variables already set in the shell
(shell exports win). Comments (#) and blank lines are ignored; surrounding
quotes on values are stripped.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Optional[Path] = None) -> None:
    env_path = Path(path) if path else (_REPO_ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
