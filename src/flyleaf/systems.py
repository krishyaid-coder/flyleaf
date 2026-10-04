# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Systems are groupings a person declares. flyleaf never infers them.

A component is evidence: one framework in one file. A system is the thing a
person documents. Which files belong together depends on purpose and audience,
which are not in the code, so the grouping is read from a file in the
repository rather than guessed.
"""

import fnmatch
import tomllib
from dataclasses import dataclass
from pathlib import Path

SYSTEMS_FILE = Path(".flyleaf") / "systems.toml"
REQUIRED_FIELDS = ("name", "includes")


@dataclass(frozen=True)
class System:
    name: str
    includes: tuple[str, ...]
    card: str | None
    owner: str | None

    def matches(self, path: str) -> bool:
        return any(_match(path, pattern) for pattern in self.includes)

    def payload(self) -> dict:
        return {
            "name": self.name,
            "owner": self.owner,
            "card": self.card,
            "includes": list(self.includes),
        }


def load_systems(root: Path) -> tuple[list[System], list[str]]:
    """Read `.flyleaf/systems.toml`. Return the valid systems and any problems.

    A malformed entry is reported and ignored. Its files then stand alone as
    components, which is the behaviour when no systems file exists at all.
    """
    path = root / SYSTEMS_FILE
    if not path.is_file():
        return [], []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return [], [f"Could not read {SYSTEMS_FILE.as_posix()}: {exc}"]

    entries = data.get("system")
    if entries is None:
        return [], []
    if not isinstance(entries, list):
        return [], [f"{SYSTEMS_FILE.as_posix()}: system must be a list of tables."]

    systems: list[System] = []
    problems: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, 1):
        system, problem = _parse(entry, index)
        if problem:
            problems.append(problem)
        if system is None:
            continue
        if system.name in seen:
            problems.append(
                f"{SYSTEMS_FILE.as_posix()} entry {index}: ignored because the name "
                f"'{system.name}' is already used."
            )
            continue
        seen.add(system.name)
        systems.append(system)
    return systems, problems


def _parse(entry, index: int) -> tuple[System | None, str | None]:
    label = f"{SYSTEMS_FILE.as_posix()} entry {index}"
    if not isinstance(entry, dict):
        return None, f"{label}: not a table."

    missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
    if missing:
        return None, (
            f"{label}: ignored because it is missing {', '.join(missing)}. "
            "A system needs a name and a list of includes."
        )

    includes = entry["includes"]
    if isinstance(includes, str):
        includes = [includes]
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        return None, f"{label}: includes must be a list of path patterns."
    patterns = tuple(item.strip() for item in includes if item.strip())
    if not patterns:
        return None, f"{label}: includes must name at least one path pattern."

    return (
        System(
            name=str(entry["name"]),
            includes=patterns,
            card=str(entry["card"]) if entry.get("card") else None,
            owner=str(entry["owner"]) if entry.get("owner") else None,
        ),
        None,
    )


def assign(systems: list[System], path: str) -> System | None:
    """Return the system that claims `path`. The first declared match wins."""
    for system in systems:
        if system.matches(path):
            return system
    return None


def claimants(systems: list[System], path: str) -> list[str]:
    """Every system that claims `path`, in declaration order."""
    return [system.name for system in systems if system.matches(path)]


def _match(path: str, pattern: str) -> bool:
    """Match a repository-relative posix path against one include pattern.

    An exact path, a glob, or a directory prefix all work. A `*` spans
    directory separators, so `src/*` claims everything under `src`.
    """
    if path == pattern:
        return True
    if fnmatch.fnmatchcase(path, pattern):
        return True
    prefix = pattern.rstrip("/")
    return bool(prefix) and path.startswith(prefix + "/")
