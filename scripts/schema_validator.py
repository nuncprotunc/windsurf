"""Pareto v2 schema validation for flashcards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    template: Optional[str] = None


class SchemaValidator:
    """Validate flashcards against the policy constraints."""

    _HEADING_REGEX = re.compile(
        r"^(Issue\.|Rule\.|Application scaffold\.|Authorities map\.|Statutory hook\.|Tripwires\.|Conclusion\.)\s*(.*)$"
    )

    _PINPOINT_REGEXES = (
        re.compile(r"\[para[^]]+\]", re.IGNORECASE),
        re.compile(r"\bpara(?:graph)?\s+\d+", re.IGNORECASE),
        re.compile(r",\s*\d{1,4}(?:–\d{1,4})?"),
        re.compile(
            r"\b(?:CLR|ALR|AC|NSWLR|VR|FCR|SASR|WLR|QB|Ch|All\s+ER|SCR|FCAFC|FCA|HCA|VSCA|VSC|Aust\s+Torts\s+Reports)\s*\d{1,4}",
            re.IGNORECASE,
        ),
        re.compile(r"\bs{1,2}\s*\d+[A-Za-z]*", re.IGNORECASE),
    )

    _REQUIRED_TRIPWIRE_PATTERNS = {
        "contractor misclass": re.compile(r"contractor\s+misclass", re.IGNORECASE),
        'automatic "in course"': re.compile(
            r'automatic[^\w]+["\u201c]?in course["\u201d]?',
            re.IGNORECASE,
        ),
        "non-delegable duty confusion": re.compile(
            r"non-?delegable\s+duty\s+confusion", re.IGNORECASE
        ),
    }

    def __init__(self, policy_path: str):
        self.policy = self._load_yaml(policy_path)
        self.schema = self.policy.get("schema", {})
        self.global_rules = self.policy.get("global_rules", {})
        self.anchors_policy = self.policy.get("anchors", {})
        self.diagram_policy = self.policy.get("diagram", {})
        self.tripwire_policy = self.policy.get("tripwires", {})
        self.required_headings = [
            "Issue.",
            "Rule.",
            "Application scaffold.",
            "Authorities map.",
            "Statutory hook.",
            "Tripwires.",
            "Conclusion.",
        ]

    def _load_yaml(self, path: str) -> Dict:
        import yaml  # Local import to avoid dependency at module import time.

        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def validate_card(self, card_data: Dict) -> ValidationResult:
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            template=card_data.get("template", "concept"),
        )

        self._check_required_fields(card_data, result)
        self._check_front(card_data, result)
        self._check_back(card_data, result)
        self._check_anchors(card_data, result)
        self._check_diagram(card_data, result)
        self._check_tripwires(card_data, result)

        result.is_valid = not bool(result.errors)
        return result

    # ------------------------------------------------------------------
    # Required fields
    def _check_required_fields(self, card_data: Dict, result: ValidationResult) -> None:
        required = self.schema.get("required_fields", [])
        for field in required:
            value = card_data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                result.errors.append(f"Missing required field: {field}")

    # ------------------------------------------------------------------
    # Front validation
    def _check_front(self, card_data: Dict, result: ValidationResult) -> None:
        front_rules = self.global_rules.get("front", {})
        front_text = card_data.get("front", "")
        if not isinstance(front_text, str) or not front_text.strip():
            result.errors.append("Front content must be a non-empty string")
            return

        word_count = self._word_count(front_text)
        max_words = front_rules.get("max_words")
        if max_words is not None and word_count > max_words:
            result.errors.append(
                f"Front exceeds {max_words} words (found {word_count})"
            )

        must_end_question = front_rules.get("must_end_with_question_mark", False)
        if must_end_question and not front_text.strip().endswith("?"):
            result.errors.append("Front must end with a question mark")

    # ------------------------------------------------------------------
    # Back validation and heading enforcement
    def _check_back(self, card_data: Dict, result: ValidationResult) -> None:
        back_rules = self.global_rules.get("back", {})
        back_text = card_data.get("back", "")

        if not isinstance(back_text, str) or not back_text.strip():
            result.errors.append("Back content must be provided")
            return

        words = self._word_count(back_text)
        min_words = back_rules.get("min_words")
        max_words = back_rules.get("max_words")
        if min_words is not None and words < min_words:
            result.errors.append(
                f"Back has fewer than {min_words} words (found {words})"
            )
        if max_words is not None and words > max_words:
            result.errors.append(f"Back exceeds {max_words} words (found {words})")

        max_sentence_words = back_rules.get("max_sentence_words")
        if max_sentence_words:
            for sentence in self._split_sentences(back_text):
                sentence_words = self._word_count(sentence)
                if sentence_words > max_sentence_words:
                    result.errors.append(
                        "Back sentence exceeds "
                        f"{max_sentence_words} words: {sentence.strip()}"
                    )

        sections, order = self._parse_back_sections(back_text)

        last_index = -1
        for heading in self.required_headings:
            if heading not in sections:
                result.errors.append(f"Missing required heading: {heading}")
                continue
            current_index = order.index(heading)
            if current_index < last_index:
                result.errors.append("Back headings are out of order")
            last_index = max(last_index, current_index)

        self._check_statutory_hook(sections.get("Statutory hook."), result)

    def _parse_back_sections(self, back_text: str) -> Tuple[Dict[str, str], List[str]]:
        sections: Dict[str, List[str]] = {}
        order: List[str] = []
        current_heading: Optional[str] = None

        for raw_line in back_text.splitlines():
            line = raw_line.strip()
            if not line and current_heading:
                sections[current_heading].append("")
                continue

            match = self._HEADING_REGEX.match(line)
            if match:
                current_heading = match.group(1)
                if current_heading not in sections:
                    order.append(current_heading)
                sections[current_heading] = []
                remainder = match.group(2).lstrip()
                if remainder:
                    sections[current_heading].append(remainder)
            elif current_heading:
                sections[current_heading].append(line)

        joined_sections = {
            heading: "\n".join(
                [segment for segment in segments if segment is not None]
            ).strip()
            for heading, segments in sections.items()
        }
        return joined_sections, order

    def _check_statutory_hook(
        self, block: Optional[str], result: ValidationResult
    ) -> None:
        if not block:
            result.errors.append(
                "Statutory hook block must describe the Wrongs Act overlays"
            )
            return

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        bullet_lines = [line for line in lines if line.startswith("-")]

        if not bullet_lines:
            result.errors.append(
                "Statutory hook block must use bullet points for each statute"
            )
            return

        pt_iv_index = self._find_line_index(bullet_lines, ["pt iv"])
        if pt_iv_index is None:
            pt_iv_index = self._find_line_index(bullet_lines, ["part iv"])

        pt_vba_index = self._find_line_index(bullet_lines, ["pt vba"])

        if pt_iv_index is None:
            result.errors.append(
                "Statutory hook block must include a bullet for Wrongs Act Pt IV"
            )
        if pt_vba_index is None:
            result.errors.append(
                "Statutory hook block must include a bullet for Wrongs Act Pt VBA"
            )
        if (
            pt_iv_index is not None
            and pt_vba_index is not None
            and pt_iv_index == pt_vba_index
        ):
            result.errors.append(
                "Wrongs Act Pt IV and Pt VBA must appear on separate bullet lines"
            )

    @staticmethod
    def _find_line_index(lines: List[str], needles: List[str]) -> Optional[int]:
        for index, line in enumerate(lines):
            lowered = line.lower()
            if all(needle in lowered for needle in needles):
                return index
        return None

    # ------------------------------------------------------------------
    # Anchors validation
    def _check_anchors(self, card_data: Dict, result: ValidationResult) -> None:
        anchors = card_data.get("anchors")
        if anchors is None:
            result.errors.append("Anchors field is required")
            return

        items: List[str] = []
        if isinstance(anchors, dict):
            for key in ("cases", "statutes", "notes"):
                values = anchors.get(key, [])
                if isinstance(values, list):
                    items.extend(str(value) for value in values if value is not None)
        elif isinstance(anchors, list):
            items = [str(value) for value in anchors if value is not None]
        else:
            result.errors.append("Anchors must be a list or mapping of anchor items")
            return

        if not items:
            result.errors.append("Anchors list cannot be empty")
            return

        min_items = 4
        max_items = 5
        if not (min_items <= len(items) <= max_items):
            result.warnings.append(
                f"Anchors should list between {min_items} and {max_items} items (found {len(items)})"
            )

        for anchor in items:
            if not self._has_pinpoint(anchor):
                result.warnings.append(f"Anchor missing pinpoint: {anchor}")

    def _has_pinpoint(self, text: str) -> bool:
        for pattern in self._PINPOINT_REGEXES:
            if pattern.search(text):
                return True
        return False

    # ------------------------------------------------------------------
    # Diagram validation
    def _check_diagram(self, card_data: Dict, result: ValidationResult) -> None:
        diagram = card_data.get("diagram")
        if not isinstance(diagram, str) or not diagram.strip():
            result.errors.append("Diagram field must contain a fenced mermaid block")
            return

        if "```mermaid" not in diagram:
            result.errors.append("Diagram must include a fenced ```mermaid block")

        lines = [line.strip() for line in diagram.splitlines() if line.strip()]
        node_lines = [
            line
            for line in lines
            if line not in {"```mermaid", "```"}
            and not line.lower().startswith("mindmap")
        ]
        max_nodes = self.diagram_policy.get("max_total_nodes")
        if max_nodes is None:
            max_nodes = 12
        if len(node_lines) > max_nodes:
            result.warnings.append(
                f"Diagram contains {len(node_lines)} nodes; consider trimming to {max_nodes}"
            )

    # ------------------------------------------------------------------
    # Tripwire checks
    def _check_tripwires(self, card_data: Dict, result: ValidationResult) -> None:
        tripwires = card_data.get("tripwires")
        if not isinstance(tripwires, list) or not tripwires:
            result.errors.append("Tripwires list must contain entries")
            return

        for label, pattern in self._REQUIRED_TRIPWIRE_PATTERNS.items():
            if not any(
                isinstance(item, str) and pattern.search(item) for item in tripwires
            ):
                result.warnings.append(f"Tripwire missing: {label}")

    # ------------------------------------------------------------------
    # Text helpers
    @staticmethod
    def _word_count(text: str) -> int:
        tokens = re.findall(r"\b\w+\b", text)
        return len(tokens)

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        cleaned = " ".join(text.split())
        if not cleaned:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        return [sentence for sentence in sentences if sentence]
