"""One-time fixer to add required v2a fields/sections with stub content."""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import shutil
import sys
from pathlib import Path
from typing import Iterable, Mapping

# --- replace your current YAML import + helpers with this ---
USING_PYYAML = True

try:  # pragma: no cover - exercised via runtime availability
    import yaml

    def y_load(text: str):
        return yaml.safe_load(text) or {}

    def y_dump(data: dict) -> str:
        return yaml.safe_dump(
            data, sort_keys=False, allow_unicode=True, default_flow_style=False
        )

except Exception:  # pragma: no cover - fallback path
    USING_PYYAML = False
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.yaml_fallback import safe_load as _fallback_load, safe_dump as _fallback_dump

    def y_load(text: str):
        return _fallback_load(_normalize_yaml_for_fallback(text)) or {}

    def y_dump(data: dict) -> str:
        buffer = io.StringIO()
        _fallback_dump(data, buffer)
        return buffer.getvalue()


# ------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = Path("jd/policy/cards_policy.yml")
CARDS_GLOB = "jd/cards_yaml/*.yml"
BACKUP_ROOT = Path("backups")


def _normalize_yaml_for_fallback(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    pending_indent: int | None = None
    previous_was_list = False
    previous_list_indent = 0
    for line in lines:
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        if pending_indent is not None and stripped.startswith("- "):
            needed = pending_indent + 2
            if current_indent <= pending_indent:
                line = " " * needed + stripped
                current_indent = needed
        if (
            previous_was_list
            and current_indent >= previous_list_indent
            and stripped
            and not stripped.startswith("- ")
            and not stripped.endswith(":")
        ):
            # treat as continuation of prior list item
            result[-1] = result[-1] + " " + stripped.strip()
            if stripped.endswith(":") and not stripped.startswith("-"):
                pending_indent = current_indent
            elif stripped:
                pending_indent = None
            previous_was_list = False
            continue
        result.append(line)
        if stripped.endswith(":") and not stripped.startswith("-"):
            pending_indent = current_indent
        elif stripped.startswith("- "):
            # keep pending indent active for subsequent sequence items
            previous_was_list = True
            previous_list_indent = current_indent
            continue
        elif stripped:
            pending_indent = None
            previous_was_list = False
    return "\n".join(result)


def load_yaml(p: Path) -> dict:
    try:
        return y_load(p.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"[SKIP] {p}: failed to parse YAML ({e})")
        return {}


def save_yaml(p: Path, data: dict, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    if p.exists():
        shutil.copy2(p, backup_dir / p.name)
    p.write_text(y_dump(data), encoding="utf-8")


def ensure_required_fields(card: dict, policy: Mapping[str, object]) -> bool:
    changed = False
    schema = policy.get("schema")
    required_fields: Iterable[str] = []
    if isinstance(schema, Mapping):
        fields = schema.get("required_fields", [])
        if isinstance(fields, Iterable) and not isinstance(fields, (str, bytes)):
            required_fields = list(fields)

    def mark_changed() -> None:
        nonlocal changed
        changed = True

    def ensure_text(field: str, placeholder: str) -> None:
        value = card.get(field)
        if not isinstance(value, str) or not value.strip():
            card[field] = placeholder
            mark_changed()

    def ensure_list(field: str, items: Iterable[str]) -> None:
        value = card.get(field)
        if not isinstance(value, list):
            card[field] = list(items)
            mark_changed()
            return
        existing = [item for item in value if isinstance(item, str) and item.strip()]
        if len(existing) != len(value):
            card[field] = existing
            mark_changed()
        if not existing:
            card[field] = list(items)
            mark_changed()

    for field in required_fields:
        if field in {"front", "back", "why_it_matters"}:
            continue
        if field == "mnemonic":
            value = card.get(field)
            if not isinstance(value, str):
                card[field] = ""
                mark_changed()
        elif field == "diagram":
            value = card.get(field)
            if not isinstance(value, str) or not value.strip():
                card[field] = (
                    "```mermaid\nmindmap\n  root((TODO concept))\n"
                    "    Branch A\n    Branch B\n    Branch C\n    Branch D\n```\n"
                )
                mark_changed()
        elif field == "tripwires":
            tripwire_policy = policy.get("tripwires")
            min_items = 3
            if isinstance(tripwire_policy, Mapping):
                raw_min = tripwire_policy.get("min", 3)
                try:
                    min_items = int(raw_min)
                except (TypeError, ValueError):
                    min_items = 3
            ensure_list(
                field,
                [f"TODO: add tripwire insight {i+1}" for i in range(max(3, min_items))],
            )
            if len(card[field]) < min_items:
                needed = min_items - len(card[field])
                card[field].extend(
                    [f"TODO: add tripwire insight {len(card[field]) + i + 1}" for i in range(needed)]
                )
                mark_changed()
        elif field == "anchors":
            value = card.get(field)
            anchor_policy = policy.get("anchors")
            structure: dict[str, list[str]] = {}
            min_anchor_items = 1
            if isinstance(anchor_policy, Mapping):
                raw_structure = anchor_policy.get("structure", {})
                if isinstance(raw_structure, Mapping):
                    structure = {
                        key: list(val) if isinstance(val, list) else []
                        for key, val in raw_structure.items()
                    }
                raw_min = anchor_policy.get("min_items", 1)
                try:
                    min_anchor_items = int(raw_min)
                except (TypeError, ValueError):
                    min_anchor_items = 1
            if not isinstance(value, dict):
                card[field] = {}
                value = card[field]
                mark_changed()
            if isinstance(value, dict):
                for key, default in structure.items():
                    if key not in value or not isinstance(value[key], list):
                        value[key] = list(default) if isinstance(default, list) else []
                        mark_changed()
                total_items = sum(len(v) for v in value.values() if isinstance(v, list))
                if total_items < min_anchor_items:
                    value.setdefault("cases", [])
                    while total_items < min_anchor_items:
                        value["cases"].append(f"TODO anchor case {total_items + 1}")
                        total_items += 1
                        mark_changed()
        elif field == "keywords":
            kw_policy = policy.get("keywords")
            min_kw = 6
            recommended: list[str] = []
            if isinstance(kw_policy, Mapping):
                raw_min = kw_policy.get("min", 6)
                try:
                    min_kw = int(raw_min)
                except (TypeError, ValueError):
                    min_kw = 6
                recommended = [
                    kw
                    for kw in kw_policy.get("recommended_include_if_relevant", [])
                    if isinstance(kw, str)
                ]
            ensure_list(field, [])
            current = card[field]
            for kw in recommended:
                if len(current) >= min_kw:
                    break
                if kw not in current:
                    current.append(kw)
                    mark_changed()
            while len(current) < min_kw:
                placeholder = f"todo-keyword-{len(current) + 1}"
                current.append(placeholder)
                mark_changed()
        elif field == "reading_level":
            reading_policy = policy.get("reading_level")
            target = "Plain English (JD)"
            if isinstance(reading_policy, Mapping):
                candidate = reading_policy.get("target", target)
                if isinstance(candidate, str) and candidate.strip():
                    target = candidate
            ensure_text(field, target)
        elif field == "tags":
            tag_policy = policy.get("tags")
            required_tags: list[str] = []
            if isinstance(tag_policy, Mapping):
                required_tags = [
                    tag for tag in tag_policy.get("required", []) if isinstance(tag, str)
                ]
            ensure_list(field, required_tags or ["MLS_H1"])
            tags = card[field]
            for tag in required_tags:
                if tag not in tags:
                    tags.append(tag)
                    mark_changed()
        else:
            value = card.get(field)
            if isinstance(value, list):
                if not any(isinstance(item, str) and item.strip() for item in value):
                    card[field] = ["TODO: populate"]
                    mark_changed()
            elif not value:
                card[field] = "TODO: populate"
                mark_changed()

    ensure_text("front", "TODO: Draft a question for the front of the card?")
    ensure_text("why_it_matters", "TODO: Explain why this matters for the exam.")

    back_rules = policy.get("back")
    heading_patterns = []
    if isinstance(back_rules, Mapping):
        heading_patterns = [
            pattern for pattern in back_rules.get("required_headings_regex", []) if isinstance(pattern, str)
        ]

    back_value = card.get("back")
    if not isinstance(back_value, str) or not back_value.strip():
        stub_sections = []
        for pattern in heading_patterns:
            label = _heading_label(pattern)
            stub_sections.append(f"{label}\nTODO: {label.lower()} content.")
        if not stub_sections:
            stub_sections = ["Issue.\nTODO: Issue content.", "Conclusion.\nTODO: Conclusion content."]
        card["back"] = "\n\n".join(stub_sections)
        mark_changed()
    else:
        text = back_value
        for pattern in heading_patterns:
            if not _has_heading(text, pattern):
                label = _heading_label(pattern)
                text = text.rstrip() + f"\n\n{label}\nTODO: {label.lower()} content."
                mark_changed()
        card["back"] = text

    return changed


def _has_heading(text: str, pattern: str) -> bool:
    try:
        import re

        return re.search(pattern, text, flags=re.MULTILINE) is not None
    except re.error:  # pragma: no cover - defensive fallback
        label = _heading_label(pattern)
        return label in text


def _heading_label(pattern: str) -> str:
    cleaned = pattern.strip()
    if cleaned.startswith("^"):
        cleaned = cleaned[1:]
    if cleaned.endswith("$"):
        cleaned = cleaned[:-1]
    return cleaned.replace("\\", "")


def gather_cards(paths: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in paths:
        if any(ch in pattern for ch in "*?[]"):
            files.extend(sorted(Path().glob(pattern)))
        else:
            files.append(Path(pattern))
    return [p for p in files if p.exists() and p.suffix.lower() in {".yml", ".yaml"}]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add missing v2a-required fields with stubs.")
    parser.add_argument("paths", nargs="*", default=[CARDS_GLOB], help="Card paths or globs")
    parser.add_argument(
        "--policy",
        default=str(DEFAULT_POLICY),
        help="Path to the policy YAML (default: jd/policy/cards_policy.yml)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    policy_path = Path(args.policy)
    if not policy_path.exists():
        print(f"[ERROR] Policy not found: {policy_path}")
        return 1

    policy = load_yaml(policy_path)
    if not policy:
        print(f"[ERROR] Failed to load policy: {policy_path}")
        return 1

    if not USING_PYYAML:
        print("[WARN] PyYAML not available; quick_fix_v2a requires it to safely edit cards.")
        print("       No changes were applied. Install PyYAML and rerun for full functionality.")
        return 0

    cards = gather_cards(args.paths)
    if not cards:
        print("[INFO] No cards found for the provided paths.")
        return 0

    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / f"quick_fix_v2a/{timestamp}"
    updated = 0

    for card_path in cards:
        data = load_yaml(card_path)
        if not data:
            continue
        if ensure_required_fields(data, policy):
            save_yaml(card_path, data, backup_dir)
            updated += 1
            print(f"[FIXED] {card_path}")

    if updated == 0:
        print("[OK] All cards already contain required v2a fields/sections.")
    else:
        print(f"[DONE] Updated {updated} card(s). Backups in {backup_dir}.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())

