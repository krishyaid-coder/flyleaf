# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Render inventories, briefs, and citation entries."""

import json

from flyleaf import DISCLAIMER
from flyleaf.citations import CHANGELOG, CITATIONS, PACK_VERSION, citation_payload


def render(document: dict, output_format: str) -> str:
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


def _component_lines(component: dict, citations: dict, pack: str) -> list[str]:
    card = component["model_card_status"]
    if component["model_card_path"]:
        card = f"{card} (`{component['model_card_path']}`)"
    lines = [
        f"## {component['path']} ({component['framework']})",
        "",
        f"- Category: {component['category']}",
        f"- Role hint: {component['role_hint']}",
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
    pack = brief["citation_pack"]["version"]
    head = brief["head"]
    head_line = head["ref"]
    if head.get("dirty"):
        head_line = f"{head_line} (uncommitted changes)"
    lines = [
        "# flyleaf brief",
        "",
        DISCLAIMER,
        "",
        f"Citation pack: {pack}",
        "",
        f"Base: {brief['base']['ref']} ({brief['base']['rev']})",
        f"Head: {head_line}",
        "",
        f"Findings: {len(findings)}",
        "",
    ]
    if not findings:
        lines.append("No compliance-relevant change.")
        lines.append("")
        return "\n".join(lines)
    for finding in findings:
        lines.extend(
            [
                f"## {finding['path']} ({finding['framework']})",
                "",
                f"- Change: {finding['change']}",
                f"- Status: {finding['status']}",
                f"- Model card: {finding['model_card_status']}",
                f"- {finding['summary']}",
                "- Read:",
            ]
        )
        lines.extend(_citation_lines(finding["citation_ids"], brief["citations"], pack))
        lines.append("")
    return "\n".join(lines)


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
