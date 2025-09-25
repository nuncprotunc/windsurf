#!/usr/bin/env python3
"""
Consolidated flashcard processing script combining:
- normalize_and_qa_cards.py
- repair_and_qa_yaml.py
- apply_curated_edits.py
- seed_scaffolds.py

Usage:
  python flashcard_processor.py [command] [options]

Commands:
  normalize    Standardize card content and format
  repair      Fix YAML structure and formatting
  edit        Apply curated content improvements
  scaffold    Generate new card templates
  process     Run complete processing pipeline
"""

import sys
import re
import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import shutil
from datetime import datetime

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Please install it with: pip install pyyaml")
    sys.exit(1)

# TODO: externalise to policy YAML.
AUTHORITY_PATTERNS = {
    "0004": [
        r"\bs\s*51\(2\)\b",
        r"Wallace v Kam",
        r"March v Stramare",
    ],
    "0005": [
        r"Plenty v Dillon",
        r"Halliday v Nevill",
        r"Kuru v (State of )?NSW",
    ],
    "0006": [
        r"gravity of harm",
        r"locality",
        r"sensitivity",
        r"duration",
        r"malice",
        r"utility",
    ],
    "0007": [
        r"Defamation Act 2005 \(Vic\)",
        r"publication",
        r"identification",
        r"defamatory meaning",
        r"serious harm",
    ],
    "0008": [
        r"Carlill",
        r"Masters v Cameron|Masters v\.? Cameron",
        r"R v Clarke",
        r"Ermogenous",
    ],
    "0009": [
        r"Pt\s*IVAA",
        r"economic loss|property damage",
        r"concurrent wrongdoers?|apportionment",
        r"contribution",
    ],
}

# TODO: externalise to policy YAML.
AUTHORITY_HINTS = {
    "Duty": [r"Sullivan v Moody", r"Perre v Apand", r"Woolcock Street"],
    "Breach": [r"Wyong.*Shirt", r"Rogers v Whitaker", r"\bs\s*59\b"],
    "Causation": [
        r"\bs\s*51\(1\)\(a\)",
        r"March v Stramare",
        r"Strong v Woolworths",
        r"Wallace v Kam",
    ],
    "Property": [r"Plenty v Dillon|Halliday v Nevill|Kuru v (State of )?NSW"],
    "Defamation": [r"Defamation Act 2005 \(Vic\)"],
    "Apportionment": [r"Pt\s*IVAA"],
}

# --- Constants ---
CARD_DIRS = [
    Path("jd/cards_yaml"),
    Path("jd") / "LAWS50025 - Torts" / "cards_yaml",
    Path("jd") / "LAWS50029 - Contracts" / "cards_yaml",
]

# Convert to absolute paths and ensure they exist
CARD_DIRS = [d.resolve() for d in CARD_DIRS if d.exists()]
if not CARD_DIRS:
    # If no card dirs found, use the first one and create it
    default_dir = Path("jd/cards_yaml").resolve()
    default_dir.mkdir(parents=True, exist_ok=True)
    CARD_DIRS = [default_dir]

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)


# --- Data Models ---
@dataclass
class Flashcard:
    """Represents a flashcard with all its metadata and content."""

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


