# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""A baseline is the inventory as it stood at the last sign-off."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from flyleaf import __version__
from flyleaf.scan import scan_path

BASELINE_FILE = Path(".flyleaf") / "baseline.json"


class BaselineError(Exception):
    """The baseline could not be read."""


def baseline_path(repo: Path) -> Path:
    return repo / BASELINE_FILE


def write_baseline(repo: Path, rev: str | None, approved_by: str | None) -> Path:
    """Record the current tree as the approved state."""
    inventory = scan_path(repo)
    document = {
        "kind": "baseline",
        "tool": {"name": "flyleaf", "version": __version__},
        "recorded_at": datetime.now(timezone.utc).date().isoformat(),
        "rev": rev,
        "approved_by": approved_by,
        "inventory": inventory,
    }
    destination = baseline_path(repo)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return destination


def read_baseline(repo: Path) -> dict:
    path = baseline_path(repo)
    if not path.is_file():
        raise BaselineError(
            f"No baseline at {BASELINE_FILE.as_posix()}. Run 'flyleaf baseline' to record one."
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BaselineError(f"Could not read {BASELINE_FILE.as_posix()}: {exc}") from exc
    inventory = document.get("inventory")
    if not isinstance(inventory, dict) or "components" not in inventory:
        raise BaselineError(f"{BASELINE_FILE.as_posix()} does not contain an inventory.")
    return document


def describe(document: dict) -> dict:
    return {
        "ref": "baseline",
        "rev": document.get("rev"),
        "recorded_at": document.get("recorded_at"),
        "approved_by": document.get("approved_by"),
    }


def today() -> date:
    return datetime.now(timezone.utc).date()
