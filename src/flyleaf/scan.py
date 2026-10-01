# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Scan a tree for AI libraries and report one component per file."""

import ast
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from flyleaf import DISCLAIMER, __version__
from flyleaf.citations import DOCUMENTATION_CITATION_IDS, pack_meta, payloads_for
from flyleaf.rules import ReviewHint, Rule, match_import, match_package

SCHEMA_VERSION = "0.2.0"

IGNORE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
    }
)

CARD_NAMES = (
    "MODEL_CARD.md",
    "model_card.md",
    "modelcard.md",
    "MODEL_CARD.yaml",
    "model_card.yaml",
    "modelcard.yaml",
)

_MAX_BYTES = 1_000_000
_GOOGLE_SUBMODULES = {"generativeai": "google.generativeai", "genai": "google.genai"}


@dataclass
class _Hit:
    rule: Rule
    kind: str
    line: int
    text: str


def scan_path(path: Path) -> dict:
    """Scan `path` and return a JSON-ready inventory.

    A component is one detected framework in one file. It is not an AI system.
    Systems are groupings a person makes later.
    """
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    if path.is_file():
        root = path.parent
        files = [path]
    else:
        root = path
        files = list(_walk(root))

    hits: dict[tuple[str, str], list[_Hit]] = {}
    warnings: list[dict[str, str]] = []

    for file_path in files:
        rel = file_path.relative_to(root).as_posix()
        try:
            if file_path.stat().st_size > _MAX_BYTES:
                warnings.append({"path": rel, "message": "Skipped a file larger than 1MB."})
                continue
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            warnings.append({"path": rel, "message": f"Could not read file: {exc}"})
            continue

        name = file_path.name
        if name.endswith(".py"):
            found, problem = _python_hits(text)
            if problem:
                warnings.append({"path": rel, "message": problem})
        elif _is_requirements(name):
            found = _requirement_hits(text)
        elif name == "pyproject.toml":
            found, problem = _pyproject_hits(text)
            if problem:
                warnings.append({"path": rel, "message": problem})
        elif name == "package.json":
            found, problem = _package_json_hits(text)
            if problem:
                warnings.append({"path": rel, "message": problem})
        else:
            continue

        for hit in found:
            hits.setdefault((rel, hit.rule.framework), []).append(hit)

    components = [_component(root, rel, framework, group) for (rel, framework), group in hits.items()]
    components.sort(key=lambda item: (item["path"], item["framework"]))
    warnings.sort(key=lambda item: item["path"])

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "inventory",
        "tool": {"name": "flyleaf", "version": __version__},
        "disclaimer": DISCLAIMER,
        "citation_pack": pack_meta(),
        "citations": _used_citations(components),
        "root": str(root),
        "components": components,
        "warnings": warnings,
    }


def _walk(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in IGNORE_DIRS and not name.endswith(".egg-info")
        )
        for filename in sorted(filenames):
            found.append(Path(dirpath) / filename)
    return found


def _is_requirements(name: str) -> bool:
    return name == "requirements.txt" or (
        name.startswith("requirements") and name.endswith(".txt")
    )


def _python_hits(text: str) -> tuple[list[_Hit], str | None]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"Could not parse Python: {exc.msg}"

    hits: list[_Hit] = []
    seen: set[tuple[str, int, str]] = set()
    for line, module, snippet in _iter_imports(tree):
        rule = match_import(module)
        if rule is None:
            continue
        key = (rule.framework, line, snippet)
        if key in seen:
            continue
        seen.add(key)
        hits.append(_Hit(rule=rule, kind="import", line=line, text=snippet))
    return hits, None


def _iter_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, f"import {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = ", ".join(alias.name for alias in node.names)
            snippet = f"from {node.module} import {names}"
            if node.module == "google":
                for alias in node.names:
                    mapped = _GOOGLE_SUBMODULES.get(alias.name)
                    if mapped:
                        yield node.lineno, mapped, snippet
                continue
            yield node.lineno, node.module, snippet


def _requirement_hits(text: str) -> list[_Hit]:
    hits: list[_Hit] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        name = _requirement_name(stripped)
        if not name:
            continue
        rule = match_package(_canon(name))
        if rule is None:
            continue
        hits.append(_Hit(rule=rule, kind="dependency", line=line_no, text=stripped))
    return hits


