#!/usr/bin/env python3
"""Command line helper for offline pinpoint verification."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.append(str(Path(__file__).resolve().parents[1]))

from tools.legal_pinpoint_pipeline import LegalDocumentFetcher, PinpointVerifier


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a legal pinpoint citation")
    parser.add_argument("--query", required=True, help="Search query (case name / topic)")
    parser.add_argument("--case", required=True, help="Case name")
    parser.add_argument("--citation", required=True, help="Case citation")
    parser.add_argument("--para", required=True, help="Target paragraph identifier")
    parser.add_argument("--prop", required=True, help="Proposition to test")
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=["volenti", "risk", "consent", "duty"],
        help="Keyword hints for candidate slicing",
    )
    parser.add_argument(
        "--source-file",
        help="Path to local HTML/PDF to verify against",
    )
    args = parser.parse_args()

    if args.source_file:
        fetcher = LegalDocumentFetcher()
        source_path = Path(args.source_file)
        if not source_path.exists():
            parser.error(f"source file not found: {source_path}")
        with source_path.open("rb") as handle:
            data = handle.read()
        paragraphs = (
            fetcher._extract_from_pdf(data)
            if source_path.suffix.lower() == ".pdf"
            else fetcher.parse_html(data.decode("utf-8", errors="ignore"))
        )

        def fake_searcher(_query: str):
            return [f"file://{source_path.resolve()}"]

        def fake_fetcher(_url: str):
            return paragraphs

        verifier = PinpointVerifier(searcher=fake_searcher, fetcher=fake_fetcher)
    else:
        verifier = PinpointVerifier()

    result = verifier.verify(
        query=args.query,
        case_name=args.case,
        citation=args.citation,
        target_para=args.para,
        proposition=args.prop,
        keywords=args.keywords,
    )

    if result is None:
        payload: Dict[str, Any] = {"status": "NO_VERIFIED_AUTHORITY_FOUND"}
    else:
        payload = {
            "case_name": result.case_name,
            "citation": result.citation,
            "pinpoint": result.pinpoint,
            "quote": result.quote,
            "reason": result.reason,
            "source_url": result.source_url,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
