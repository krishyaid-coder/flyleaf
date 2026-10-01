# Copyright 2026 Krishna Dahale
# SPDX-License-Identifier: Apache-2.0
"""Versioned citations for review findings.

Edit this module when the Official Journal changes a provision the tool cites.
Bump PACK_VERSION and add a CHANGELOG entry in the same change. Reports copy
the version so an older run still names the text it used.
"""

from dataclasses import dataclass

PACK_VERSION = "2026.07.27"
AS_OF = "2026-07-27"

_AI_ACT_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689"
_AMENDMENT_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R1744"


@dataclass(frozen=True)
class Citation:
    id: str
    instrument: str
    celex: str
    pinpoint: str
    quote: str
    note: str
    source_url: str
    status: str = "current"


CITATIONS: dict[str, Citation] = {
    "art-3-provider": Citation(
        id="art-3-provider",
        instrument="Regulation (EU) 2024/1689",
        celex="32024R1689",
        pinpoint="Article 3(3)",
        quote=(
            "provider means a natural or legal person, public authority, agency or other body "
            "that develops an AI system or a general-purpose AI model or that has an AI system "
            "or a general-purpose AI model developed and places it on the market or puts the AI "
            "system into service under its own name or trademark, whether for payment or free of charge"
        ),
        note=(
            "Use this definition to decide whether you provide the model. "
            "An import of a hosted API does not settle that question."
        ),
        source_url=_AI_ACT_URL,
    ),
    "art-3-deployer": Citation(
        id="art-3-deployer",
        instrument="Regulation (EU) 2024/1689",
        celex="32024R1689",
        pinpoint="Article 3(4)",
        quote=(
            "deployer means a natural or legal person, public authority, agency or other body "
            "using an AI system under its authority except where the AI system is used in the "
            "course of a personal non-professional activity"
        ),
        note=(
            "Use this definition to decide whether you deploy someone else's system. "
            "Points (3) and (4) of Article 3 were not the points amended by Regulation (EU) 2026/1744."
        ),
        source_url=_AI_ACT_URL,
    ),
    "art-6-annex-iii": Citation(
        id="art-6-annex-iii",
        instrument="Regulation (EU) 2024/1689",
        celex="32024R1689",
        pinpoint="Article 6(2) and Annex III",
        quote=(
            "In addition to the high-risk AI systems referred to in paragraph 1, "
            "AI systems referred to in Annex III shall be considered to be high-risk."
        ),
        note=(
            "Annex III is a list of use cases. A library name is not one of those use cases. "
            "Fill in the purpose yourself, then read Article 6(3) for the derogation. "
            "Regulation (EU) 2026/1744 inserted Article 6(1a) to (1c) on safety components. "
            "It left this Article 6(2) sentence in place."
        ),
        source_url=_AI_ACT_URL,
    ),
    "art-11-annex-iv": Citation(
        id="art-11-annex-iv",
        instrument="Regulation (EU) 2024/1689",
        celex="32024R1689",
        pinpoint="Article 11(1) and Annex IV",
        quote=(
            "The technical documentation of a high-risk AI system shall be drawn up before that "
            "system is placed on the market or put into service and shall be kept up to date."
        ),
        note=(
            "This duty applies to high-risk systems. The scan cannot tell whether this component is one. "
            "Regulation (EU) 2026/1744 replaced the second subparagraph of Article 11(1): "
            "SMEs, including start-ups, and small mid-caps may supply the Annex IV elements "
            "in a simplified form once the Commission establishes that form. "
            "A missing or stale model card is a gap in the repository. It is not a finding that Article 11 has been breached."
        ),
        source_url=_AI_ACT_URL,
    ),
    "art-50-interaction": Citation(
        id="art-50-interaction",
        instrument="Regulation (EU) 2024/1689",
        celex="32024R1689",
        pinpoint="Article 50(1)",
        quote=(
            "Providers shall ensure that AI systems intended to interact directly with natural persons "
            "are designed and developed in such a way that the natural persons concerned are informed "
            "that they are interacting with an AI system, unless this is obvious from the point of view "
            "of a natural person who is reasonably well-informed, observant and circumspect, taking into "
            "account the circumstances and the context of use."
        ),
        note=(
            "Read this when people interact with generated output. "
            "The scan does not see the interface, so it cannot tell whether the duty applies. "
            "Regulation (EU) 2026/1744 replaced Article 50(7), which concerns codes of practice for marking synthetic content."
        ),
        source_url=_AI_ACT_URL,
    ),
    "art-53-gpai": Citation(
        id="art-53-gpai",
        instrument="Regulation (EU) 2024/1689",
        celex="32024R1689",
        pinpoint="Article 53(1)",
        quote=(
            "Providers of general-purpose AI models shall: "
            "(a) draw up and keep up to date the technical documentation of the model"
        ),
        note=(
            "Article 53 binds the provider of the general-purpose model. "
            "Calling that provider's API does not, by itself, make the caller that provider."
        ),
        source_url=_AI_ACT_URL,
    ),
    "art-113-application": Citation(
        id="art-113-application",
        instrument="Regulation (EU) 2026/1744",
        celex="32026R1744",
        pinpoint="Article 113, third paragraph, point (c), of Regulation (EU) 2024/1689, as replaced",
        quote=(
            "Chapter III, Sections 1, 2, and 3, with the exception of Article 6(5), shall apply from: "
            "(i) 2 December 2027 as regards AI systems classified as high-risk pursuant to Article 6(2) "
            "and Annex III; and (ii) 2 August 2028 as regards AI systems classified as high-risk pursuant "
            "to Article 6(1) and Annex I"
        ),
        note=(
            "Regulation (EU) 2026/1744 was published in the Official Journal on 24 July 2026 "
            "and entered into force on 27 July 2026. It deferred these Chapter III dates. "
            "The citation tells you when to read the high-risk duties. It does not classify the system."
        ),
        source_url=_AMENDMENT_URL,
    ),
}

DOCUMENTATION_CITATION_IDS = ("art-11-annex-iv", "art-113-application")

CHANGELOG: tuple[dict[str, str], ...] = (
    {
        "version": "2026.07.27",
        "summary": (
            "Initial pack. Regulation (EU) 2024/1689 as amended by Regulation (EU) 2026/1744, "
            "in force 27 July 2026. Records the deferred Chapter III dates in Article 113."
        ),
    },
)


def pack_meta() -> dict[str, str]:
    return {"version": PACK_VERSION, "as_of": AS_OF}


def citation_payload(citation_id: str) -> dict[str, str]:
    citation = CITATIONS[citation_id]
    return {
        "id": citation.id,
        "instrument": citation.instrument,
        "celex": citation.celex,
        "pinpoint": citation.pinpoint,
        "quote": citation.quote,
        "note": citation.note,
        "source_url": citation.source_url,
        "status": citation.status,
    }


def payloads_for(citation_ids: set[str]) -> dict[str, dict[str, str]]:
    return {citation_id: citation_payload(citation_id) for citation_id in sorted(citation_ids)}
