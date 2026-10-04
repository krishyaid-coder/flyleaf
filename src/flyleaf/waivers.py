# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Waivers that suppress a finding for a stated reason, until a stated date.

A waiver is a deliberate, written act. It needs a reason, a person, and an
expiry date. Silence is not a waiver, and nothing is suppressed forever.
"""

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

WAIVER_FILE = Path(".flyleaf") / "waivers.toml"
EXPIRY_WARNING_DAYS = 14
REQUIRED_FIELDS = ("component", "reason", "approved_by", "expires")


@dataclass(frozen=True)
class Waiver:
    component: str
    change: str | None
    reason: str
    approved_by: str
    expires: date

    def covers(self, component_id: str, change: str) -> bool:
        if self.component != component_id:
            return False
        return self.change is None or self.change == change

    def days_left(self, today: date) -> int:
        return (self.expires - today).days

    def payload(self, today: date) -> dict:
        return {
            "component": self.component,
            "change": self.change,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "expires": self.expires.isoformat(),
            "days_left": self.days_left(today),
        }


def load_waivers(repo: Path) -> tuple[list[Waiver], list[str]]:
    """Read `.flyleaf/waivers.toml`. Return the valid waivers and any problems.

    A malformed entry is reported and ignored. It never suppresses a finding.
    """
    path = repo / WAIVER_FILE
    if not path.is_file():
        return [], []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return [], [f"Could not read {WAIVER_FILE.as_posix()}: {exc}"]

    entries = data.get("waiver")
    if entries is None:
        return [], []
    if not isinstance(entries, list):
        return [], [f"{WAIVER_FILE.as_posix()}: waiver must be a list of tables."]

    waivers: list[Waiver] = []
    problems: list[str] = []
    for index, entry in enumerate(entries, 1):
        waiver, problem = _parse(entry, index)
        if problem:
            problems.append(problem)
        if waiver:
            waivers.append(waiver)
    return waivers, problems


def _parse(entry, index: int) -> tuple[Waiver | None, str | None]:
    label = f"{WAIVER_FILE.as_posix()} entry {index}"
    if not isinstance(entry, dict):
        return None, f"{label}: not a table."

    missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
    if missing:
        return None, (
            f"{label}: ignored because it is missing {', '.join(missing)}. "
            "A waiver needs a component, a reason, an approver, and an expiry date."
        )

    expires = entry["expires"]
    if isinstance(expires, date):
        expiry = expires
    else:
        try:
            expiry = date.fromisoformat(str(expires))
        except ValueError:
            return None, f"{label}: expires must be a date such as 2026-12-31."

    change = entry.get("change")
    if change in ("", "*", None):
        change = None

    return (
        Waiver(
            component=str(entry["component"]),
            change=None if change is None else str(change),
            reason=str(entry["reason"]),
            approved_by=str(entry["approved_by"]),
            expires=expiry,
        ),
        None,
    )


def match(waivers: list[Waiver], component_id: str, change: str) -> Waiver | None:
    """Return the covering waiver, expired or not.

    A more specific waiver, one naming the change, wins over a blanket one.
    """
    best: Waiver | None = None
    for waiver in waivers:
        if not waiver.covers(component_id, change):
            continue
        if best is None or (best.change is None and waiver.change is not None):
            best = waiver
    return best
