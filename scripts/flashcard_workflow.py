#!/usr/bin/env python3
"""Unified flashcard workflow tool.

This script combines scaffolding, curated edits, normalisation and QA checks into a
single entry point so cards can be created and iteratively refined until they
conform with the v2a policy gates defined in `tools/gates.yml`.

Exit codes:
  0: Success
  1: General error
  2: Policy validation failed
  3: Card validation failed
  4: System error (unhandled exception)
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml  # type: ignore[import]
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm
from typing import Tuple, Dict, List, Optional

# --- Exit codes ---
class ExitCode(IntEnum):
    SUCCESS = 0
    GENERAL_ERROR = 1
    POLICY_VALIDATION_FAILED = 2
    CARD_VALIDATION_FAILED = 3
    SYSTEM_ERROR = 4

# --- Paths ---
ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR = REPORTS_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)
DEFAULT_POLICY_PATH = ROOT / "tools" / "gates.yml"
SCHEMA_PATH = ROOT / "jd" / "policy" / "cards_policy.yml"

try:
    from repair_and_qa_yaml import (  # type: ignore[attr-defined]
        CARD_DIRS as QA_CARD_DIRS,
        fix as qa_fix,
        gates as qa_gates,
    )
except ImportError as exc:  # pragma: no cover - hard failure
    raise SystemExit("flashcard_workflow.py requires repair_and_qa_yaml.py to be importable") from exc

try:
    import apply_curated_edits as curated  # type: ignore[import]
except ImportError:  # pragma: no cover - optional dependency
    curated = None  # type: ignore[assignment]

try:
    import seed_scaffolds  # type: ignore[import]
except ImportError:  # pragma: no cover - optional dependency
    seed_scaffolds = None  # type: ignore[assignment]


# --- Policy and Schema ---
@dataclass
class Policy:
    """Policy configuration with validation rules."""
    path: Path
    raw: Dict[str, Any]
    schema: Dict[str, Any]
    
    @classmethod
    def load(cls, policy_path: Optional[Path] = None, schema_path: Optional[Path] = None) -> 'Policy':
        """Load policy and schema with validation."""
        policy_path = policy_path or DEFAULT_POLICY_PATH
        schema_path = schema_path or SCHEMA_PATH
        
        try:
            policy_data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
            schema_data = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
            return cls(path=policy_path, raw=policy_data, schema=schema_data)
        except yaml.YAMLError as e:
            print(f"Failed to load policy/schema: {e}", file=sys.stderr)
            sys.exit(ExitCode.POLICY_VALIDATION_FAILED)
    
    def validate_card(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """
        Validate card against policy and return list of validation results.
        
        Args:
            card: The flashcard data to validate
            
        Returns:
            List of validation results with rule IDs, messages, and severities
        """
        validator = CardValidator(self)
        return validator.validate(card)
        
    def should_autofix(self, rule_id: str) -> bool:
        """Check if a rule should be auto-fixed based on policy."""
        return self.raw.get("autofix", {}).get(rule_id, False)
        
    def get_rule_config(self, rule_id: str) -> Dict[str, Any]:
        """Get configuration for a specific rule."""
        return self.raw.get("rules", {}).get(rule_id, {})
        
    def get_severity(self, rule_id: str) -> RuleSeverity:
        """Get severity level for a rule."""
        severity_map = {
            "error": RuleSeverity.ERROR,
            "warning": RuleSeverity.WARNING,
            "suggestion": RuleSeverity.SUGGESTION
        }
        severity_str = self.get_rule_config(rule_id).get("severity", "error").lower()
        return severity_map.get(severity_str, RuleSeverity.ERROR)


# --- Core validation rules ---
class RuleSeverity(IntEnum):
    ERROR = 1
    SUGGESTION = 3


@dataclass
class ValidationResult:
    """Container for validation results."""
    rule_id: str
    message: str
    severity: str = dataclass_field(default="error")
    fix_available: bool = dataclass_field(default=False)
    context: Dict[str, Any] = dataclass_field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity.name,
            "context": self.context
        }


class CardValidator:
    """Validates cards against policy rules with stable IDs and provides auto-fix capabilities."""
    
    def __init__(self, policy: Policy):
        self.policy = policy
        self._init_rules()
        
    def _init_rules(self) -> None:
        """Initialize validation rules from policy."""
        self.rules = {
            "F001": self._validate_required_field,
            "F002": self._validate_question_mark,
            "F003": self._validate_front_length,
            "B001": self._validate_back_content,
            "B002": self._validate_authorities,
            "S001": self._validate_schema,
            "D001": self._validate_diagram_syntax,
            "A001": self._validate_anchors
        }
    
    def validate(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """
        Run all validations and return results.
        
        Args:
            card: The flashcard data to validate
            
        Returns:
            List of validation results with rule IDs and messages
        """
        results: List[ValidationResult] = []
        
        # Run all validation rules
        for rule_id, validator in self.rules.items():
            if not self.policy.get_rule_config(rule_id).get("enabled", True):
                continue
                
            rule_results = validator(card)
            for result in rule_results:
                # Set severity based on policy
                result.severity = self.policy.get_severity(rule_id)
                results.append(result)
        
        return results
    
    def autofix(self, card: Dict[str, Any], rule_id: str) -> bool:
        """
        Attempt to automatically fix a specific rule violation.
        
        Args:
            card: The flashcard data to fix
            rule_id: The ID of the rule to fix
            
        Returns:
            bool: True if the card was modified, False otherwise
        """
        if not self.policy.should_autofix(rule_id):
            return False
            
        # Map rule IDs to fixer methods
        fixers = {
            "F002": self._fix_question_mark,
            "F003": self._fix_front_length,
            "B001": self._fix_back_content,
            "D001": self._fix_diagram_syntax
        }
        
        fixer = fixers.get(rule_id)
        if fixer:
            return fixer(card)
        return False
    
    # --- Validation Rules ---
    
    def _validate_required_field(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """F001: Required fields must be present."""
        results = []
        required_fields = ["front", "back"]
        
        for field in required_fields:
            if not card.get(field):
                results.append(ValidationResult(
                    rule_id="F001",
                    message=f"Required field '{field}' is missing",
                    context={"field": field}
                ))
        
        return results
    
    def _validate_question_mark(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """F002: Front should end with a question mark."""
        front = (card.get("front") or "").strip()
        if front and not front.endswith("?"):
            return [ValidationResult(
                rule_id="F002",
                message="Front should end with a question mark",
                context={"current": front}
            )]
        return []
    
    def _validate_front_length(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """F003: Front should not exceed maximum word count."""
        front = card.get("front", "")
        max_words = self.policy.get_rule_config("F003").get("max_words", 30)
        word_count = len(front.split())
        
        if word_count > max_words:
            return [ValidationResult(
                rule_id="F003",
                message=f"Front exceeds {max_words} words ({word_count} words)",
                context={"word_count": word_count, "max_words": max_words}
            )]
        return []
    
    def _validate_back_content(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """B001: Back should contain sufficient content."""
        back = card.get("back", "").strip()
        min_length = self.policy.get_rule_config("B001").get("min_length", 20)
        
        if len(back) < min_length:
            return [ValidationResult(
                rule_id="B001",
                message=f"Back content is too short (minimum {min_length} characters)",
                context={"length": len(back), "min_length": min_length}
            )]
        return []
    
    def _validate_authorities(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """B002: Back should cite authoritative sources when appropriate."""
        back = card.get("back", "").lower()
        if "case" in back or "section" in back or "act" in back:
            if not any(marker in back for marker in ["v ", "(20", " s ", " s("]):
                return [ValidationResult(
                    rule_id="B002",
                    message="Legal references should include proper citations",
                    context={"snippet": back[:100] + "..." if len(back) > 100 else back}
                )]
        return []
    
    def _validate_schema(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """S001: Card should match the expected schema."""
        # TODO: Implement full schema validation
        return []
    
    def _validate_diagram_syntax(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """D001: Mermaid diagrams should be syntactically valid."""
        if "diagram" in card:
            try:
                # Simple validation - check for required graph type declaration
                diagram = card["diagram"].strip()
                if not any(diagram.startswith(prefix) for prefix in ["graph", "sequenceDiagram", "classDiagram"]):
                    return [ValidationResult(
                        rule_id="D001",
                        message="Diagram must start with a valid type (graph, sequenceDiagram, classDiagram)",
                        context={"diagram_start": diagram[:50]}
                    )]
            except Exception as e:
                return [ValidationResult(
                    rule_id="D001",
                    message=f"Invalid diagram syntax: {str(e)}",
                    severity=RuleSeverity.ERROR
                )]
        return []
    
    def _validate_anchors(self, card: Dict[str, Any]) -> List[ValidationResult]:
        """A001: Internal links should be valid."""
        results = []
        back = card.get("back", "")
        
        # Find all markdown links
        import re
        for match in re.finditer(r'\[([^\]]+)\]\(#([^)]+)\)', back):
            link_text, anchor = match.groups()
            if not anchor.startswith("card-"):
                results.append(ValidationResult(
                    rule_id="A001",
                    message=f"Invalid anchor format: '{anchor}'. Should start with 'card-'"
                ))
        
        return results
    
    # --- Auto-fix Methods ---
    
    def _fix_question_mark(self, card: Dict[str, Any]) -> bool:
        """Auto-fix F002: Add question mark to front if missing."""
        front = card.get("front", "").strip()
        if front and not front.endswith("?"):
            card["front"] = front + "?"
            return True
        return False
    
    def _fix_front_length(self, card: Dict[str, Any]) -> bool:
        """Auto-fix F003: Truncate front if too long."""
        max_words = self.policy.get_rule_config("F003").get("max_words", 30)
        words = card.get("front", "").split()
        if len(words) > max_words:
            card["front"] = " ".join(words[:max_words]) + "..."
            return True
        return False
    
    def _fix_back_content(self, card: Dict[str, Any]) -> bool:
        """Auto-fix B001: Add placeholder text if back is empty."""
        if not card.get("back", "").strip():
            card["back"] = "[Add detailed explanation here]"
            return True
        return False
    
    def _fix_diagram_syntax(self, card: Dict[str, Any]) -> bool:
        """Auto-fix D001: Add default graph type if missing."""
        if "diagram" in card and card["diagram"].strip() and not any(
            card["diagram"].strip().startswith(prefix)
            for prefix in ["graph", "sequenceDiagram", "classDiagram"]
        ):
            card["diagram"] = "graph TD\n    " + card["diagram"]
            return True
        return False


# ---------------------------------------------------------------------------
# Core workflow
# ---------------------------------------------------------------------------

def unique_existing_dirs(dirs: Iterable[Path]) -> List[Path]:
    seen: set[Path] = set()
    out: List[Path] = []
    for directory in dirs:
        resolved = directory.resolve()
        if not resolved.exists():
            continue
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


CARD_DIRS: List[Path] = unique_existing_dirs(list(QA_CARD_DIRS))
if not CARD_DIRS:
    default_cards = ROOT / "jd" / "cards_yaml"
    default_cards.mkdir(parents=True, exist_ok=True)
    CARD_DIRS.append(default_cards.resolve())

ALLOWED_BASES = CARD_DIRS + [REPORTS_DIR.resolve(), BACKUPS_DIR.resolve()]


def ensure_allowed(path: Path) -> None:
    resolved = path.resolve()
    for base in ALLOWED_BASES:
        try:
            resolved.relative_to(base)
            return
        except ValueError:
            continue
    raise RuntimeError(f"Refusing to write outside managed directories: {resolved}")


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:80] or "card"


def discover_cards(subject: str = "", limit: int = 0) -> List[Path]:
    results: List[Path] = []
    seen: set[Path] = set()
    for directory in CARD_DIRS:
        for path in sorted(directory.glob("*.yml")):
            if subject and subject.lower() not in path.name.lower():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            results.append(resolved)
            if limit and len(results) >= limit:
                return results
    return results


def resolve_card(name: str) -> Optional[Path]:
    candidates: List[str] = [name]
    if not name.endswith(".yml"):
        candidates.append(f"{name}.yml")
    for candidate in candidates:
        candidate_path = Path(candidate)
        probe: List[Path] = []
        if candidate_path.is_absolute():
            probe.append(candidate_path)
        else:
            probe.append(ROOT / candidate_path)
            for directory in CARD_DIRS:
                probe.append(directory / candidate_path)
                probe.append(directory / candidate_path.name)
        for option in probe:
            resolved = option.resolve()
            if resolved.exists():
                return resolved
    return None


def load_card(path: Path) -> Dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - guard rails
        raise ValueError(f"YAML parse error for {path}: {exc}")


def write_card(path: Path, data: Dict[str, Any]) -> None:
    ensure_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)


def backup_card(path: Path) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUPS_DIR / f"{path.name}.bak-{timestamp}"
    ensure_allowed(backup_path)
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


# ---------------------------------------------------------------------------
# Curated edits adapter (optional)
# ---------------------------------------------------------------------------

def curated_functions() -> Sequence:
    if curated is None:
        return ()
    func_names = (
        "touch_assault",
        "touch_medical_battery",
        "touch_rogers_negligence",
        "touch_occupiers",
        "touch_public_road",
        "touch_causation_march",
        "touch_non_delegable",
        "touch_illegality",
        "merge_compliance_cards",
        "tweak_neighbour",
        "tweak_incrementalism",
        "ensure_mental_harm_bits",
    )
    funcs = []
    for name in func_names:
        fn = getattr(curated, name, None)
        if fn is not None:
            funcs.append(fn)
    return funcs


def run_curated_pass(card: Dict[str, Any]) -> bool:
    changed = False
    for fn in curated_functions():
        try:
            changed = fn(card) or changed
        except Exception:
            continue
    return changed


# ---------------------------------------------------------------------------
# Autofix / QA processing
# ---------------------------------------------------------------------------

@dataclass
class CardResult:
    """Container for flashcard processing results."""
    path: Path
    relpath: str
    status: str
    actions: List[str] = dataclass_field(default_factory=list)
    fails_before: List[str] = dataclass_field(default_factory=list)
    fails_after: List[str] = dataclass_field(default_factory=list)
    applied: bool = False
    backup_path: Optional[Path] = None


def process_card(
    path: Path,
    apply_autofix: bool,
    apply_curated: bool,
    max_iterations: int,
    write: bool,
    dry_run: bool,
    policy: Optional[Policy] = None,
) -> CardResult:
    """
    Process a single flashcard with validation and optional fixes.
    
    Args:
        path: Path to the flashcard file
        apply_autofix: Whether to attempt automatic fixes
        apply_curated: Whether to apply curated content nudges
        max_iterations: Maximum number of fix iterations
        write: Whether to save changes to disk
        dry_run: If True, don't actually write changes
        policy: Optional policy to use for validation
        
    Returns:
        CardResult containing processing results
    """
    relpath = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
    original = load_card(path)
    working = copy.deepcopy(original)
    
    # Initialize validator if we have a policy
    validator = CardValidator(policy) if policy else None
    
    # Run initial validation
    if validator:
        validation_results = validator.validate(working)
        fails_before = [
            f"[{r.rule_id}] {r.message}" 
            for r in validation_results 
            if r.severity == RuleSeverity.ERROR
        ]
    else:
        fails_before = qa_gates(copy.deepcopy(working))
    
    actions: List[str] = []
    
    # Apply fixes if requested
    if apply_autofix and validator:
        for _ in range(max_iterations):
            iteration_changed = False
            
            # Run validation to find issues
            validation_results = validator.validate(working)
            
            # Try to fix each validation error
            for result in validation_results:
                if result.severity == RuleSeverity.ERROR:
                    fixed = validator.autofix(working, result.rule_id)
                    if fixed:
                        actions.append(f"fixed:{result.rule_id}")
                        iteration_changed = True
            
            # Apply legacy QA fixes if no policy
            if not policy:
                qa_fixes = qa_fix(working)
                if qa_fixes:
                    actions.extend(qa_fixes)
                    iteration_changed = True
            
            # Apply curated edits if enabled
            if apply_curated and curated:
                if run_curated_pass(working):
                    actions.append("curated_pass")
                    iteration_changed = True
            
            # Stop if no changes were made in this iteration
            if not iteration_changed:
                break
    
    # Final validation
    if validator:
        validation_results = validator.validate(working)
        fails_after = [
            f"[{r.rule_id}] {r.message}" 
            for r in validation_results 
            if r.severity == RuleSeverity.ERROR
        ]
    else:
        fails_after = qa_gates(copy.deepcopy(working))
    
    applied = working != original
    backup_path = None
    
    # Apply changes if requested and not in dry-run mode
    if applied and write and not dry_run:
        backup_path = backup_card(path)
        write_card(path, working)
    
    status = "PASS" if not fails_after else "FAIL"
    
    return CardResult(
        path=path,
        relpath=relpath,
        status=status,
        actions=actions,
        fails_before=fails_before,
        fails_after=fails_after,
        applied=applied and write,
        backup_path=backup_path,
    )


# ---------------------------------------------------------------------------
# Card creation helpers
# ---------------------------------------------------------------------------

def next_card_path(directory: Optional[Path], front: str) -> Path:
    target_dir = directory or (CARD_DIRS[0] if CARD_DIRS else ROOT / "jd" / "cards_yaml")
    target_dir.mkdir(parents=True, exist_ok=True)
    existing_numbers: List[int] = []
    for candidate in target_dir.glob("*.yml"):
        try:
            number = int(candidate.name.split("-", 1)[0])
        except (ValueError, IndexError):
            continue
        existing_numbers.append(number)
    next_number = max(existing_numbers, default=0) + 1
    slug = slugify(front)
    return target_dir / f"{next_number:04d}-{slug}.yml"


def scaffold_card(front: str) -> Dict[str, Any]:
    if seed_scaffolds is not None and hasattr(seed_scaffolds, "create_card_data"):
        return seed_scaffolds.create_card_data(front)
    topic_slug = slugify(front).replace("-", "_")
    return {
        "front": front,
        "back": "[DRAFT] Issue.\n\nRule.\n\nApplication scaffold.\n\nAuthorities map.\n\nStatutory hook.\n\nTripwires.\n\nConclusion.",
        "why_it_matters": "[DRAFT] Explain why this matters under exam pressure.",
        "mnemonic": "",
        "diagram": (
            "```mermaid\nmindmap\n  root((" + topic_slug + "))\n    Branch A\n    Branch B\n    Branch C\n    Branch D\n```"
        ),
        "tripwires": [
            "[DRAFT] Common mistake 1",
            "[DRAFT] Common mistake 2",
            "[DRAFT] Common mistake 3",
            "[DRAFT] Common mistake 4",
        ],
        "anchors": {"cases": [], "statutes": []},
        "keywords": [],
        "reading_level": "JD-ready",
        "tags": ["MLS_H1"],
    }


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def build_report(results: Sequence[CardResult], md_path: Path, json_path: Path) -> None:
    """Generate and save markdown and JSON reports for card processing results."""
    generated = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    total = len(results)
    passed = sum(1 for r in results if getattr(r, 'status', '') == "PASS")
    failed = total - passed
    autofixed = sum(1 for r in results if getattr(r, 'applied', False))

    # Generate markdown report
    md_content = [
        "# Flashcard Workflow Report",
        f"- **Generated:** {generated}",
        f"- **Cards processed:** {total}",
        f"- **Pass:** {passed}",
        f"- **Fail:** {failed}",
        f"- **Autofixes committed:** {autofixed}",
        "",
    ]
    
    # Generate JSON report
    json_content = {
        "timestamp": generated,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "autofixed": autofixed
        },
        "results": [
            {
                "path": str(getattr(r, 'path', 'unknown')),
                "status": getattr(r, 'status', 'UNKNOWN'),
                "issues": getattr(r, 'fails_after', []),
                "actions": getattr(r, 'actions', [])
            }
            for r in results
        ]
    }
    
    # Save reports
    md_path.write_text("\n".join(md_content), encoding="utf-8")
    json_path.write_text(json.dumps(json_content, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified flashcard creation and QA workflow with policy validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new card
  %(prog)s create --front "What are the elements of negligence?"
  
  # Check cards against policy
  %(prog)s check 0001-0022
  
  # Fix issues in cards
  %(prog)s refine --write --curated
  
  # Optimize study strategy
  %(prog)s optimize --deck-size 150 --simulations 1000000
"""
    )
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", required=True, title="commands")

    # optimize command
    optimize_parser = subparsers.add_parser(
        "optimize", help="Optimize flashcard study strategy"
    )
    optimize_parser.add_argument(
        "--deck-size",
        type=int,
        default=150,
        help="Total number of cards in deck (default: 150)"
    )
    optimize_parser.add_argument(
        "--simulations",
        type=int,
        default=1_000_000,
        help="Number of Monte Carlo simulations to run (default: 1,000,000)"
    )

    # create command
    create_parser = subparsers.add_parser(
        "create", help="Create a new flashcard with the given front text"
    )
    create_parser.add_argument(
        "--front", 
        required=True, 
        help="Front/question text (required)"
    )
    create_parser.add_argument(
        "--back", 
        default="", 
        help="Back/answer text (default: empty)"
    )
    create_parser.add_argument(
        "--directory",
        type=Path,
        help=f"Output directory (default: {CARD_DIRS[0] if CARD_DIRS else 'jd/cards_yaml'})"
    )
    create_parser.add_argument(
        "--refine", 
        action="store_true", 
        help="Run autofix + QA after creation"
    )
    create_parser.add_argument(
        "--curated",
        action="store_true",
        help="Apply curated content nudges when refining"
    )
    create_parser.add_argument(
        "--write",
        action="store_true",
        help="Write the card to disk"
    )
    create_parser.add_argument(
        "--no-validate",
        action="store_false",
        dest="validate",
        help="Skip validation after creation"
    )

    # refine command ---------------------------------------------------------
    refine_parser = subparsers.add_parser(
        "refine", 
        help="Refine existing flashcards",
        description="Apply fixes and improvements to existing flashcards."
    )
    refine_parser.add_argument(
        "cards", 
        nargs="*", 
        default=[],
        help="Card filenames or patterns (default: all cards)"
    )
    refine_parser.add_argument(
        "--subject", 
        help="Filter by subject (substring match)"
    )
    refine_parser.add_argument(
        "--limit", 
        type=int, 
        help="Limit number of cards processed"
    )
    refine_parser.add_argument(
        "--write", 
        action="store_true", 
        help="Save changes to disk"
    )
    refine_parser.add_argument(
        "--curated", 
        action="store_true", 
        help="Apply curated content nudges"
    )
    refine_parser.add_argument(
        "--iterations", 
        type=int, 
        default=3, 
        help="Maximum autofix iterations (default: 3)"
    )
    refine_parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Show what would be changed without saving"
    )
    refine_parser.add_argument(
        "--report-prefix", 
        default="flashcard_refine", 
        help="Report filename prefix (default: flashcard_refine)"
    )
    refine_parser.add_argument(
        "--fix",
        action="store_true",
        default=True,
        help="Enable auto-fixing of issues (default: True)"
    )

    # check command ----------------------------------------------------------
    check_parser = subparsers.add_parser(
        "check", 
        help="Check cards against policy",
        description="Validate flashcards against the specified policy."
    )
    check_parser.add_argument(
        "cards", 
        nargs="*",
        default=[],
        help="Card filenames or patterns (default: all cards)"
    )
    check_parser.add_argument(
        "--subject", 
        help="Filter by subject (substring match)"
    )
    check_parser.add_argument(
        "--limit", 
        type=int, 
        help="Limit number of cards checked"
    )
    check_parser.add_argument(
        "--report-prefix", 
        default="flashcard_check", 
        help="Report filename prefix (default: flashcard_check)"
    )
    check_parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Return non-zero exit code on warnings"
    )
    check_parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text)"
    )

    # docs command -----------------------------------------------------------
    docs_parser = subparsers.add_parser(
        "docs", 
        help="Generate documentation",
        description="Generate documentation about the flashcard format and validation rules."
    )
    docs_parser.add_argument(
        "--write", 
        type=Path, 
        help="Write to file instead of stdout"
    )
    docs_parser.add_argument(
        "--format",
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Output format (default: markdown)"
    )
    docs_parser.add_argument(
        "--include-examples",
        action="store_true",
        help="Include example cards in the documentation"
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def command_create(args: argparse.Namespace, policy: Optional[Policy] = None) -> int:
    """Create a new flashcard with the given front text.
    
    Args:
        args: Command line arguments
        policy: Optional policy to validate against
        
    Returns:
        Exit code indicating success or failure
    """
    card = scaffold_card(args.front.strip())
    target_path = next_card_path(args.directory, args.front.strip())
    write_card(target_path, card)
    print(f"Created scaffold: {target_path}")

    if args.refine:
        result = process_card(
            path=target_path,
            apply_autofix=True,
            apply_curated=args.curated,
            max_iterations=3,
            write=True,
            dry_run=False,
            policy=policy,
        )
        if result.fails_after:
            print("Remaining gate failures:")
            for fail in result.fails_after:
                print(f"  - {fail}")
            return ExitCode.CARD_VALIDATION_FAILED
        print("Card passes all gates after refinement.")
    return ExitCode.SUCCESS


def resolve_card_args(explicit_cards: Sequence[str], subject: str, limit: int) -> List[Path]:
    resolved: List[Path] = []
    if explicit_cards:
        for item in explicit_cards:
            path = resolve_card(item)
            if path is None:
                print(f"[WARN] Card not found: {item}", file=sys.stderr)
                continue
            resolved.append(path)
    else:
        resolved.extend(discover_cards(subject=subject, limit=limit))
    if limit:
        resolved = resolved[:limit]
    if not resolved:
        print("No cards matched the provided criteria.", file=sys.stderr)
    return resolved


def command_refine(args: argparse.Namespace, policy: Optional[Policy] = None) -> int:
    """Refine existing flashcards based on policy rules.
    
    Args:
        args: Command line arguments
        policy: Optional policy to validate against
        
    Returns:
        Exit code indicating success or failure
    """
    card_paths = resolve_card_args(args.cards, args.subject, args.limit)
    if not card_paths:
        return ExitCode.GENERAL_ERROR

    results: List[CardResult] = []
    for path in card_paths:
        result = process_card(
            path=path,
            apply_autofix=True,
            apply_curated=args.curated,
            max_iterations=max(1, args.iterations),
            write=args.write,
            dry_run=args.dry_run,
            policy=policy,
        )
        results.append(result)
        summary = ", ".join(result.fails_after) if result.fails_after else "clean"
        print(f"[{result.status}] {result.relpath}: {summary}")

    report_md = REPORTS_DIR / f"{args.report_prefix}.md"
    report_json = REPORTS_DIR / f"{args.report_prefix}.json"
    build_report(results, report_md, report_json)
    print(f"Report written to {report_md} and {report_json}")

    return ExitCode.SUCCESS if all(r.status == "PASS" for r in results) else ExitCode.CARD_VALIDATION_FAILED


def command_check(args: argparse.Namespace, policy: Optional[Policy] = None) -> int:
    """Check cards against policy without making changes."""
    if not policy:
        try:
            policy = Policy(args.policy)
        except Exception as e:
            print(f"Error loading policy: {e}", file=sys.stderr)
            return ExitCode.POLICY_VALIDATION_FAILED
            
    # Find and process cards
    card_paths = find_card_paths(args.cards, args.subject, args.limit)
    if not card_paths:
        print("No matching cards found.", file=sys.stderr)
        return ExitCode.SUCCESS
        
    # Process each card
    results = []
    for path in card_paths:
        result = process_card(
            path=path,
            apply_autofix=False,
            apply_curated=False,
            max_iterations=0,
            write=False,
            dry_run=False,
            policy=policy
        )
        results.append(result)
    
    # Setup report paths
    report_prefix = args.report_prefix or "flashcard_check"
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    md_path = REPORTS_DIR / f"{report_prefix}_{timestamp}.md"
    json_path = REPORTS_DIR / f"{report_prefix}_{timestamp}.json"
    
    # Generate reports
    build_report(results, md_path, json_path)
    
    # Print summary to console
    print(f"\nChecked {len(results)} cards")
    passed = sum(1 for r in results if getattr(r, 'status', '') == "PASS")
    print(f"✓ {passed} passed")
    print(f"✗ {len(results) - passed} failed")
    print(f"\nReports saved to:\n- {md_path}\n- {json_path}")
    
    # Return appropriate exit code
    if any(getattr(r, 'status', '') != "PASS" for r in results):
        return ExitCode.CARD_VALIDATION_FAILED
    return ExitCode.SUCCESS


def find_card_paths(patterns: List[str] = None, subject: str = None, limit: int = None) -> List[Path]:
    """Find card paths matching patterns and optional subject filter."""
    card_dirs = CARD_DIRS if hasattr(sys, 'CARD_DIRS') else [Path('jd/cards_yaml')]
    paths = []
    
    for card_dir in card_dirs:
        if not card_dir.exists():
            continue
            
        # Get all YAML files if no patterns
        if not patterns:
            paths.extend(card_dir.glob('*.yml'))
            paths.extend(card_dir.glob('*.yaml'))
        else:
            # Handle patterns
            for pattern in patterns:
                paths.extend(card_dir.glob(f"{pattern}.yml"))
                paths.extend(card_dir.glob(f"{pattern}.yaml"))
    
    # Filter by subject if specified
    if subject:
        paths = [p for p in paths if subject.lower() in str(p).lower()]
    
    # Apply limit
    if limit and limit > 0:
        return paths[:limit]
    return paths


def save_report(md_content: str, json_content: dict, prefix: str) -> Path:
    """Save report files with the given prefix."""
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save markdown
    md_path = REPORTS_DIR / f"{prefix}_{timestamp}.md"
    md_path.write_text(md_content, encoding='utf-8')
    
    # Save JSON if provided
    if json_content:
        json_path = REPORTS_DIR / f"{prefix}_{timestamp}.json"
        json_path.write_text(json.dumps(json_content, indent=2), encoding='utf-8')
    
    return md_path


def command_docs(args: argparse.Namespace, policy: Optional[Policy] = None) -> int:
    """Generate essential flashcard documentation."""
    from datetime import datetime
    
    # Load policy if not provided
    if not policy:
        try:
            policy = Policy(args.policy)
        except Exception as e:
            print(f"Error loading policy: {e}", file=sys.stderr)
            return ExitCode.POLICY_VALIDATION_FAILED
    
    # Core documentation sections
    doc = f"""# Flashcard System - Essential Reference
*Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

## Quick Start

```bash
# Create and refine a card
{os.path.basename(sys.argv[0])} create --front "Question?" --back "Answer" --write

# Check cards
{os.path.basename(sys.argv[0])} check 00*.yml

# Fix issues
{os.path.basename(sys.argv[0])} refine --write --curated
```

## Active Validation Rules
| ID   | Severity | Auto-fix | Description
|------|----------|----------|------------
"""
# Add rules table
    rules = policy.raw.get("rules", {})
    autofix = policy.raw.get("autofix", {})
    
    for rule_id, config in sorted(rules.items()):
        doc += f"| {rule_id} | {config.get('severity', 'error')} | "
        doc += "✓ | " if autofix.get(rule_id) else "× | "
        doc += f"{config.get('description', '')}\n"

    # Write or print
    if hasattr(args, 'write') and args.write:
        try:
            args.write.parent.mkdir(parents=True, exist_ok=True)
            args.write.write_text(doc, encoding="utf-8")
            print(f"Documentation written to {args.write}")
        except Exception as e:
            print(f"Error writing documentation: {e}", file=sys.stderr)
            return ExitCode.GENERAL_ERROR
    else:
        print(doc)
    
    return ExitCode.SUCCESS


class FlashcardOptimizer:
    """Optimize flashcard study strategy using Monte Carlo simulation."""
    
    def __init__(self, n_simulations: int = 1_000_000, deck_size: int = 150):
        self.n_simulations = n_simulations
        self.deck_size = deck_size
        self.results = []
        
    def simulate_retention(self, card_type: str, n_cards: int, days: int = 30, 
                         reviews_per_day: int = 3) -> float:
        """Simulate retention based on card type and study parameters."""
        if card_type == 'name_recognition':
            base_retention = 0.7
            decay_rate = 0.15
        elif card_type == 'active_recall':
            base_retention = 0.85
            decay_rate = 0.08
        else:  # applied
            base_retention = 0.6
            decay_rate = 0.12
            
        total_retention = 0
        for _ in range(n_cards):
            retention = base_retention * (1 - decay_rate) ** (days / reviews_per_day)
            total_retention += min(1.0, max(0, retention + np.random.normal(0, 0.05)))
        return total_retention / n_cards if n_cards > 0 else 0
    
    def run_simulation(self) -> Tuple[Dict, pd.DataFrame]:
        """Run Monte Carlo simulation of flashcard study strategies."""
        for _ in tqdm(range(self.n_simulations), desc="Running simulations"):
            # Randomly generate deck composition
            name_recognition = np.random.randint(15, 36)  # 15-35 cards (10-23%)
            active_recall = np.random.randint(90, 106)    # 90-105 cards (60-70%)
            applied = self.deck_size - name_recognition - active_recall
            
            # Ensure valid distribution
            if applied < 10 or applied > 30:  # 7-20% of deck
                continue
                
            # Simulate retention
            nr_retention = self.simulate_retention('name_recognition', name_recognition)
            ar_retention = self.simulate_retention('active_recall', active_recall)
            ap_retention = self.simulate_retention('applied', applied)
            
            # Calculate weighted score
            total_retention = (nr_retention * name_recognition + 
                             ar_retention * active_recall + 
                             ap_retention * applied) / self.deck_size
            
            self.results.append({
                'name_recognition': name_recognition,
                'active_recall': active_recall,
                'applied': applied,
                'total_retention': total_retention,
                'nr_retention': nr_retention,
                'ar_retention': ar_retention,
                'ap_retention': ap_retention
            })
        
        # Convert to DataFrame and find optimal strategy
        df = pd.DataFrame(self.results)
        optimal = df.loc[df['total_retention'].idxmax()].to_dict()
        
        return optimal, df

    def generate_report(self, optimal: Dict, output_dir: Path = None) -> None:
        """Generate optimization report and visualizations."""
        if output_dir is None:
            output_dir = REPORTS_DIR
        
        output_dir.mkdir(exist_ok=True)
        
        # Generate retention plot
        plt.figure(figsize=(10, 6))
        plt.hist([r['total_retention'] for r in self.results], bins=50, alpha=0.7)
        plt.axvline(optimal['total_retention'], color='r', linestyle='--', 
                   label=f'Optimal: {optimal["total_retention"]:.2%}')
        plt.title('Distribution of Retention Rates')
        plt.xlabel('Retention Rate')
        plt.ylabel('Frequency')
        plt.legend()
        plt.savefig(output_dir / 'retention_distribution.png')
        
        # Generate composition plot
        plt.figure(figsize=(10, 6))
        comp = [optimal['name_recognition'], 
               optimal['active_recall'], 
               optimal['applied']]
        plt.pie(comp, 
               labels=['Name Recognition', 'Active Recall', 'Applied'],
               autopct='%1.1f%%')
        plt.title('Optimal Flashcard Composition')
        plt.savefig(output_dir / 'optimal_composition.png')
        
        # Generate text report
        report = f"""# Flashcard Optimization Report
        
## Optimal Flashcard Composition
- Name Recognition: {optimal['name_recognition']} cards ({optimal['name_recognition']/self.deck_size:.1%})
- Active Recall: {optimal['active_recall']} cards ({optimal['active_recall']/self.deck_size:.1%})
- Applied: {optimal['applied']} cards ({optimal['applied']/self.deck_size:.1%})

## Expected Retention Rates
- Name Recognition: {optimal['nr_retention']:.1%}
- Active Recall: {optimal['ar_retention']:.1%}
- Applied: {optimal['ap_retention']:.1%}
- **Overall Retention: {optimal['total_retention']:.1%}**

## Recommendations
1. Focus on creating more active recall cards (60-70% of deck)
2. Use name recognition for basic concepts (15-25% of deck)
3. Reserve 10-20% for applied/problem-solving cards
4. Review cards daily for optimal retention
"""
        report_path = output_dir / 'optimization_report.md'
        report_path.write_text(report, encoding='utf-8')
        
        print(f"\nOptimization complete! Report saved to: {report_path}")
        print(f"Visualizations saved to: {output_dir}")


def command_optimize(args: argparse.Namespace) -> int:
    """Optimize flashcard study strategy using Monte Carlo simulation."""
    print("=== Flashcard Optimization Simulation ===")
    print(f"Running {args.simulations:,} Monte Carlo iterations...\n")
    
    optimizer = FlashcardOptimizer(
        n_simulations=args.simulations,
        deck_size=args.deck_size
    )
    
    optimal, _ = optimizer.run_simulation()
    optimizer.generate_report(optimal, REPORTS_DIR / 'optimization')
    
    return ExitCode.SUCCESS


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        
        # Load policy if needed
        policy = None
        if hasattr(args, 'policy') and args.policy:
            try:
                policy = Policy(args.policy)
            except Exception as e:
                print(f"Error loading policy: {e}", file=sys.stderr)
                return ExitCode.POLICY_VALIDATION_FAILED
        
        # Route to appropriate command
        if args.command == "create":
            return command_create(args, policy)
        elif args.command == "check":
            return command_check(args, policy)
        elif args.command == "refine":
            return command_refine(args, policy)
        elif args.command == "docs":
            return command_docs(args, policy)
        elif args.command == "optimize":
            return command_optimize(args)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            return ExitCode.GENERAL_ERROR
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        return ExitCode.GENERAL_ERROR
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if hasattr(e, '__traceback__'):
            import traceback
            traceback.print_exc()
        return ExitCode.SYSTEM_ERROR


if __name__ == "__main__":
    sys.exit(main())
