#!/usr/bin/env python3
"""Pareto flashcard processor.

Consolidated normalization, repair, curated edits, authority checks,
and scaffold generation. Designed for your Windsurf repo layout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import shutil

# ---------------------------------------------------------------------------
# Third-party deps
# ---------------------------------------------------------------------------
try:
    import yaml  # type: ignore
except ImportError:  # deterministic failure path
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]  # repo root (…/Windsurf)

CARD_DIRS = [
    ROOT / "jd" / "cards_yaml",
    ROOT / "jd" / "LAWS50025 - Torts",                # your folder with cards
    ROOT / "jd" / "LAWS50025 - Torts" / "cards_yaml",
    ROOT / "jd" / "LAWS50029 - Contracts" / "cards_yaml",
]
CARD_DIRS = [d for d in CARD_DIRS if d.exists()]

if not CARD_DIRS:
    default_dir = ROOT / "jd" / "cards_yaml"
    default_dir.mkdir(parents=True, exist_ok=True)
    CARD_DIRS = [default_dir]

REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Topic-based authority expectations (stable, no filename coupling)
# ---------------------------------------------------------------------------
TOPIC_AUTHORITY_PATTERNS: Dict[str, List[str]] = {
    "causation": [
        r"\bWrongs Act 1958 \(Vic\)\s*s\s*51\(2\)\b",
        r"March v Stramare",
        r"Wallace v Kam",
    ],
    "trespass-person": [
        r"Plenty v Dillon",
        r"Halliday v Nevill",
        r"Kuru v (State of )?NSW",
    ],
    "nuisance": [
        r"\bgravity of harm\b",
        r"\blocality\b",
        r"\bsensitivity\b",
        r"\bduration\b",
        r"\bmalice\b",
        r"\butility\b",
    ],
    "defamation": [
        r"Defamation Act 2005 \(Vic\)",
        r"\bpublication\b",
        r"\bidentification\b",
        r"\bdefamatory meaning\b",
        r"\bserious harm\b",
    ],
    "contracts": [
        r"Carlill",
        r"Masters v Cameron|Masters v\.? Cameron",
        r"R v Clarke",
        r"Ermogenous",
    ],
    "apportionment": [
        r"\bPt\s*IVAA\b",
        r"\beconomic loss|property damage\b",
        r"\bconcurrent wrongdoers?|apportionment\b",
        r"\bcontribution\b",
    ],
}

AUTHORITY_HINTS: Dict[str, List[str]] = {
    "Duty": [r"Sullivan v Moody", r"Perre v Apand", r"Woolcock Street"],
    "Breach": [r"Wyong.*Shirt", r"Rogers v Whitaker", r"\bs\s*59\b"],
    "Causation": [
        r"\bWrongs Act 1958 \(Vic\)\s*s\s*51\(1\)\(a\)",
        r"March v Stramare",
        r"Strong v Woolworths",
        r"Wallace v Kam",
    ],
    "Property": [r"Plenty v Dillon|Halliday v Nevill|Kuru v (State of )?NSW"],
    "Defamation": [r"Defamation Act 2005 \(Vic\)"],
    "Apportionment": [r"Pt\s*IVAA"],
}

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------
@dataclass
class Flashcard:
    path: Path
    front: str = ""
    back: str = ""
    tags: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    mnemonic: str = ""
    _raw: Dict = field(default_factory=dict)
    _errors: List[str] = field(default_factory=list)
    _warnings: List[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------
class FlashcardProcessor:
    """End-to-end processing pipeline for flashcards."""

    CONTRACT_REQUIRED_ELEMENTS = (
        "offer",
        "acceptance",
        "consideration",
        "intention to create legal relations",
    )

    def __init__(self) -> None:
        self.card_dirs = [d for d in CARD_DIRS if d.exists()]
        self._policy_path = ROOT / "jd" / "policy" / "cards_policy.yml"

        self._schema_validator = None
        self._schema_validator_error = ""
        self._schema_validator_loaded = False

        self._compiled_topic_patterns = {
            topic: [re.compile(pat, re.IGNORECASE) for pat in patterns]
            for topic, patterns in TOPIC_AUTHORITY_PATTERNS.items()
        }
        self._compiled_authority_hints = {
            topic: [re.compile(pat, re.IGNORECASE) for pat in patterns]
            for topic, patterns in AUTHORITY_HINTS.items()
        }

    # ---------------- Schema validator (optional, non-fatal) ----------------
    def _get_schema_validator(self):
        if self._schema_validator_loaded:
            return self._schema_validator
        self._schema_validator_loaded = True
        try:
            from schema_validator import SchemaValidator
        except ImportError as exc:
            self._schema_validator_error = (
                f"Warning: Could not import SchemaValidator ({exc}); validation disabled."
            )
            return None
        if not self._policy_path.exists():
            self._schema_validator_error = (
                "Warning: Flashcard policy file not found; validation disabled."
            )
            return None
        try:
            self._schema_validator = SchemaValidator(str(self._policy_path))
        except Exception as exc:
            self._schema_validator_error = f"Warning: Failed to load schema validator: {exc}"
        return self._schema_validator

    def _add_validator_warning(self, card: Flashcard) -> None:
        if self._schema_validator_error and self._schema_validator_error not in card._warnings:
            card._warnings.append(self._schema_validator_error)

    # ---------------- Persistence ----------------
    def load_card(self, path: Path) -> Flashcard:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            card = Flashcard(path=path)
            card.front = (data.get("front") or "").strip()
            card.back = (data.get("back") or "").strip()
            card.tags = data.get("tags", []) or []
            card.sources = data.get("sources", []) or []
            card.created = data.get("created", "") or ""
            card.updated = data.get("updated", "") or ""
            card.mnemonic = (data.get("mnemonic") or "").strip()
            card._raw = data
            return card
        except Exception as exc:
            card = Flashcard(path=path)
            card._errors.append(f"Failed to load card: {exc}")
            return card

    def save_card(self, card: Flashcard, backup: bool = True) -> bool:
        if not card.path.parent.exists():
            card.path.parent.mkdir(parents=True, exist_ok=True)

        if backup and card.path.exists():
            backup_dir = REPORTS_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"{card.path.stem}.bak-{timestamp}"
            shutil.copy2(card.path, backup_path)

        try:
            with open(card.path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(card._raw, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return True
        except Exception as exc:
            card._errors.append(f"Failed to save card: {exc}")
            return False

    # ---------------- Classification helpers ----------------
    def is_contract_card(
        self,
        card: Flashcard,
        content_lower: Optional[str] = None,
        card_directory: Optional[Path] = None,
    ) -> bool:
        # Heuristics: filename, tags, folder, content
        if card.path.stem.startswith("0008-"):
            return True
        card_directory = card_directory or card.path.parent
        tags = {t.lower() for t in (card.tags or [])}
        if {"contract", "contracts"} & tags:
            return True
        if "contracts" in card_directory.name.lower():
            return True
        if content_lower is None:
            content_lower = f"{card.front} {card.back}".lower()
        return "contract" in content_lower

    def _detect_topics(self, card: Flashcard, content_lower: str) -> List[str]:
        stem = card.path.stem.lower()
        tags = {t.lower() for t in (card.tags or [])}
        topics: List[str] = []

        if "causation" in stem or "s51" in stem or "scope" in stem:
            topics.append("causation")
        if "trespass" in stem and "person" in stem:
            topics.append("trespass-person")
        if "nuisance" in stem:
            topics.append("nuisance")
        if stem.startswith("s001-") or "defamation" in stem:
            topics.append("defamation")
        if "proportionate" in stem or "ivaa" in content_lower:
            topics.append("apportionment")
        if self.is_contract_card(card, content_lower, card.path.parent) or ("contract" in tags or "contracts" in tags):
            topics.append("contracts")

        # de-dup, preserve order
        return list(dict.fromkeys(topics))

    def check_authorities(self, card: Flashcard, content: str, is_contract: bool) -> List[str]:
        missing: List[str] = []
        topics = self._detect_topics(card, content.lower())

        for topic in topics:
            for pat in self._compiled_topic_patterns.get(topic, []):
                if not pat.search(content):
                    missing.append(f"Missing authority reference: {pat.pattern} (topic: {topic})")

        # If it looks like contracts but topic detection missed it
        if not topics and is_contract:
            for pat in self._compiled_topic_patterns.get("contracts", []):
                if not pat.search(content):
                    missing.append(f"Missing authority reference: {pat.pattern} (topic: contracts)")

        # Friendly hint if we see nearby signals but no exact matches above
        if missing:
            for hint_topic, hint_pats in self._compiled_authority_hints.items():
                if any(h.search(content) for h in hint_pats):
                    missing.append(f"Consider referencing key {hint_topic.lower()} authorities.")
                    break

        return missing

    # ---------------- Transforms ----------------
    def normalize_card(self, card: Flashcard) -> None:
        validator = self._get_schema_validator()

        card_data = dict(card._raw)
        card_data.setdefault("front", card.front)
        card_data.setdefault("back", card.back)
        card_data.setdefault("tags", card.tags)
        card_data.setdefault("created", card.created)
        card_data.setdefault("updated", card.updated)
        card_data.setdefault("template", card._raw.get("template", "concept"))

        if validator is not None:
            result = validator.validate_card(card_data)
            card._errors.extend(result.errors)
            card._warnings.extend(result.warnings)
        else:
            self._add_validator_warning(card)

        if not card.front:
            card._errors.append("Front text is required")

        # squash whitespace
        card.front = " ".join((card.front or "").split())
        card.back = " ".join((card.back or "").split())

        # normalize tags
        seen = set()
        normalized_tags: List[str] = []
        for tag in card.tags or []:
            clean = tag.lower().strip()
            if clean and clean not in seen:
                seen.add(clean)
                normalized_tags.append(clean)
        card.tags = normalized_tags

        if "template" not in card_data:
            card_data["template"] = "concept"

        timestamp = datetime.utcnow().isoformat() + "Z"
        if not card.created:
            card.created = timestamp
        card.updated = timestamp

        # push back to raw
        card._raw.update(card_data)
        card._raw["front"] = card.front
        card._raw["back"] = card.back
        card._raw["tags"] = card.tags
        card._raw["created"] = card.created
        card._raw["updated"] = card.updated

    def repair_yaml(self, card: Flashcard) -> bool:
        repaired = False
        if "front" not in card._raw:
            card._raw["front"] = card.front
            repaired = True
        for lf in ("tags", "sources"):
            if lf not in card._raw or not isinstance(card._raw[lf], list):
                card._raw[lf] = getattr(card, lf)
                repaired = True
        return repaired

    def apply_curated_edits(self, card: Flashcard) -> bool:
        edited = False
        # Style polish for case names on front if tagged torts
        if "tort" in {t.lower() for t in card.tags} and "v." in card.front and " v. " not in card.front:
            card.front = card.front.replace(" v ", " v. ")
            edited = True
        return edited

    def _check_contract_requirements(self, card: Flashcard, content_lower: str) -> None:
        missing = [e for e in self.CONTRACT_REQUIRED_ELEMENTS if e not in content_lower]
        if missing:
            card._warnings.append(f"Contract card missing key elements: {', '.join(missing)}")

        # nudge to include foundational contract authorities
        has_key = any(
            pat.search(content_lower)
            for pat in self._compiled_topic_patterns.get("contracts", [])
        )
        if not has_key:
            card._warnings.append("Contract card should reference key cases (Carlill, Masters v Cameron, etc.)")

    # ---------------- Public interface ----------------
    def process_card(self, path: Path, apply_changes: bool = False) -> Dict:
        card = self.load_card(path)
        if card._errors:
            return {
                "path": str(path),
                "status": "error",
                "errors": card._errors,
                "warnings": card._warnings,
                "valid": False,
            }

        repairs = self.repair_yaml(card)
        edits = self.apply_curated_edits(card)
        self.normalize_card(card)

        combined = f"{card.front} {card.back}".strip()
        content_lower = combined.lower()
        is_contract = self.is_contract_card(card, content_lower, path.parent)

        missing = self.check_authorities(card, combined, is_contract)
        card._warnings.extend(missing)

        if is_contract:
            self._check_contract_requirements(card, content_lower)

        result: Dict[str, object] = {
            "path": str(path),
            "status": "valid" if not card._errors else "invalid",
            "errors": card._errors,
            "warnings": card._warnings,
            "repairs": repairs,
            "edits": edits,
            "valid": not bool(card._errors),
        }

        if apply_changes and result["valid"]:
            saved = self.save_card(card)
            result["saved"] = saved
            result["status"] = "saved" if saved else "error"
            if not saved:
                result["valid"] = False

        return result

    def find_cards(self, pattern: str = "*.yml") -> List[Path]:
        # Always search within known card dirs; pattern is relative glob
        matches: List[Path] = []
        for base in self.card_dirs:
            matches.extend(sorted(base.glob(pattern)))
        return matches

# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _print_result(card_path: Path, result: Dict, verbose: bool = False) -> None:
    status = str(result["status"]).upper()
    print(f"{status}: {card_path.name}")
    if verbose or result.get("errors") or result.get("warnings"):
        for error in result.get("errors", []):
            print(f"  ERROR: {error}")
        for warning in result.get("warnings", []):
            print(f"  WARN: {warning}")

def _print_summary(results: List[Dict]) -> None:
    print("\nProcessing complete!")
    print(f"Total cards: {len(results)}")
    print(f"Valid: {sum(1 for r in results if r.get('valid'))}")
    print(f"Errors: {sum(1 for r in results if r.get('errors'))}")
    print(f"Warnings: {sum(1 for r in results if r.get('warnings'))}")

def _write_json_report(results: List[Dict], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "processed": len(results),
            "pass": sum(1 for r in results if r.get("valid")),
            "fail": sum(1 for r in results if not r.get("valid")),
        },
        "cards": results,
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

def _write_markdown_report(results: List[Dict], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = [
        "# Flashcard QA Report",
        "",
        f"- Processed: {len(results)}",
        f"- Pass: {sum(1 for r in results if r.get('valid'))}",
        f"- Fail: {sum(1 for r in results if not r.get('valid'))}",
        "",
    ]
    for item in results:
        lines.append(f"## {item['path']}")
        lines.append(f"- Status: {item['status']}")
        lines.append(f"- Valid: {'Yes' if item['valid'] else 'No'}")
        lines.append(f"- Repairs: {bool(item.get('repairs'))}")
        lines.append(f"- Edits: {bool(item.get('edits'))}")
        if "saved" in item:
            lines.append(f"- Saved: {bool(item.get('saved'))}")
        if item.get("errors"):
            lines.append("- Errors:")
            lines.extend(f"  - {e}" for e in item["errors"])
        else:
            lines.append("- Errors: None")
        if item.get("warnings"):
            lines.append("- Warnings:")
            lines.extend(f"  - {w}" for w in item["warnings"])
        else:
            lines.append("- Warnings: None")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def process_cards(
    processor: FlashcardProcessor,
    pattern: str,
    apply_changes: bool = False,
    verbose: bool = False,
    report_json: Optional[str] = None,
    report_md: Optional[str] = None,
) -> int:
    cards = processor.find_cards(pattern)
    if not cards:
        print(f"No cards found matching pattern: {pattern}")
        return 1

    print(f"Processing {len(cards)} cards...")
    results: List[Dict] = []
    for card_path in cards:
        result = processor.process_card(card_path, apply_changes)
        results.append(result)
        _print_result(card_path, result, verbose)

    _print_summary(results)

    if report_json:
        _write_json_report(results, (ROOT / report_json) if not Path(report_json).is_absolute() else Path(report_json))
    if report_md:
        _write_markdown_report(results, (ROOT / report_md) if not Path(report_md).is_absolute() else Path(report_md))

    return 0 if all(r.get("valid") for r in results) else 1

def _run_single_stage(
    processor: FlashcardProcessor,
    pattern: str,
    stage: str,
    handler,
    apply_changes: bool,
    verbose: bool,
) -> int:
    cards = processor.find_cards(pattern)
    if not cards:
        print(f"No cards found matching pattern: {pattern}")
        return 1

    print(f"{stage.capitalize()} {len(cards)} cards...")
    results: List[Dict] = []
    for card_path in cards:
        result = handler(card_path, apply_changes)
        results.append(result)
        _print_result(card_path, result, verbose)

    _print_summary(results)
    return 0 if all(r.get("valid") for r in results) else 1

def normalize_cards(processor: FlashcardProcessor, pattern: str, apply_changes: bool, verbose: bool) -> int:
    def handler(card_path: Path, apply_changes: bool) -> Dict:
        card = processor.load_card(card_path)
        if card._errors:
            return {"path": str(card_path), "status": "error", "errors": card._errors, "warnings": card._warnings, "repairs": False, "edits": False, "valid": False}
        processor.normalize_card(card)
        result = {"path": str(card_path), "status": "valid" if not card._errors else "invalid", "errors": card._errors, "warnings": card._warnings, "repairs": False, "edits": False, "valid": not bool(card._errors)}
        if apply_changes and result["valid"]:
            saved = processor.save_card(card)
            result["saved"] = saved
            result["status"] = "saved" if saved else "error"
            if not saved:
                result["valid"] = False
        return result
    return _run_single_stage(processor, pattern, "normalizing", handler, apply_changes, verbose)

def repair_cards(processor: FlashcardProcessor, pattern: str, apply_changes: bool, verbose: bool) -> int:
    def handler(card_path: Path, apply_changes: bool) -> Dict:
        card = processor.load_card(card_path)
        if card._errors:
            return {"path": str(card_path), "status": "error", "errors": card._errors, "warnings": card._warnings, "repairs": False, "edits": False, "valid": False}
        repairs = processor.repair_yaml(card)
        result = {"path": str(card_path), "status": "repaired" if repairs else "unchanged", "errors": card._errors, "warnings": card._warnings, "repairs": repairs, "edits": False, "valid": not bool(card._errors)}
        if apply_changes and repairs:
            saved = processor.save_card(card)
            result["saved"] = saved
            result["status"] = "saved" if saved else "error"
            if not saved:
                result["valid"] = False
        return result
    return _run_single_stage(processor, pattern, "repairing", handler, apply_changes, verbose)

def edit_cards(processor: FlashcardProcessor, pattern: str, apply_changes: bool, verbose: bool) -> int:
    def handler(card_path: Path, apply_changes: bool) -> Dict:
        card = processor.load_card(card_path)
        if card._errors:
            return {"path": str(card_path), "status": "error", "errors": card._errors, "warnings": card._warnings, "repairs": False, "edits": False, "valid": False}
        edits = processor.apply_curated_edits(card)
        result = {"path": str(card_path), "status": "edited" if edits else "unchanged", "errors": card._errors, "warnings": card._warnings, "repairs": False, "edits": edits, "valid": not bool(card._errors)}
        if apply_changes and edits:
            saved = processor.save_card(card)
            result["saved"] = saved
            result["status"] = "saved" if saved else "error"
            if not saved:
                result["valid"] = False
        return result
    return _run_single_stage(processor, pattern, "editing", handler, apply_changes, verbose)

def scaffold_cards(
    processor: FlashcardProcessor,
    card_type: str,
    name: str,
    count: int,
    prefix: str,
    verbose: bool,
) -> int:
    policy_path = processor._policy_path
    policy = {}
    if policy_path.exists():
        with open(policy_path, "r", encoding="utf-8") as fh:
            policy = yaml.safe_load(fh) or {}

    required_fields: Iterable[str] = policy.get("schema", {}).get("required_fields", ["front", "back", "tags"])

    type_path = Path(card_type)
    if not type_path.is_absolute():
        within_jd = ROOT / "jd" / card_type
        if (within_jd / "cards_yaml").exists():
            target_dir = (within_jd / "cards_yaml")
        elif within_jd.exists():
            target_dir = within_jd
        else:
            target_dir = ROOT / "jd" / "cards_yaml"
    else:
        if (type_path / "cards_yaml").exists():
            target_dir = (type_path / "cards_yaml")
        elif type_path.is_dir():
            target_dir = type_path
        else:
            target_dir = ROOT / "jd" / "cards_yaml"

    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "card"
    created_files: List[Path] = []

    for index in range(count):
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        suffix = f"-{index + 1:02d}" if count > 1 else ""
        filename = f"{prefix}-{timestamp}-{slug}{suffix}.yml"
        file_path = target_dir / filename

        card_data: Dict[str, object] = {}
        diagram_block = "\n".join(
            [
                "```mermaid",
                "mindmap",
                f"  root(({name.strip()} scaffold))",
                "    Step 1",
                "    Step 2",
                "    Step 3",
                "    Step 4",
                "```",
            ]
        )

        anchors_block = {
            "cases": [
                "Placeholder v Placeholder (20XX) 123 CLR 456, 457",
                "Example Pty Ltd v Sample [2024] VSCA 12 [45]",
            ],
            "statutes": [
                "Wrongs Act 1958 (Vic) s 48",
                "Wrongs Act 1958 (Vic) s 51",
            ],
            "notes": [
                "Add policy nuance with pinpoint support [para XX].",
            ],
        }

        tripwire_list = [
            "Contractor misclassification vs employee status",
            'Automatic "in course" assumption without analysis',
            "Non-delegable duty confusion between categories",
        ]

        keywords = [
            "placeholder",
            "scaffold",
            "wrongs-act",
            "analysis",
            "statutory-hook",
            "tripwires",
        ]

        tags = ["MLS_H1"]
        type_tag = re.sub(r"[^A-Za-z0-9]+", "_", card_type).strip("_")
        if type_tag:
            tags.append(type_tag)

        for field in required_fields:
            if field == "front":
                card_data[field] = f"{name.strip()}?"
            elif field == "back":
                card_data[field] = "\n".join(
                    [
                        "Issue. <State the controversy needing resolution>",
                        "",
                        "Rule. <Summarise the governing tests and authorities>",
                        "",
                        "Application scaffold. <Lay out the analytical steps>",
                        "",
                        "Authorities map.",
                        "- Placeholder authority v Placeholder (20XX) 123 CLR 456, 457",
                        "- Example Pty Ltd v Sample [2024] VSCA 12 [45]",
                        "",
                        "Statutory hook.",
                        "- Wrongs Act 1958 (Vic) Pt IV  [add pinpoint]",
                        "- Wrongs Act 1958 (Vic) Pt VBA [add pinpoint]",
                        "",
                        "Tripwires.",
                        "- Contractor misclassification vs employee status",
                        '- Automatic "in course" assumption without analysis',
                        "- Non-delegable duty confusion between categories",
                        "",
                        "Conclusion. <Close the loop on the scaffold and relief>",
                    ]
                )
            elif field == "why_it_matters":
                card_data[field] = "Highlight how this scaffold wins time and marks under exam pressure."
            elif field == "mnemonic":
                card_data[field] = "Mnemonic to be confirmed"
            elif field == "diagram":
                card_data[field] = diagram_block
            elif field == "tripwires":
                card_data[field] = tripwire_list
            elif field == "anchors":
                card_data[field] = anchors_block
            elif field == "keywords":
                card_data[field] = keywords
            elif field == "reading_level":
                card_data[field] = policy.get("reading_level", {}).get("target", "Plain English (JD)")
            elif field == "tags":
                card_data[field] = tags
            else:
                card_data.setdefault(field, "")

        card_data.setdefault("template", "concept")

        with open(file_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(card_data, fh, sort_keys=False, allow_unicode=True)

        created_files.append(file_path)
        if verbose:
            print(f"Created scaffold: {file_path}")

    print(f"Created {len(created_files)} scaffold card(s) in {target_dir}")
    return 0

# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def process_command(args, processor: FlashcardProcessor) -> int:
    if args.command == "process":
        return process_cards(
            processor,
            args.pattern,
            args.apply,
            args.verbose,
            args.report_json,
            args.report_md,
        )
    if args.command == "normalize":
        return normalize_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == "repair":
        return repair_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == "edit":
        return edit_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == "scaffold":
        return scaffold_cards(processor, args.type, args.name, args.count, args.prefix, args.verbose)
    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process flashcards through various stages.")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    process_parser = subparsers.add_parser("process", help="Process cards through all stages")
    process_parser.add_argument("pattern", nargs="?", default="*.yml", help="File pattern to match (default: *.yml)")
    process_parser.add_argument("--apply", action="store_true", help="Apply changes to files")
    process_parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    process_parser.add_argument(
        "--report-json",
        nargs="?",
        const="reports/flashcard_check.json",
        default=None,
        help="Write JSON summary report (default path if flag provided)",
    )
    process_parser.add_argument(
        "--report-md",
        nargs="?",
        const="reports/flashcard_check.md",
        default=None,
        help="Write Markdown summary report (default path if flag provided)",
    )

    norm_parser = subparsers.add_parser("normalize", help="Normalize card content and format")
    norm_parser.add_argument("pattern", nargs="?", default="*.yml", help="File pattern to match (default: *.yml)")
    norm_parser.add_argument("--apply", action="store_true", help="Apply changes to files")
    norm_parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    repair_parser = subparsers.add_parser("repair", help="Repair YAML structure and formatting")
    repair_parser.add_argument("pattern", nargs="?", default="*.yml", help="File pattern to match (default: *.yml)")
    repair_parser.add_argument("--apply", action="store_true", help="Apply changes to files")
    repair_parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    edit_parser = subparsers.add_parser("edit", help="Apply curated content improvements")
    edit_parser.add_argument("pattern", nargs="?", default="*.yml", help="File pattern to match (default: *.yml)")
    edit_parser.add_argument("--apply", action="store_true", help="Apply changes to files")
    edit_parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    scaffold_parser = subparsers.add_parser("scaffold", help="Generate new card templates")
    scaffold_parser.add_argument("--type", required=True, help="Type of card to create")
    scaffold_parser.add_argument("--name", required=True, help="Name for the new card")
    scaffold_parser.add_argument("--count", type=int, default=1, help="Number of cards to generate")
    scaffold_parser.add_argument("--prefix", default="card", help="Prefix for generated filenames")
    scaffold_parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    processor = FlashcardProcessor()
    try:
        return process_command(args, processor)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            import traceback
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
