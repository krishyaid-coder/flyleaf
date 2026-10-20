# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Pack a token budget, and keep a reason for every candidate.

``density`` maximises total worth. It solves the 0/1 knapsack exactly
while the instance is small enough, and falls back to packing by worth
per token after that. ``similarity`` is the usual baseline: rank by
relevance, then take from the top until the budget is gone. ``greedy``
is that same pack, ordered by worth per token instead of relevance.
"""

from dataclasses import dataclass

# n * (budget + 1) cells. Past this, exact search gives way to greedy.
EXACT_CELL_LIMIT = 250_000
# Extra exact solves used only to explain drops. Past this, the reason
# names the trade without re-solving.
FORCE_IN_CELL_LIMIT = 2_000_000
_EPS = 1e-9


@dataclass(frozen=True)
class Candidate:
    """One item after worth and token cost are known."""

    index: int
    id: str
    text: str
    tokens: int
    value: float
    relevance: float | None

    @property
    def density(self) -> float:
        return self.value / self.tokens


@dataclass(frozen=True)
class Pack:
    chosen: frozenset[int]
    codes: dict[int, str]
    reasons: dict[int, str]
    method: str


def density_pack(candidates: list[Candidate], budget: int) -> Pack:
    if _over_exact_limit(candidates, budget):
        return _rank_pack(
            candidates,
            budget,
            score_of=lambda item: item.density,
            included_by="value per token",
            higher_than="higher value-per-token items",
            skip_non_positive=True,
            method="greedy",
        )
    chosen = _exact_indices(candidates, budget)
    codes, reasons = _explain_exact(candidates, chosen, budget)
    return Pack(frozenset(chosen), codes, reasons, "exact")


def greedy_pack(candidates: list[Candidate], budget: int) -> Pack:
    return _rank_pack(
        candidates,
        budget,
        score_of=lambda item: item.density,
        included_by="value per token",
        higher_than="higher value-per-token items",
        skip_non_positive=True,
        method="greedy",
    )


def similarity_pack(candidates: list[Candidate], budget: int) -> Pack:
    return _rank_pack(
        candidates,
        budget,
        score_of=_similarity,
        included_by="similarity rank",
        higher_than="higher-similarity items",
        skip_non_positive=False,
        method="rank",
    )


def _similarity(item: Candidate) -> float:
    if item.relevance is not None:
        return item.relevance
    return item.value


def _over_exact_limit(candidates: list[Candidate], budget: int) -> bool:
    return len(candidates) * (budget + 1) > EXACT_CELL_LIMIT


def _exact_indices(candidates: list[Candidate], budget: int) -> list[int]:
    """Indices of the maximum-value subset. Ties break toward fewer tokens."""
    if budget <= 0:
        return []
    items = [item for item in candidates if item.value > 0 and item.tokens <= budget]
    count = len(items)
    if count == 0:
        return []

    value = [0.0] * (budget + 1)
    used = [0] * (budget + 1)
    took = [bytearray(budget + 1) for _ in range(count)]

    for index, item in enumerate(items):
        weight = item.tokens
        gain = item.value
        row = took[index]
        for capacity in range(budget, weight - 1, -1):
            candidate_value = value[capacity - weight] + gain
            candidate_used = used[capacity - weight] + weight
            better_value = candidate_value > value[capacity] + _EPS
            same_value = abs(candidate_value - value[capacity]) <= _EPS
            if better_value or (same_value and candidate_used < used[capacity]):
                value[capacity] = candidate_value
                used[capacity] = candidate_used
                row[capacity] = 1

    best_capacity = 0
    for capacity in range(1, budget + 1):
        better_value = value[capacity] > value[best_capacity] + _EPS
        same_value = abs(value[capacity] - value[best_capacity]) <= _EPS
        if better_value or (same_value and used[capacity] < used[best_capacity]):
            best_capacity = capacity

    chosen: list[int] = []
    capacity = best_capacity
    for index in range(count - 1, -1, -1):
        if took[index][capacity]:
            chosen.append(items[index].index)
            capacity -= items[index].tokens
    return chosen


def _explain_exact(
    candidates: list[Candidate],
    chosen: list[int],
    budget: int,
) -> tuple[dict[int, str], dict[int, str]]:
    chosen_set = set(chosen)
    chosen_items = [item for item in candidates if item.index in chosen_set]
    best_value = sum(item.value for item in chosen_items)
    best_tokens = sum(item.tokens for item in chosen_items)
    codes: dict[int, str] = {}
    reasons: dict[int, str] = {}
    competitive: list[Candidate] = []

    for item in candidates:
        if item.index in chosen_set:
            codes[item.index] = "selected"
            reasons[item.index] = "In the highest-value set that fits."
        elif budget <= 0:
            codes[item.index] = "empty_budget"
            reasons[item.index] = "The budget is 0 tokens."
        elif item.value <= 0:
            codes[item.index] = "non_positive"
            reasons[item.index] = "Value is not positive, so it does not earn any tokens."
        elif item.tokens > budget:
            codes[item.index] = "exceeds_budget"
            reasons[item.index] = f"Needs {item.tokens} tokens, more than the budget of {budget}."
        else:
            competitive.append(item)

    use_force_in = len(competitive) * max(len(candidates), 1) * (budget + 1) <= FORCE_IN_CELL_LIMIT
    for item in competitive:
        codes[item.index] = "displaced"
        if use_force_in:
            reasons[item.index] = _force_in_reason(item, candidates, budget, best_value, best_tokens)
        else:
            reasons[item.index] = _displacement_reason(item, chosen_items, budget, best_value)
    return codes, reasons


def _force_in_reason(
    item: Candidate,
    candidates: list[Candidate],
    budget: int,
    best_value: float,
    best_tokens: int,
) -> str:
    others = [candidate for candidate in candidates if candidate.index != item.index]
    rest = _exact_indices(others, budget - item.tokens)
    rest_set = set(rest)
    rest_items = [candidate for candidate in others if candidate.index in rest_set]
    forced_value = item.value + sum(candidate.value for candidate in rest_items)
    forced_tokens = item.tokens + sum(candidate.tokens for candidate in rest_items)
    if forced_value < best_value - _EPS:
        return f"Forcing this in drops total value from {best_value:.2f} to {forced_value:.2f}."
    if forced_tokens > best_tokens:
        return (
            f"Forcing this in ties on value but uses {forced_tokens} tokens instead of {best_tokens}."
        )
    return "Left out of the highest-value set that fits."


def _displacement_reason(
    item: Candidate,
    chosen_items: list[Candidate],
    budget: int,
    best_value: float,
) -> str:
    """A concrete trade that is true even when we do not re-solve."""
    room = budget - sum(candidate.tokens for candidate in chosen_items)
    if item.tokens <= room:
        return f"Left out of the highest-value set (worth {best_value:.2f})."
    need = item.tokens - room
    victims = sorted(
        chosen_items,
        key=lambda candidate: (candidate.density, candidate.value, candidate.index),
    )
    removed: list[Candidate] = []
    freed = 0
    for victim in victims:
        removed.append(victim)
        freed += victim.tokens
        if freed >= need:
            break
    removed_value = sum(victim.value for victim in removed)
    if removed and item.value <= removed_value + _EPS:
        names = ", ".join(victim.id for victim in removed)
        return (
            f"Taking it means dropping {names} (worth {removed_value:.2f}) "
            f"to free {freed} tokens, and this item is only worth {item.value:.2f}."
        )
    return f"Left out of the highest-value set (worth {best_value:.2f})."


def _rank_pack(
    candidates: list[Candidate],
    budget: int,
    *,
    score_of,
    included_by: str,
    higher_than: str,
    skip_non_positive: bool,
    method: str,
) -> Pack:
    codes: dict[int, str] = {}
    reasons: dict[int, str] = {}
    chosen: list[int] = []
    remaining = budget
    ordered = sorted(candidates, key=lambda item: (-score_of(item), item.index))

    for item in ordered:
        if budget <= 0:
            codes[item.index] = "empty_budget"
            reasons[item.index] = "The budget is 0 tokens."
            continue
        if skip_non_positive and item.value <= 0:
            codes[item.index] = "non_positive"
            reasons[item.index] = "Value is not positive, so it does not earn any tokens."
            continue
        if item.tokens > budget:
            codes[item.index] = "exceeds_budget"
            reasons[item.index] = f"Needs {item.tokens} tokens, more than the budget of {budget}."
            continue
        if item.tokens <= remaining:
            open_before = remaining
            remaining -= item.tokens
            chosen.append(item.index)
            codes[item.index] = "selected"
            reasons[item.index] = (
                f"Included by {included_by}, and {item.tokens} tokens fit in the {open_before} still open."
            )
            continue
        codes[item.index] = "no_room"
        reasons[item.index] = (
            f"Needs {item.tokens} tokens and only {remaining} remained after {higher_than}."
        )

    return Pack(frozenset(chosen), codes, reasons, method)
