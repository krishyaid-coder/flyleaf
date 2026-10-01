# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Command line interface."""

from pathlib import Path

import typer

from flyleaf import __version__
from flyleaf.brief import GitError, build_brief
from flyleaf.card import write_cards
from flyleaf.report import render, render_citations
from flyleaf.scan import scan_path

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


@app.callback()
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
    _check_format(output_format)
    try:
        document = scan_path(path)
    except FileNotFoundError:
        typer.echo(f"Path not found: {path}", err=True)
        raise typer.Exit(code=2) from None
    _emit(render(document, output_format), output)


@app.command()
def brief(
    base: str = typer.Argument(..., help="Git ref to compare from."),
    head: str | None = typer.Argument(None, help="Git ref to compare to. Defaults to the working tree."),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Repository to read."),
    output_format: str = typer.Option("json", "--format", "-f", help="json or markdown."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write the brief to this file."),
) -> None:
    """Compare two revisions and list documentation changes with citations.

    Status values are missing and needs_review. The brief does not declare a legal breach.
    """
    _check_format(output_format)
    try:
        document = build_brief(path, base, head)
    except FileNotFoundError:
        typer.echo(f"Path not found: {path}", err=True)
        raise typer.Exit(code=2) from None
    except GitError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    _emit(render(document, output_format), output)


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
    """Write a model-card scaffold for each detected component."""
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
    _check_format(output_format)
    try:
        text = render_citations(citation_id, changelog, output_format)
    except KeyError:
        typer.echo(f"Unknown citation: {citation_id}", err=True)
        raise typer.Exit(code=2) from None
    _emit(text, output)


def _check_format(output_format: str) -> None:
    if output_format not in {"json", "markdown"}:
        typer.echo("Format must be json or markdown.", err=True)
        raise typer.Exit(code=2)


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        typer.echo(text, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
