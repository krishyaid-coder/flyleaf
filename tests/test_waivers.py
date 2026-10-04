# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

from typer.testing import CliRunner

from flyleaf.brief import build_brief
from flyleaf.cli import app

runner = CliRunner()
TODAY = date(2026, 10, 4)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=dev@example.com", "-c", "user.name=Flyleaf", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo_with_new_component(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "readme.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "app.py").write_text("import openai\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add client")
    return tmp_path, base


def _write_waiver(repo: Path, expires: date, change: str | None = None, **overrides: str) -> None:
    fields = {
        "component": "app.py:openai",
        "reason": "Prototype only, card due with the release.",
        "approved_by": "krishna@example.com",
        "expires": expires.isoformat(),
    }
    fields.update(overrides)
    lines = ["[[waiver]]"]
    for key, value in fields.items():
        lines.append(f'{key} = "{value}"')
    if change:
        lines.append(f'change = "{change}"')
    directory = repo / ".flyleaf"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "waivers.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_new_undocumented_component_is_high_and_runtime(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    finding = brief["findings"][0]
    assert finding["severity"] == "high"
    assert finding["impact"] == "runtime"
    assert finding["line"] == 1
    assert finding["waiver_state"] == "none"
    assert brief["waived"] == []


def test_valid_waiver_suppresses_but_stays_auditable(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    _write_waiver(repo, TODAY + timedelta(days=90))
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert brief["findings"] == []
    assert len(brief["waived"]) == 1
    waived = brief["waived"][0]
    assert waived["waiver_state"] == "active"
    assert waived["waiver"]["approved_by"] == "krishna@example.com"
    assert waived["waiver"]["days_left"] == 90
    assert "Prototype only" in waived["waiver"]["reason"]


def test_expired_waiver_reopens_the_finding(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    _write_waiver(repo, TODAY - timedelta(days=1))
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert brief["waived"] == []
    finding = brief["findings"][0]
    assert finding["waiver_state"] == "expired"
    assert "expired on 2026-10-03" in finding["summary"]


def test_waiver_without_a_reason_is_ignored_and_reported(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    directory = repo / ".flyleaf"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "waivers.toml").write_text(
        '[[waiver]]\ncomponent = "app.py:openai"\nexpires = "2027-01-01"\n',
        encoding="utf-8",
    )
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert len(brief["findings"]) == 1
    assert brief["waived"] == []
    assert any("missing reason, approved_by" in warning for warning in brief["warnings"])


def test_waiver_nearing_expiry_warns(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    _write_waiver(repo, TODAY + timedelta(days=3))
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert brief["waived"]
    assert any("expires on" in warning for warning in brief["warnings"])


def test_waiver_for_another_change_does_not_suppress(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    _write_waiver(repo, TODAY + timedelta(days=30), change="card_stale")
    brief = build_brief(repo, base, "HEAD", today=TODAY)
    assert len(brief["findings"]) == 1
    assert brief["waived"] == []


def test_baseline_round_trip_and_fail_on_exit_code(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "readme.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")

    recorded = runner.invoke(
        app, ["baseline", "--path", str(tmp_path), "--approved-by", "krishna@example.com"]
    )
    assert recorded.exit_code == 0
    assert (tmp_path / ".flyleaf" / "baseline.json").is_file()

    quiet = runner.invoke(app, ["brief", "--baseline", "--path", str(tmp_path), "--fail-on", "high"])
    assert quiet.exit_code == 0

    (tmp_path / "app.py").write_text("import openai\n", encoding="utf-8")
    loud = runner.invoke(app, ["brief", "--baseline", "--path", str(tmp_path), "--fail-on", "high"])
    assert loud.exit_code == 1

    warn_only = runner.invoke(app, ["brief", "--baseline", "--path", str(tmp_path)])
    assert warn_only.exit_code == 0
    document = json.loads(warn_only.stdout)
    assert document["base"]["approved_by"] == "krishna@example.com"
    assert document["findings"][0]["severity"] == "high"


def test_brief_without_base_or_baseline_is_an_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["brief", "--path", str(tmp_path)])
    assert result.exit_code == 2


def test_sarif_output_carries_level_and_location(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    result = runner.invoke(app, ["brief", base, "HEAD", "--path", str(repo), "--format", "sarif"])
    assert result.exit_code == 0
    sarif = json.loads(result.stdout)
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "flyleaf"
    finding = run["results"][0]
    assert finding["level"] == "error"
    assert finding["ruleId"] == "flyleaf/added"
    location = finding["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "app.py"
    assert location["region"]["startLine"] == 1
    assert "Article 11(1) and Annex IV" in finding["message"]["text"]


def test_markdown_brief_shows_severity_and_waivers(tmp_path: Path) -> None:
    repo, base = _repo_with_new_component(tmp_path)
    _write_waiver(repo, TODAY + timedelta(days=365))
    result = runner.invoke(app, ["brief", base, "HEAD", "--path", str(repo), "--format", "markdown"])
    assert result.exit_code == 0
    assert "not legal risk" in result.stdout
    assert "## Waived" in result.stdout
    assert "krishna@example.com" in result.stdout
    assert "\u2014" not in result.stdout
