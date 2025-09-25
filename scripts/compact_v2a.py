#!/usr/bin/env python3
"""
Compact cards to comply with v2a limits *without* losing required sections.

- Reads limits (headings, word caps, max anchors/keywords/tripwires) from policy YAML.
- Removes "TODO: ... content." stubs.
- Preserves canonical headings; trims each section so back <= max_words.
- Caps anchors (8), keywords (10), tripwires (6) using keep-first strategy.
- Backs up originals to backups/compact_v2a/YYYYmmdd-HHMMSS/

Usage:
  python scripts/compact_v2a.py --policy jd/policy/cards_policy.yml "jd/cards_yaml/*.yml" [more globs...]

"""

from __future__ import annotations
import argparse, json, re, sys, shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# --- YAML loader with fallback to your repo's tools/yaml_fallback.py ---
try:
    import yaml
    def y_load(text: str):
        return yaml.safe_load(text) or {}
    def y_dump(data: dict) -> str:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
except Exception:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.yaml_fallback import safe_load as _fallback_load  # type: ignore

    def _normalize_yaml_for_fallback(text: str) -> str:
        lines = text.splitlines()
        result: List[str] = []
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
                previous_was_list = True
                previous_list_indent = current_indent
                continue
            elif stripped:
                pending_indent = None
                previous_was_list = False

        return "\n".join(result)

    def y_load(text: str):
        try:
            return _fallback_load(_normalize_yaml_for_fallback(text)) or {}
        except Exception:
            return {}

    def _format_simple(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(str(value), ensure_ascii=False)

    def _emit_scalar(value: object, indent: int, prefix: str, with_colon: bool) -> List[str]:
        if isinstance(value, str):
            if "\n" in value:
                header = f"{prefix}{':' if with_colon else ''} |"
                pad = " " * (indent + 2)
                lines = [header]
                for line in value.split("\n"):
                    lines.append(f"{pad}{line}")
                return lines
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = _format_simple(value)
        if with_colon:
            return [f"{prefix}: {text}"]
        return [f"{prefix} {text}"]

    def _dump_yaml(value: object, indent: int = 0) -> List[str]:
        space = " " * indent
        if isinstance(value, dict):
            if not value:
                return [f"{space}{{}}"]
            lines: List[str] = []
            for key, val in value.items():
                key_str = str(key)
                if isinstance(val, dict):
                    if val:
                        lines.append(f"{space}{key_str}:")
                        lines.extend(_dump_yaml(val, indent + 2))
                    else:
                        lines.append(f"{space}{key_str}: {{}}")
                elif isinstance(val, list):
                    if val:
                        lines.append(f"{space}{key_str}:")
                        lines.extend(_dump_yaml(val, indent + 2))
                    else:
                        lines.append(f"{space}{key_str}: []")
                else:
                    lines.extend(_emit_scalar(val, indent, f"{space}{key_str}", True))
            return lines
        if isinstance(value, list):
            if not value:
                return [f"{space}[]"]
            lines: List[str] = []
            for item in value:
                if isinstance(item, dict):
                    if item:
                        lines.append(f"{space}-")
                        lines.extend(_dump_yaml(item, indent + 2))
                    else:
                        lines.append(f"{space}- {{}}")
                elif isinstance(item, list):
                    if item:
                        lines.append(f"{space}-")
                        lines.extend(_dump_yaml(item, indent + 2))
                    else:
                        lines.append(f"{space}- []")
                else:
                    lines.extend(_emit_scalar(item, indent, f"{space}-", False))
            return lines
        return _emit_scalar(value, indent, space, False)

    def y_dump(data: dict) -> str:
        return "\n".join(_dump_yaml(data)) + "\n"

# --- Helpers -----------------------------------------------------------------

SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')
TODO_LINE = re.compile(r'^\s*TODO\s*:\s*.*$', re.IGNORECASE)

@dataclass
class Limits:
    headings: List[str]
    back_min: int
    back_max: int
    anchors_max: int
    keywords_max: int
    tripwires_max: int

def load_policy(policy_path: Path) -> Limits:
    p = y_load(policy_path.read_text(encoding="utf-8"))
    # Sensible defaults if keys change
    headings = [
        "Issue.", "Rule.", "Application scaffold.",
        "Authorities map.", "Statutory hook.", "Tripwires.", "Conclusion."
    ]
    back_min = 160
    back_max = 280
    anchors_max = 8
    keywords_max = 10
    tripwires_max = 6

    try:
        cards = p.get("cards", {})
        back_cfg = cards.get("back", {})
        back_min = int(back_cfg.get("min_words", back_min))
        back_max = int(back_cfg.get("max_words", back_max))

        hcfg = cards.get("headings", {})
        # Prefer explicit order if present
        ordered = hcfg.get("ordered", [])
        if ordered and all(isinstance(h, str) for h in ordered):
            headings = ordered

        # Optional caps from policy (fall back to known values)
        anchors_max = int(cards.get("anchors", {}).get("max_items", anchors_max))
        keywords_max = int(cards.get("keywords", {}).get("max_items", keywords_max))
        tripwires_max = int(cards.get("tripwires", {}).get("max_items", tripwires_max))
    except Exception:
        pass

    return Limits(headings, back_min, back_max, anchors_max, keywords_max, tripwires_max)

def split_back_into_sections(back: str, headings: List[str]) -> Dict[str, List[str]]:
    """Return {heading: [lines...]} even when headings appear inline."""

    sections: Dict[str, List[str]] = {h: [] for h in headings}
    if not back.strip():
        return sections

    pattern = re.compile(rf"(?<!\S)({'|'.join(re.escape(h) for h in headings)})")
    text = back.replace("\r\n", "\n")
    matches = list(pattern.finditer(text))

    if not matches:
        sections[headings[0]].extend([ln for ln in text.split("\n") if ln.strip()])
        return sections

    def add_chunk(target: str, chunk: str) -> None:
        lines = [ln.rstrip() for ln in chunk.split("\n") if ln.strip()]
        sections[target].extend(lines)

    # Handle any intro text before first heading
    first_start = matches[0].start()
    if first_start > 0:
        intro = text[:first_start]
        if intro.strip():
            add_chunk(headings[0], intro)

    for idx, match in enumerate(matches):
        heading = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk = text[start:end]
        if chunk.strip():
            add_chunk(heading, chunk)

    return sections

def remove_todo_stubs(text_lines: List[str]) -> List[str]:
    return [ln for ln in text_lines if not TODO_LINE.match(ln)]

def word_count(text: str) -> int:
    return len([w for w in re.findall(r"\b\w+(?:[-’']\w+)?\b", text)])

def trim_paragraph_to_words(paragraph: str, limit: int) -> str:
    # Try sentence-aware trim first
    pieces = SENT_SPLIT.split(paragraph.strip())
    out, total = [], 0
    for sent in pieces:
        w = word_count(sent)
        if total + w <= limit or not out:
            out.append(sent)
            total += w
        else:
            break
    # If still too long (single monster sentence), hard trim by words
    combined = " ".join(out).strip()
    if word_count(combined) <= limit:
        return combined
    words = re.findall(r"\S+", combined)
    return " ".join(words[:limit]).rstrip(",;—-:")

def compact_section(lines: List[str], budget: int) -> List[str]:
    if not lines:
        return []
    # Preserve bullets as bullets, compact paragraphs
    out: List[str] = []
    para: List[str] = []

    def flush_para():
        if not para:
            return
        text = " ".join([p.strip() for p in para if p.strip()])
        out.append(trim_paragraph_to_words(text, budget_remaining()))
        para.clear()

    # dynamic budget tracker
    total_used = 0
    def budget_remaining() -> int:
        return max(0, budget - total_used)

    for ln in lines:
        if ln.strip().startswith(("- ", "* ")):
            flush_para()
            txt = ln.strip()[2:].strip()
            trimmed = trim_paragraph_to_words(txt, budget_remaining())
            if trimmed:
                out.append(f"- {trimmed}")
                total_used += word_count(trimmed)
        elif ln.strip() == "":
            flush_para()
        else:
            para.append(ln)

    flush_para()
    # Final hard cap: if we overflowed budget due to rounding, trim last entry
    words_now = sum(word_count(re.sub(r"^-+\s*", "", l)) for l in out)
    if words_now > budget and out:
        overflow = words_now - budget
        last = out[-1]
        base = re.sub(r"^-+\s*", "", last)
        trimmed = trim_paragraph_to_words(base, max(1, word_count(base) - overflow))
        if last.startswith("- "):
            out[-1] = f"- {trimmed}"
        else:
            out[-1] = trimmed
    return out

def rebuild_back(sections: Dict[str, List[str]], order: List[str]) -> str:
    blocks = []
    for h in order:
        blocks.append(h)
        if sections[h]:
            blocks.extend(sections[h])
        blocks.append("")  # blank line between sections
    return "\n".join(blocks).rstrip() + "\n"

def cap_list(lst: List[str] | None, limit: int) -> List[str]:
    if not lst:
        return []
    # Keep the first N (user-ordered = user-prioritised)
    return lst[:limit]

def tidy_anchors(anchors: dict | None, max_items: int) -> dict:
    if not anchors or not isinstance(anchors, dict):
        return anchors or {}
    cases = list(anchors.get("cases", []) or [])
    statutes = list(anchors.get("statutes", []) or [])
    notes = list(anchors.get("notes", []) or [])

    # priority: cases > statutes > notes
    out_cases = cap_list(cases, max_items)
    remaining = max(0, max_items - len(out_cases))
    out_statutes = cap_list(statutes, remaining)
    remaining -= len(out_statutes)
    out_notes = cap_list(notes, remaining)

    return {
        "cases": out_cases,
        "statutes": out_statutes,
        "notes": out_notes
    }

# --- Main compactor -----------------------------------------------------------

def compact_card(data: dict, limits: Limits) -> Tuple[dict, bool, str]:
    changed_msgs: List[str] = []

    # 1) Clean and split back
    back_text = str(data.get("back") or "")
    # Drop TODO stubs
    lines = remove_todo_stubs(back_text.splitlines())
    cleaned = "\n".join(lines)
    sections = split_back_into_sections(cleaned, limits.headings)

    # 2) Compact per-section to fit overall back_max
    # Allocate a heuristic budget by section (can be tuned via policy later)
    # Start with even split then nudge weights (Issue/Rule/Application slightly higher)
    base_budget = max(30, limits.back_max // max(1, len(limits.headings)))
    weights = {h: 1.0 for h in limits.headings}
    for h in ("Issue.", "Rule.", "Application scaffold."):
        if h in weights:
            weights[h] = 1.25
    if "Authorities map." in weights:
        weights["Authorities map."] = 0.9
    if "Statutory hook." in weights:
        weights["Statutory hook."] = 0.8
    if "Tripwires." in weights:
        weights["Tripwires."] = 0.9
    if "Conclusion." in weights:
        weights["Conclusion."] = 0.9

    total_w = sum(weights.values())
    budgets = {h: int(limits.back_max * (weights[h] / total_w)) for h in limits.headings}
    # Ensure each section gets at least 20 words
    for h in budgets:
        budgets[h] = max(20, budgets[h])

    compacted: Dict[str, List[str]] = {}
    for h in limits.headings:
        before = "\n".join(sections[h]).strip()
        compacted[h] = compact_section(sections[h], budgets[h])
        after = "\n".join(compacted[h]).strip()
        if after != before:
            changed_msgs.append(f"compacted {h}")

    new_back = rebuild_back(compacted, limits.headings)
    if word_count(re.sub(r"```.*?```", "", new_back, flags=re.DOTALL)) > limits.back_max:
        # Hard guard: if still over, lop conclusion first, then authorities map extras
        # (You can tweak this priority later.)
        for h in ("Conclusion.", "Authorities map.", "Application scaffold.", "Rule.", "Issue."):
            comp = " ".join(re.sub(r"^-+\s*", "", l) for l in compacted[h])
            if not comp:
                continue
            trimmed = trim_paragraph_to_words(comp, max(20, budgets[h] - 20))
            if trimmed != comp:
                compacted[h] = [trimmed]
                new_back = rebuild_back(compacted, limits.headings)
                if word_count(new_back) <= limits.back_max:
                    changed_msgs.append(f"hard-trimmed {h}")
                    break

    data["back"] = new_back

    # 3) Cap list fields
    kw = data.get("keywords")
    if isinstance(kw, list) and len(kw) > limits.keywords_max:
        data["keywords"] = kw[:limits.keywords_max]
        changed_msgs.append("keywords capped")

    tw = data.get("tripwires")
    if isinstance(tw, list) and len(tw) > limits.tripwires_max:
        data["tripwires"] = tw[:limits.tripwires_max]
        changed_msgs.append("tripwires capped")

    anchors = data.get("anchors")
    new_anchors = tidy_anchors(anchors, limits.anchors_max)
    if anchors != new_anchors:
        data["anchors"] = new_anchors
        changed_msgs.append("anchors capped")

    return data, bool(changed_msgs), ", ".join(changed_msgs) or "no changes"

def main():
    ap = argparse.ArgumentParser(description="Compact v2a cards to fit policy limits without losing required sections.")
    ap.add_argument("--policy", required=True, help="Path to policy YAML")
    ap.add_argument("patterns", nargs="+", help="Glob pattern(s) for card YAML files")
    args = ap.parse_args()

    root = Path(".").resolve()
    limits = load_policy(Path(args.policy).resolve())

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = root / "backups" / f"compact_v2a" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    files: List[Path] = []
    for g in args.patterns:
        files.extend(sorted(root.glob(g)))

    touched = 0
    for p in files:
        try:
            data = y_load(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                print(f"[SKIP] {p} (not a mapping)")
                continue

            new_data, changed, info = compact_card(data, limits)
            if changed:
                # backup then write
                shutil.copy2(p, backup_dir / p.name)
                p.write_text(y_dump(new_data), encoding="utf-8")
                touched += 1
                print(f"[OK] {p.name}: {info}")
            else:
                print(f"[OK] {p.name}: unchanged")
        except Exception as e:
            print(f"[ERR] {p}: {e}")

    print(f"\nDone. Touched {touched} file(s). Backups: {backup_dir}")

if __name__ == "__main__":
    main()
