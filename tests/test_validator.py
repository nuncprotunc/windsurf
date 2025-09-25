from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tools.schema_validator import SchemaValidator

POLICY_PATH = Path(__file__).resolve().parents[1] / "jd/policy/cards_policy.yml"

POLICY_DATA = {
    "schema": {
        "required_fields": [
            "front",
            "back",
            "why_it_matters",
            "mnemonic",
            "diagram",
            "tripwires",
            "anchors",
            "keywords",
            "reading_level",
            "tags",
        ]
    },
    "back": {
        "min_words": 160,
        "max_words": 280,
        "max_sentence_words": 28,
        "required_headings_regex": [
            "^Issue\\.",
            "^Rule\\.",
            "^Application scaffold\\.",
            "^Authorities map\\.",
            "^Statutory hook\\.",
            "^Tripwires\\.",
            "^Conclusion\\.",
        ],
        "allow_missing_blocks_if_not_applicable": True,
        "authority_per_step": {
            "lead_required": True,
            "fallback_allowed": True,
            "max_per_step": 2,
        },
        "statutes_listed_must_be_used_in_text": True,
        "abbreviations": {
            "expand_on_first_use": True,
            "use_after_definition": True,
        },
        "tripwire_mentions_in_back": "discourage",
    },
    "anchors": {
        "structure": {"cases": [], "statutes": [], "notes": []},
        "min_items": 1,
        "max_items": 8,
        "each_item_max_words": 120,
        "require_case_or_statute_ref_per_item": True,
        "uk_or_persuasive_requires_note": True,
    },
    "statutes": {
        "include_only_operational_sections": True,
        "prefer_victoria_first": True,
        "require_commonwealth_if_engaged": True,
    },
    "authorities": {
        "priority_order": ["HCA", "State CA", "Other Aus", "UK/PC (nuance)"],
        "uk_nuance_note_required": True,
        "flag_overruled_or_distinguished": True,
        "require_year_and_neutral_or_report_cite": True,
        "min_unique_authorities_in_back": 2,
        "max_unique_authorities_in_back": 8,
    },
    "keywords": {
        "min": 6,
        "max": 10,
        "recommended_include_if_relevant": [
            "salient features",
            "exclusive possession",
            "relational loss",
            "proportionate liability",
            "obvious risk",
            "scope of liability",
            "voluntary assumption of risk",
            "vicarious liability",
        ],
    },
    "diagram": {
        "type": "mindmap",
        "must_be_valid_mermaid": True,
        "max_total_nodes": 12,
        "top_level_branches_min": 4,
        "top_level_branches_max": 5,
        "discourage_heading_mirroring": True,
    },
    "tripwires": {
        "min": 3,
        "max": 6,
    },
    "tags": {
        "required": ["MLS_H1"],
        "recommended_subject_tags": ["LAWS50025_Torts", "Exam_Fundamentals"],
    },
    "lint": {
        "forbid_repeated_sentences_similarity_threshold": 0.8,
        "forbid_duplicate_section_headers": True,
        "forbid_placeholder_text_regex": ["TBD", "lorem ipsum"],
        "allow_explicit_uncertainty_token": "[NO VERIFIED AUTHORITY FOUND]",
    },
}

HEADINGS = [
    "Issue.",
    "Rule.",
    "Application scaffold.",
    "Authorities map.",
    "Statutory hook.",
    "Tripwires.",
    "Conclusion.",
]

SECTION_TEXT = {
    "Issue.": (
        "This negligence duty question maps the plaintiff relationship and notes the risk context for exam precision. "
        "We keep the issue distinct from breach or causation so the answer stays aligned with the call."
    ),
    "Rule.": (
        "The duty analysis follows salient features, coherence and statutory adjustments from Wrongs Act reforms and High Court guidance. "
        "We emphasise policy reasons that justify recognising the duty while rejecting factors that undermine negligence doctrine."
    ),
    "Application scaffold.": (
        "First, compare the scenario to recognised categories, identifying vulnerability, control and reliance without skipping statutory text. "
        "Second, run Wrongs Act breach calculus and causation pathways so the reasoning integrates legislative and common law structure. "
        "Third, close by flagging defences and remedial considerations, keeping the scaffold exam-ready and easy to adapt under pressure."
    ),
    "Authorities map.": (
        "Step 1 — Sullivan v Moody (HCA 2001) [2001] HCA 59; 207 Commonwealth Law Reports (CLR) 562 emphasises coherence in novel relationships. "
        "Step 2 — Perre v Apand (HCA 1999) [1999] HCA 36; 198 CLR 180 confirms vulnerability as the lead feature in economic loss."
    ),
    "Statutory hook.": (
        "Wrongs Act 1958 (Vic) s 48 demands breach reasoning that tracks foreseeability, response and burden through each exam step. "
        "Wrongs Act 1958 (Vic) s 52 reinforces causation by requiring material contribution analysis aligned with the Application scaffold."
    ),
    "Tripwires.": (
        "Never conflate the duty question with breach calibration or the answer loses coherence and ignores reservations. "
        "Watch for defendants invoking policy to block recognition when facts mirror Sullivan v Moody constraints in the authorities map."
    ),
    "Conclusion.": (
        "Return to the issue by affirming the plaintiff pathway and specify how the duty opens the door to relief. "
        "Finish with a reminder about residual statutory requirements so markers see disciplined compliance."
    ),
}

