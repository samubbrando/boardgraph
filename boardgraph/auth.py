"""Resolução de credencial para a API do GitHub."""

from __future__ import annotations

import os
import shutil
import subprocess

REQUIRED_SCOPE = "read:project"


class AuthError(RuntimeError):
    pass


def has_gh() -> bool:
    return shutil.which("gh") is not None


def gh_token() -> str | None:
    if not has_gh():
        return None
    proc = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def resolve_token(explicit: str | None = None) -> str | None:
    """Token explícito > env > `gh auth token`."""
    return (
        explicit
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or gh_token()
    )


def missing_scope_hint() -> str:
    return (
        "token sem escopo `read:project`, que o GitHub Projects v2 exige.\n"
        "Rode: gh auth refresh -s read:project"
    )
