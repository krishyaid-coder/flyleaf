# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from typer.testing import CliRunner

from flyleaf.card import write_cards
from flyleaf.cli import app

runner = CliRunner()


def test_card_scaffold_cites_the_pack_and_skips_existing_files(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import openai\n", encoding="utf-8")
    output = tmp_path / "cards"
    written = write_cards(tmp_path, output)
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "Citation pack: 2026.07.27" in text
    assert "Article 11(1) and Annex IV" in text
    assert "Annex III category, if any." in text
    assert "\u2014" not in text
    assert write_cards(tmp_path, output) == []

    result = runner.invoke(app, ["cite", "art-11-annex-iv"])
    assert result.exit_code == 0
    assert "32024R1689" in result.stdout
    assert "kept up to date" in result.stdout

    missing = runner.invoke(app, ["cite", "not-a-real-id"])
    assert missing.exit_code == 2


def test_readme_has_architecture_diagrams_and_no_em_dash() -> None:
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
    assert readme.count("```mermaid") >= 2
    assert "\u2014" not in readme
