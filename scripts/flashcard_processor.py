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
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass, field
import shutil
from datetime import datetime

try:
    from schema_validator import SchemaValidator
except ImportError as exc:  # pragma: no cover - defensive guard
    SchemaValidator = None  # type: ignore[assignment]
    print(
        f"Warning: Could not import SchemaValidator ({exc}); validation disabled.",
        file=sys.stderr,
    )

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Please install it with: pip install pyyaml")
    sys.exit(1)

# --- Constants ---
CARD_DIRS = [
    Path("jd/cards_yaml"),
    Path("jd") / "LAWS50025 - Torts" / "cards_yaml",
    Path("jd") / "LAWS50029 - Contracts" / "cards_yaml"
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
    
    # Validation rules from normalize_and_qa_cards.py
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

    AUTHORITY_HINTS = {
        "Duty": [r"Sullivan v Moody", r"Perre v Apand", r"Woolcock Street"],
        "Breach": [r"Wyong.*Shirt", r"Rogers v Whitaker", r"\bs\s*59\b"],
        "Causation": [r"\bs\s*51\(1\)\(a\)", r"March v Stramare", r"Strong v Woolworths", r"Wallace v Kam"],
        "Property": [r"Plenty v Dillon|Halliday v Nevill|Kuru v (State of )?NSW"],
        "Defamation": [r"Defamation Act 2005 \(Vic\)"],
        "Apportionment": [r"Pt\s*IVAA"],
    }
    
    def __init__(self):
        self.card_dirs = [d for d in CARD_DIRS if d.exists()]
        self._policy_path = (
            Path(__file__).resolve().parent.parent
            / 'jd'
            / 'policy'
            / 'flashcard_policy_consolidated.yml'
        )
        self._schema_validator = None
        self._compiled_authority_patterns = {
            key: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for key, patterns in self.AUTHORITY_PATTERNS.items()
        }

        if SchemaValidator is not None and self._policy_path.exists():
            try:
                self._schema_validator = SchemaValidator(str(self._policy_path))
            except Exception as exc:  # pragma: no cover - defensive guard
                print(
                    f"Warning: Failed to load schema validator: {exc}",
                    file=sys.stderr,
                )
        elif SchemaValidator is not None:
            print(
                "Warning: Flashcard policy file not found; validation disabled.",
                file=sys.stderr,
            )
        
    def load_card(self, path: Path) -> Flashcard:
        """Load a flashcard from a YAML file."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            card = Flashcard(path=path)
            card.front = data.get('front', '').strip()
            card.back = data.get('back', '').strip()
            card.tags = data.get('tags', [])
            card.sources = data.get('sources', [])
            card.created = data.get('created', '')
            card.updated = data.get('updated', '')
            card.mnemonic = data.get('mnemonic', '').strip()
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
        content = f"{card.front} {card.back}"

        # Check for topic-specific authorities
        if self.is_contract_card(card):
            for pattern in self._compiled_authority_patterns.get("0008", []):
                if not pattern.search(content):
                    missing.append(
                        f"Missing contract authority: {pattern.pattern}"
                    )


        return missing

    def normalize_card(self, card: 'Flashcard') -> None:
        """Normalize card content and format."""
        validator = self._schema_validator

        # Convert card to dict for validation
        card_data = {
            'front': card.front,
            'back': card.back,
            'tags': card.tags,
            'created': card.created,
            'updated': card.updated,
            'template': card._raw.get('template', 'concept')
        }

        # Validate card data
        if validator is not None:
            result = validator.validate_card(card_data)

            # Update card with validation results
            card._errors.extend(result.errors)
            card._warnings.extend(result.warnings)

        if not card.front:
            card._errors.append("Front text is required")

        # Normalize whitespace and formatting
        card.front = ' '.join(card.front.split())
        card.back = ' '.join(card.back.split())

        # Ensure tags are lowercase and unique
        card.tags = list({tag.lower().strip() for tag in card.tags if tag.strip()})

        # Ensure template is set
        if 'template' not in card._raw:
            card._raw['template'] = 'concept'

        # Add timestamps if missing
        now = datetime.utcnow().isoformat() + 'Z'
        if not card.created:
            card.created = now
        card.updated = now

        # Keep raw representation aligned with normalized fields before saving
        card._raw.update(
            {
                'front': card.front,
                'back': card.back,
                'tags': card.tags,
                'sources': card.sources,
                'created': card.created,
                'updated': card.updated,
                'mnemonic': card.mnemonic,
            }
        )
    
    def repair_yaml(self, card: Flashcard) -> bool:
        """Fix YAML formatting and structure issues."""
        repaired = False
        
        # Ensure required fields exist
        if 'front' not in card._raw:
            card._raw['front'] = card.front
            repaired = True
            
        # Ensure lists are properly formatted
        for field in ['tags', 'sources']:
            if field not in card._raw or not isinstance(card._raw[field], list):
                card._raw[field] = getattr(card, field)
                repaired = True
                
        return repaired
    
    def apply_curated_edits(self, card: Flashcard) -> bool:
        """Apply curated content improvements."""
        edited = False
        
        # Example edit: Ensure case names are properly formatted
        if 'tort' in card.tags and 'v.' in card.front and ' v. ' not in card.front:
            card.front = card.front.replace(' v ', ' v. ')
            edited = True
            
        # Add more curated edits here
        
        return edited
    
    def save_card(self, card: Flashcard, backup: bool = True) -> bool:
        """Save card to disk with optional backup."""
        if not card.path.parent.exists():
            card.path.parent.mkdir(parents=True)
            
        if backup and card.path.exists():
            backup_dir = REPORTS_DIR / 'backups'
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            backup_path = backup_dir / f"{card.path.stem}.bak-{timestamp}"
            shutil.copy2(card.path, backup_path)
        
        try:
            with open(card.path, 'w', encoding='utf-8') as f:
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
                'path': str(path),
                'status': 'error',
                'errors': card._errors,
                'warnings': card._warnings,
                'valid': False
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
            'path': str(path),
            'status': 'valid' if not card._errors else 'invalid',
            'errors': card._errors,
            'warnings': card._warnings,
            'repairs': repairs,
            'edits': edits,
            'valid': not bool(card._errors)
        }
        
        # Save changes if requested and valid
        if apply_changes and result['valid']:
            try:
                result['saved'] = self.save_card(card)
                if result['saved']:
                    result['status'] = 'saved'
            except Exception as e:
                result['errors'].append(f"Failed to save card: {str(e)}")
                result['valid'] = False
                result['status'] = 'error'
        
        return result
    
    def _check_contract_requirements(self, card: Flashcard) -> None:
        """Check contract-specific requirements."""
        # Ensure required contract elements are present
        required_elements = [
            'offer', 'acceptance', 'consideration', 
            'intention to create legal relations'
        ]
        
        content = f"{card.front} {card.back}".lower()
        missing = [el for el in required_elements if el.lower() not in content]
        
        if missing:
            card._warnings.append(
                f"Contract card missing key elements: {', '.join(missing)}"
            )
        
        # Check for case law references
        if not any(pattern.search(content)
                   for pattern in self._compiled_authority_patterns.get("0008", [])):
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
def process_cards(processor, pattern, apply_changes=False, verbose=False):
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
        
        status = result['status'].upper()
        print(f"{status}: {card_path.name}")
        
        if verbose or result['errors'] or result['warnings']:
            for err in result['errors']:
                print(f"  ERROR: {err}")
            for warn in result['warnings']:
                print(f"  WARN: {warn}")
    
    # Print summary
    print("\nProcessing complete!")
    print(f"Total cards: {len(results)}")
    print(f"Valid: {sum(1 for r in results if r['valid'])}")
    print(f"Errors: {sum(1 for r in results if r['errors'])}")
    print(f"Warnings: {sum(1 for r in results if r['warnings'])}")
    
    return 0 if all(r['valid'] for r in results) else 1

def normalize_cards(processor, pattern, apply_changes=False, verbose=False):
    """Normalize card content and format."""
    # Implementation similar to process_cards but only runs normalization
    pass

def repair_cards(processor, pattern, apply_changes=False, verbose=False):
    """Repair YAML structure and formatting."""
    # Implementation similar to process_cards but only runs repairs
    pass

def edit_cards(processor, pattern, apply_changes=False, verbose=False):
    """Apply curated content improvements."""
    # Implementation similar to process_cards but only applies edits
    pass

def scaffold_cards(processor, template, count, prefix, verbose=False):
    """Generate new card templates."""
    # Implementation for generating new card templates
    pass

def process_command(args, processor):
    """Process command with the given processor."""
    if args.command == 'process':
        return process_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == 'normalize':
        return normalize_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == 'repair':
        return repair_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == 'edit':
        return edit_cards(processor, args.pattern, args.apply, args.verbose)
    if args.command == 'scaffold':
        return scaffold_cards(processor, args.template, args.count, args.prefix, args.verbose)
    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1

def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Process flashcards through various stages.')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    # Use parser to avoid unused variable warning
    _ = parser
    
    # Common arguments for subparsers
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-a", "--apply",
        action="store_true",
        help="Apply changes (default: dry run)"
    )
    process_parser = subparsers.add_parser('process', help='Process cards through all stages')
    process_parser.add_argument('pattern', nargs='?', default='*.yml', help='File pattern to match (default: *.yml)')
    process_parser.add_argument('--apply', action='store_true', help='Apply changes to files')
    process_parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    # Normalize command
    norm_parser = subparsers.add_parser('normalize', help='Normalize card content and format')
    norm_parser.add_argument('pattern', nargs='?', default='*.yml', help='File pattern to match (default: *.yml)')
    norm_parser.add_argument('--apply', action='store_true', help='Apply changes to files')
    norm_parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    # Repair command
    repair_parser = subparsers.add_parser('repair', help='Repair YAML structure and formatting')
    repair_parser.add_argument('pattern', nargs='?', default='*.yml', help='File pattern to match (default: *.yml)')
    repair_parser.add_argument('--apply', action='store_true', help='Apply changes to files')
    repair_parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    # Edit command
    edit_parser = subparsers.add_parser('edit', help='Apply curated content improvements')
    edit_parser.add_argument('pattern', nargs='?', default='*.yml', help='File pattern to match (default: *.yml)')
    edit_parser.add_argument('--apply', action='store_true', help='Apply changes to files')
    edit_parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    # Scaffold command
    scaffold_parser = subparsers.add_parser('scaffold', help='Generate new card templates')
    scaffold_parser.add_argument('--type', required=True, help='Type of card to create')
    scaffold_parser.add_argument('--name', required=True, help='Name for the new card')
    scaffold_parser.add_argument('--count', type=int, default=1, help='Number of cards to generate')
    scaffold_parser.add_argument('--prefix', default='card', help='Prefix for generated filenames')
    scaffold_parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    args = parser.parse_args()
    
    if not hasattr(args, 'command'):
        parser.print_help()
        return 1
    
    processor = FlashcardProcessor()
    
    try:
        return process_command(args, processor)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        if hasattr(args, 'verbose') and args.verbose:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
