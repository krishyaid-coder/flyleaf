# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

import subprocess
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from flyleaf.attribution import label, last_author
from flyleaf.brief import build_brief
from flyleaf.cli import app
from flyleaf.report import reviewer_of

runner = CliRunner()
TODAY = date(2026, 10, 7)


def _git(repo: Path, *args: str, author: str = "Rae <rae@example.com>") -> None:
    subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", "user.email=ci@example.com",
            "-c", "user.name=CI",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=None,
    )


def _commit(repo: Path, message: str, author: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message, f"--author={author}")


def _repo(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "readme.txt").write_text("base\n", encoding="utf-8")
    _commit(tmp_path, "init", "Rae <rae@example.com>")
    base = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    return tmp_path, base


def test_blame_names_the_author_of_the_change(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "add the client", "Nadia <nadia@example.com>")

    brief = build_brief(repo, base, "HEAD", today=TODAY)
    finding = brief["findings"][0]
    assert finding["author"]["email"] == "nadia@example.com"
    assert finding["author"]["name"] == "Nadia"
    assert finding["author"]["uncommitted"] is False
    assert finding["author"]["is_bot"] is False
    assert reviewer_of(finding) == "nadia@example.com"


def test_declared_owner_is_reported_alongside_the_author(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / ".flyleaf").mkdir()
    (repo / ".flyleaf" / "systems.toml").write_text(
        '[[system]]\nname = "bot"\nowner = "platform@example.com"\nincludes = ["app.py"]\n',
        encoding="utf-8",
    )
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "add the client", "Nadia <nadia@example.com>")

    brief = build_brief(repo, base, "HEAD", today=TODAY)
    finding = brief["findings"][0]
    assert finding["owner"] == "platform@example.com"
    assert finding["author"]["email"] == "nadia@example.com"
    assert finding["members"][0]["author"]["email"] == "nadia@example.com"


def test_a_bot_author_falls_back_to_the_declared_owner(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / ".flyleaf").mkdir()
    (repo / ".flyleaf" / "systems.toml").write_text(
        '[[system]]\nname = "bot"\nowner = "platform@example.com"\nincludes = ["*.toml", "app.py"]\n',
        encoding="utf-8",
    )
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "bump", "dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>")

    brief = build_brief(repo, base, "HEAD", today=TODAY)
    finding = brief["findings"][0]
    assert finding["author"]["is_bot"] is True
    # A bot cannot own a review, so the declared owner answers for it.
    assert reviewer_of(finding) == "platform@example.com"


def test_an_untracked_file_has_no_author(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")

    brief = build_brief(repo, base, None, today=TODAY)
    finding = brief["findings"][0]
    assert finding["author"] is None
    assert label(None) == "unknown"
    assert reviewer_of(finding) == "unassigned"


def test_an_uncommitted_edit_is_reported_as_not_yet_committed(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "add the client", "Nadia <nadia@example.com>")
    base = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    (repo / "app.py").write_text("from openai import OpenAI\n", encoding="utf-8")

    brief = build_brief(repo, base, None, today=TODAY)
    finding = brief["findings"][0]
    assert finding["author"]["uncommitted"] is True
    assert label(finding["author"]) == "uncommitted change"
    assert reviewer_of(finding) == "uncommitted change"


def test_no_blame_leaves_the_author_empty(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "add the client", "Nadia <nadia@example.com>")

    brief = build_brief(repo, base, "HEAD", today=TODAY, blame=False)
    assert brief["findings"][0]["author"] is None


def test_blame_on_a_missing_path_is_quiet(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    assert last_author(repo, "HEAD", "nowhere.py", 1) is None


def test_render_reproduces_every_format_from_one_scan(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "add the client", "Nadia <nadia@example.com>")

    saved = repo / "brief.json"
    first = runner.invoke(
        app, ["brief", base, "HEAD", "--path", str(repo), "--format", "json", "-o", str(saved)]
    )
    assert first.exit_code == 0

    as_markdown = runner.invoke(app, ["render", str(saved), "--format", "markdown"])
    assert as_markdown.exit_code == 0
    assert "nadia@example.com" in as_markdown.stdout

    as_sarif = runner.invoke(app, ["render", str(saved), "--format", "sarif"])
    assert as_sarif.exit_code == 0
    import json as _json

    results = _json.loads(as_sarif.stdout)["runs"][0]["results"]
    assert results[0]["properties"]["author"] == "nadia@example.com"

    direct = runner.invoke(
        app, ["brief", base, "HEAD", "--path", str(repo), "--format", "markdown"]
    )
    assert as_markdown.stdout == direct.stdout


def test_render_rejects_a_file_that_is_not_a_report(tmp_path: Path) -> None:
    stray = tmp_path / "notes.json"
    stray.write_text('{"kind": "shopping list"}', encoding="utf-8")
    assert runner.invoke(app, ["render", str(stray)]).exit_code == 2
    assert runner.invoke(app, ["render", str(tmp_path / "absent.json")]).exit_code == 2


def test_markdown_names_who_should_look(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    (repo / "app.py").write_text("import openai\n", encoding="utf-8")
    _commit(repo, "add the client", "Nadia <nadia@example.com>")

    result = runner.invoke(
        app, ["brief", base, "HEAD", "--path", str(repo), "--format", "markdown"]
    )
    assert result.exit_code == 0
    assert "## Who should look at this" in result.stdout
    assert "nadia@example.com" in result.stdout
    assert "Blame names a line, not a fault." in result.stdout
    assert "\u2014" not in result.stdout
