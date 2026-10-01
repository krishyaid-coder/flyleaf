# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Compare two inventories and list documentation changes with citations."""

import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from flyleaf import DISCLAIMER, __version__
from flyleaf.citations import pack_meta, payloads_for
from flyleaf.scan import SCHEMA_VERSION, scan_path


class GitError(Exception):
    """The repository could not be read with git."""


def build_brief(start: Path, base: str, head: str | None) -> dict:
    """Diff `base` against `head`.

    `head` is a git ref. When it is omitted, the working tree is the head.
    """
    if not start.exists():
        raise FileNotFoundError(start)
    repo = _git_root(start)
    base_rev = _rev_parse(repo, base)
    base_inventory = _scan_ref(repo, base_rev)

    if head is None:
        head_label = "working tree"
        head_rev = _rev_parse(repo, "HEAD")
        dirty = bool(_git(repo, "status", "--porcelain"))
        head_inventory = scan_path(repo)
    else:
        head_label = head
        head_rev = _rev_parse(repo, head)
        dirty = False
        head_inventory = _scan_ref(repo, head_rev)

    findings = _diff(base_inventory, head_inventory)
    citation_ids: set[str] = set()
    for finding in findings:
        citation_ids.update(finding["citation_ids"])

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "brief",
        "tool": {"name": "flyleaf", "version": __version__},
        "disclaimer": DISCLAIMER,
        "citation_pack": pack_meta(),
        "citations": payloads_for(citation_ids),
        "repository": str(repo),
        "base": {"ref": base, "rev": base_rev},
        "head": {"ref": head_label, "rev": head_rev, "dirty": dirty},
        "findings": findings,
    }


def _diff(base_inventory: dict, head_inventory: dict) -> list[dict]:
    base_map = {component["id"]: component for component in base_inventory["components"]}
    head_map = {component["id"]: component for component in head_inventory["components"]}
    findings: list[dict] = []
    for component_id in sorted(set(base_map) | set(head_map)):
        before = base_map.get(component_id)
        after = head_map.get(component_id)
        if before is None and after is not None:
            findings.append(_added(after))
        elif after is None and before is not None:
            findings.append(_removed(before))
        elif before is not None and after is not None:
            findings.extend(_changed(before, after))
    return findings


def _added(component: dict) -> dict:
    missing = component["model_card_status"] == "missing"
    summary = (
        "New component, and no model card was found."
        if missing
        else "New component. A model card is present. Confirm that the card describes this component."
    )
    return _finding(
        component,
        change="added",
        status="missing" if missing else "needs_review",
        summary=summary,
    )


def _removed(component: dict) -> dict:
    return _finding(
        component,
        change="removed",
        status="needs_review",
        summary=(
            "This component was in the base tree and is absent from the head tree. "
            "Check whether a model card still describes it."
        ),
    )


def _changed(before: dict, after: dict) -> list[dict]:
    evidence_changed = _evidence_key(before) != _evidence_key(after)
    card_changed = before.get("model_card_sha256") != after.get("model_card_sha256")
    missing = after["model_card_status"] == "missing"
    if not evidence_changed and not card_changed:
        return []

    if missing and before["model_card_status"] == "present":
        change = "card_removed"
        summary = "The model card that was present at the base ref is gone."
        status = "missing"
    elif evidence_changed and missing:
        change = "evidence_changed"
        summary = "The detected evidence changed, and there is still no model card."
        status = "missing"
    elif evidence_changed and not card_changed:
        change = "card_stale"
        summary = (
            "The detected evidence changed and the model card content did not. "
            "Article 11 asks that technical documentation of a high-risk system be kept up to date. "
            "Confirm whether that article applies, and whether this card still matches the code."
        )
        status = "needs_review"
    elif evidence_changed and card_changed:
        change = "evidence_and_card_changed"
        summary = "The detected evidence and the model card both changed. Read them together."
        status = "needs_review"
    else:
        change = "card_changed"
        summary = "The model card changed and the detected evidence did not."
        status = "needs_review"
    return [_finding(after, change=change, status=status, summary=summary)]


def _finding(component: dict, change: str, status: str, summary: str) -> dict:
    citation_ids: list[str] = []
    for hint in component["review_hints"]:
        for citation_id in hint["citation_ids"]:
            if citation_id not in citation_ids:
                citation_ids.append(citation_id)
    for citation_id in component["documentation_citation_ids"]:
        if citation_id not in citation_ids:
            citation_ids.append(citation_id)
    return {
        "component_id": component["id"],
        "path": component["path"],
        "framework": component["framework"],
        "change": change,
        "status": status,
        "summary": summary,
        "model_card_status": component["model_card_status"],
        "citation_ids": citation_ids,
    }


def _evidence_key(component: dict) -> tuple[tuple[str, str], ...]:
    return tuple((item["kind"], item["text"]) for item in component["evidence"])


def _scan_ref(repo: Path, rev: str) -> dict:
    raw = _git_bytes(repo, "archive", rev)
    temp = Path(tempfile.mkdtemp(prefix="flyleaf-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
            archive.extractall(temp, **kwargs)
        return scan_path(temp)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _git_root(start: Path) -> Path:
    return Path(_git(start, "rev-parse", "--show-toplevel"))


def _rev_parse(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", ref)


def _git(repo: Path, *args: str) -> str:
    return _run(repo, args, text=True).strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return _run(repo, args, text=False)


def _run(repo: Path, args: tuple[str, ...], text: bool):
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=text,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr or exc.stdout or "git failed"
        if isinstance(message, bytes):
            message = message.decode(errors="replace")
        raise GitError(str(message).strip()) from exc
    return completed.stdout