# --- Core Processing Logic ---
class FlashcardProcessor:
    """Main class for processing flashcards with all combined functionality."""

    def __init__(self):
        self.card_dirs = [d for d in CARD_DIRS if d.exists()]

    def load_card(self, path: Path) -> Flashcard:
        """Load a flashcard from a YAML file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            card = Flashcard(path=path)
            card.front = data.get("front", "").strip()
            card.back = data.get("back", "").strip()
            card.tags = data.get("tags", [])
            card.sources = data.get("sources", [])
            card.created = data.get("created", "")
            card.updated = data.get("updated", "")
            card.mnemonic = data.get("mnemonic", "").strip()
            card._raw = data

            return card

        except Exception as e:
            card = Flashcard(path=path)
            card._errors.append(f"Failed to load card: {str(e)}")
            return card

    def is_contract_card(self, card: Flashcard) -> bool:
        """Check if a card is related to contract law."""
        tags = set((card.tags or []))
        front = (card.front or "").lower()

        if card.path.stem.startswith("0008-"):
            return True
        if any(t.lower() == "contract" for t in tags):
            return True
        if "contract" in front:
            return True
        return False

    def check_authorities(self, card: Flashcard) -> List[str]:
        """Check for required legal authorities based on card content."""
        missing = []
        content = f"{card.front} {card.back}".lower()

        # Check for topic-specific authorities
        if self.is_contract_card(card):
            for pattern in AUTHORITY_PATTERNS.get("0008", []):
                if not re.search(pattern, content, re.IGNORECASE):
                    missing.append(f"Missing contract authority: {pattern}")

        return missing

    def normalize_card(self, card: "Flashcard") -> None:
        """Normalize card content, sync raw data, and validate."""
        from schema_validator import SchemaValidator

        policy_path = (
            Path(__file__).parent.parent / "jd" / "policy" / "cards_policy.yml"
        )
        validator = SchemaValidator(str(policy_path))

        card.front = " ".join((card.front or "").split())
        card.back = " ".join((card.back or "").split())
        card.tags = sorted(
            {tag.lower().strip() for tag in (card.tags or []) if tag.strip()}
        )

        now = datetime.utcnow().isoformat() + "Z"
        if not card.created:
            card.created = now
        card.updated = now

        card._raw["front"] = card.front
        card._raw["back"] = card.back
        card._raw["tags"] = card.tags
        card._raw["created"] = card.created
        card._raw["updated"] = card.updated
        card._raw.setdefault("template", "concept")

        result = validator.validate_card(card._raw)

        card._errors.extend(result.errors)
        card._warnings.extend(result.warnings)

    def repair_yaml(self, card: Flashcard) -> bool:
        """Fix YAML formatting and structure issues."""
        repaired = False

        # Ensure required fields exist
        if "front" not in card._raw:
            card._raw["front"] = card.front
            repaired = True

        # Ensure lists are properly formatted
        for list_field in ["tags", "sources"]:
            if list_field not in card._raw or not isinstance(
                card._raw[list_field], list
            ):
                card._raw[list_field] = getattr(card, list_field)
                repaired = True

        return repaired

    def apply_curated_edits(self, card: Flashcard) -> bool:
        """Apply curated content improvements."""
        edited = False

        # Example edit: Ensure case names are properly formatted
        if "tort" in card.tags and "v." in card.front and " v. " not in card.front:
            card.front = card.front.replace(" v ", " v. ")
            edited = True

        # Add more curated edits here

        return edited

    def save_card(self, card: Flashcard, backup: bool = True) -> bool:
        """Save card to disk with optional backup."""
        if not card.path.parent.exists():
            card.path.parent.mkdir(parents=True)

        if backup and card.path.exists():
            backup_dir = REPORTS_DIR / "backups"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"{card.path.stem}.bak-{timestamp}"
            shutil.copy2(card.path, backup_path)

        try:
            with open(card.path, "w", encoding="utf-8") as f:
                yaml.dump(card._raw, f, default_flow_style=False, sort_keys=False)
            return True
        except Exception as e:
            card._errors.append(f"Failed to save card: {str(e)}")
            return False

    def process_card(self, path: Path, apply_changes: bool = False) -> Dict:
        """
        Process a single card through all stages:
        1. Load and parse the card
        2. Repair YAML structure
        3. Apply curated edits
        4. Normalize content
        5. Validate against rules
        """
        # Load and validate basic structure
        card = self.load_card(path)

        # Skip processing if we couldn't load the card
        if card._errors:
            return {
                "path": str(path),
                "status": "error",
                "errors": card._errors,
                "warnings": card._warnings,
                "valid": False,
            }

        # Process the card through all stages
        repairs = self.repair_yaml(card)
        edits = self.apply_curated_edits(card)
        self.normalize_card(card)

        # Check for missing authorities
        missing_auths = self.check_authorities(card)
        card._warnings.extend(missing_auths)

        # Check for contract-specific requirements
        if self.is_contract_card(card):
            self._check_contract_requirements(card)

        # Prepare result
        result = {
            "path": str(path),
            "status": "valid" if not card._errors else "invalid",
            "errors": card._errors,
            "warnings": card._warnings,
            "repairs": repairs,
            "edits": edits,
            "valid": not bool(card._errors),
        }

        # Save changes if requested and valid
        if apply_changes and result["valid"]:
            try:
                result["saved"] = self.save_card(card)
                if result["saved"]:
                    result["status"] = "saved"
            except Exception as e:
                result["errors"].append(f"Failed to save card: {str(e)}")
                result["valid"] = False
                result["status"] = "error"

        return result

    def _check_contract_requirements(self, card: Flashcard) -> None:
        """Check contract-specific requirements."""
        # Ensure required contract elements are present
        required_elements = [
            "offer",
            "acceptance",
            "consideration",
            "intention to create legal relations",
        ]

        content = f"{card.front} {card.back}".lower()
        missing = [el for el in required_elements if el.lower() not in content]

        if missing:
            card._warnings.append(
                f"Contract card missing key elements: {', '.join(missing)}"
            )

        # Check for case law references
        if not any(
            re.search(pattern, content, re.IGNORECASE)
            for pattern in AUTHORITY_PATTERNS.get("0008", [])
        ):
            card._warnings.append(
                "Contract card should reference key cases (Carlill, Masters v Cameron, etc.)"
            )


def find_cards(self, pattern: str = "*.yml") -> List[Path]:
    """Find all card files matching the pattern."""
    cards = []
    for card_dir in self.card_dirs:
        cards.extend(card_dir.glob(pattern))
    return sorted(cards)


# --- Command Line Interface ---
def _print_result(card_path: Path, result: Dict, verbose: bool = False) -> None:
    status = result["status"].upper()
    print(f"{status}: {card_path.name}")
    if verbose or result["errors"] or result["warnings"]:
        for err in result["errors"]:
            print(f"  ERROR: {err}")
        for warn in result["warnings"]:
            print(f"  WARN: {warn}")


def _print_summary(results: List[Dict]) -> None:
    print("\nProcessing complete!")
    print(f"Total cards: {len(results)}")
    print(f"Valid: {sum(1 for r in results if r['valid'])}")
    print(f"Errors: {sum(1 for r in results if r['errors'])}")
    print(f"Warnings: {sum(1 for r in results if r['warnings'])}")


def _write_json_report(results: List[Dict], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "processed": len(results),
            "pass": sum(1 for r in results if r["valid"]),
            "fail": sum(1 for r in results if not r["valid"]),
        },
        "cards": [],
    }

    for item in results:
        card_entry = {
            "path": item["path"],
            "status": item["status"],
            "valid": item["valid"],
            "errors": item["errors"],
            "warnings": item["warnings"],
            "repairs": item.get("repairs"),
            "edits": item.get("edits"),
        }
        if "saved" in item:
            card_entry["saved"] = item["saved"]
        report["cards"].append(card_entry)

    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def _write_markdown_report(results: List[Dict], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = [
        "# Flashcard QA Report",
        "",
        f"- Processed: {len(results)}",
        f"- Pass: {sum(1 for r in results if r['valid'])}",
        f"- Fail: {sum(1 for r in results if not r['valid'])}",
        "",
    ]

    for item in results:
        lines.append(f"### {item['path']}")
        lines.append(f"- Status: {item['status']}")
        lines.append(f"- Valid: {'Yes' if item['valid'] else 'No'}")
        if "repairs" in item:
            lines.append(f"- Repairs: {bool(item.get('repairs'))}")
        if "edits" in item:
            lines.append(f"- Edits: {bool(item.get('edits'))}")
        if "saved" in item:
            lines.append(f"- Saved: {bool(item.get('saved'))}")
        if item["errors"]:
            lines.append("- Errors:")
            lines.extend([f"  - {err}" for err in item["errors"]])
        else:
            lines.append("- Errors: None")
        if item["warnings"]:
            lines.append("- Warnings:")
            lines.extend([f"  - {warn}" for warn in item["warnings"]])
        else:
            lines.append("- Warnings: None")
        lines.append("")

    destination.write_text("\n".join(lines), encoding="utf-8")


def process_cards(
    processor,
    pattern,
    apply_changes=False,
    verbose=False,
    report_json: Optional[str] = None,
    report_md: Optional[str] = None,
):
    """Process cards through all stages."""
    cards = processor.find_cards(pattern)
    if not cards:
        print(f"No cards found matching pattern: {pattern}")
        return 1

    print(f"Processing {len(cards)} cards...")
    results = []
    for card_path in cards:
        result = processor.process_card(card_path, apply_changes)
        results.append(result)
        _print_result(card_path, result, verbose)

    _print_summary(results)

    if report_json:
        _write_json_report(results, Path(report_json))
    if report_md:
        _write_markdown_report(results, Path(report_md))

    return 0 if all(r["valid"] for r in results) else 1


def normalize_cards(processor, pattern, apply_changes=False, verbose=False):
    """Normalize card content and format."""
    cards = processor.find_cards(pattern)
    if not cards:
        print(f"No cards found matching pattern: {pattern}")
        return 1

    print(f"Normalizing {len(cards)} cards...")
    results = []
    for card_path in cards:
        card = processor.load_card(card_path)
        if card._errors:
            result = {
                "path": str(card_path),
                "status": "error",
                "errors": card._errors,
                "warnings": card._warnings,
                "repairs": False,
                "edits": False,
                "valid": False,
            }
            results.append(result)
            _print_result(card_path, result, verbose)
            continue

        processor.normalize_card(card)
        result = {
            "path": str(card_path),
            "status": "valid" if not card._errors else "invalid",
            "errors": card._errors,
            "warnings": card._warnings,
            "repairs": False,
            "edits": False,
            "valid": not bool(card._errors),
        }

        if apply_changes and result["valid"]:
            saved = processor.save_card(card)
            result["saved"] = saved
            if saved:
                result["status"] = "saved"
            else:
                result["status"] = "error"
                result["errors"] = card._errors
                result["valid"] = False

        results.append(result)
        _print_result(card_path, result, verbose)

    _print_summary(results)
    return 0 if all(r["valid"] for r in results) else 1


def repair_cards(processor, pattern, apply_changes=False, verbose=False):
    """Repair YAML structure and formatting."""
    cards = processor.find_cards(pattern)
    if not cards:
        print(f"No cards found matching pattern: {pattern}")
        return 1

    print(f"Repairing {len(cards)} cards...")
    results = []
    for card_path in cards:
        card = processor.load_card(card_path)
        if card._errors:
            result = {
                "path": str(card_path),
                "status": "error",
                "errors": card._errors,
                "warnings": card._warnings,
                "repairs": False,
                "edits": False,
                "valid": False,
            }
            results.append(result)
            _print_result(card_path, result, verbose)
            continue

        repairs = processor.repair_yaml(card)
        result = {
            "path": str(card_path),
            "status": "repaired" if repairs else "unchanged",
            "errors": card._errors,
            "warnings": card._warnings,
            "repairs": repairs,
            "edits": False,
            "valid": not bool(card._errors),
        }

        if apply_changes and repairs:
            saved = processor.save_card(card)
            result["saved"] = saved
            if saved:
                result["status"] = "saved"
            else:
                result["status"] = "error"
                result["errors"] = card._errors
                result["valid"] = False

        results.append(result)
        _print_result(card_path, result, verbose)

    _print_summary(results)
    return 0 if all(r["valid"] for r in results) else 1


def edit_cards(processor, pattern, apply_changes=False, verbose=False):
    """Apply curated content improvements."""
    cards = processor.find_cards(pattern)
    if not cards:
        print(f"No cards found matching pattern: {pattern}")
        return 1

    print(f"Applying curated edits to {len(cards)} cards...")
    results = []
    for card_path in cards:
        card = processor.load_card(card_path)
        if card._errors:
            result = {
                "path": str(card_path),
                "status": "error",
                "errors": card._errors,
                "warnings": card._warnings,
                "repairs": False,
                "edits": False,
                "valid": False,
            }
            results.append(result)
            _print_result(card_path, result, verbose)
            continue

        edits = processor.apply_curated_edits(card)
        result = {
            "path": str(card_path),
            "status": "edited" if edits else "unchanged",
            "errors": card._errors,
            "warnings": card._warnings,
            "repairs": False,
            "edits": edits,
            "valid": not bool(card._errors),
        }

        if apply_changes and edits:
            saved = processor.save_card(card)
            result["saved"] = saved
            if saved:
                result["status"] = "saved"
            else:
                result["status"] = "error"
                result["errors"] = card._errors
                result["valid"] = False

        results.append(result)
        _print_result(card_path, result, verbose)

    _print_summary(results)
    return 0 if all(r["valid"] for r in results) else 1


def scaffold_cards(processor, card_type, name, count, prefix, verbose=False):
    """Generate new card templates."""
    policy_path = Path(__file__).parent.parent / "jd" / "policy" / "cards_policy.yml"
    with open(policy_path, "r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}

    required_fields = policy.get("schema", {}).get("required_fields", [])

    type_path = Path(card_type)
    if not type_path.is_absolute():
        within_jd = Path("jd") / card_type
        if (within_jd / "cards_yaml").exists():
            target_dir = (within_jd / "cards_yaml").resolve()
        elif within_jd.exists():
            target_dir = within_jd.resolve()
        else:
            target_dir = (Path("jd") / "cards_yaml").resolve()
    else:
        if (type_path / "cards_yaml").exists():
            target_dir = (type_path / "cards_yaml").resolve()
        elif type_path.is_dir():
            target_dir = type_path.resolve()
        else:
            target_dir = (Path("jd") / "cards_yaml").resolve()

    target_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "card"
    created_paths: List[Path] = []

    for index in range(count):
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        suffix = f"-{index + 1:02d}" if count > 1 else ""
        filename = f"{prefix}-{timestamp}-{slug}{suffix}.yml"
        file_path = target_dir / filename

        card_data: Dict[str, object] = {}
        front_placeholder = f"{name.strip()}?"
        back_lines = [
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
            "- Wrongs Act 1958 (Vic) Pt IV — [add pinpoint]",
            "- Wrongs Act 1958 (Vic) Pt VBA — [add pinpoint]",
            "",
            "Tripwires.",
            "- Contractor misclassification vs employee status",
            '- Automatic "in course" assumption without analysis',
            "- Non-delegable duty confusion between categories",
            "",
            "Conclusion. <Close the loop on the scaffold and relief>",
        ]

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

        for required_field in required_fields:
            if required_field == "front":
                card_data["front"] = front_placeholder
            elif required_field == "back":
                card_data["back"] = "\n".join(back_lines)
            elif required_field == "why_it_matters":
                card_data[required_field] = (
                    "Highlight how this scaffold wins time and marks under exam pressure."
                )
            elif required_field == "mnemonic":
                card_data[required_field] = "Mnemonic to be confirmed"
            elif required_field == "diagram":
                card_data[required_field] = diagram_block
            elif required_field == "tripwires":
                card_data[required_field] = [
                    "Contractor misclassification vs employee status",
                    'Automatic "in course" assumption without analysis',
                    "Non-delegable duty confusion between categories",
                ]
            elif required_field == "anchors":
                card_data[required_field] = anchors_block
            elif required_field == "keywords":
                card_data[required_field] = keywords
            elif required_field == "reading_level":
                card_data[required_field] = policy.get("reading_level", {}).get(
                    "target", "Plain English (JD)"
                )
            elif required_field == "tags":
                card_data[required_field] = tags
            else:
                card_data[required_field] = card_data.get(required_field, "")

        card_data.setdefault("template", "concept")

        with open(file_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(card_data, handle, sort_keys=False, allow_unicode=True)

        created_paths.append(file_path)
        if verbose:
            print(f"Created scaffold: {file_path}")

    print(f"Created {len(created_paths)} scaffold card(s) in {target_dir}")
    return 0


def process_command(args, processor):
    """Process command with the given processor."""
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
        return scaffold_cards(
            processor, args.type, args.name, args.count, args.prefix, args.verbose
        )
    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Process flashcards through various stages."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    # Use parser to avoid unused variable warning
    _ = parser

    # Common arguments for subparsers
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-a", "--apply", action="store_true", help="Apply changes (default: dry run)"
    )
    process_parser = subparsers.add_parser(
        "process", help="Process cards through all stages"
    )
    process_parser.add_argument(
        "pattern",
        nargs="?",
        default="*.yml",
        help="File pattern to match (default: *.yml)",
    )
    process_parser.add_argument(
        "--apply", action="store_true", help="Apply changes to files"
    )
    process_parser.add_argument(
        "--verbose", action="store_true", help="Show detailed output"
    )
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

    # Normalize command
    norm_parser = subparsers.add_parser(
        "normalize", help="Normalize card content and format"
    )
    norm_parser.add_argument(
        "pattern",
        nargs="?",
        default="*.yml",
        help="File pattern to match (default: *.yml)",
    )
    norm_parser.add_argument(
        "--apply", action="store_true", help="Apply changes to files"
    )
    norm_parser.add_argument(
        "--verbose", action="store_true", help="Show detailed output"
    )

    # Repair command
    repair_parser = subparsers.add_parser(
        "repair", help="Repair YAML structure and formatting"
    )
    repair_parser.add_argument(
        "pattern",
        nargs="?",
        default="*.yml",
        help="File pattern to match (default: *.yml)",
    )
    repair_parser.add_argument(
        "--apply", action="store_true", help="Apply changes to files"
    )
    repair_parser.add_argument(
        "--verbose", action="store_true", help="Show detailed output"
    )

    # Edit command
    edit_parser = subparsers.add_parser(
        "edit", help="Apply curated content improvements"
    )
    edit_parser.add_argument(
        "pattern",
        nargs="?",
        default="*.yml",
        help="File pattern to match (default: *.yml)",
    )
    edit_parser.add_argument(
        "--apply", action="store_true", help="Apply changes to files"
    )
    edit_parser.add_argument(
        "--verbose", action="store_true", help="Show detailed output"
    )

    # Scaffold command
    scaffold_parser = subparsers.add_parser(
        "scaffold", help="Generate new card templates"
    )
    scaffold_parser.add_argument("--type", required=True, help="Type of card to create")
    scaffold_parser.add_argument("--name", required=True, help="Name for the new card")
    scaffold_parser.add_argument(
        "--count", type=int, default=1, help="Number of cards to generate"
    )
    scaffold_parser.add_argument(
        "--prefix", default="card", help="Prefix for generated filenames"
    )
    scaffold_parser.add_argument(
        "--verbose", action="store_true", help="Show detailed output"
    )

    args = parser.parse_args()

    if not hasattr(args, "command"):
        parser.print_help()
        return 1

    processor = FlashcardProcessor()

    try:
        return process_command(args, processor)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        if hasattr(args, "verbose") and args.verbose:
            import traceback

            traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
