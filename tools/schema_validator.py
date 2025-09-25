from __future__ import annotations

import itertools
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - exercised via runtime checks
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - fallback for restricted environments
    from tools import yaml_fallback as yaml  # type: ignore


@dataclass
class ValidationResult:
    """Result of validating a single flashcard."""

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class HeadingRequirement:
    pattern: re.Pattern
    label: str


@dataclass
class AuthorityDiscipline:
    lead_required: bool
    fallback_allowed: bool
    max_per_step: int


class PolicyLoader:
    """Utility for loading and caching policy files."""

    _cache: Dict[Path, Dict] = {}

    @classmethod
    def load(cls, path: Path) -> Dict:
        resolved = path.resolve()
        if resolved in cls._cache:
            return cls._cache[resolved]
        with open(resolved, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        cls._cache[resolved] = data
        return data


class SchemaValidator:
    """Validator that enforces the v2a flashcard policy."""

    def __init__(self, policy: str | Path, policy_data: Optional[Dict] = None):
        self._policy_path = Path(policy)
        self.policy = policy_data or PolicyLoader.load(self._policy_path)

        schema = self.policy.get("schema", {})
        back = self.policy.get("back", {})
        anchors = self.policy.get("anchors", {})
        statutes = self.policy.get("statutes", {})
        authorities = self.policy.get("authorities", {})
        keywords = self.policy.get("keywords", {})
        diagram = self.policy.get("diagram", {})
        tripwires = self.policy.get("tripwires", {})
        lint = self.policy.get("lint", {})
        tags = self.policy.get("tags", {})

        self.required_fields: List[str] = list(schema.get("required_fields", []))
        self.back_required_headings: List[HeadingRequirement] = []
        for raw_pattern in back.get("required_headings_regex", []):
            pattern_text = raw_pattern.replace("\\\\", "\\")
            self.back_required_headings.append(
                HeadingRequirement(
                    pattern=re.compile(pattern_text, re.IGNORECASE),
                    label=self._extract_heading_label(pattern_text),
                )
            )
        self.back_min_words = int(back.get("min_words", 0) or 0)
        self.back_max_words = int(back.get("max_words", 10 ** 6) or 10 ** 6)
        self.back_max_sentence_words = int(back.get("max_sentence_words", 10 ** 6) or 10 ** 6)
        authority_cfg = back.get("authority_per_step", {})
        self.back_allow_missing_blocks = bool(back.get("allow_missing_blocks_if_not_applicable", False))
        self.authority_rules = AuthorityDiscipline(
            lead_required=bool(authority_cfg.get("lead_required", False)),
            fallback_allowed=bool(authority_cfg.get("fallback_allowed", False)),
            max_per_step=int(authority_cfg.get("max_per_step", 1)),
        )
        self.anchors_policy = anchors
        self.statutes_policy = statutes
        self.authorities_policy = authorities
        self.keywords_policy = keywords
        self.diagram_policy = diagram
        self.tripwires_policy = tripwires
        self.lint_policy = lint
        self.tags_policy = tags
        self.placeholder_regexes = [re.compile(pat, re.IGNORECASE) for pat in lint.get("forbid_placeholder_text_regex", [])]
        allow_token = lint.get("allow_explicit_uncertainty_token")
        self.allowed_uncertainty_token = allow_token if isinstance(allow_token, str) else None
        self.priority_order = authorities.get("priority_order", [])
        self.priority_index = {name: idx for idx, name in enumerate(self.priority_order)}
        self.recommended_keywords = keywords.get("recommended_include_if_relevant", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate_card(self, card: Dict) -> ValidationResult:
        result = ValidationResult()
        self._check_required_fields(card, result)
        self._check_tags(card, result)
        self._check_keywords(card, result)
        self._check_tripwires(card, result)
        self._check_anchors(card, result)

        back_text = str(card.get("back", ""))
        sections, heading_count = self._parse_back_sections(back_text)
        self._check_back_headings(back_text, sections, heading_count, result)
        self._check_back_word_counts(back_text, result)
        self._check_authorities(sections.get("Authorities map."), result)
        self._check_statutes(sections.get("Statutory hook."), back_text, result)
        self._check_diagram(card.get("diagram"), sections, result)
        self._check_abbreviations(back_text, result)

        if self.allowed_uncertainty_token and self.allowed_uncertainty_token in back_text:
            result.add_warning("Back includes explicit uncertainty token; ensure follow-up research")

        self._check_placeholder_text(card, result)
        self._check_repeated_sentences(card, result)
        return result

    # ------------------------------------------------------------------
    # Required fields
    # ------------------------------------------------------------------
    def _check_required_fields(self, card: Dict, result: ValidationResult) -> None:
        for field in self.required_fields:
            value = card.get(field)
            if value is None:
                result.add_error(f"Missing required field: {field}")
                continue
            if isinstance(value, str) and not value.strip():
                result.add_error(f"Field '{field}' must not be empty")
            elif isinstance(value, (list, tuple, set)) and not any(str(item).strip() for item in value):
                result.add_error(f"Field '{field}' must contain at least one value")

    # ------------------------------------------------------------------
    # Back sections
    # ------------------------------------------------------------------
    def _parse_back_sections(self, back_text: str) -> Tuple[Dict[str, str], Dict[str, int]]:
        sections: Dict[str, str] = {}
        heading_counts: Dict[str, int] = defaultdict(int)
        if not back_text:
            return sections, heading_counts

        current_label: Optional[str] = None
        buffer: List[str] = []
        lines = back_text.splitlines()

        for raw_line in lines:
            line = raw_line.strip()
            matched_label: Optional[str] = None
            for req in self.back_required_headings:
                if req.pattern.match(line):
                    matched_label = req.label
                    break
            if matched_label:
                if current_label is not None:
                    sections[current_label] = "\n".join(buffer).strip()
                heading_counts[matched_label] += 1
                current_label = matched_label
                buffer = []
            else:
                if current_label is not None:
                    buffer.append(raw_line)
        if current_label is not None:
            sections[current_label] = "\n".join(buffer).strip()
        return sections, heading_counts

    def _check_back_headings(
        self,
        back_text: str,
        sections: Dict[str, str],
        heading_count: Dict[str, int],
        result: ValidationResult,
    ) -> None:
        missing = []
        for requirement in self.back_required_headings:
            count = heading_count.get(requirement.label, 0)
            if count == 0:
                missing.append(requirement.label)
            elif count > 1 and self.lint_policy.get("forbid_duplicate_section_headers", False):
                result.add_error(f"Duplicate heading detected: {requirement.label}")
        if missing:
            if self.back_allow_missing_blocks and self._has_rationale_marker(back_text):
                result.add_warning(
                    "Missing sections replaced with rationale marker: " + ", ".join(missing)
                )
            else:
                for label in missing:
                    result.add_error(f"Missing required heading: {label}")

    def _has_rationale_marker(self, back_text: str) -> bool:
        return bool(re.search(r"\(No [^\n)]*applicable\)\s*$", back_text.strip()))

    def _check_back_word_counts(self, back_text: str, result: ValidationResult) -> None:
        words = self._tokenize_words(back_text)
        if words < self.back_min_words:
            result.add_error(f"Back must contain at least {self.back_min_words} words (found {words})")
        if words > self.back_max_words:
            result.add_error(f"Back must contain no more than {self.back_max_words} words (found {words})")

        sentences = re.split(r"[\.\?\!]", back_text)
        for idx, sentence in enumerate(sentences, start=1):
            sentence_words = self._tokenize_words(sentence)
            if sentence_words > self.back_max_sentence_words:
                result.add_error(
                    f"Sentence {idx} exceeds {self.back_max_sentence_words} words ({sentence_words} words)"
                )

    # ------------------------------------------------------------------
    # Authorities discipline
    # ------------------------------------------------------------------
    def _check_authorities(self, section_text: Optional[str], result: ValidationResult) -> None:
        if not section_text:
            result.add_error("Authorities map section is empty")
            return

        lines = [line.strip() for line in section_text.splitlines() if line.strip()]
        if not lines:
            result.add_error("Authorities map must describe at least one step")
            return

        any_authority = False
        for idx, line in enumerate(lines, start=1):
            extracted = self._extract_authorities(line)
            if not extracted:
                result.add_error(f"Step {idx} in authorities map lacks cited authority")
                continue
            any_authority = True
            if len(extracted) > self.authority_rules.max_per_step:
                result.add_error(
                    f"Step {idx} lists {len(extracted)} authorities; maximum is {self.authority_rules.max_per_step}"
                )
            if len(extracted) > 1 and not self.authority_rules.fallback_allowed:
                result.add_error(f"Step {idx} cannot include fallback authorities")
            categories = [auth.category for auth in extracted]
            if not self._is_priority_respected(categories):
                result.add_error(
                    f"Step {idx} authorities are out of priority order (expected {self.priority_order})"
                )
            for auth in extracted:
                self._validate_authority_details(auth, result)
        if self.authority_rules.lead_required and not any_authority:
            result.add_error("Authorities map requires at least one lead authority")

    @dataclass
    class ExtractedAuthority:
        text: str
        category: str

    def _extract_authorities(self, line: str) -> List[ExtractedAuthority]:
        authorities: List[SchemaValidator.ExtractedAuthority] = []
        explicit_token = self.allowed_uncertainty_token
        if explicit_token and explicit_token in line:
            authorities.append(self.ExtractedAuthority(text=explicit_token, category="Token"))
            return authorities

        case_pattern = re.compile(r"([A-Z][A-Za-z]+ v [A-Z][A-Za-z][^;\.,]*)")
        statute_pattern = re.compile(r"([A-Z][A-Za-z]+ Act[^;\.,]*)")
        matches = case_pattern.findall(line)
        matches += statute_pattern.findall(line)
        seen = set()
        for match in matches:
            cleaned = match.strip()
            if cleaned in seen:
                continue
            seen.add(cleaned)
            category = self._classify_authority(cleaned)
            authorities.append(self.ExtractedAuthority(text=cleaned, category=category))
        return authorities

    def _classify_authority(self, authority: str) -> str:
        lowered = authority.lower()
        if "hca" in lowered:
            return "HCA"
        if "vsca" in lowered or "nswca" in lowered or "qsca" in lowered or "sascfc" in lowered or "wasca" in lowered:
            return "State CA"
        if "uk" in lowered or "pc" in lowered or "privy" in lowered:
            return "UK/PC (nuance)"
        if "act" in lowered or "reg" in lowered:
            return "Statute"
        return "Other Aus"

    def _is_priority_respected(self, categories: List[str]) -> bool:
        if not categories:
            return True
        last_index = -1
        for category in categories:
            if category not in self.priority_index:
                continue
            idx = self.priority_index[category]
            if idx < last_index:
                return False
            last_index = idx
        return True

    def _validate_authority_details(self, authority: "SchemaValidator.ExtractedAuthority", result: ValidationResult) -> None:
        text = authority.text
        if authority.category == "Token":
            result.add_warning("Authority placeholder used; follow up to locate verified authority")
            return
        if re.search(r"\[(overruled|distinguished)\]", text, re.IGNORECASE):
            result.add_warning(f"Authority marked as {text}")
        if authority.category == "UK/PC (nuance)":
            if not re.search(r"nuance|approved|persuasive|caution", text, re.IGNORECASE):
                result.add_error("UK/PC authority requires a nuance note")
        if self.authorities_policy.get("require_year_and_neutral_or_report_cite", False):
            if not self._has_year_and_citation(text):
                result.add_error(f"Authority missing year and neutral/report citation: {text}")

    def _has_year_and_citation(self, text: str) -> bool:
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        neutral = re.search(r"\[(19|20)\d{2}\]\s*[A-Z]{2,}\s*\d+", text)
        report = re.search(r"\b(\d+\s*[A-Z]{2,}\s*\d+)\b", text)
        return bool(year_match and (neutral or report))

    # ------------------------------------------------------------------
    # Statutes discipline
    # ------------------------------------------------------------------
    def _check_statutes(self, section_text: Optional[str], back_text: str, result: ValidationResult) -> None:
        if not section_text:
            result.add_warning("Statutory hook section is empty")
            return
        lines = [line.strip() for line in section_text.splitlines() if line.strip()]
        if not lines:
            result.add_warning("Statutory hook section contains no statutes")
            return

        mentions = []
        for line in lines:
            matches = re.findall(r"([A-Z][A-Za-z]+ Act[^;\.,]*)", line)
            for match in matches:
                mention = match.strip()
                mentions.append(mention)
                if self.statutes_policy.get("include_only_operational_sections", False):
                    lowered = mention.lower()
                    if " s " not in lowered and " section " not in lowered and "s." not in lowered:
                        result.add_error(f"Statute reference must include operational section: {mention}")
        if not mentions:
            result.add_warning("No statutes referenced in statutory hook")
        if self.statutes_policy.get("prefer_victoria_first", False) and mentions:
            first = mentions[0]
            if "(Vic" not in first:
                result.add_warning("Victorian legislation should be prioritised before other jurisdictions")
        if self.statutes_policy.get("require_commonwealth_if_engaged", False):
            if re.search(r"\b(Cth|Commonwealth(?!\s+Law Reports)|federal)\b", back_text, re.IGNORECASE):
                if not any("(Cth" in mention or re.search(r"Commonwealth(?!\s+Law Reports)", mention) for mention in mentions):
                    result.add_error("Commonwealth engagement flagged but no Commonwealth statute cited")

    # ------------------------------------------------------------------
    # Diagram discipline
    # ------------------------------------------------------------------
    def _check_diagram(
        self,
        diagram: Optional[str],
        sections: Dict[str, str],
        result: ValidationResult,
    ) -> None:
        if diagram is None:
            result.add_error("Diagram content is missing")
            return
        if not isinstance(diagram, str):
            result.add_error("Diagram must be provided as a string")
            return
        text = diagram.strip()
        if not text:
            result.add_error("Diagram must not be empty")
            return
        if not self.diagram_policy:
            return

        mermaid_block = self._extract_mermaid_block(text)
        if mermaid_block is None:
            result.add_error("Diagram must be a fenced mermaid block")
            return
        header, body = mermaid_block
        if self.diagram_policy.get("must_be_valid_mermaid", False) and header != "mermaid":
            result.add_error("Diagram fence must declare mermaid language")
        lines = [line.rstrip() for line in body.splitlines() if line.strip()]
        if not lines:
            result.add_error("Diagram mermaid content is empty")
            return
        first_line = lines[0].strip()
        if self.diagram_policy.get("type") == "mindmap" and not first_line.lower().startswith("mindmap"):
            result.add_error("Diagram must declare a mindmap")

        node_lines = lines[1:] if first_line.lower().startswith("mindmap") else lines
        total_nodes = sum(1 for line in node_lines if line.strip())
        max_nodes = int(self.diagram_policy.get("max_total_nodes", 0) or 0)
        if max_nodes and total_nodes > max_nodes:
            result.add_error(
                f"Mindmap contains {total_nodes} nodes but maximum is {max_nodes}"
            )

        top_level = self._count_top_level_branches(node_lines)
        min_branches = int(self.diagram_policy.get("top_level_branches_min", 0) or 0)
        max_branches = int(self.diagram_policy.get("top_level_branches_max", 0) or 0)
        if min_branches and top_level < min_branches:
            result.add_error(
                f"Mindmap must have at least {min_branches} top-level branches (found {top_level})"
            )
        if max_branches and top_level > max_branches:
            result.add_error(
                f"Mindmap must have no more than {max_branches} top-level branches (found {top_level})"
            )

        if self.diagram_policy.get("discourage_heading_mirroring", False):
            headings = {self._normalise_heading_name(name) for name in sections.keys()}
            mirrored = [
                branch
                for branch in self._iter_top_level_labels(node_lines)
                if self._normalise_heading_name(branch) in headings
            ]
            if mirrored:
                result.add_warning(
                    "Mindmap branches mirror back section headings: " + ", ".join(sorted(set(mirrored)))
                )

    # ------------------------------------------------------------------
    # Anchors
    # ------------------------------------------------------------------
    def _check_anchors(self, card: Dict, result: ValidationResult) -> None:
        anchors = card.get("anchors")
        if anchors is None:
            result.add_error("Anchors field is missing")
            return
        items = self._flatten_anchor_items(anchors)
        min_items = int(self.anchors_policy.get("min_items", 0))
        max_items = int(self.anchors_policy.get("max_items", len(items) or 0))
        if len(items) < min_items:
            result.add_error(f"Anchors must include at least {min_items} items (found {len(items)})")
        if max_items and len(items) > max_items:
            result.add_error(f"Anchors must include no more than {max_items} items (found {len(items)})")
        each_item_max = int(self.anchors_policy.get("each_item_max_words", 10 ** 6))
        for idx, item in enumerate(items, start=1):
            words = self._tokenize_words(item)
            if words > each_item_max:
                result.add_error(
                    f"Anchor {idx} exceeds {each_item_max} words ({words} words)"
                )
            if self.anchors_policy.get("require_case_or_statute_ref_per_item", False):
                if not self._contains_case_or_statute(item):
                    result.add_error(f"Anchor {idx} must reference a case or statute")
            if self.anchors_policy.get("uk_or_persuasive_requires_note", False):
                if re.search(r"\b(UK|PC|Privy Council)\b", item) and not re.search(
                    r"nuance|approved|distinguished|persuasive", item, re.IGNORECASE
                ):
                    result.add_error("UK/PC anchors must include nuance or note")

    def _flatten_anchor_items(self, anchors: object) -> List[str]:
        if isinstance(anchors, list):
            return [str(item).strip() for item in anchors if str(item).strip()]
        if isinstance(anchors, dict):
            items: List[str] = []
            for value in anchors.values():
                if isinstance(value, list):
                    items.extend(str(item).strip() for item in value if str(item).strip())
                elif isinstance(value, str) and value.strip():
                    items.append(value.strip())
            return items
        if isinstance(anchors, str) and anchors.strip():
            return [anchors.strip()]
        return []

    def _contains_case_or_statute(self, text: str) -> bool:
        if re.search(r"\bv\b", text):
            return True
        if re.search(r"\bAct\b", text):
            return True
        if re.search(r"\bs\s*\d", text):
            return True
        return False

    # ------------------------------------------------------------------
    # Abbreviations
    # ------------------------------------------------------------------
    def _check_abbreviations(self, back_text: str, result: ValidationResult) -> None:
        if not back_text:
            return
        seen: Dict[str, int] = {}
        for match in re.finditer(r"\b([A-Z]{2,})\b", back_text):
            abbreviation = match.group(1)
            if abbreviation in seen:
                continue
            seen[abbreviation] = match.start()
            if self._is_all_caps_word_allowed(abbreviation):
                continue
            if not self._has_abbreviation_definition(back_text, abbreviation, match.start()):
                result.add_error(
                    f"Abbreviation '{abbreviation}' must be expanded on first use"
                )

    def _is_all_caps_word_allowed(self, token: str) -> bool:
        whitelist = {"HCA", "AGLC", "JD", "LLB", "NSW", "VIC", "SA", "WA", "QLD", "ACT"}
        return token in whitelist

    def _has_abbreviation_definition(self, text: str, abbreviation: str, index: int) -> bool:
        window_start = max(0, index - 80)
        window_end = index + len(abbreviation) + 80
        window = text[window_start:window_end]
        # Long form (ABBR)
        pattern = re.compile(rf"([A-Za-z][A-Za-z\s'-]{{3,}})\s*\({re.escape(abbreviation)}\)")
        for match in pattern.finditer(window):
            start = window_start + match.start(0)
            end = window_start + match.end(0)
            if start <= index <= end:
                return True
        reverse = re.compile(rf"{re.escape(abbreviation)}\s*\([A-Za-z][A-Za-z\s'-]{{3,}}\)")
        for match in reverse.finditer(window):
            start = window_start + match.start(0)
            end = window_start + match.end(0)
            if start <= index <= end:
                return True
        return False

    # ------------------------------------------------------------------
    # Tripwires
    # ------------------------------------------------------------------
    def _check_tripwires(self, card: Dict, result: ValidationResult) -> None:
        tripwires = card.get("tripwires")
        if tripwires is None:
            result.add_error("Tripwires field is missing")
            return
        if not isinstance(tripwires, list):
            result.add_error("Tripwires must be a list")
            return
        tripwires = [str(item).strip() for item in tripwires if str(item).strip()]
        min_tripwires = int(self.tripwires_policy.get("min", 0))
        max_tripwires = int(self.tripwires_policy.get("max", len(tripwires) or 0))
        if len(tripwires) < min_tripwires:
            result.add_error(f"At least {min_tripwires} tripwires required (found {len(tripwires)})")
        if max_tripwires and len(tripwires) > max_tripwires:
            result.add_error(f"No more than {max_tripwires} tripwires allowed (found {len(tripwires)})")
        self._check_tripwire_duplicates(tripwires, result)

    def _check_tripwire_duplicates(self, tripwires: List[str], result: ValidationResult) -> None:
        threshold = float(self.tripwires_policy.get("duplicate_similarity_threshold", 0.8))
        for first, second in itertools.combinations(enumerate(tripwires, start=1), 2):
            (idx_a, trip_a), (idx_b, trip_b) = first, second
            if self._text_similarity(trip_a, trip_b) >= threshold:
                result.add_error(
                    f"Tripwires {idx_a} and {idx_b} are near-duplicates (similarity >= {threshold})"
                )

    # ------------------------------------------------------------------
    # Keywords and tags
    # ------------------------------------------------------------------
    def _check_keywords(self, card: Dict, result: ValidationResult) -> None:
        keywords = card.get("keywords")
        if keywords is None or not isinstance(keywords, list):
            result.add_error("Keywords must be a list")
            return
        keywords = [str(item).strip() for item in keywords if str(item).strip()]
        min_keywords = int(self.keywords_policy.get("min", 0))
        max_keywords = int(self.keywords_policy.get("max", len(keywords) or 0))
        if len(keywords) < min_keywords:
            result.add_error(f"At least {min_keywords} keywords required (found {len(keywords)})")
        if max_keywords and len(keywords) > max_keywords:
            result.add_error(f"No more than {max_keywords} keywords allowed (found {len(keywords)})")
        recommended = set(k.lower() for k in self.recommended_keywords)
        chosen = set(k.lower() for k in keywords)
        missing_recommended = [kw for kw in recommended if kw not in chosen]
        back_text = str(card.get("back", ""))
        for keyword in missing_recommended:
            if re.search(re.escape(keyword), back_text, re.IGNORECASE):
                result.add_warning(f"Consider adding recommended keyword: {keyword}")

    def _check_tags(self, card: Dict, result: ValidationResult) -> None:
        tags = card.get("tags")
        if tags is None or not isinstance(tags, list):
            result.add_error("Tags must be a list")
            return
        tag_values = {str(tag).strip() for tag in tags if str(tag).strip()}
        required = set(self.tags_policy.get("required", []))
        missing = [tag for tag in required if tag not in tag_values]
        if missing:
            result.add_error("Missing required tags: " + ", ".join(sorted(missing)))

    # ------------------------------------------------------------------
    # Linting helpers
    # ------------------------------------------------------------------
    def _check_placeholder_text(self, card: Dict, result: ValidationResult) -> None:
        fields_to_scan = {
            "front": card.get("front", ""),
            "back": card.get("back", ""),
            "why_it_matters": card.get("why_it_matters", ""),
            "mnemonic": card.get("mnemonic", ""),
        }
        for field, value in fields_to_scan.items():
            text = str(value)
            for regex in self.placeholder_regexes:
                if regex.search(text):
                    result.add_error(f"Field '{field}' contains placeholder text matching '{regex.pattern}'")

    def _check_repeated_sentences(self, card: Dict, result: ValidationResult) -> None:
        threshold = float(self.lint_policy.get("forbid_repeated_sentences_similarity_threshold", 0.8))
        sentences = []
        for field in ("front", "back", "why_it_matters"):
            text = str(card.get(field, ""))
            for sentence in filter(None, [segment.strip() for segment in re.split(r"[\.\?\!]", text)]):
                sentences.append((field, sentence))
        for (field_a, sent_a), (field_b, sent_b) in itertools.combinations(sentences, 2):
            if self._text_similarity(sent_a, sent_b) >= threshold:
                result.add_error(
                    f"Sentences from {field_a} and {field_b} are near-duplicates (>= {threshold})"
                )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _extract_heading_label(self, pattern: str) -> str:
        stripped = pattern
        stripped = stripped.strip("^")
        stripped = stripped.replace("\\.", ".")
        stripped = re.sub(r"\\", "", stripped)
        return stripped

    def _extract_mermaid_block(self, text: str) -> Optional[Tuple[str, str]]:
        fence = re.search(r"```\s*(\w+)\s*(.*?)```", text, re.DOTALL)
        if not fence:
            return None
        language = fence.group(1).strip().lower()
        body = fence.group(2)
        return language, body

    def _count_top_level_branches(self, node_lines: List[str]) -> int:
        branches = 0
        for line in node_lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent in (1, 2):
                branches += 1
        return branches

    def _iter_top_level_labels(self, node_lines: List[str]) -> Iterable[str]:
        for line in node_lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent in (1, 2):
                yield stripped.strip()

    def _normalise_heading_name(self, name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.lower())

    def _tokenize_words(self, text: str) -> int:
        tokens = re.findall(r"[A-Za-z0-9']+", text)
        return len(tokens)

    def _text_similarity(self, text_a: str, text_b: str) -> float:
        tokens_a = self._normalise_tokens(text_a)
        tokens_b = self._normalise_tokens(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        counter_a = Counter(tokens_a)
        counter_b = Counter(tokens_b)
        intersection = set(counter_a) & set(counter_b)
        dot = sum(counter_a[token] * counter_b[token] for token in intersection)
        norm_a = math.sqrt(sum(count ** 2 for count in counter_a.values()))
        norm_b = math.sqrt(sum(count ** 2 for count in counter_b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _normalise_tokens(self, text: str) -> List[str]:
        return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token]
