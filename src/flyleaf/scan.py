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
from flyleaf.systems import SYSTEMS_FILE, System, assign, claimants, load_systems

SCHEMA_VERSION = "0.5.0"

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

    systems, problems = load_systems(root)
    warnings.extend({"path": SYSTEMS_FILE.as_posix(), "message": problem} for problem in problems)

    for file_path in files:
        rel = file_path.relative_to(root).as_posix()
        kind = _scan_kind(file_path.name)
        if kind is None:
            continue
        try:
            if file_path.stat().st_size > _MAX_BYTES:
                warnings.append({"path": rel, "message": "Skipped a file larger than 1MB."})
                continue
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            warnings.append({"path": rel, "message": f"Could not read file: {exc}"})
            continue

        if kind == "python":
            found, problem = _python_hits(text)
        elif kind == "notebook":
            found, problem = _notebook_hits(text)
        elif kind == "requirements":
            found = _requirement_hits(text)
            problem = None
        elif kind == "pyproject":
            found, problem = _pyproject_hits(text)
        else:
            found, problem = _package_json_hits(text)
        if problem:
            warnings.append({"path": rel, "message": problem})

        for hit in found:
            hits.setdefault((rel, hit.rule.framework), []).append(hit)

    components = [
        _component(root, rel, framework, group, assign(systems, rel))
        for (rel, framework), group in hits.items()
    ]
    components.sort(key=lambda item: (item["path"], item["framework"]))
    warnings.extend(_system_warnings(systems, components))
    warnings.sort(key=lambda item: item["path"])

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "inventory",
        "tool": {"name": "flyleaf", "version": __version__},
        "disclaimer": DISCLAIMER,
        "citation_pack": pack_meta(),
        "citations": _used_citations(components),
        "root": str(root),
        "systems": [_system_block(root, system, components) for system in systems],
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


def _scan_kind(name: str) -> str | None:
    if name.endswith(".py"):
        return "python"
    if name.endswith(".ipynb"):
        return "notebook"
    if _is_requirements(name):
        return "requirements"
    if name == "pyproject.toml":
        return "pyproject"
    if name == "package.json":
        return "package_json"
    return None


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


