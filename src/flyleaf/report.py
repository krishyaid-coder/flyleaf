# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Render inventories, briefs, and citation entries."""

import json

from flyleaf import DISCLAIMER, __version__
from flyleaf.citations import CHANGELOG, CITATIONS, PACK_VERSION, citation_payload
from flyleaf.severity import SEVERITY_NOTE

FORMATS = ("json", "markdown", "sarif")
HOMEPAGE = "https://github.com/krishyaid-coder/flyleaf"
_SARIF_LEVEL = {"high": "error", "medium": "warning", "low": "note"}


def render(document: dict, output_format: str) -> str:
    if output_format == "sarif":
        if document.get("kind") != "brief":
            raise ValueError("sarif is available for brief only")
        return json.dumps(_sarif(document), indent=2) + "\n"
    if output_format == "json":
        return json.dumps(document, indent=2) + "\n"
    if output_format != "markdown":
        raise ValueError(f"unknown format: {output_format}")
    if document.get("kind") == "brief":
        return _brief_markdown(document)
    return _inventory_markdown(document)


def render_citations(citation_id: str | None, changelog: bool, output_format: str) -> str:
    if changelog:
        document = {"citation_pack": {"version": PACK_VERSION}, "changelog": list(CHANGELOG)}
    elif citation_id is None:
        document = {
            "citation_pack": {"version": PACK_VERSION},
            "citations": {item_id: citation_payload(item_id) for item_id in sorted(CITATIONS)},
        }
    else:
        if citation_id not in CITATIONS:
            raise KeyError(citation_id)
        document = {"citation_pack": {"version": PACK_VERSION}, "citations": {citation_id: citation_payload(citation_id)}}
    if output_format == "json":
        return json.dumps(document, indent=2) + "\n"
    if output_format != "markdown":
        raise ValueError(f"unknown format: {output_format}")
    return _citations_markdown(document, changelog)


def _inventory_markdown(inventory: dict) -> str:
    components = inventory["components"]
    pack = inventory["citation_pack"]["version"]
    lines = [
        "# flyleaf inventory",
        "",
        DISCLAIMER,
        "",
        f"Citation pack: {pack}",
        "",
        f"Components: {len(components)}",
        "",
    ]
    if not components:
        lines.append("No AI libraries detected.")
        lines.append("")
    lines.extend(_systems_lines(inventory))
    for component in components:
        lines.extend(_component_lines(component, inventory["citations"], pack))
    warnings = inventory["warnings"]
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- `{warning['path']}`: {warning['message']}")
        lines.append("")
    return "\n".join(lines)


def _systems_lines(inventory: dict) -> list[str]:
    systems = inventory.get("systems") or []
    components = inventory["components"]
    if not systems:
        return []
    unassigned = [item["id"] for item in components if not item["system"]]
    lines = ["## Systems", "", "Declared in `.flyleaf/systems.toml`. flyleaf does not infer them.", ""]
    for system in systems:
        card = system["model_card_path"] or system["model_card_status"]
        lines.append(f"### {system['name']}")
        lines.append("")
        lines.append(f"- Owner: {system['owner'] or 'not stated'}")
        lines.append(f"- Model card: {card}")
        lines.append(f"- Frameworks: {', '.join(system['frameworks']) or 'none detected'}")
        lines.append(f"- Components: {len(system['component_ids'])}")
        for component_id in system["component_ids"]:
            lines.append(f"  - `{component_id}`")
        lines.append("")
    lines.append(f"Components in no declared system: {len(unassigned)}")
    lines.append("")
    for component_id in unassigned:
        lines.append(f"- `{component_id}`")
    if unassigned:
        lines.append("")
    return lines


def _component_lines(component: dict, citations: dict, pack: str) -> list[str]:
    card = component["model_card_status"]
    if component["model_card_path"]:
        card = f"{card} (`{component['model_card_path']}`)"
    lines = [
        f"## {component['path']} ({component['framework']})",
        "",
        f"- Category: {component['category']}",
        f"- Role hint: {component['role_hint']}",
        f"- System: {component['system'] or 'none declared'}",
        f"- Model card: {card}",
        "- Evidence:",
    ]
    for item in component["evidence"]:
        lines.append(f"  - line {item['line']}: `{item['text']}` ({item['kind']})")
    lines.append("- Areas to review:")
    for hint in component["review_hints"]:
        lines.append(f"  - {hint['text']}")
        lines.extend(_citation_lines(hint["citation_ids"], citations, pack))
    lines.append("- Documentation:")
    lines.append(f"  - status {component['model_card_status']}")
    lines.extend(_citation_lines(component["documentation_citation_ids"], citations, pack))
    lines.append("")
    return lines


