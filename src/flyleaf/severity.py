# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Severity and impact for a finding.

Severity ranks how much engineering attention a change deserves. It is not a
legal risk tier, and it says nothing about whether an obligation applies.
"""

SEVERITY_NOTE = (
    "Severity ranks engineering attention, not legal risk. "
    "It does not indicate a risk tier under the EU AI Act."
)

ORDER = ("low", "medium", "high")

# change -> (impact, severity)
# runtime means the detected code changed. documentation means only the card did.
GRADES: dict[str, tuple[str, str]] = {
    "added_undocumented": ("runtime", "high"),
    "added": ("runtime", "medium"),
    "removed": ("runtime", "medium"),
    "evidence_changed": ("runtime", "high"),
    "card_stale": ("runtime", "high"),
    "evidence_and_card_changed": ("runtime", "medium"),
    "card_removed": ("documentation", "high"),
    "card_added": ("documentation", "low"),
    "card_changed": ("documentation", "low"),
}


def grade(change: str, documented: bool) -> tuple[str, str]:
    key = "added_undocumented" if change == "added" and not documented else change
    return GRADES.get(key, ("documentation", "low"))


def rank(severity: str) -> int:
    try:
        return ORDER.index(severity)
    except ValueError:
        return 0


def at_least(severity: str, threshold: str) -> bool:
    return rank(severity) >= rank(threshold)
