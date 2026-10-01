# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Write model-card scaffolds. A person completes the blanks."""

from pathlib import Path

from flyleaf.citations import citation_payload
from flyleaf.scan import scan_path


def write_cards(path: Path, output: Path, force: bool = False) -> list[Path]:
    """Write one scaffold per component under `output`.

    Existing files are left in place unless `force` is set.
    """
    inventory = scan_path(path)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for component in inventory["components"]:
        destination = output / _filename(component["id"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not force:
            continue
        destination.write_text(_render(component, inventory), encoding="utf-8")
        written.append(destination)
    return written


def _filename(component_id: str) -> Path:
    return Path(component_id.replace(":", ".") + ".md")


def _render(component: dict, inventory: dict) -> str:
    pack = inventory["citation_pack"]["version"]
    evidence = "\n".join(
        f"- line {item['line']}: `{item['text']}` ({item['kind']})" for item in component["evidence"]
    )
    citation_ids = list(component["documentation_citation_ids"])
    for hint in component["review_hints"]:
        for citation_id in hint["citation_ids"]:
            if citation_id not in citation_ids:
                citation_ids.append(citation_id)
    sources = "\n\n".join(_source(inventory, citation_id) for citation_id in citation_ids)
    hints = "\n".join(f"- {hint['text']}" for hint in component["review_hints"])
    return (
        f"# Model card\n\n"
        f"Component: `{component['id']}`\n\n"
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
        f"Framework: {component['framework']}\n\n"
        f"Evidence:\n\n"
        f"{evidence}\n\n"
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