def _brief_markdown(brief: dict) -> str:
    findings = brief["findings"]
    waived = brief["waived"]
    pack = brief["citation_pack"]["version"]
    head = brief["head"]
    head_line = head["ref"]
    if head.get("dirty"):
        head_line = f"{head_line} (uncommitted changes)"
    base = brief["base"]
    base_line = base["ref"] or "HEAD"
    if base.get("recorded_at"):
        base_line = f"{base_line} (recorded {base['recorded_at']})"
    elif base.get("rev"):
        base_line = f"{base_line} ({base['rev']})"

    lines = [
        "# flyleaf brief",
        "",
        DISCLAIMER,
        "",
        SEVERITY_NOTE,
        "",
        f"Citation pack: {pack}",
        "",
        f"Base: {base_line}",
        f"Head: {head_line}",
        "",
        f"Findings: {len(findings)} ({_severity_tally(findings)})",
        f"Waived: {len(waived)}",
        "",
    ]
    if not findings:
        lines.append("No compliance-relevant change.")
        lines.append("")
    for finding in findings:
        lines.extend(_finding_lines(finding, brief["citations"], pack))
    if waived:
        lines.append("## Waived")
        lines.append("")
        for finding in waived:
            waiver = finding["waiver"]
            lines.append(
                f"- {_subject(finding)}, {finding['change']}, severity {finding['severity']}"
            )
            lines.append(
                f"  waived by {waiver['approved_by']} until {waiver['expires']} "
                f"({waiver['days_left']} day(s) left): {waiver['reason']}"
            )
        lines.append("")
    if brief["warnings"]:
        lines.append("## Warnings")
        lines.append("")
        for warning in brief["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    return "\n".join(lines)


def _subject(finding: dict) -> str:
    if finding.get("kind") == "system":
        return f"system {finding['system']} ({finding['framework']})"
    return f"{finding['path']} ({finding['framework']})"


def _finding_lines(finding: dict, citations: dict, pack: str) -> list[str]:
    lines = [
        f"## [{finding['severity']}] {_subject(finding)}",
        "",
        f"- Change: {finding['change']}",
        f"- Impact: {finding['impact']}",
        f"- Status: {finding['status']}",
        f"- Model card: {finding['model_card_status']}",
        f"- {finding['summary']}",
    ]
    if finding.get("waiver_state") == "expired":
        lines.append("- Waiver: expired")
    members = finding.get("members")
    if members:
        lines.append(f"- Components ({len(members)}):")
        for member in members:
            lines.append(
                f"  - `{member['path']}` line {member['line']} ({member['framework']}), "
                f"{member['change']}, severity {member['severity']}"
            )
    lines.append("- Read:")
    lines.extend(_citation_lines(finding["citation_ids"], citations, pack))
    lines.append("")
    return lines


def _severity_tally(findings: list[dict]) -> str:
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    return ", ".join(f"{level} {counts[level]}" for level in ("high", "medium", "low"))


def _sarif(brief: dict) -> dict:
    rules: dict[str, dict] = {}
    results: list[dict] = []
    for finding in brief["findings"]:
        rule_id = f"flyleaf/{finding['change']}"
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "name": finding["change"],
                "shortDescription": {"text": _rule_text(finding["change"])},
                "fullDescription": {"text": SEVERITY_NOTE},
                "helpUri": HOMEPAGE,
                "properties": {"impact": finding["impact"]},
            },
        )
        citations = ", ".join(
            brief["citations"][citation_id]["pinpoint"] for citation_id in finding["citation_ids"]
        )
        results.append(
            {
                "ruleId": rule_id,
                "level": _SARIF_LEVEL.get(finding["severity"], "warning"),
                "message": {"text": f"{finding['summary']} Read: {citations}."},
                "locations": _sarif_locations(finding),
                "properties": {
                    "severity": finding["severity"],
                    "impact": finding["impact"],
                    "status": finding["status"],
                    "component": finding["component_id"],
                    "system": finding.get("system"),
                },
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "flyleaf",
                        "version": __version__,
                        "informationUri": HOMEPAGE,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def _sarif_locations(finding: dict) -> list[dict]:
    """The lead location comes first, because GitHub annotates the first one."""
    places = [(finding["path"], finding["line"])]
    for member in finding.get("members") or []:
        place = (member["path"], member["line"])
        if place not in places:
            places.append(place)
    return [
        {
            "physicalLocation": {
                "artifactLocation": {"uri": path},
                "region": {"startLine": max(1, line)},
            }
        }
        for path, line in places
    ]


def _rule_text(change: str) -> str:
    return {
        "added": "A new AI component appeared.",
        "removed": "A detected AI component is gone.",
        "evidence_changed": "The detected AI code changed.",
        "card_stale": "The AI code changed and the model card did not.",
        "card_removed": "A model card was removed.",
        "card_added": "A model card appeared.",
        "card_changed": "A model card changed.",
        "evidence_and_card_changed": "The AI code and the model card both changed.",
    }.get(change, change)


def _citations_markdown(document: dict, changelog: bool) -> str:
    pack = document["citation_pack"]["version"]
    lines = ["# flyleaf citation pack", "", f"Version: {pack}", ""]
    if changelog:
        for entry in document["changelog"]:
            lines.append(f"## {entry['version']}")
            lines.append("")
            lines.append(entry["summary"])
            lines.append("")
        return "\n".join(lines)
    for citation in document["citations"].values():
        lines.extend(
            [
                f"## {citation['id']}",
                "",
                f"{citation['pinpoint']}",
                "",
                f"{citation['instrument']} ({citation['celex']}), status {citation['status']}.",
                "",
                f"> {citation['quote']}",
                "",
                citation["note"],
                "",
                citation["source_url"],
                "",
            ]
        )
    return "\n".join(lines)


def _citation_lines(citation_ids: list[str], citations: dict, pack: str) -> list[str]:
    lines: list[str] = []
    for citation_id in citation_ids:
        citation = citations[citation_id]
        lines.append(f"    - {citation['pinpoint']} ({citation['celex']}, pack {pack})")
        lines.append(f"      {citation['source_url']}")
    return lines
