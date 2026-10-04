# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

import subprocess
from datetime import date
from pathlib import Path

from flyleaf.brief import build_brief
from flyleaf.card import write_cards
from flyleaf.scan import scan_path

TODAY = date(2026, 10, 4)

SUPPORT_BOT = """
[[system]]
name = "support-bot"
owner = "platform@example.com"
card = "docs/cards/support-bot.md"
includes = ["chatbot.py", "summarizer.py", "pyproject.toml"]
"""


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tree(repo: Path, systems: str = SUPPORT_BOT) -> Path:
    _write(repo, "pyproject.toml", '[project]\nname = "bot"\ndependencies = ["openai>=1.0.0"]\n')
    _write(repo, "chatbot.py", "import openai\n")
    _write(repo, "summarizer.py", "import openai\n")
    _write(repo, ".flyleaf/systems.toml", systems)
    return repo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=dev@example.com", "-c", "user.name=Flyleaf", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(repo: Path, systems: str = SUPPORT_BOT) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _write(repo, "readme.txt", "base\n")
    _write(repo, ".flyleaf/systems.toml", systems)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    _tree(repo, systems)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add bot")
    return repo, base


def test_declared_system_claims_its_components(tmp_path: Path) -> None:
    inventory = scan_path(_tree(tmp_path))
    assert [component["system"] for component in inventory["components"]] == [
        "support-bot",
        "support-bot",
        "support-bot",
    ]
    system = inventory["systems"][0]
    assert system["name"] == "support-bot"
    assert system["owner"] == "platform@example.com"
    assert system["frameworks"] == ["openai"]
    assert len(system["component_ids"]) == 3
    assert system["model_card_status"] == "missing"


def test_one_declared_card_documents_every_component_in_the_system(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _write(repo, "docs/cards/support-bot.md", "# support bot\n")
    inventory = scan_path(repo)
    assert inventory["systems"][0]["model_card_status"] == "present"
    for component in inventory["components"]:
        assert component["model_card_status"] == "present"
        assert component["model_card_path"] == "docs/cards/support-bot.md"


def test_a_file_outside_the_includes_stands_alone(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _write(repo, "labs/experiment.py", "import torch\n")
    inventory = scan_path(repo)
    loose = [item for item in inventory["components"] if item["system"] is None]
    assert [item["id"] for item in loose] == ["labs/experiment.py:torch"]


def test_brief_reports_one_finding_for_the_whole_system(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert len(brief["findings"]) == 1
    finding = brief["findings"][0]
    assert finding["kind"] == "system"
    assert finding["component_id"] == "system:support-bot"
    assert finding["severity"] == "high"
    assert finding["impact"] == "runtime"
    assert len(finding["members"]) == 3
    assert "3 components changed" in finding["summary"]
    assert "art-11-annex-iv" in finding["citation_ids"]


def test_a_component_waiver_shrinks_the_system_finding(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        ".flyleaf/waivers.toml",
        '[[waiver]]\n'
        'component = "summarizer.py:openai"\n'
        'reason = "Internal only, no customer sees it."\n'
        'approved_by = "krishna@example.com"\n'
        'expires = "2027-01-01"\n',
    )
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert len(brief["findings"]) == 1
    assert len(brief["findings"][0]["members"]) == 2
    assert len(brief["waived"]) == 1
    assert brief["waived"][0]["component_id"] == "summarizer.py:openai"


def test_a_system_waiver_covers_the_rollup(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        ".flyleaf/waivers.toml",
        '[[waiver]]\n'
        'component = "system:support-bot"\n'
        'reason = "Card lands with the 1.3 release."\n'
        'approved_by = "krishna@example.com"\n'
        'expires = "2027-01-01"\n',
    )
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert brief["findings"] == []
    assert len(brief["waived"]) == 1
    waived = brief["waived"][0]
    assert waived["component_id"] == "system:support-bot"
    assert waived["waiver_state"] == "active"


def test_a_malformed_entry_is_reported_and_claims_nothing(tmp_path: Path) -> None:
    inventory = scan_path(_tree(tmp_path, '[[system]]\nname = "support-bot"\n'))
    assert inventory["systems"] == []
    assert all(component["system"] is None for component in inventory["components"])
    assert any("missing includes" in warning["message"] for warning in inventory["warnings"])


def test_overlapping_systems_give_the_file_to_the_first(tmp_path: Path) -> None:
    systems = (
        '[[system]]\nname = "first"\nincludes = ["chatbot.py"]\n'
        '[[system]]\nname = "second"\nincludes = ["*.py"]\n'
    )
    inventory = scan_path(_tree(tmp_path, systems))
    by_path = {item["path"]: item["system"] for item in inventory["components"]}
    assert by_path["chatbot.py"] == "first"
    assert by_path["summarizer.py"] == "second"
    assert by_path["pyproject.toml"] is None
    assert any("Claimed by first, second" in warning["message"] for warning in inventory["warnings"])


def test_a_system_claiming_nothing_warns(tmp_path: Path) -> None:
    systems = SUPPORT_BOT + '\n[[system]]\nname = "ghost"\nincludes = ["nowhere/*"]\n'
    inventory = scan_path(_tree(tmp_path, systems))
    assert any(
        "System 'ghost' claims no detected component" in warning["message"]
        for warning in inventory["warnings"]
    )


def test_card_writes_one_scaffold_for_the_system(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    _write(repo, "labs/experiment.py", "import torch\n")
    written = write_cards(repo, repo / "cards")
    names = sorted(path.relative_to(repo / "cards").as_posix() for path in written)
    assert names == ["labs/experiment.py.torch.md", "support-bot.md"]
    text = (repo / "cards" / "support-bot.md").read_text(encoding="utf-8")
    assert "System: `support-bot`" in text
    assert "Owner: platform@example.com" in text
    assert "`chatbot.py` (openai)" in text
    assert "`summarizer.py` (openai)" in text
    assert "Article 11(1) and Annex IV" in text
    assert "\u2014" not in text


def test_a_generated_scaffold_does_not_count_as_documentation(tmp_path: Path) -> None:
    repo = _tree(tmp_path)
    write_cards(repo, repo / "cards")
    inventory = scan_path(repo)
    assert inventory["systems"][0]["model_card_status"] == "missing"