def _notebook_hits(text: str) -> tuple[list[_Hit], str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"Could not parse notebook: {exc.msg}"
    if not isinstance(data, dict):
        return [], "Notebook was not an object."

    cells = data.get("cells")
    if not isinstance(cells, list):
        return [], None

    hits: list[_Hit] = []
    seen: set[tuple[str, str]] = set()
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        code = _cell_source(cell.get("source"))
        if not code.strip():
            continue
        try:
            tree = ast.parse(_strip_magics(code))
        except SyntaxError:
            continue
        for _line, module, snippet in _iter_imports(tree):
            rule = match_import(module)
            if rule is None:
                continue
            key = (rule.framework, snippet)
            if key in seen:
                continue
            seen.add(key)
            line_no, _ = _find_dep_line(text, snippet, spec=snippet)
            hits.append(_Hit(rule=rule, kind="import", line=line_no, text=snippet))
    return hits, None


def _cell_source(source) -> str:
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    if isinstance(source, str):
        return source
    return ""


def _strip_magics(code: str) -> str:
    kept: list[str] = []
    for line in code.splitlines():
        if line.lstrip().startswith(("%", "!")):
            kept.append("")
        else:
            kept.append(line)
    return "\n".join(kept)


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
        if not stripped or stripped.startswith(("#", "-")):
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

    entries: list[tuple[str, str | None]] = []
    project = data.get("project")
    if isinstance(project, dict):
        entries.extend(_string_deps(project.get("dependencies")))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                entries.extend(_string_deps(group))
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            entries.extend(_string_deps(group))
    poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    if isinstance(poetry, dict):
        entries.extend(_poetry_names(poetry.get("dependencies")))
        group_table = poetry.get("group")
        if isinstance(group_table, dict):
            for group in group_table.values():
                if isinstance(group, dict):
                    entries.extend(_poetry_names(group.get("dependencies")))

    return _hits_for_names(text, entries), None


def _string_deps(value) -> list[tuple[str, str | None]]:
    if not isinstance(value, list):
        return []
    entries: list[tuple[str, str | None]] = []
    for item in value:
        if isinstance(item, str):
            spec = item.strip()
            name = _requirement_name(spec)
            if name:
                entries.append((name, spec))
    return entries


def _poetry_names(value) -> list[tuple[str, str | None]]:
    if not isinstance(value, dict):
        return []
    return [(name, None) for name in value if name.lower() != "python"]


def _package_json_hits(text: str) -> tuple[list[_Hit], str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"Could not parse package.json: {exc.msg}"
    if not isinstance(data, dict):
        return [], "package.json was not an object."

    entries: list[tuple[str, str | None]] = []
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            entries.extend((str(name), None) for name in block)
    return _hits_for_names(text, entries), None


def _hits_for_names(text: str, entries: list[tuple[str, str | None]]) -> list[_Hit]:
    hits: list[_Hit] = []
    seen: set[str] = set()
    for name, spec in entries:
        canonical = _canon(name)
        if canonical in seen:
            continue
        rule = match_package(canonical)
        if rule is None:
            continue
        seen.add(canonical)
        line, snippet = _find_dep_line(text, name, spec)
        hits.append(_Hit(rule=rule, kind="dependency", line=line, text=snippet))
    return hits


def _find_dep_line(text: str, name: str, spec: str | None = None) -> tuple[int, str]:
    """Find a dependency or import line.

    A bare mention, such as a keyword list, is not evidence. Prefer the
    requirement string, then a line shaped like a dependency declaration.
    """
    lines = text.splitlines()
    if spec:
        for line_no, raw in enumerate(lines, 1):
            if spec in raw:
                return line_no, raw.strip()
    declaration = re.compile(
        rf"(?i)(^|\s|[\"']){re.escape(name)}(\s*[<>=!~\[]|\s*=|\s*\"\s*:)"
    )
    for line_no, raw in enumerate(lines, 1):
        if declaration.search(raw):
            return line_no, raw.strip()
    return 1, spec or name


def _canon(name: str) -> str:
    name = name.strip().lower()
    if name.startswith("@"):
        return name
    return re.sub(r"[-_.]+", "-", name)


def _component(
    root: Path,
    rel: str,
    framework: str,
    hits: list[_Hit],
    system: System | None,
) -> dict:
    rule = hits[0].rule
    evidence = [
        {"kind": hit.kind, "line": hit.line, "text": hit.text}
        for hit in sorted(hits, key=lambda hit: (hit.line, hit.text))
    ]
    card = _resolve_card(root, rel, system)
    return {
        "id": f"{rel}:{framework}",
        "path": rel,
        "framework": framework,
        "category": rule.category,
        "role_hint": rule.role_hint,
        "system": system.name if system else None,
        "evidence": evidence,
        "review_hints": [_hint(hint) for hint in rule.review_hints],
        "model_card_status": "present" if card else "missing",
        "model_card_path": card.relative_to(root).as_posix() if card else None,
        "model_card_sha256": hashlib.sha256(card.read_bytes()).hexdigest() if card else None,
        "documentation_citation_ids": list(DOCUMENTATION_CITATION_IDS),
    }


def _resolve_card(root: Path, rel: str, system: System | None) -> Path | None:
    """A declared system card is the answer for every component in it.

    One system, one card. Without a declared card, fall back to looking beside
    the file and at the repository root.
    """
    if system is not None and system.card:
        candidate = root / system.card
        return candidate if candidate.is_file() else None
    return _find_card(root / rel, root)


def _system_block(root: Path, system: System, components: list[dict]) -> dict:
    members = [item for item in components if item["system"] == system.name]
    card = (root / system.card) if system.card else None
    present = bool(card and card.is_file())
    block = system.payload()
    block.update(
        {
            "model_card_status": "present" if present else ("missing" if card else "undeclared"),
            "model_card_path": system.card if present else None,
            "model_card_sha256": hashlib.sha256(card.read_bytes()).hexdigest() if present else None,
            "component_ids": [item["id"] for item in members],
            "frameworks": sorted({item["framework"] for item in members}),
        }
    )
    return block


def _system_warnings(systems: list[System], components: list[dict]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    label = SYSTEMS_FILE.as_posix()
    claimed = {item["system"] for item in components}
    for system in systems:
        if system.name not in claimed:
            warnings.append(
                {
                    "path": label,
                    "message": (
                        f"System '{system.name}' claims no detected component. "
                        "Check the includes patterns."
                    ),
                }
            )
    for path in dict.fromkeys(item["path"] for item in components):
        names = claimants(systems, path)
        if len(names) > 1:
            warnings.append(
                {
                    "path": path,
                    "message": (
                        f"Claimed by {', '.join(names)}. The first declared system, "
                        f"'{names[0]}', takes it."
                    ),
                }
            )
    return warnings


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
