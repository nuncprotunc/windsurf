from __future__ import annotations
import argparse
from windsurf.paths import JD_CARDS_DIR, REPORTS_DIR, ensure_dirs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="windsurf-cards", description="Process JD cards"
    )
    parser.add_argument("--pattern", default=str(JD_CARDS_DIR / "*.yml"))
    parser.add_argument(
        "--report-json", default=str(REPORTS_DIR / "flashcard_check.json")
    )
    parser.add_argument("--report-md", default=str(REPORTS_DIR / "flashcard_check.md"))
    _args = parser.parse_args(argv)
    ensure_dirs()
    print("stub OK: wire to processor.process_cards")
    return 0
