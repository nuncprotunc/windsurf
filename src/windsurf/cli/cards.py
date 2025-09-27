from __future__ import annotations

import argparse
import inspect
from typing import Any, Optional

from windsurf.paths import JD_CARDS_DIR, REPORTS_DIR, ensure_dirs
from windsurf.flashcards import processor as _proc_mod
from windsurf.flashcards.processor import process_cards  # type: ignore


def _make_processor() -> Optional[Any]:
    """Best-effort factory for a processor instance from processor.py."""
    for name in ("Processor", "CardProcessor", "FlashcardProcessor", "FlashcardsProcessor"):
        cls = getattr(_proc_mod, name, None)
        if isinstance(cls, type):
            try:
                return cls()  # type: ignore[call-arg]
            except TypeError:
                try:
                    return cls(card_dirs=[JD_CARDS_DIR])  # type: ignore[call-arg]
                except Exception:
                    pass
    for fn in ("build_processor", "make_processor", "get_processor", "create_processor"):
        f = getattr(_proc_mod, fn, None)
        if callable(f):
            try:
                return f()
            except Exception:
                pass
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="windsurf-cards",
        description="Process JD cards",
    )
    parser.add_argument(
        "--pattern",
        default=str(JD_CARDS_DIR / "*.yml"),
        help="Glob or path to card YAML files",
    )
    parser.add_argument(
        "--report-json",
        default=str(REPORTS_DIR / "flashcard_check.json"),
        help="Path to write JSON report",
    )
    parser.add_argument(
        "--report-md",
        default=str(REPORTS_DIR / "flashcard_check.md"),
        help="Path to write Markdown report",
    )
    args = parser.parse_args(argv)
    ensure_dirs()

    kwargs: dict[str, Any] = {
        "pattern": str(args.pattern),
        "report_json": str(args.report_json) if args.report_json else None,
        "report_md": str(args.report_md) if args.report_md else None,
    }

    sig = inspect.signature(process_cards)
    if "processor" in sig.parameters and sig.parameters["processor"].default is inspect._empty:
        proc = _make_processor()
        if proc is not None:
            kwargs["processor"] = proc

    rc = process_cards(**kwargs)  # type: ignore[misc]
    if isinstance(rc, bool):
        return 0 if rc else 1
    if isinstance(rc, int):
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())