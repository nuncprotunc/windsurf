"""Utility helpers for JD Master Card QA validation inside Code Interpreter sessions."""
from __future__ import annotations

import re
from typing import Dict, List

SECTION_HEADERS: List[str] = [
    "Issue.",
    "Rule.",
    "Application scaffold.",
    "Authorities map.",
    "Statutory hook.",
    "Tripwires.",
    "Conclusion.",
]


def word_count(text: str) -> int:
    """Count the number of word tokens in ``text``."""
    return len(re.findall(r"\b\w+\b", text))


def extract_sections(back_text: str) -> Dict[str, str]:
    """Split the ``back`` field into sections keyed by policy headers."""
    sections: Dict[str, List[str]] = {}
    current: str | None = None

    for line in back_text.splitlines():
        stripped = line.strip()
        if stripped in SECTION_HEADERS:
            current = stripped
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def diagram_node_count(diagram: str) -> int:
    """Crude node count for Mermaid mindmaps (root + branches + children)."""
    nodes = 0
    in_block = False
    for line in diagram.splitlines():
        stripped = line.strip()
        if stripped == "```mermaid":
            in_block = True
            continue
        if stripped.startswith("```") and in_block:
            break
        if not in_block or stripped == "":
            continue
        if stripped.startswith("mindmap"):
            nodes += 1
        else:
            nodes += 1
    return nodes
