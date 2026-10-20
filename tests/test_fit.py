# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

from typer.testing import CliRunner

from flyleaf.cli import app
from flyleaf.fit import (
    awkward_pack,
    equal_length,
    fit,
    fit_document,
    random_scenarios,
    short_gems,
)

runner = CliRunner()


def _values(name: str) -> tuple[float, float, float]:
    scenarios = {"short gems": short_gems, "awkward pack": awkward_pack, "equal length": equal_length}
    label, budget, memories = scenarios[name]()
    density = fit(memories, budget, strategy="density").value_captured
    greedy = fit(memories, budget, strategy="greedy").value_captured
    similarity = fit(memories, budget, strategy="similarity").value_captured
    assert label == name
    return density, greedy, similarity


def test_short_gems_prefers_four_useful_items_over_the_lookalike() -> None:
    density, greedy, similarity = _values("short gems")
    assert density == greedy == 3.2
    assert similarity == 0.45
    _, budget, memories = short_gems()
    dropped = fit(memories, budget, strategy="density").dropped
    essay = next(item for item in dropped if item.id == "essay")
    assert "drops total value from 3.20 to 0.45" in essay.reason


def test_awkward_pack_is_where_greedy_and_density_split() -> None:
    density, greedy, similarity = _values("awkward pack")
    assert density == 8
    assert greedy == 6
    assert similarity == 6
    _, budget, memories = awkward_pack()
    kept = [item.id for item in fit(memories, budget, strategy="density").included]
    assert kept == ["pair-a", "pair-b"] or set(kept) == {"pair-a", "pair-b"}


def test_equal_length_is_where_packing_from_the_top_was_already_right() -> None:
    density, greedy, similarity = _values("equal length")
    assert density == greedy == similarity == 1.4


def test_density_is_never_behind_on_the_suite() -> None:
    scenarios = [short_gems(), awkward_pack(), equal_length(), *random_scenarios()]
    for _name, budget, memories in scenarios:
        density = fit(memories, budget, strategy="density").value_captured
        greedy = fit(memories, budget, strategy="greedy").value_captured
        similarity = fit(memories, budget, strategy="similarity").value_captured
        assert density + 1e-9 >= greedy
        assert density + 1e-9 >= similarity


def test_random_means_match_the_shipped_suite() -> None:
    rows = []
    for _name, budget, memories in random_scenarios():
        rows.append(
            (
                fit(memories, budget, strategy="density").value_captured,
                fit(memories, budget, strategy="greedy").value_captured,
                fit(memories, budget, strategy="similarity").value_captured,
            )
        )
    count = len(rows)
    assert round(sum(row[0] for row in rows) / count, 2) == 2.73
    assert round(sum(row[1] for row in rows) / count, 2) == 2.68
    assert round(sum(row[2] for row in rows) / count, 2) == 2.40


def test_a_tie_on_worth_keeps_the_smaller_pack() -> None:
    memories = [
        {"id": "long", "text": "long", "tokens": 5, "value": 5},
        {"id": "short", "text": "short", "tokens": 3, "value": 5},
    ]
    result = fit(memories, 5, strategy="density")
    assert [item.id for item in result.included] == ["short"]
    assert result.tokens_used == 3


def test_an_item_larger_than_the_budget_says_so() -> None:
    result = fit([{"id": "essay", "text": "too big", "tokens": 50, "value": 1}], 10)
    assert result.included == ()
    assert "more than the budget of 10" in result.dropped[0].reason


def test_brief_keeps_two_short_findings_instead_of_the_long_one_listed_first() -> None:
    brief = {
        "kind": "brief",
        "findings": [
            _finding("essay", "high", "e" * 400),
            _finding("gem-1", "high", "a" * 40),
            _finding("gem-2", "high", "b" * 40),
        ],
        "waived": [{"component_id": "old"}],
        "citations": {},
    }
    tokens = _tokens(brief)
    budget = tokens["essay"]
    assert tokens["gem-1"] + tokens["gem-2"] <= budget
    assert tokens["essay"] + tokens["gem-1"] > budget

    fitted = fit_document(brief, budget=budget, strategy="density")
    assert fitted["method"] == "exact"
    assert [item["id"] for item in fitted["included"]] == ["gem-1", "gem-2"]
    assert fitted["value"] == 6
    assert fitted["compared"]["similarity"]["value"] == 3
    assert fitted["waived_not_packed"] == 1
    assert "drops total value from 6.00 to 3.00" in fitted["dropped"][0]["reason"]


def test_similarity_follows_the_query_and_density_does_not() -> None:
    brief = {
        "kind": "brief",
        "findings": [
            _finding("essay", "low", "lisbon " + ("e" * 400)),
            _finding("gem", "high", "a" * 40),
        ],
        "citations": {},
    }
    tokens = _tokens(brief)
    budget = tokens["essay"]
    assert tokens["gem"] <= budget
    assert tokens["essay"] + tokens["gem"] > budget

    similarity = fit_document(brief, budget=budget, strategy="similarity", query="lisbon")
    density = fit_document(brief, budget=budget, strategy="density", query="lisbon")
    assert [item["id"] for item in similarity["included"]] == ["essay"]
    assert [item["id"] for item in density["included"]] == ["gem"]


def test_fit_command_prints_the_benchmark(tmp_path: Path) -> None:
    result = runner.invoke(app, ["fit", "--benchmark"])
    assert result.exit_code == 0
    assert "short gems" in result.stdout
    assert "awkward pack" in result.stdout
    assert "behind in 0" in result.stdout


def test_fit_command_reads_a_saved_brief(tmp_path: Path) -> None:
    path = tmp_path / "brief.json"
    path.write_text(
        json.dumps(
            {
                "kind": "brief",
                "findings": [_finding("gem", "high", "short note")],
                "citations": {},
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["fit", str(path), "--budget", "40", "--format", "json"])
    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["kind"] == "fit"
    assert document["included"][0]["id"] == "gem"
    assert "not legal" in document["value_note"]


def _tokens(brief: dict) -> dict[str, int]:
    measured = fit_document(brief, budget=10_000)
    return {item["id"]: item["tokens"] for item in [*measured["included"], *measured["dropped"]]}


def _finding(component_id: str, severity: str, summary: str) -> dict:
    return {
        "kind": "component",
        "component_id": component_id,
        "path": f"{component_id}.py",
        "framework": "openai",
        "change": "added",
        "status": "missing",
        "severity": severity,
        "summary": summary,
        "citation_ids": [],
    }
