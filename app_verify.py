"""Manual entry point to run a single pinpoint verification via OpenAI.

To use ``verify_once``:
* install ``openai`` (``pip install openai``)
* export ``OPENAI_API_KEY`` in your environment
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

try:  # pragma: no cover - optional dependency in some envs.
    from openai import OpenAI
except Exception:  # pragma: no cover - allow script to run without the package.
    OpenAI = None  # type: ignore

from tools.legal_pinpoint_pipeline import (
    CaseSearchClient,
    LegalDocumentFetcher,
    build_pinpoint_prompt,
    slice_candidate_paragraphs,
)


def _format_response(raw_content: str) -> Dict[str, Any]:
    """Return a structured dictionary for easier inspection."""

    return {"status": "OK", "raw": raw_content}


def verify_once(query: str, case_name: str, proposition: str) -> Dict[str, Any]:
    """Execute the happy-path verification described in the user brief."""

    if OpenAI is None:
        return {
            "status": "NO_VERIFIED_AUTHORITY_FOUND",
            "reason": "The 'openai' package is not installed.",
        }

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "status": "NO_VERIFIED_AUTHORITY_FOUND",
            "reason": "OPENAI_API_KEY environment variable is required.",
        }

    client = OpenAI()
    urls = CaseSearchClient().search_cases(query)
    if not urls:
        return {
            "status": "NO_VERIFIED_AUTHORITY_FOUND",
            "reason": "No search hits.",
        }

    paragraphs = LegalDocumentFetcher().fetch_and_normalise(urls[0])
    candidates = slice_candidate_paragraphs(
        paragraphs,
        keywords=["volenti", "duty", "risk"],
        window=2,
        max_total=6,
    )
    if not candidates:
        return {
            "status": "NO_VERIFIED_AUTHORITY_FOUND",
            "reason": "No paragraphs parsed.",
        }

    prompt = build_pinpoint_prompt(candidates, case_name, proposition)
    response = client.chat.completions.create(
        model="gpt-5",
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return _format_response(response.choices[0].message.content)


if __name__ == "__main__":
    output = verify_once(
        "Rootes v Shelton volenti",
        "Rootes v Shelton",
        "Volenti acceptance test",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
