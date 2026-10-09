# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Who should look at a finding.

Two different names, deliberately kept apart. The owner is declared in
`.flyleaf/systems.toml` and is accountable for the system. The author is read
from git blame and is whoever last touched the evidence line. The author is
the person who can answer the question now. The owner is the person who is
answerable for it either way.

Blame names a line, not a responsibility. A reformat, a rename, or a bot
bumping a version will make the wrong person the author, so the report says
where the name came from and never calls it fault.
"""

import re
import subprocess
from pathlib import Path

BOT_PATTERN = re.compile(r"(?i)\[bot\]|^(dependabot|renovate|github-actions)\b")
_EMPTY_SHA = "0" * 40


def last_author(repo: Path, rev: str | None, path: str, line: int) -> dict | None:
    """Return who last changed `line` of `path`, or None when git cannot say.

    `rev` blames at a revision. None blames the working tree, where an
    uncommitted edit has no author yet.
    """
    args = ["blame", "--porcelain", "-L", f"{max(1, line)},{max(1, line)}"]
    if rev:
        args.append(rev)
    args.extend(["--", path])
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return _parse(completed.stdout)


def _parse(output: str) -> dict | None:
    lines = output.splitlines()
    if not lines:
        return None
    commit = lines[0].split(" ", 1)[0]
    fields: dict[str, str] = {}
    for raw in lines[1:]:
        if raw.startswith("\t"):
            break
        key, _, value = raw.partition(" ")
        fields.setdefault(key, value)

    name = fields.get("author", "").strip()
    email = fields.get("author-mail", "").strip().strip("<>")
    uncommitted = commit == _EMPTY_SHA
    if uncommitted:
        return {
            "name": None,
            "email": None,
            "commit": None,
            "summary": None,
            "uncommitted": True,
            "is_bot": False,
            "source": "git blame",
        }
    if not name and not email:
        return None
    return {
        "name": name or None,
        "email": email or None,
        "commit": commit[:12],
        "summary": fields.get("summary") or None,
        "uncommitted": False,
        "is_bot": _is_bot(name, email),
        "source": "git blame",
    }


def _is_bot(name: str, email: str) -> bool:
    return bool(BOT_PATTERN.search(name or "") or BOT_PATTERN.search(email or ""))


def label(author: dict | None) -> str:
    """A short human label for a report line."""
    if author is None:
        return "unknown"
    if author["uncommitted"]:
        return "uncommitted change"
    who = author["email"] or author["name"] or "unknown"
    suffix = " (bot)" if author["is_bot"] else ""
    return f"{who}{suffix}"
