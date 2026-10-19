"""Which code ran: the git commit of the modpilot package and whether its files differ from it.
Read once per import of this module (a reload re-reads it)."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


def _git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(PKG), *args], capture_output=True, text=True,
                              timeout=20, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


@lru_cache(maxsize=1)
def code() -> dict:
    sha = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--", ".")) if sha else True
    return {"sha": sha or "unknown", "dirty": dirty, "path": str(PKG)}
