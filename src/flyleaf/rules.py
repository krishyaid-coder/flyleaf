# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Detection rules.

A rule matches a library, not a legal outcome. Role hints and review hints
are prompts for a person. They are not a risk tier.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewHint:
    id: str
    text: str
    citation_ids: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    framework: str
    category: str
    role_hint: str
    packages: frozenset[str]
    import_roots: frozenset[str]
    review_hints: tuple[ReviewHint, ...]


_API_HINTS = (
    ReviewHint(
        id="role",
        text=(
            "This looks like a client of a hosted model. "
            "Confirm whether you provide the model or deploy someone else's. "
            "Those roles carry different duties."
        ),
        citation_ids=("art-3-provider", "art-3-deployer", "art-53-gpai"),
    ),
    ReviewHint(
        id="transparency",
        text=(
            "If people receive generated text, audio, or images, "
            "Article 50 transparency is an area to review."
        ),
        citation_ids=("art-50-interaction",),
    ),
)

_ORCHESTRATION_HINTS = (
    ReviewHint(
        id="role",
        text=(
            "Orchestration code composes model calls. "
            "Review the system those calls sit inside. "
            "The import does not identify the use case."
        ),
        citation_ids=("art-3-provider", "art-3-deployer"),
    ),
)

_ML_HINTS = (
    ReviewHint(
        id="use_case",
        text=(
            "A machine-learning library does not say whether a use case is high-risk. "
            "Annex III depends on purpose. Fill that in yourself."
        ),
        citation_ids=("art-6-annex-iii",),
    ),
)


def _rule(
    framework: str,
    category: str,
    role_hint: str,
    packages: tuple[str, ...],
    import_roots: tuple[str, ...],
    review_hints: tuple[ReviewHint, ...],
) -> Rule:
    return Rule(
        framework=framework,
        category=category,
        role_hint=role_hint,
        packages=frozenset(packages),
        import_roots=frozenset(import_roots),
        review_hints=review_hints,
    )


RULES: tuple[Rule, ...] = (
    _rule(
        "openai",
        "llm_api",
        "api_client",
        ("openai",),
        ("openai",),
        _API_HINTS,
    ),
    _rule(
        "anthropic",
        "llm_api",
        "api_client",
        ("anthropic", "@anthropic-ai/sdk"),
        ("anthropic",),
        _API_HINTS,
    ),
    _rule(
        "google-genai",
        "llm_api",
        "api_client",
        (
            "google-generativeai",
            "google-genai",
            "@google/generative-ai",
            "@google/genai",
        ),
        ("google.generativeai", "google.genai"),
        _API_HINTS,
    ),
    _rule(
        "mistralai",
        "llm_api",
        "api_client",
        ("mistralai", "@mistralai/mistralai"),
        ("mistralai",),
        _API_HINTS,
    ),
    _rule(
        "cohere",
        "llm_api",
        "api_client",
        ("cohere", "cohere-ai"),
        ("cohere",),
        _API_HINTS,
    ),
    _rule(
        "langchain",
        "orchestration",
        "orchestration",
        (
            "langchain",
            "langchain-core",
            "langchain-openai",
            "langchain-community",
            "langchain-anthropic",
            "langchain-google-genai",
            "@langchain/core",
            "@langchain/openai",
            "@langchain/community",
            "@langchain/anthropic",
            "@langchain/google-genai",
        ),
        (
            "langchain",
            "langchain_core",
            "langchain_openai",
            "langchain_community",
            "langchain_anthropic",
            "langchain_google_genai",
        ),
        _ORCHESTRATION_HINTS,
    ),
    _rule(
        "llama-index",
        "orchestration",
        "orchestration",
        ("llama-index", "llama-index-core", "llamaindex"),
        ("llama_index",),
        _ORCHESTRATION_HINTS,
    ),
    _rule(
        "langgraph",
        "orchestration",
        "orchestration",
        ("langgraph", "@langchain/langgraph"),
        ("langgraph",),
        _ORCHESTRATION_HINTS,
    ),
    _rule(
        "torch",
        "ml_framework",
        "local_ml",
        ("torch", "torchvision", "torchaudio"),
        ("torch", "torchvision", "torchaudio"),
        _ML_HINTS,
    ),
    _rule(
        "tensorflow",
        "ml_framework",
        "local_ml",
        ("tensorflow", "tensorflow-cpu", "tensorflow-macos"),
        ("tensorflow",),
        _ML_HINTS,
    ),
    _rule(
        "scikit-learn",
        "ml_framework",
        "local_ml",
        ("scikit-learn", "sklearn"),
        ("sklearn",),
        _ML_HINTS,
    ),
    _rule(
        "transformers",
        "ml_framework",
        "local_ml",
        ("transformers",),
        ("transformers",),
        _ML_HINTS,
    ),
    _rule(
        "xgboost",
        "ml_framework",
        "local_ml",
        ("xgboost",),
        ("xgboost",),
        _ML_HINTS,
    ),
)


def match_import(module: str) -> Rule | None:
    """Return the rule with the longest import root that covers `module`."""
    best: Rule | None = None
    best_len = -1
    for rule in RULES:
        for root in rule.import_roots:
            if module == root or module.startswith(root + "."):
                if len(root) > best_len:
                    best = rule
                    best_len = len(root)
    return best


_PACKAGES: dict[str, Rule] = {}
for _rule_item in RULES:
    for _package in _rule_item.packages:
        if _package in _PACKAGES:
            raise RuntimeError(f"package {_package} is claimed by two rules")
        _PACKAGES[_package] = _rule_item


def match_package(name: str) -> Rule | None:
    return _PACKAGES.get(name)


def _validate_citation_ids() -> None:
    from flyleaf.citations import CITATIONS

    for rule in RULES:
        for hint in rule.review_hints:
            missing = [citation_id for citation_id in hint.citation_ids if citation_id not in CITATIONS]
            if missing:
                raise RuntimeError(f"{rule.framework} hint {hint.id} cites unknown ids: {missing}")


_validate_citation_ids()
