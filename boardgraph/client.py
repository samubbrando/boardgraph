"""Cliente GraphQL mínimo: `gh api graphql` ou HTTPS direto."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request

from .auth import AuthError, missing_scope_hint, resolve_token

ENDPOINT = "https://api.github.com/graphql"


class GraphQLError(RuntimeError):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        paths = [".".join(str(p) for p in e.get("path", [])) for e in errors]
        messages = "; ".join(e.get("message", "?") for e in errors)
        super().__init__(f"GraphQL: {messages}" + (f" [paths: {', '.join(filter(None, paths))}]" if any(paths) else ""))
        joined = " ".join(paths) + " " + messages
        self.hint_missing_scope = "read:project" in joined or "INSUFFICIENT_SCOPES" in joined


class GraphQLClient:
    def __init__(self, transport: str = "auto", token: str | None = None):
        self.token = resolve_token(token)
        if transport == "auto":
            transport = "gh" if self.token is None or _gh_available() else "http"
        if transport == "gh" and not _gh_available():
            raise AuthError("transporte `gh` pedido, mas o binário `gh` não está no PATH")
        if transport == "http" and not self.token:
            raise AuthError("transporte `http` precisa de GITHUB_TOKEN/GH_TOKEN")
        self.transport = transport

    def execute(self, query: str, variables: dict | None = None) -> dict:
        body = {"query": query, "variables": variables or {}}
        if self.transport == "gh":
            payload = self._via_gh(body)
        else:
            payload = self._via_http(body)

        if payload.get("errors"):
            raise GraphQLError(payload["errors"])
        if "data" not in payload:
            raise GraphQLError([{"message": "resposta sem `data`"}])
        return payload["data"]

    def _via_gh(self, body: dict) -> dict:
        proc = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"],
            input=json.dumps(body),
            capture_output=True,
            text=True,
            check=False,
        )
        raw = proc.stdout.strip()
        if not raw:
            msg = proc.stderr.strip() or "gh api graphql não retornou nada"
            if "read:project" in msg or "missing required scopes" in msg:
                raise AuthError(missing_scope_hint())
            raise RuntimeError(msg)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"resposta não-JSON do gh: {raw[:300]}") from exc

    def _via_http(self, body: dict) -> dict:
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "boardgraph",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            if exc.code == 401 or "read:project" in detail:
                raise AuthError(missing_scope_hint()) from exc
            raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}") from exc


def _gh_available() -> bool:
    from .auth import has_gh

    return has_gh()