def _requirement_name(spec: str) -> str:
    name = re.split(r"[<>=!~;\s\[]", spec, maxsplit=1)[0].strip()
    if not name or name.startswith(("git+", "http://", "https://")):
        return ""
    return name


def _pyproject_hits(text: str) -> tuple[list[_Hit], str | None]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [], f"Could not parse pyproject.toml: {exc}"

    names: list[str] = []
    project = data.get("project")
    if isinstance(project, dict):
        names.extend(_string_deps(project.get("dependencies")))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                names.extend(_string_deps(group))
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            names.extend(_string_deps(group))
    poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    if isinstance(poetry, dict):
        names.extend(_poetry_names(poetry.get("dependencies")))
        group_table = poetry.get("group")
        if isinstance(group_table, dict):
            for group in group_table.values():
                if isinstance(group, dict):
                    names.extend(_poetry_names(group.get("dependencies")))

    return _hits_for_names(text, names), None


def _string_deps(value) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            name = _requirement_name(item.strip())
            if name:
                names.append(name)
    return names


def _poetry_names(value) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [name for name in value if name.lower() != "python"]


def _package_json_hits(text: str) -> tuple[list[_Hit], str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"Could not parse package.json: {exc.msg}"
    if not isinstance(data, dict):
        return [], "package.json was not an object."

    names: list[str] = []
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            names.extend(str(name) for name in block)
    return _hits_for_names(text, names), None


def _hits_for_names(text: str, names: list[str]) -> list[_Hit]:
    hits: list[_Hit] = []
    seen: set[str] = set()
    for name in names:
        canonical = _canon(name)
        if canonical in seen:
            continue
        rule = match_package(canonical)
        if rule is None:
            continue
        seen.add(canonical)
        line, snippet = _find_dep_line(text, name)
        hits.append(_Hit(rule=rule, kind="dependency", line=line, text=snippet))
    return hits


def _find_dep_line(text: str, name: str) -> tuple[int, str]:
    pattern = re.compile(rf"(?i)(^|[^A-Za-z0-9_.@/-]){re.escape(name)}([^A-Za-z0-9_.@/-]|$)")
    for line_no, raw in enumerate(text.splitlines(), 1):
        if pattern.search(raw):
            return line_no, raw.strip()
    return 1, name


def _canon(name: str) -> str:
    name = name.strip().lower()
    if name.startswith("@"):
        return name
    return re.sub(r"[-_.]+", "-", name)


def _component(root: Path, rel: str, framework: str, hits: list[_Hit]) -> dict:
    rule = hits[0].rule
    evidence = [
        {"kind": hit.kind, "line": hit.line, "text": hit.text}
        for hit in sorted(hits, key=lambda hit: (hit.line, hit.text))
    ]
    card = _find_card(root / rel, root)
    return {
        "id": f"{rel}:{framework}",
        "path": rel,
        "framework": framework,
        "category": rule.category,
        "role_hint": rule.role_hint,
        "evidence": evidence,
        "review_hints": [_hint(hint) for hint in rule.review_hints],
        "model_card_status": "present" if card else "missing",
        "model_card_path": card.relative_to(root).as_posix() if card else None,
        "model_card_sha256": hashlib.sha256(card.read_bytes()).hexdigest() if card else None,
        "documentation_citation_ids": list(DOCUMENTATION_CITATION_IDS),
    }


def _hint(hint: ReviewHint) -> dict:
    return {"id": hint.id, "text": hint.text, "citation_ids": list(hint.citation_ids)}


def _used_citations(components: list[dict]) -> dict[str, dict[str, str]]:
    citation_ids: set[str] = set()
    for component in components:
        citation_ids.update(component["documentation_citation_ids"])
        for hint in component["review_hints"]:
            citation_ids.update(hint["citation_ids"])
    return payloads_for(citation_ids)


def _find_card(component_file: Path, root: Path) -> Path | None:
    directories = [component_file.parent]
    if root not in directories:
        directories.append(root)
    for directory in directories:
        for name in CARD_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None
