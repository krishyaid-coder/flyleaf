# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Command line interface."""

from pathlib import Path

import typer

from flyleaf import __version__
from flyleaf.baseline import BASELINE_FILE, BaselineError, write_baseline
from flyleaf.brief import GitError, build_brief, highest_severity
from flyleaf.card import write_cards
from flyleaf.report import render, render_citations
from flyleaf.scan import scan_path
from flyleaf.severity import ORDER, at_least

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Inventory AI components in a repository and list areas to review, with citations. "
        "Not a legal risk classifier."
    ),
)


def main() -> None:
    app()


@app.callback(invoke_without_command=True)
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print the version and exit.",
        is_eager=True,
    ),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def scan(
    path: Path = typer.Argument(Path("."), exists=False, help="Repository, directory, or file to scan."),
    output_format: str = typer.Option("json", "--format", "-f", help="json or markdown."),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the report to this file. Prints to stdout when omitted.",
    ),
) -> None:
    """Scan a tree and print an AI component inventory.

    The command exits 0 when the scan finishes, including when it finds AI
    libraries. It does not fail a build for using an AI library.
    """
    _check_format(output_format, {"json", "markdown"})
    try:
        document = scan_path(path)
    except FileNotFoundError:
        typer.echo(f"Path not found: {path}", err=True)
        raise typer.Exit(code=2) from None
    _emit(render(document, output_format), output)


@app.command()
def brief(
    base: str | None = typer.Argument(None, help="Git ref to compare from. Omit with --baseline."),
    head: str | None = typer.Argument(None, help="Git ref to compare to. Defaults to the working tree."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository to read."),
    use_baseline: bool = typer.Option(
        False,
        "--baseline",
        help=f"Compare against the approved state in {BASELINE_FILE.as_posix()} instead of a git ref.",
    ),
    fail_on: str = typer.Option(
        "none",
        "--fail-on",
        help="Exit 1 when an active finding reaches this severity: none, low, medium, or high.",
    ),
    output_format: str = typer.Option("json", "--format", "-f", help="json, markdown, or sarif."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write the brief to this file."),
) -> None:
    """Compare two states and list documentation changes with citations.

    Status values are missing and needs_review. Severity ranks engineering
    attention, not legal risk. The brief does not declare a legal breach.
    """
    _check_format(output_format, {"json", "markdown", "sarif"})
    if fail_on not in {"none", *ORDER}:
        typer.echo("Fail-on must be none, low, medium, or high.", err=True)
        raise typer.Exit(code=2)
    if base is None and not use_baseline:
        typer.echo("Give a base ref, or pass --baseline.", err=True)
        raise typer.Exit(code=2)

    try:
        document = build_brief(path, base, head, use_baseline=use_baseline)
    except FileNotFoundError:
        typer.echo(f"Path not found: {path}", err=True)
        raise typer.Exit(code=2) from None
    except (GitError, BaselineError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None

    _emit(render(document, output_format), output)
    for warning in document["warnings"]:
        typer.echo(warning, err=True)

    if fail_on == "none":
        return
    worst = highest_severity(document)
    if worst is not None and at_least(worst, fail_on):
        typer.echo(
            f"Highest severity is {worst}, at or above the --fail-on threshold of {fail_on}.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command(name="baseline")
def baseline_command(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository to read."),
    approved_by: str | None = typer.Option(
        None, "--approved-by", help="Who signed off on this state."
    ),
    rev: str | None = typer.Option(None, "--rev", help="Revision this snapshot represents."),
) -> None:
    """Record the current inventory as the approved state.

    Later runs of 'flyleaf brief --baseline' report what changed since this sign-off.
    """
    try:
        destination = write_baseline(path, rev, approved_by)
    except FileNotFoundError:
        typer.echo(f"Path not found: {path}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(destination)


@app.command()
def card(
    path: Path = typer.Argument(Path("."), exists=False, help="Repository, directory, or file to scan."),
    output: Path = typer.Option(
        Path("flyleaf-cards"),
        "--output",
        "-o",
        help="Directory for the scaffolds. Existing files are kept unless --force is set.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite scaffolds that already exist."),
) -> None:
    """Write a model-card scaffold per declared system, then per loose component.

    Scaffolds land under --output, never at a declared card path, so an
    unfinished draft never counts as documentation.
    """
    try:
        written = write_cards(path, output, force=force)
    except FileNotFoundError:
        typer.echo(f"Path not found: {path}", err=True)
        raise typer.Exit(code=2) from None
    if not written:
        typer.echo(f"No new scaffolds written under {output}.")
        return
    for destination in written:
        typer.echo(destination)


@app.command(name="cite")
def cite_command(
    citation_id: str | None = typer.Argument(None, help="Citation id. Omit to list the pack."),
    changelog: bool = typer.Option(False, "--changelog", help="Print the pack changelog."),
    output_format: str = typer.Option("markdown", "--format", "-f", help="markdown or json."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write the citation text to this file."),
) -> None:
    """Print the citation pack, or one entry, with the source URL and pack version."""
    _check_format(output_format, {"json", "markdown"})
    try:
        text = render_citations(citation_id, changelog, output_format)
    except KeyError:
        typer.echo(f"Unknown citation: {citation_id}", err=True)
        raise typer.Exit(code=2) from None
    _emit(text, output)


def _check_format(output_format: str, allowed: set[str]) -> None:
    if output_format not in allowed:
        typer.echo(f"Format must be {' or '.join(sorted(allowed))}.", err=True)
        raise typer.Exit(code=2)


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        typer.echo(text, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
