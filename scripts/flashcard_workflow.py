#!/usr/bin/env python3
"""CLI workflow for validating flashcards against the v2a policy."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from flashcard_processor import FlashcardProcessor, REPORTS_DIR

ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_RESET = "\033[0m"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flashcard QA workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Validate flashcards against the policy")
    check.add_argument("patterns", nargs="+", help="Glob pattern(s) for flashcard YAML files")
    check.add_argument("--policy", default=str(Path("jd/policy/cards_policy.yml")), help="Path to policy YAML")
    check.add_argument("--strict", action="store_true", help="Exit with code 1 when any errors are found")
    check.add_argument("--dry-run", action="store_true", help="Skip any write or backup operations")

    return parser


def gather_cards(processor: FlashcardProcessor, patterns: Iterable[str]) -> List[Path]:
    cards: List[Path] = []
    seen = set()
    for pattern in patterns:
        for path in processor.find_cards(pattern):
            if path in seen:
                continue
            seen.add(path)
            cards.append(path)
    cards.sort()
    return cards


def write_json_report(results, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "total": len(results),
            "errors": sum(1 for r in results if r.get("errors")),
            "warnings": sum(1 for r in results if r.get("warnings")),
        },
        "cards": results,
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown_report(results, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = len(results)
    errors = sum(1 for r in results if r.get("errors"))
    warnings = sum(1 for r in results if r.get("warnings"))
    lines: List[str] = [
        "# Flashcard QA Report",
        "",
        "| metric | count |",
        "| --- | --- |",
        f"| total | {total} |",
        f"| errors | {errors} |",
        f"| warnings | {warnings} |",
        "",
        "| file | status | errors | warnings |",
        "| --- | --- | --- | --- |",
    ]
    for item in results:
        errors_joined = "; ".join(item.get("errors", [])) or "—"
        warnings_joined = "; ".join(item.get("warnings", [])) or "—"
        lines.append(
            f"| {item['path']} | {item['status']} | {errors_joined} | {warnings_joined} |"
        )
    lines.append("")
    lines.append("## Details")
    for item in results:
        lines.append(f"### {item['path']}")
        lines.append(f"- Status: {item['status']}")
        lines.append(f"- Valid: {'Yes' if item.get('valid') else 'No'}")
        if item.get("errors"):
            lines.append("- Errors:")
            lines.extend(f"  - {err}" for err in item["errors"])
        else:
            lines.append("- Errors: None")
        if item.get("warnings"):
            lines.append("- Warnings:")
            lines.extend(f"  - {warn}" for warn in item["warnings"])
        else:
            lines.append("- Warnings: None")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")


def print_console_summary(results) -> None:
    failing = [item for item in results if item.get("errors")]
    if failing:
        summary = f"Validation failed: {len(failing)} card(s) with errors"
        print(f"{ANSI_RED}{summary}{ANSI_RESET}")
        for item in failing:
            print(f"- {item['path']}")
            for error in item.get("errors", []):
                print(f"    • {error}")
    else:
        summary = f"Validation passed: {len(results)} card(s) checked"
        print(f"{ANSI_GREEN}{summary}{ANSI_RESET}")


def run_check(args) -> int:
    processor = FlashcardProcessor(policy_path=args.policy)
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") if not args.dry_run else None
    processor.configure_run(run_id, dry_run=args.dry_run)

    cards = gather_cards(processor, args.patterns)
    if not cards:
        print("No cards matched the provided pattern(s).")
        return 0

    results = []
    for path in cards:
        result = processor.process_card(path, apply_changes=False)
        results.append(result)

    json_path = REPORTS_DIR / "flashcard_check.json"
    md_path = REPORTS_DIR / "flashcard_check.md"
    write_json_report(results, json_path)
    write_markdown_report(results, md_path)

    print_console_summary(results)

    if not args.dry_run:
        processor.prune_backups(retain=10)

    has_errors = any(item.get("errors") for item in results)
    return 1 if (args.strict and has_errors) else 0


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return run_check(args)
    raise RuntimeError("Unknown command")


if __name__ == "__main__":
    sys.exit(main())
