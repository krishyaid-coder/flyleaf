# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Write model-card scaffolds. A person completes the blanks."""

import re
from pathlib import Path

from flyleaf.citations import citation_payload
from flyleaf.scan import scan_path


def write_cards(path: Path, output: Path, force: bool = False) -> list[Path]:
    """Write one scaffold per declared system, then one per loose component.

    Existing files are left in place unless `force` is set. A scaffold is
    written under `output`, never at a declared card path, so an unfinished
    draft is never counted as documentation.
    """
    inventory = scan_path(path)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for system in inventory.get("systems") or []:
        members = [
            component
            for component in inventory["components"]
            if component["system"] == system["name"]
        ]
        if not members:
            continue
        destination = output / f"{_slug(system['name'])}.md"
        if destination.exists() and not force:
            continue
        destination.write_text(_render_system(system, members, inventory), encoding="utf-8")
        written.append(destination)

    for component in inventory["components"]:
        if component["system"]:
            continue
        destination = output / _filename(component["id"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not force:
            continue
        destination.write_text(_render(component, inventory), encoding="utf-8")
        written.append(destination)
    return written


def _filename(component_id: str) -> Path:
    return Path(component_id.replace(":", ".") + ".md")


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "system"


def _render(component: dict, inventory: dict) -> str:
    evidence = "\n".join(_evidence_lines(component))
    citation_ids = _citation_ids([component])
    return _page(
        identity=[f"Component: `{component['id']}`"],
        model_section=f"Framework: {component['framework']}\n\nEvidence:\n\n{evidence}",
        hints="\n".join(f"- {hint['text']}" for hint in component["review_hints"]),
        sources="\n\n".join(_source(inventory, item) for item in citation_ids),
        pack=inventory["citation_pack"]["version"],
    )


def _render_system(system: dict, members: list[dict], inventory: dict) -> str:
    identity = [f"System: `{system['name']}`"]
    if system["owner"]:
        identity.append(f"Owner: {system['owner']}")
    if system["card"]:
        identity.append(f"Declared card path: `{system['card']}`")
    identity.append(
        "This system is declared in `.flyleaf/systems.toml`. The components below "
        "are the evidence flyleaf found in it. One system, one card."
    )

    blocks = [f"Frameworks: {', '.join(system['frameworks'])}", "", "Components:", ""]
    for component in members:
        blocks.append(f"### `{component['path']}` ({component['framework']})")
        blocks.append("")
        blocks.extend(_evidence_lines(component))
        blocks.append("")
    hints: list[str] = []
    for component in members:
        for hint in component["review_hints"]:
            line = f"- {hint['text']}"
            if line not in hints:
                hints.append(line)
    return _page(
        identity=identity,
        model_section="\n".join(blocks).rstrip(),
        hints="\n".join(hints),
        sources="\n\n".join(_source(inventory, item) for item in _citation_ids(members)),
        pack=inventory["citation_pack"]["version"],
    )


def _evidence_lines(component: dict) -> list[str]:
    return [
        f"- line {item['line']}: `{item['text']}` ({item['kind']})"
        for item in component["evidence"]
    ]


def _citation_ids(components: list[dict]) -> list[str]:
    citation_ids: list[str] = []
    for component in components:
        for citation_id in component["documentation_citation_ids"]:
            if citation_id not in citation_ids:
                citation_ids.append(citation_id)
    for component in components:
        for hint in component["review_hints"]:
            for citation_id in hint["citation_ids"]:
                if citation_id not in citation_ids:
                    citation_ids.append(citation_id)
    return citation_ids


def _page(identity: list[str], model_section: str, hints: str, sources: str, pack: str) -> str:
    header = "\n\n".join(identity)
    return (
        f"# Model card\n\n"
        f"{header}\n\n"
        f"Citation pack: {pack}\n\n"
        f"flyleaf prepared this page. A person completes it. "
        f"The scaffold does not decide the use case, the legal role, or whether a duty applies.\n\n"
        f"## Purpose\n\n"
        f"What this system is for:\n\n"
        f"## Role\n\n"
        f"Who provides the model, and who deploys the system. Read Article 3(3) and Article 3(4).\n\n"
        f"Provider or deployer:\n\n"
        f"## Data\n\n"
        f"Training data, prompts, and personal data involved:\n\n"
        f"## Model\n\n"
        f"{model_section}\n\n"
        f"## Limitations\n\n"
        f"Known limits and failure modes:\n\n"
        f"## Human oversight\n\n"
        f"Who reviews outputs before they affect a person:\n\n"
        f"## Use case\n\n"
        f"Annex III category, if any. Leave this blank when none applies. "
        f"The library name does not answer it.\n\n"
        f"## Areas the scan asked a person to review\n\n"
        f"{hints}\n\n"
        f"## Sources\n\n"
        f"{sources}\n"
    )


def _source(inventory: dict, citation_id: str) -> str:
    citation = inventory["citations"].get(citation_id) or citation_payload(citation_id)
    return (
        f"### {citation['pinpoint']}\n\n"
        f"{citation['instrument']} ({citation['celex']}), status {citation['status']}.\n\n"
        f"> {citation['quote']}\n\n"
        f"{citation['note']}\n\n"
        f"{citation['source_url']}"
    )
