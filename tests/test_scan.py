# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

from typer.testing import CliRunner

from flyleaf import __version__
from flyleaf.cli import app
from flyleaf.scan import scan_path

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "import openai\n"
        "from langchain_openai import ChatOpenAI\n"
        "import requests\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "torch==2.4.0\nrequests==2.32.0\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "sample"\n'
        "dependencies = [\n"
        '  "scikit-learn>=1.4",\n'
        "]\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@anthropic-ai/sdk": "^0.30.0", "leftpad": "1.0.0"}}),
        encoding="utf-8",
    )
    card_dir = tmp_path / "models"
    card_dir.mkdir()
    (card_dir / "carded.py").write_text("import transformers\n", encoding="utf-8")
    (card_dir / "MODEL_CARD.md").write_text("# card\n", encoding="utf-8")
    (tmp_path / "noise.py").write_text("import json\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def (\n", encoding="utf-8")
    return tmp_path


def test_scan_groups_components_and_skips_unrelated_imports(tmp_path: Path) -> None:
    inventory = scan_path(_repo(tmp_path))
    ids = [component["id"] for component in inventory["components"]]
    assert ids == [
        "app.py:langchain",
        "app.py:openai",
        "models/carded.py:transformers",
        "package.json:anthropic",
        "pyproject.toml:scikit-learn",
        "requirements.txt:torch",
    ]
    by_id = {component["id"]: component for component in inventory["components"]}
    assert by_id["app.py:openai"]["category"] == "llm_api"
    assert by_id["app.py:openai"]["role_hint"] == "api_client"
    assert by_id["app.py:openai"]["model_card_status"] == "missing"
    assert by_id["app.py:openai"]["evidence"][0]["text"] == "import openai"
    assert "risk_tier" not in by_id["app.py:openai"]
    assert by_id["models/carded.py:transformers"]["model_card_status"] == "present"
    assert by_id["models/carded.py:transformers"]["model_card_path"] == "models/MODEL_CARD.md"
    assert by_id["pyproject.toml:scikit-learn"]["review_hints"][0]["id"] == "use_case"
    assert by_id["pyproject.toml:scikit-learn"]["review_hints"][0]["citation_ids"] == ["art-6-annex-iii"]
    assert by_id["app.py:openai"]["documentation_citation_ids"] == ["art-11-annex-iv", "art-113-application"]
    assert inventory["citation_pack"]["version"] == "2026.07.27"
    assert "art-11-annex-iv" in inventory["citations"]
    assert inventory["citations"]["art-50-interaction"]["source_url"].startswith("https://eur-lex.europa.eu/")
    assert inventory["disclaimer"]
    assert any(warning["path"] == "broken.py" for warning in inventory["warnings"])


def test_google_import_from_alias(tmp_path: Path) -> None:
    (tmp_path / "gen.py").write_text("from google import genai\n", encoding="utf-8")
    inventory = scan_path(tmp_path)
    assert [component["framework"] for component in inventory["components"]] == ["google-genai"]


def test_cli_writes_markdown_without_failing_on_findings(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "out" / "inventory.md"
    result = runner.invoke(app, ["scan", str(repo), "--format", "markdown", "-o", str(output)])
    assert result.exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert "not legal advice" in text
    assert "app.py" in text
    assert "Citation pack: 2026.07.27" in text
    assert "Article 11(1) and Annex IV" in text
    assert "\u2014" not in text
    assert "No AI libraries detected." not in text


def test_cli_missing_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path / "missing")])
    assert result.exit_code == 2


def test_version_flag_prints_the_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_pyproject_keyword_is_not_the_evidence_line(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "sample"\n'
        'keywords = ["claude", "skills", "linter", "anthropic", "agent"]\n'
        "dependencies = []\n"
        "\n"
        "[project.optional-dependencies]\n"
        "eval = [\n"
        '  "anthropic>=0.30.0",\n'
        "]\n",
        encoding="utf-8",
    )
    inventory = scan_path(tmp_path)
    evidence = inventory["components"][0]["evidence"][0]["text"]
    assert "anthropic>=0.30.0" in evidence
    assert "keywords" not in evidence


def test_keyword_alone_is_not_a_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "sample"\n'
        'keywords = ["anthropic", "agent"]\n'
        'dependencies = ["PyYAML>=6"]\n',
        encoding="utf-8",
    )
    inventory = scan_path(tmp_path)
    assert inventory["components"] == []


def test_notebook_code_cells_are_scanned_and_binaries_are_quiet(tmp_path: Path) -> None:
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {"cell_type": "markdown", "source": ["This notebook imports torch for training.\n"]},
            {"cell_type": "code", "source": ["%pip install torch\n", "import torch\n"]},
            {"cell_type": "code", "source": ["from transformers import AutoModel\n"]},
        ],
    }
    (tmp_path / "train.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    inventory = scan_path(tmp_path)
    frameworks = [component["framework"] for component in inventory["components"]]
    assert frameworks == ["torch", "transformers"]
    assert inventory["warnings"] == []
    torch_evidence = inventory["components"][0]["evidence"][0]["text"]
    assert torch_evidence == "import torch"
