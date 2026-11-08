"""Resolve logins do GitHub para nomes de pessoas.

O arquivo `people-names.json` é local e ignorado pelo Git. O exemplo
versionado é `people-names.example.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_PEOPLE_FILE = Path("people-names.json")
EXAMPLE_PEOPLE_FILE = Path("people-names.example.json")
SCHEMA_VERSION = 1
MODES = ("name", "login", "both")
UNKNOWN = "—"


class PeopleError(ValueError):
    """Arquivo de pessoas inválido ou ausente."""


@dataclass(frozen=True)
class Person:
    login: str
    name: str
    short: str = ""
    aliases: tuple[str, ...] = ()
    active: bool = True
    bot: bool = False
    role: str | None = None
    team: str | None = None
    manager: str | None = None

    def display(self, mode: str = "name") -> str:
        if mode not in MODES:
            raise PeopleError(f"formato de responsável inválido: {mode!r}")
        if mode == "login":
            return f"@{self.login}"
        label = self.short or self.name
        if mode == "both":
            return f"{label} (@{self.login})"
        return label


@dataclass
class PeopleIndex:
    people: dict[str, Person] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def resolve(self, login: str | None) -> Person | None:
        key = _normalize(login)
        if not key:
            return None
        if key in self.people:
            return self.people[key]
        canonical = self.aliases.get(key)
        if canonical:
            return self.people.get(canonical)
        return None

    def format(self, login: str | None, mode: str = "name") -> str:
        if mode not in MODES:
            raise PeopleError(f"formato de responsável inválido: {mode!r}")
        person = self.resolve(login)
        if person is not None:
            return person.display(mode)
        if not login:
            return UNKNOWN
        if _normalize(login) == "ghost":
            return "Conta removida"
        return f"@{str(login).lstrip('@')}"

    def format_many(
        self,
        logins: Iterable[str] | None,
        mode: str = "name",
        limit: int = 2,
    ) -> str:
        seen: set[str] = set()
        labels: list[str] = []
        for login in logins or ():
            key = _normalize(login)
            if not key:
                continue
            person = self.resolve(login)
            if person is not None:
                key = _normalize(person.login)
            if key in seen:
                continue
            seen.add(key)
            labels.append(self.format(login, mode))
        if not labels:
            return UNKNOWN
        if limit <= 0 or len(labels) <= limit:
            return ", ".join(labels)
        return ", ".join(labels[:limit]) + f" +{len(labels) - limit}"


def load(path: str | Path = DEFAULT_PEOPLE_FILE) -> PeopleIndex:
    """Carrega e valida o arquivo de pessoas."""
    path = Path(path).expanduser()
    if not path.exists():
        raise PeopleError(
            f"arquivo de pessoas não encontrado: {path}\n"
            f"copie {EXAMPLE_PEOPLE_FILE} para {path} e preencha."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PeopleError(f"JSON inválido em {path}: {exc}") from None

    if not isinstance(data, dict):
        raise PeopleError(f"{path}: o topo precisa ser um objeto JSON")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise PeopleError(
            f"{path}: schema_version {version!r} não suportado "
            f"(esperado {SCHEMA_VERSION})"
        )

    raw_people = data.get("people")
    if not isinstance(raw_people, dict) or not raw_people:
        raise PeopleError(f"{path}: 'people' precisa ser um objeto não vazio")

    people: dict[str, Person] = {}
    raw_aliases: list[tuple[str, str]] = []

    for raw_login, raw_person in raw_people.items():
        if not isinstance(raw_person, dict):
            raise PeopleError(f"{path}: pessoa {raw_login!r} precisa ser um objeto")

        login = str(raw_login).strip().lstrip("@")
        key = _normalize(login)
        if not key:
            raise PeopleError(f"{path}: login vazio em 'people'")
        if key in people:
            raise PeopleError(f"{path}: login duplicado (case-insensitive): {login!r}")

        name = raw_person.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PeopleError(f"{path}: pessoa {login!r} sem 'name'")

        short = raw_person.get("short") or ""
        if not isinstance(short, str):
            raise PeopleError(f"{path}: 'short' de {login!r} precisa ser texto")

        active = raw_person.get("active", True)
        if not isinstance(active, bool):
            raise PeopleError(f"{path}: 'active' de {login!r} precisa ser booleano")

        bot = raw_person.get("bot", False)
        if not isinstance(bot, bool):
            raise PeopleError(f"{path}: 'bot' de {login!r} precisa ser booleano")

        aliases = raw_person.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            raise PeopleError(
                f"{path}: 'aliases' de {login!r} precisa ser lista de textos"
            )

        role = raw_person.get("role")
        team = raw_person.get("team")
        manager = raw_person.get("manager")
        for field_name, value in (("role", role), ("team", team), ("manager", manager)):
            if value is not None and not isinstance(value, str):
                raise PeopleError(
                    f"{path}: '{field_name}' de {login!r} precisa ser texto ou null"
                )

        person = Person(
            login=login,
            name=name.strip(),
            short=short.strip(),
            aliases=tuple(aliases),
            active=active,
            bot=bot,
            role=(role.strip() or None) if isinstance(role, str) else None,
            team=(team.strip() or None) if isinstance(team, str) else None,
            manager=(manager.strip().lstrip("@") or None) if isinstance(manager, str) else None,
        )
        people[key] = person
        for alias in aliases:
            raw_aliases.append((alias, key))

    aliases_map: dict[str, str] = {}
    for alias, canonical in raw_aliases:
        alias_key = _normalize(alias)
        if not alias_key:
            raise PeopleError(f"{path}: alias vazio para {people[canonical].login!r}")
        if alias_key in people:
            raise PeopleError(
                f"{path}: alias {alias!r} conflita com o login {people[alias_key].login!r}"
            )
        if alias_key in aliases_map:
            other = people[aliases_map[alias_key]].login
            raise PeopleError(
                f"{path}: alias {alias!r} duplicado entre {other!r} e "
                f"{people[canonical].login!r}"
            )
        aliases_map[alias_key] = canonical

    index = PeopleIndex(people=people, aliases=aliases_map)
    for person in people.values():
        if person.manager:
            manager_key = _normalize(person.manager)
            if manager_key not in people and manager_key not in aliases_map:
                index.warnings.append(
                    f"manager de {person.login!r} não encontrado: {person.manager!r}"
                )
    return index


def _normalize(login: str | None) -> str:
    return str(login or "").strip().lstrip("@").lower()