DIAGRAM = """```mermaid
mindmap
  Duty focus
    Thresholds
    Salient features
  Statutes
    Wrongs Act s 48
  Authorities
    Sullivan v Moody
    Perre v Apand
  Exam tips
    Time management
```
"""

BASE_CARD = {
    "front": "How do you establish a negligence duty in novel relationships?",
    "back": "",
    "why_it_matters": "Exam markers reward disciplined duty analysis because it directs the negligence answer under heavy time pressure.",
    "mnemonic": "DUTYMAP",
    "diagram": DIAGRAM,
    "tripwires": [
        "Confusing duty scope with breach calibration when salient features need separate attention.",
        "Skipping Wrongs Act s 48 elements before concluding on breach obligations.",
        "Relying on policy slogans without anchoring them in Sullivan v Moody guidance.",
    ],
    "anchors": [
        "Sullivan v Moody (2001) 207 CLR 562 — coherence boundaries for duty recognition.",
        "Wrongs Act 1958 (Vic) s 48 — breach calculus structure that informs the scaffold.",
        "Perre v Apand (1999) 198 CLR 180 — vulnerability focus and economic loss nuance.",
    ],
    "keywords": [
        "salient features",
        "coherence",
        "Wrongs Act",
        "vulnerability",
        "policy",
        "exam strategy",
    ],
    "reading_level": "Plain English (JD)",
    "tags": ["MLS_H1", "LAWS50025_Torts"],
}


@pytest.fixture(scope="module")
def validator() -> SchemaValidator:
    return SchemaValidator(POLICY_PATH, policy_data=POLICY_DATA)


def build_back(overrides: dict[str, str] | None = None, omit: set[str] | None = None) -> str:
    overrides = overrides or {}
    omit = omit or set()
    parts = []
    for heading in HEADINGS:
        if heading in omit:
            continue
        body = overrides.get(heading, SECTION_TEXT[heading])
        parts.append(f"{heading}\n{body.strip()}")
    return "\n\n".join(parts)


@pytest.fixture
def base_card() -> dict:
    card = copy.deepcopy(BASE_CARD)
    card["back"] = build_back()
    return card


def test_valid_card_passes(validator: SchemaValidator, base_card: dict) -> None:
    result = validator.validate_card(base_card)
    assert result.is_valid
    assert not result.errors


def test_missing_required_field(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    card.pop("mnemonic")
    result = validator.validate_card(card)
    assert any("Missing required field" in err or "Field 'mnemonic'" in err for err in result.errors)


def test_missing_rule_heading(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    card["back"] = build_back(omit={"Rule."})
    result = validator.validate_card(card)
    assert any("Rule." in err for err in result.errors)


def test_too_many_authorities(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    authorities = (
        "Step 1 — Sullivan v Moody (HCA 2001) [2001] HCA 59; 207 CLR 562 emphasises coherence when recognising duties. "
        "Caparo Industries v Dickman (UK 1990) [1990] UKHL 2 nuance: fairness guidance. "
        "Donoghue v Stevenson (UK 1932) [1932] AC 562 articulated neighbour principle."
    )
    card["back"] = build_back(overrides={"Authorities map.": authorities})
    result = validator.validate_card(card)
    assert any("lists" in err for err in result.errors)


def test_uk_authority_requires_nuance(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    authorities = (
        "Step 1 — Sullivan v Moody (HCA 2001) [2001] HCA 59; 207 CLR 562 emphasises coherence when recognising duties. "
        "Step 2 — Caparo Industries v Dickman (UK 1990) [1990] UKHL 2 confirms proximity and fairness obligations."
    )
    card["back"] = build_back(overrides={"Authorities map.": authorities})
    result = validator.validate_card(card)
    assert any("nuance" in err.lower() for err in result.errors)


def test_invalid_mermaid_nodes(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    nodes = "\n".join(f"  Branch{i}" for i in range(6))
    card["diagram"] = f"```mermaid\nmindmap\n{nodes}\n```"
    result = validator.validate_card(card)
    assert any("Mindmap" in err for err in result.errors)


def test_tripwires_below_minimum(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    card["tripwires"] = ["Only one tripwire provided."]
    result = validator.validate_card(card)
    assert any("tripwires" in err.lower() for err in result.errors)


def test_keywords_below_minimum(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    card["keywords"] = ["salient features", "coherence", "policy"]
    result = validator.validate_card(card)
    assert any("keywords" in err.lower() for err in result.errors)


def test_duplicate_sentences_flagged(validator: SchemaValidator, base_card: dict) -> None:
    card = copy.deepcopy(base_card)
    duplicate_sentence = "This negligence duty question demands mapping the plaintiff relationship and noting the risk context for exam precision."
    card["why_it_matters"] = duplicate_sentence
    result = validator.validate_card(card)
    assert any("duplicate" in err.lower() for err in result.errors)
