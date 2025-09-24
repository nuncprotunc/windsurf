# pyright: reportMissingImports=false, reportMissingTypeStubs=false
"""Script to generate flashcard templates from topics."""
import re
from pathlib import Path
from typing import Any, Dict

import yaml  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
TOPICS = ROOT / "tools" / "topics.yml"
OUT = ROOT / "jd" / "cards_yaml"
OUT.mkdir(parents=True, exist_ok=True)

topics = yaml.safe_load(TOPICS.read_text(encoding="utf-8")) or []


def slug(text: str) -> str:
    """Convert text to URL-friendly slug.
    
    Args:
        text: Input text to convert
        
    Returns:
        str: URL-friendly slug
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def create_card_data(front_text: str) -> Dict[str, Any]:
    """Create a new flashcard data structure.
    
    Args:
        front_text: The front text/question for the card
        
    Returns:
        Dict containing card data
    """
    return {
        "front": front_text,
        "back": "",
        "why_it_matters": "",
        "mnemonic": "",
        "diagram": f"mindmap\n  root(({slug(front_text).replace('-', '_')}))",
        "tripwires": [],
        "anchors": {"cases": [], "statutes": []},
        "keywords": [],
        "reading_level": "JD-ready",
        "tags": []
    }


def main() -> None:
    """Generate flashcard templates from topics."""
    cards_created = 0
    
    for i, topic in enumerate(topics, start=1):
        front = topic["front"].strip()
        path = OUT / f"{i:04d}-{slug(front)}.yml"
        
        if path.exists():  # Skip if file already exists
            continue
            
        card_data = create_card_data(front)
        path.write_text(
            yaml.safe_dump(card_data, sort_keys=False, allow_unicode=True),
            encoding="utf-8"
        )
        cards_created += 1
    
    print(f"Seeded {cards_created} cards to {OUT}")


if __name__ == "__main__":
    main()
