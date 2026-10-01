# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from flyleaf.brief import build_brief
from flyleaf.cli import app

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=dev@example.com", "-c", "user.name=Flyleaf", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _init(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True, text=True)
    (repo / "readme.txt").write_text("base\n", encoding="utf-8")
    _commit(repo, "init")


def test_brief_flags_a_new_component_as_missing(tmp_path: Path) -> None:
    _init(tmp_path)
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(tmp_path, "add client")

    brief = build_brief(tmp_path, base, "HEAD")
    assert len(brief["findings"]) == 1
    finding = brief["findings"][0]
    assert finding["change"] == "added"
    assert finding["status"] == "missing"
    assert finding["component_id"] == "app.py:openai"
    assert "art-11-annex-iv" in finding["citation_ids"]
    assert "art-3-deployer" in finding["citation_ids"]
    assert "violated" not in finding["summary"].lower()
    assert brief["citation_pack"]["version"] == "2026.07.27"
    assert brief["citations"]["art-11-annex-iv"]["celex"] == "32024R1689"


def test_brief_flags_a_stale_card_when_evidence_changes(tmp_path: Path) -> None:
    _init(tmp_path)
    (tmp_path / "app.py").write_text("import openai\n", encoding="utf-8")
    (tmp_path / "MODEL_CARD.md").write_text("# card\n", encoding="utf-8")
    _commit(tmp_path, "carded")
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "app.py").write_text("from openai import OpenAI\n", encoding="utf-8")
    _commit(tmp_path, "change call")

    brief = build_brief(tmp_path, base, "HEAD")
    finding = brief["findings"][0]
    assert finding["change"] == "card_stale"
    assert finding["status"] == "needs_review"
    assert "art-11-annex-iv" in finding["citation_ids"]


def test_brief_is_quiet_when_nothing_relevant_changed(tmp_path: Path) -> None:
    _init(tmp_path)
    (tmp_path / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(tmp_path, "add client")
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    _commit(tmp_path, "notes")

    brief = build_brief(tmp_path, base, "HEAD")
    assert brief["findings"] == []


def test_brief_cli_on_a_plain_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["brief", "HEAD", "--path", str(tmp_path)])
    assert result.exit_code == 2
