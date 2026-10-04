# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Compare two inventories and list documentation changes with citations."""

import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path

from flyleaf import DISCLAIMER, __version__
from flyleaf import baseline as baseline_store
from flyleaf import severity as severity_grades
from flyleaf import waivers as waiver_store
from flyleaf.citations import pack_meta, payloads_for
from flyleaf.scan import SCHEMA_VERSION, scan_path


class GitError(Exception):
    """The repository could not be read with git."""


def build_brief(
    start: Path,
    base: str | None,
    head: str | None,
    use_baseline: bool = False,
    today: date | None = None,
) -> dict:
    """Diff a base state against a head state.

    The base is a git ref, or the recorded baseline when `use_baseline` is set.
    The head is a git ref, or the working tree when `head` is omitted.
    """
    if not start.exists():
        raise FileNotFoundError(start)
    repo = _git_root(start)
    now = today or baseline_store.today()

    if use_baseline:
        document = baseline_store.read_baseline(repo)
        base_inventory = document["inventory"]
        base_meta = baseline_store.describe(document)
    else:
        base_rev = _rev_parse(repo, base or "HEAD")
        base_inventory = _scan_ref(repo, base_rev)
        base_meta = {"ref": base, "rev": base_rev}

    if head is None:
        head_meta = {
            "ref": "working tree",
            "rev": _rev_parse(repo, "HEAD"),
            "dirty": bool(_git(repo, "status", "--porcelain")),
        }
        head_inventory = scan_path(repo)
    else:
        head_rev = _rev_parse(repo, head)
        head_meta = {"ref": head, "rev": head_rev, "dirty": False}
        head_inventory = _scan_ref(repo, head_rev)

    loaded, warnings = waiver_store.load_waivers(repo)
    findings, waived = _partition(_diff(base_inventory, head_inventory), loaded, now)
    findings, system_waived = _partition(_rollup(findings), loaded, now)
    waived.extend(system_waived)
    warnings.extend(_expiry_warnings(waived, now))

    citation_ids: set[str] = set()
    for finding in findings + waived:
        citation_ids.update(finding["citation_ids"])

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "brief",
        "tool": {"name": "flyleaf", "version": __version__},
        "disclaimer": DISCLAIMER,
        "severity_note": severity_grades.SEVERITY_NOTE,
        "citation_pack": pack_meta(),
        "citations": payloads_for(citation_ids),
        "repository": str(repo),
        "as_of": now.isoformat(),
        "base": base_meta,
        "head": head_meta,
        "systems": head_inventory.get("systems", []),
        "findings": findings,
        "waived": waived,
        "warnings": warnings,
    }


def highest_severity(brief: dict) -> str | None:
    """The worst severity among active findings, or None when the brief is quiet."""
    worst: str | None = None
    for finding in brief["findings"]:
        if worst is None or severity_grades.at_least(finding["severity"], worst):
            worst = finding["severity"]
    return worst


def _partition(
    findings: list[dict],
    waivers: list[waiver_store.Waiver],
    today: date,
) -> tuple[list[dict], list[dict]]:
    """Split findings into active and waived.

    An expired waiver does not suppress. The finding returns for review and
    says which waiver lapsed.
    """
    active: list[dict] = []
    waived: list[dict] = []
    for finding in findings:
        waiver = waiver_store.match(waivers, finding["component_id"], finding["change"])
        if waiver is None:
            active.append(finding)
            continue
        payload = waiver.payload(today)
        if waiver.days_left(today) < 0:
            finding["waiver"] = payload
            finding["waiver_state"] = "expired"
            finding["summary"] = (
                f"{finding['summary']} A waiver by {waiver.approved_by} expired on "
                f"{waiver.expires.isoformat()}, so this is open again."
            )
            active.append(finding)
        else:
            finding["waiver"] = payload
            finding["waiver_state"] = "active"
            waived.append(finding)
    return active, waived


def _expiry_warnings(waived: list[dict], today: date) -> list[str]:
    warnings: list[str] = []
    for finding in waived:
        waiver = finding["waiver"]
        days = waiver["days_left"]
        if days <= waiver_store.EXPIRY_WARNING_DAYS:
            warnings.append(
                f"Waiver for {finding['component_id']} expires on {waiver['expires']} "
                f"in {days} day(s). Renew it or close the finding."
            )
    return warnings


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
    return _sorted(findings)


def _sorted(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda item: (-severity_grades.rank(item["severity"]), item["path"], item["framework"]),
    )


def _rollup(findings: list[dict]) -> list[dict]:
    """Collapse the findings of a declared system into one.

    Components are the evidence. A system is what a person documents, so when
    the repository declares one, the system is what the brief reports.
    """
    grouped: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    for finding in findings:
        name = finding.get("system")
        if name:
            grouped.setdefault(name, []).append(finding)
        else:
            standalone.append(finding)
    rolled = [_system_finding(name, members) for name, members in grouped.items()]
    return _sorted(standalone + rolled)


def _system_finding(name: str, members: list[dict]) -> dict:
    lead = max(members, key=lambda item: severity_grades.rank(item["severity"]))
    citation_ids: list[str] = []
    for member in members:
        for citation_id in member["citation_ids"]:
            if citation_id not in citation_ids:
                citation_ids.append(citation_id)
    frameworks = sorted({member["framework"] for member in members})
    changes = sorted({member["change"] for member in members})
    missing = any(member["model_card_status"] == "missing" for member in members)
    if len(members) == 1:
        summary = f"System '{name}': {lead['summary']}"
    else:
        summary = (
            f"System '{name}': {len(members)} components changed "
            f"({', '.join(changes)}). {lead['summary']}"
        )
    return {
        "kind": "system",
        "component_id": f"system:{name}",
        "system": name,
        "path": lead["path"],
        "line": lead["line"],
        "framework": ", ".join(frameworks),
        "frameworks": frameworks,
        "change": lead["change"],
        "changes": changes,
        "impact": "runtime"
        if any(member["impact"] == "runtime" for member in members)
        else "documentation",
        "severity": lead["severity"],
        "status": "missing" if missing else "needs_review",
        "summary": summary,
        "model_card_status": "missing" if missing else "present",
        "citation_ids": citation_ids,
        "members": [_member(member) for member in members],
        "waiver": None,
        "waiver_state": "none",
    }


def _member(finding: dict) -> dict:
    return {
        "component_id": finding["component_id"],
        "path": finding["path"],
        "line": finding["line"],
        "framework": finding["framework"],
        "change": finding["change"],
        "impact": finding["impact"],
        "severity": finding["severity"],
    }


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
            "This component was in the base state and is absent from the head state. "
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
        summary = "The model card that was present in the base state is gone."
        status = "missing"
    elif before["model_card_status"] == "missing" and not missing:
        change = "card_added"
        summary = (
            "A model card appeared for this component. "
            "Confirm that it describes this component and not only its neighbours."
        )
        status = "needs_review"
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
    documented = component["model_card_status"] == "present"
    impact, level = severity_grades.grade(change, documented)
    evidence = component["evidence"]
    return {
        "kind": "component",
        "component_id": component["id"],
        "path": component["path"],
        "line": evidence[0]["line"] if evidence else 1,
        "framework": component["framework"],
        "system": component.get("system"),
        "change": change,
        "impact": impact,
        "severity": level,
        "status": status,
        "summary": summary,
        "model_card_status": component["model_card_status"],
        "citation_ids": citation_ids,
        "waiver": None,
        "waiver_state": "none",
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
