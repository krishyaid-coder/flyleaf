# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Choose which findings fit in a token budget, and say why the rest did not.

flyleaf already knows what changed. An assistant still cannot hold the whole
brief. ``fit`` is the choosing step: worth against tokens, with a reason for
every item that was kept or left out. It does not store the findings.
"""

import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from flyleaf import DISCLAIMER, __version__
from flyleaf.pack import Candidate, Pack, density_pack, greedy_pack, similarity_pack

# Worth of a finding. This is engineering attention, the same scale as severity.
# It is not a legal risk tier.
ATTENTION = {"high": 3.0, "medium": 2.0, "low": 1.0}
ATTENTION_NOTE = (
    "Worth on a brief or inventory is engineering attention, not legal importance. "
    "High is 3, medium is 2, low is 1. A missing model card is 3, and a present card is 1. "
    "Density maximises that worth. Similarity ranks by the query when you pass one, "
    "and by this same worth otherwise."
)

TokenCounter = Callable[[str], int]
Strategy = Callable[[list[Candidate], int], Pack]


class FitError(ValueError):
    """The caller asked for a fit flyleaf cannot do."""


@dataclass(frozen=True)
class Memory:
    """One candidate. flyleaf does not keep it.

    ``value`` is worth. ``relevance`` is similarity to the current question,
    and the similarity strategy ranks on it. When ``value`` is omitted, worth
    falls back to ``relevance``, then to 1. With no scores at all, shorter
    items win, because each one is worth the same and costs fewer tokens.
    """

    id: str
    text: str
    value: float | None = None
    relevance: float | None = None
    tokens: int | None = None


@dataclass(frozen=True)
class Decision:
    id: str
    text: str
    tokens: int
    value: float
    relevance: float | None
    density: float
    included: bool
    code: str
    reason: str


@dataclass(frozen=True)
class FitResult:
    strategy: str
    method: str
    budget: int
    tokens_used: int
    value_captured: float
    included: tuple[Decision, ...]
    dropped: tuple[Decision, ...]

    @property
    def relevance_captured(self) -> float:
        return sum(item.relevance or 0.0 for item in self.included)

    def prompt(self, separator: str = "\n\n") -> str:
        """The kept texts, in prompt order, ready for the context window."""
        return separator.join(item.text for item in self.included)


_STRATEGIES: dict[str, Strategy] = {
    "density": density_pack,
    "greedy": greedy_pack,
    "similarity": similarity_pack,
}


def register(name: str) -> Callable[[Strategy], Strategy]:
    """Register a packer other people can pass to ``fit(..., strategy=name)``.

    The callable receives resolved candidates and a budget, and returns a
    ``Pack`` that names a code and a reason for every candidate and stays
    inside the budget.
    """
    if not isinstance(name, str) or not name:
        raise FitError("strategy name must be a non-empty string")

    def decorator(fn: Strategy) -> Strategy:
        if name in _STRATEGIES:
            raise FitError(f"strategy already registered: {name}")
        _STRATEGIES[name] = fn
        return fn

    return decorator


def fit(
    memories: Sequence[Memory | Mapping[str, Any]],
    budget: int,
    *,
    strategy: str = "density",
    token_counter: TokenCounter | None = None,
    order: str = "density",
) -> FitResult:
    """Choose the items that fit in ``budget`` tokens, and explain the rest.

    ``order`` controls prompt order of the kept items: ``density`` (worth per
    token), ``value``, or ``input``.
    """
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise FitError("budget must be a non-negative integer")
    if order not in {"density", "value", "input"}:
        raise FitError("order must be 'density', 'value', or 'input'")
    try:
        packer = _STRATEGIES[strategy]
    except KeyError:
        known = ", ".join(sorted(_STRATEGIES))
        raise FitError(f"unknown strategy {strategy!r}. Known strategies: {known}") from None

    counter = token_counter or estimate_tokens
    normalized = _normalize(memories)
    candidates = [_candidate(index, memory, counter) for index, memory in enumerate(normalized)]
    pack = packer(candidates, budget)
    _check_pack(pack, candidates, budget)

    by_index = {candidate.index: candidate for candidate in candidates}
    included = tuple(
        _decision(by_index[index], pack, included=True) for index in _included_order(candidates, pack, order)
    )
    dropped = tuple(
        _decision(candidate, pack, included=False)
        for candidate in _dropped_order(candidates, pack, strategy)
    )
    return FitResult(
        strategy=strategy,
        method=pack.method,
        budget=budget,
        tokens_used=sum(item.tokens for item in included),
        value_captured=sum(item.value for item in included),
        included=included,
        dropped=dropped,
    )


def fit_document(
    document: dict | list,
    budget: int,
    *,
    strategy: str = "density",
    query: str | None = None,
    order: str = "density",
) -> dict:
    """Fit a saved brief, inventory, or list of memories.

    A brief packs active findings. Waived findings stay out of the suitcase.
    An inventory packs components. A memories document packs the scores it
    already carries. Worth for a brief or inventory is engineering attention.
    """
    memories, source_kind, waived = _memories_from(document, query)
    chosen = fit(memories, budget, strategy=strategy, order=order)
    others = {
        name: fit(memories, budget, strategy=name, order=order)
        for name in ("density", "greedy", "similarity")
        if name != strategy
    }
    return {
        "kind": "fit",
        "tool": {"name": "flyleaf", "version": __version__},
        "disclaimer": DISCLAIMER,
        "value_note": ATTENTION_NOTE if source_kind in {"brief", "inventory"} else None,
        "source_kind": source_kind,
        "query": query or None,
        "strategy": chosen.strategy,
        "method": chosen.method,
        "how": _how(chosen),
        "budget": chosen.budget,
        "tokens_used": chosen.tokens_used,
        "value": chosen.value_captured,
        "order": order,
        "waived_not_packed": waived,
        "compared": {
            name: {"value": result.value_captured, "tokens_used": result.tokens_used, "method": result.method}
            for name, result in others.items()
        },
        "included": [_decision_payload(item) for item in chosen.included],
        "dropped": [_decision_payload(item) for item in chosen.dropped],
        "prompt": chosen.prompt(),
    }


def render_fit(document: dict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(document, indent=2) + "\n"
    if output_format != "markdown":
        raise FitError(f"unknown format: {output_format}")
    return _markdown(document)


def estimate_tokens(text: str) -> int:
    """About four characters per token, and never fewer than one."""
    if not text:
        return 1
    return max(1, (len(text) + 3) // 4)


def benchmark_report() -> str:
    """The suite that shows density is ahead of, or tied with, packing from the top."""
    named = (short_gems(), awkward_pack(), equal_length())
    random_rows = random_scenarios()
    lines = [
        "Worth captured at the same budget. Density maximises worth.",
        "Similarity packs from the highest relevance down.",
        "",
        f"{'scenario':<16}{'budget':>8}{'density':>10}{'greedy':>10}{'similarity':>12}",
    ]
    scores = []
    for scenario in named:
        row = _score(scenario)
        scores.append(row)
        lines.append(
            f"{row['name']:<16}{row['budget']:>8}"
            f"{row['density']:>10.2f}{row['greedy']:>10.2f}{row['similarity']:>12.2f}"
        )
    random_scores = [_score(scenario) for scenario in random_rows]
    scores.extend(random_scores)
    lines.append(
        f"{'random mean':<16}{80:>8}"
        f"{_mean(row['density'] for row in random_scores):>10.2f}"
        f"{_mean(row['greedy'] for row in random_scores):>10.2f}"
        f"{_mean(row['similarity'] for row in random_scores):>12.2f}"
    )
    lines.append("")
    lines.append("Relevance captured (what similarity is trying to maximise)")
    for row in scores[:3]:
        lines.append(
            f"  {row['name']:<14} density {row['density_relevance']:.2f}"
            f"   similarity {row['similarity_relevance']:.2f}"
        )
    wins, ties, losses = _tally(scores)
    lines.append("")
    lines.append(f"On worth, density finished ahead in {wins}, tied {ties}, and behind in {losses}.")
    lines.append("")
    return "\n".join(lines)


def short_gems() -> tuple[str, int, tuple[Memory, ...]]:
    """Short, useful items against one long item that merely looks relevant."""
    gems = tuple(
        Memory(
            id=f"gem-{number}",
            text=f"Short fact {number} worth keeping.",
            tokens=25,
            value=0.80,
            relevance=0.20,
        )
        for number in range(1, 5)
    )
    essay = Memory(
        id="essay",
        text="A long, mildly useful item that merely looks similar.",
        tokens=90,
        value=0.45,
        relevance=0.98,
    )
    return "short gems", 100, (*gems, essay)


def awkward_pack() -> tuple[str, int, tuple[Memory, ...]]:
    """The best rate blocks a pair that is worth more together."""
    return (
        "awkward pack",
        10,
        (
            Memory(id="dense", text="One dense item.", tokens=6, value=6, relevance=0.99),
            Memory(id="pair-a", text="First of a better pair.", tokens=5, value=4, relevance=0.40),
            Memory(id="pair-b", text="Second of a better pair.", tokens=5, value=4, relevance=0.40),
        ),
    )


def equal_length() -> tuple[str, int, tuple[Memory, ...]]:
    """Same size, and worth matches relevance, so every strategy agrees."""
    return (
        "equal length",
        20,
        (
            Memory(id="strong", text="Clearly useful.", tokens=10, value=0.9, relevance=0.9),
            Memory(id="middle", text="Somewhat useful.", tokens=10, value=0.5, relevance=0.5),
            Memory(id="weak", text="Barely useful.", tokens=10, value=0.1, relevance=0.1),
        ),
    )


def random_scenarios(count: int = 20, seed: int = 0) -> tuple[tuple[str, int, tuple[Memory, ...]], ...]:
    """Worth and relevance diverge, and lengths vary. Each pile still solves exactly."""
    scenarios = []
    for offset in range(count):
        rng = random.Random(seed + offset)
        memories = []
        for index in range(12):
            tokens = rng.choice((8, 16, 24, 40))
            relevance = round(rng.uniform(0.2, 1.0), 2)
            value = round(relevance * rng.uniform(0.25, 1.0), 2)
            memories.append(
                Memory(
                    id=f"m{index}",
                    text="A remembered fact.",
                    tokens=tokens,
                    value=value,
                    relevance=relevance,
                )
            )
        scenarios.append((f"random-{offset}", 80, tuple(memories)))
    return tuple(scenarios)


def _score(scenario: tuple[str, int, tuple[Memory, ...]]) -> dict:
    name, budget, memories = scenario
    density = fit(memories, budget, strategy="density")
    greedy = fit(memories, budget, strategy="greedy")
    similarity = fit(memories, budget, strategy="similarity")
    for result in (density, greedy, similarity):
        if result.tokens_used > budget:
            raise FitError(f"{result.strategy} used {result.tokens_used} tokens over {budget}")
    return {
        "name": name,
        "budget": budget,
        "density": density.value_captured,
        "greedy": greedy.value_captured,
        "similarity": similarity.value_captured,
        "density_relevance": density.relevance_captured,
        "similarity_relevance": similarity.relevance_captured,
    }


def _tally(rows: list[dict]) -> tuple[int, int, int]:
    wins = ties = losses = 0
    for row in rows:
        if row["density"] > row["similarity"] + 1e-9:
            wins += 1
        elif row["density"] < row["similarity"] - 1e-9:
            losses += 1
        else:
            ties += 1
    return wins, ties, losses


def _mean(values) -> float:
    listed = list(values)
    return sum(listed) / len(listed)


def _memories_from(document: dict | list, query: str | None) -> tuple[list[Memory], str, int]:
    if isinstance(document, list):
        return _normalize(document), "memories", 0
    if not isinstance(document, dict):
        raise FitError("fit needs a brief, an inventory, or a list of memories")
    kind = document.get("kind")
    if kind == "memories":
        raw = document.get("memories")
        if not isinstance(raw, list):
            raise FitError("a memories document needs a memories list")
        return [_with_query(_coerce(item), query) for item in raw], "memories", 0
    if kind == "brief":
        return _from_brief(document, query), "brief", len(document.get("waived") or [])
    if kind == "inventory":
        return _from_inventory(document, query), "inventory", 0
    raise FitError("fit needs a brief, an inventory, or a memories document")


def _with_query(memory: Memory, query: str | None) -> Memory:
    if memory.relevance is not None or not query:
        return memory
    return Memory(
        id=memory.id,
        text=memory.text,
        value=memory.value,
        relevance=_query_relevance(memory.text, query),
        tokens=memory.tokens,
    )


def _from_brief(brief: dict, query: str | None) -> list[Memory]:
    citations = brief.get("citations") or {}
    memories = []
    for finding in brief.get("findings") or []:
        text = _attach_citations(_finding_text(finding), finding.get("citation_ids") or [], citations)
        memories.append(
            Memory(
                id=str(finding.get("component_id") or finding.get("path") or "finding"),
                text=text,
                value=ATTENTION.get(finding.get("severity"), 1.0),
                relevance=_query_relevance(text, query),
            )
        )
    return memories


def _from_inventory(inventory: dict, query: str | None) -> list[Memory]:
    citations = inventory.get("citations") or {}
    memories = []
    for component in inventory.get("components") or []:
        text = _component_text(component, citations)
        missing = component.get("model_card_status") == "missing"
        memories.append(
            Memory(
                id=str(component.get("id") or component.get("path") or "component"),
                text=text,
                value=3.0 if missing else 1.0,
                relevance=_query_relevance(text, query),
            )
        )
    return memories


def _finding_text(finding: dict) -> str:
    if finding.get("kind") == "system":
        subject = f"system {finding.get('system')} ({finding.get('framework')})"
    else:
        subject = f"{finding.get('path')} ({finding.get('framework')})"
    lines = [
        subject,
        f"severity {finding.get('severity')}, {finding.get('change')}, {finding.get('status')}",
        str(finding.get("summary") or ""),
    ]
    for member in finding.get("members") or []:
        lines.append(f"{member.get('path')} ({member.get('framework')}) {member.get('change')}")
    return "\n".join(lines)


def _component_text(component: dict, citations: dict) -> str:
    lines = [
        f"{component.get('path')} ({component.get('framework')})",
        f"role {component.get('role_hint') or ''}".rstrip(),
        f"model card {component.get('model_card_status') or ''}".rstrip(),
    ]
    for item in component.get("evidence") or []:
        lines.append(f"line {item.get('line')}: {item.get('text')}")
    ids: list[str] = []
    for hint in component.get("review_hints") or []:
        if hint.get("text"):
            lines.append(hint["text"])
        ids.extend(hint.get("citation_ids") or [])
    ids.extend(component.get("documentation_citation_ids") or [])
    return _attach_citations("\n".join(lines), ids, citations)


def _attach_citations(text: str, citation_ids: list, citations: dict) -> str:
    blocks = [text]
    seen: set[str] = set()
    for citation_id in citation_ids:
        if citation_id in seen:
            continue
        seen.add(citation_id)
        payload = citations.get(citation_id) if isinstance(citations, dict) else None
        if not isinstance(payload, dict):
            continue
        pinpoint = payload.get("pinpoint") or citation_id
        quote = payload.get("quote") or ""
        blocks.append(f"{pinpoint}: {quote}".rstrip())
    return "\n".join(blocks)


def _query_relevance(text: str, query: str | None) -> float | None:
    """Share of query words that appear in the text. Length does not raise it."""
    if not query or not query.strip():
        return None
    terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 1]
    if not terms:
        return None
    haystack = text.lower()
    hits = sum(1 for term in terms if term in haystack)
    return hits / len(terms)


def _decision_payload(item: Decision) -> dict:
    return {
        "id": item.id,
        "text": item.text,
        "tokens": item.tokens,
        "value": item.value,
        "relevance": item.relevance,
        "density": item.density,
        "code": item.code,
        "reason": item.reason,
    }


def _markdown(document: dict) -> str:
    lines = ["# flyleaf fit", "", DISCLAIMER, ""]
    if document.get("value_note"):
        lines.extend([document["value_note"], ""])
    lines.append(document["how"])
    lines.append(
        f"Budget {document['budget']}  used {document['tokens_used']}  value {document['value']:.2f}"
    )
    if document.get("query"):
        lines.append(f"Query: {document['query']}")
    compared = document.get("compared") or {}
    if compared:
        bits = [f"{name} {row['value']:.2f}" for name, row in compared.items()]
        lines.append("On this same pile: " + ", ".join(bits) + ".")
    waived = document.get("waived_not_packed") or 0
    if waived:
        lines.append(f"Waived findings left unpacked: {waived}.")
    lines.append("")
    lines.extend(_section("Included", document["included"]))
    lines.append("")
    lines.extend(_section("Left out", document["dropped"]))
    lines.append("")
    lines.append("## Hand to the assistant")
    lines.append("")
    prompt = document.get("prompt") or ""
    lines.append(prompt if prompt else "(nothing)")
    lines.append("")
    return "\n".join(lines)


def _section(title: str, decisions: list[dict]) -> list[str]:
    lines = [f"## {title} ({len(decisions)})", ""]
    if not decisions:
        lines.append("(none)")
        return lines
    for item in decisions:
        relevance = ""
        if item.get("relevance") is not None:
            relevance = f", relevance {item['relevance']:.2f}"
        lines.append(
            f"- `{item['id']}` — {item['tokens']} tok, value {item['value']:.2f}, "
            f"{item['density']:.4f} per token{relevance}"
        )
        lines.append(f"  {item['reason']}")
    return lines


def _how(result: FitResult) -> str:
    if result.strategy == "density" and result.method == "exact":
        return "density, solved exactly"
    if result.strategy == "density":
        return "density, packed by value per token"
    if result.strategy == "similarity":
        return "similarity, packed from the top"
    if result.strategy == "greedy":
        return "greedy, packed by value per token"
    return result.strategy


def _included_order(candidates: list[Candidate], pack: Pack, order: str) -> list[int]:
    chosen = [candidate for candidate in candidates if candidate.index in pack.chosen]

    def key(candidate: Candidate) -> tuple:
        if order == "value":
            return (-candidate.value, -candidate.density, candidate.index)
        if order == "input":
            return (candidate.index,)
        return (-candidate.density, -candidate.value, candidate.index)

    chosen.sort(key=key)
    return [candidate.index for candidate in chosen]


def _dropped_order(candidates: list[Candidate], pack: Pack, strategy: str) -> list[Candidate]:
    dropped = [candidate for candidate in candidates if candidate.index not in pack.chosen]
    if strategy == "similarity":
        dropped.sort(key=lambda candidate: (-_rank_relevance(candidate), candidate.index))
    else:
        dropped.sort(key=lambda candidate: (-candidate.density, -candidate.value, candidate.index))
    return dropped


def _rank_relevance(candidate: Candidate) -> float:
    if candidate.relevance is not None:
        return candidate.relevance
    return candidate.value


def _decision(candidate: Candidate, pack: Pack, *, included: bool) -> Decision:
    return Decision(
        id=candidate.id,
        text=candidate.text,
        tokens=candidate.tokens,
        value=candidate.value,
        relevance=candidate.relevance,
        density=candidate.density,
        included=included,
        code=pack.codes[candidate.index],
        reason=pack.reasons[candidate.index],
    )


def _check_pack(pack: Pack, candidates: list[Candidate], budget: int) -> None:
    expected = set(range(len(candidates)))
    if set(pack.codes) != expected or set(pack.reasons) != expected:
        raise FitError("strategy must explain every candidate")
    if any(not pack.reasons[index].strip() for index in expected):
        raise FitError("strategy returned an empty reason")
    chosen_tokens = 0
    for index in expected:
        selected = index in pack.chosen
        if selected != (pack.codes[index] == "selected"):
            raise FitError("strategy codes do not match the chosen set")
        if selected:
            chosen_tokens += candidates[index].tokens
    if chosen_tokens > budget:
        raise FitError(f"strategy used {chosen_tokens} tokens, which is over the budget of {budget}")


def _normalize(memories: Sequence[Memory | Mapping[str, Any]]) -> list[Memory]:
    normalized: list[Memory] = []
    seen: set[str] = set()
    for raw in memories:
        memory = _coerce(raw)
        if not isinstance(memory.id, str) or not memory.id:
            raise FitError("every item needs a non-empty string id")
        if not isinstance(memory.text, str):
            raise FitError(f"{memory.id}: text must be a string")
        if memory.id in seen:
            raise FitError(f"duplicate id: {memory.id}")
        seen.add(memory.id)
        normalized.append(memory)
    return normalized


def _coerce(raw: Memory | Mapping[str, Any]) -> Memory:
    if isinstance(raw, Memory):
        return raw
    if isinstance(raw, Mapping):
        try:
            ident = raw["id"]
            text = raw["text"]
        except KeyError as exc:
            raise FitError("memory mappings need 'id' and 'text'") from exc
        return Memory(
            id=ident,
            text=text,
            value=raw.get("value"),
            relevance=raw.get("relevance"),
            tokens=raw.get("tokens"),
        )
    raise FitError("memories must be items with an id and text")


def _candidate(index: int, memory: Memory, counter: TokenCounter) -> Candidate:
    relevance = None if memory.relevance is None else _number(memory.relevance, memory.id, "relevance")
    return Candidate(
        index=index,
        id=memory.id,
        text=memory.text,
        tokens=_resolve_tokens(memory, counter),
        value=_resolve_value(memory),
        relevance=relevance,
    )


def _resolve_value(memory: Memory) -> float:
    if memory.value is not None:
        return _number(memory.value, memory.id, "value")
    if memory.relevance is not None:
        return _number(memory.relevance, memory.id, "relevance")
    return 1.0


def _resolve_tokens(memory: Memory, counter: TokenCounter) -> int:
    if memory.tokens is None:
        counted = counter(memory.text)
        if isinstance(counted, bool) or not isinstance(counted, int) or counted < 1:
            raise FitError(f"{memory.id}: token_counter must return a positive integer")
        return counted
    if isinstance(memory.tokens, bool) or not isinstance(memory.tokens, int) or memory.tokens < 1:
        raise FitError(f"{memory.id}: tokens must be a positive integer")
    return memory.tokens


def _number(value: object, ident: str, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FitError(f"{ident}: {field} must be a number")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise FitError(f"{ident}: {field} must be a finite number")
    return number
