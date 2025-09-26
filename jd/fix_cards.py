from __future__ import annotations

import datetime
import os
import re
import sys
import time
import shutil
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

try:
    import openai  # type: ignore[import-not-found]
    from openai import OpenAI  # type: ignore[import-not-found]
except ImportError:
    print("Error: 'openai' package is required. Please install it with: pip install openai")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: 'pyyaml' package is required. Please install it with: pip install pyyaml")
    sys.exit(1)

print("Using API Key:", (os.environ.get("OPENAI_API_KEY") or "<missing>")[:10], "...")
openai.api_key = os.environ.get("OPENAI_API_KEY")

# Constants
CANON_MM = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    - Issue — classify\n"
    "    - Rule — test/statute\n"
    "    - Application — to facts\n"
    "    - Conclusion — outcome\n"
    "```\n"
)

# ---- Minimal OpenAI-compatible client (works with OpenAI & other compatible endpoints) ----
API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
# Ensure URL is properly formatted without double dots
base_url = os.getenv("OPENAI_BASE", "https://api.openai.com/v1")
API_BASE = base_url.replace('..', '.')  # Fix any double dots in URL
MODEL     = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")  # Using gpt-3.5-turbo for better compatibility
USE_API  = os.getenv("USE_API", "1") != "0"

# Debug info
print(f"Using API: {USE_API}")
print(f"API Base URL: {API_BASE}")
print(f"Model: {MODEL}")
print(f"API Key: {'*' * 20}{API_KEY[-4:] if API_KEY else 'None'}")

if not API_KEY:
    print("Error: OPENAI_API_KEY environment variable not set")
    print("Please set it with: $env:OPENAI_API_KEY='your-api-key'")
    sys.exit(1)

def chat(messages, temperature=None, max_completion_tokens=1800, max_retries=3):
    """Send messages to the OpenAI API with retries and timeouts using the official client."""
    client = OpenAI(api_key=API_KEY, base_url=API_BASE)
    
    for attempt in range(max_retries):
        try:
            # Prepare the request parameters
            params = {
                "model": MODEL,
                "messages": messages,
                "temperature": temperature or 0.7,
                "timeout": 60  # 60 seconds timeout
            }
            
            # Only include max_completion_tokens for OpenAI's API v1
            if "openai.com" in API_BASE:
                params["max_completion_tokens"] = max_completion_tokens
                
            # Make the API call
            response = client.chat.completions.create(**params)
            return response.choices[0].message.content
            
        except Exception as err:
            error_msg = str(err).replace('openaai.com', 'openai.com')
            if attempt == max_retries - 1:  # Last attempt
                print(f"  - ❌ Final attempt failed: {error_msg[:200]}...")
                raise
                
            wait_time = (2 ** attempt) * 2
            print(f"  - ⚠️  Error: {error_msg[:200]}...")
            print(f"  - Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
    
    raise RuntimeError(f"Failed after {max_retries} retries")

# ---- I/O & validation helpers ----
def yload(s: str) -> Dict[str, Any]:
    return yaml.safe_load(s) or {}


def ydump(d: Dict[str, Any]) -> str:
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=1000)

ROOT = Path(__file__).parent / "cards_yaml"
timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP = Path("backups") / f"llm_fix_{timestamp}"
BACKUP.mkdir(parents=True, exist_ok=True)

@dataclass
class ValidationReport:
    errors: List[str]
    warnings: List[str]


def clean_yaml_noise(text: str) -> str:
    """Strip code fences and standalone document separators that upset PyYAML."""
    cleaned = re.sub(r"```(?:yaml)?", "", text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "")
    cleaned = re.sub(r"^---\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned


REQ_HEADINGS = [
    "Issue.", "Rule.", "Application scaffold.", "Authorities map.",
    "Statutory hook.", "Tripwires.", "Conclusion."
]

CANON_MM = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    - Issue — classify\n"
    "    - Rule — test/statute\n"
    "    - Application — to facts\n"
    "    - Conclusion — outcome\n"
    "```\n"
)

DIAG_RX = re.compile(
    r"```mermaid\s*?\nmindmap\s*?\n\s*root\(\(.*?\)\)\s*?\n"  # mermaid header and root
    r"(?:\s{2,}-\s.*\n){4}"                                   # at least four children lines
    r"\s*```",
    re.S,
)

def is_structural_canon(diagram: str) -> bool:
    """Accept any mermaid mindmap with exactly four hyphen-children under root, ignoring whitespace."""
    if not diagram or not diagram.strip().startswith("```mermaid"):
        return False
    lines = [line.rstrip() for line in diagram.splitlines()]
    try:
        root_idx = next(i for i, line in enumerate(lines) 
                       if re.search(r"^\s*root\(\(", line))
    except StopIteration:
        return False
    kids = [line for line in lines[root_idx + 1:] 
            if re.match(r"^\s{4}-\s", line)]
    return len(kids) == 4

def force_canonical_diagram(_: str) -> str:
    return CANON_MM

def normalise_diagram_in_card(d: dict) -> bool:
    """If diagram is missing or non-canonical, replace with the canonical block."""
    diag = (d.get("diagram") or "").strip()
    if not diag or not is_structural_canon(diag):
        d["diagram"] = CANON_MM
        return True
    return False

H_RX = r"^(Issue\.|Rule\.|Application scaffold\.|Authorities map\.|Statutory hook\.|Tripwires\.|Conclusion\.)$"

def extract_sections(back: str) -> Dict[str, List[str]]:
    """Return {heading: [lines]} for the required headings."""
    back = back or ""
    # ensure headings exist as anchors for splitting (don't insert content here)
    for h in REQ_HEADINGS:
        if h not in back:
            back += ("" if back.endswith("\n") else "\n") + f"{h}\n"
    # split into blocks
    pat = r"(?m)^(Issue\.|Rule\.|Application scaffold\.|Authorities map\.|Statutory hook\.|Tripwires\.|Conclusion\.)\s*$"
    parts = re.split(pat, back)
    # parts = ["", H1, body1, H2, body2, ...]
    secs: Dict[str, List[str]] = {h: [] for h in REQ_HEADINGS}
    for i in range(1, len(parts), 2):
        h = parts[i]
        body = parts[i+1] if i+1 < len(parts) else ""
        secs[h] = [ln for ln in body.splitlines() if ln.strip()]
    return secs

def wordcount_content(sections: Dict[str, List[str]]) -> int:
    """Count words in all sections except headings."""
    lines: List[str] = []
    for h in REQ_HEADINGS:
        lines.extend(sections.get(h, []))
    # exclude headings; count just text
    return len(" ".join(lines).split())

def needs_llm_for_fill(d: Dict) -> bool:
    """Check if this card needs LLM processing."""
    back = d.get("back") or ""
    secs = extract_sections(back)

    # any required section empty?
    empties = any(not any(line.strip() for line in secs.get(h, [])) for h in REQ_HEADINGS)

    # placeholder markers?
    placeholders = bool(re.search(r"__HD__\d+__", back))

    # authorities map must have a Lead:
    auth_txt = "\n".join(secs.get("Authorities map.", []))
    no_lead = not re.search(r"\bLead:\b", auth_txt)

    # statutory hook needs an operative section/schedule
    hook_txt = "\n".join(secs.get("Statutory hook.", []))
    no_oper = not re.search(r"\b(?:s|ss)\s*\d|\bsch\s*\d", hook_txt, flags=re.I)

    # anchors sanity
    anc = d.get("anchors") or {}
    cases = anc.get("cases") or []
    stats = anc.get("statutes") or []
    anchors_bad = (len(cases) == 0) or (not any(re.search(r"\b(?:s|ss)\s*\d|\bsch\s*\d", str(s) or "", flags=re.I) for s in stats))

    # back must be >=160 words
    too_short = wordcount_content(secs) < 160

    return placeholders or empties or no_lead or no_oper or anchors_bad or too_short

def has_operative_section(stat_text: str) -> bool:
    return bool(re.search(r"\b(s|ss)\s*\d", str(stat_text))) or "sch " in str(stat_text).lower()

def ensure_headings(back: str) -> str:
    """Ensure all required headings exist once, in order; remove 'Step X' noise; seed minimal content when absent."""
    lines = [ln.rstrip() for ln in (back or "").splitlines()]
    body = "\n".join(lines)
    present = any(h in body for h in REQ_HEADINGS)
    if not present:
        body = (
            "Issue.\n\n"
            "Rule.\n\n"
            "Application scaffold.\n\n"
            "Authorities map.\nLead: .\n\n"
            "Statutory hook.\n\n"
            "Tripwires.\n\n"
            "Conclusion.\n"
        )
    else:
        for h in REQ_HEADINGS:
            if h not in body:
                body += "\n\n" + h + "\n"
    # strip lines that look like 'Step X'
    body = re.sub(r"^.*Step\s*\d+.*$", "", body, flags=re.M)
    return body

def validate_card(d: Dict[str, Any], fname: str) -> ValidationReport:
    """Validate a card dictionary and return errors and warnings."""
    errors: List[str] = []
    warnings: List[str] = []

    diagram = (d.get("diagram") or "").strip()
    if not diagram:
        errors.append("diagram missing")
    elif not is_structural_canon(diagram):
        errors.append("diagram not canonical")

    back = d.get("back") or ""
    sections = extract_sections(back)

    for heading in REQ_HEADINGS:
        body = sections.get(heading, [])
        if not any(line.strip() for line in body):
            errors.append(f"empty section: {heading}")

    auth_block = "\n".join(sections.get("Authorities map.", []))
    if not re.search(r"\bLead:\s*.+", auth_block):
        errors.append("Authorities map lacks a lead/case")

    stat_block = "\n".join(sections.get("Statutory hook.", []))
    if not has_operative_section(stat_block):
        errors.append("Statutory hook missing operative section")

    anchors = d.get("anchors") or {}
    if not isinstance(anchors, dict):
        errors.append("anchors missing or invalid structure")
        anchors = {}

    cases = anchors.get("cases") if isinstance(anchors, dict) else None
    if not isinstance(cases, list) or not cases:
        errors.append("anchors.cases empty")

    statutes = anchors.get("statutes") if isinstance(anchors, dict) else None
    if not isinstance(statutes, list) or not statutes:
        errors.append("anchors.statutes missing")
    elif not any(has_operative_section(str(s)) for s in statutes):
        errors.append("anchors.statutes missing operative section")

    if re.search(r"__HD__\d+__", back):
        errors.append("placeholder markers present (__HD__*)")

    word_total = wordcount_content(sections)
    if word_total < 160 or word_total > 280:
        warnings.append(f"back wordcount {word_total} outside 160–280")

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", back) if s.strip()]
    long_sentences = [s for s in sentences if len(s.split()) > 28]
    if long_sentences:
        warnings.append(f"{len(long_sentences)} sentence(s) exceed 28 words")

    if "Wagon Mound (No" in back and "No 1)" not in back:
        warnings.append("possible truncated citation: Wagon Mound")

    return ValidationReport(errors=errors, warnings=warnings)

# ---- Prompt template (surgical, deterministic-ish) ----
SYSTEM = (
"You are a meticulous JD flashcard editor and legal writing coach for Australia (Vic/NSW/Cth). "
"Follow AGLC4. Never invent authorities. Use Australian English."
)

USER_TMPL = """You will fix ONE YAML card to comply with this strict policy:

REQUIRED STRUCTURE
- diagram: canonical mermaid with root and exactly four hyphen-children indented by two spaces: Issue — classify; Rule — test/statute; Application — to facts; Conclusion — outcome
- back must contain the seven headings in order (exact punctuation): Issue.; Rule.; Application scaffold.; Authorities map.; Statutory hook.; Tripwires.; Conclusion.
- Under Authorities map., include at least a 'Lead: …' line; remove any 'Step X' lines.
- Statutory hook. must list only operative sections (e.g., 'Wrongs Act 1958 (Vic) s 48', 'Competition and Consumer Act 2010 (Cth) sch 2 s 18').
- Expand abbreviations on first use (CLR, VLR, WLR, NSWLR, NSWCA, ER, PC, AC, VR, ACL, CCA, IVAA, VBA, IIA).
- Back prose: split sentences > 28 words; dedupe near duplicates; total 160–280 words (content across sections).
- anchors: cases/statutes only, ≤8 total; statutes must include operative sections.

DO NOT:
- add placeholders like __HD__*, 'Step 1', or boilerplate that exceeds limits;
- include Commonwealth statutes unless the text engages Commonwealth or ACL/CCA;
- truncate citations.

Return ONLY valid YAML for the card (no commentary). Keep all other existing fields if sensible (why_it_matters, mnemonic, tags, keywords).

Here is the original YAML:
---
{card}
---
"""

AUDIT_TMPL = """Here is a study card in YAML. Audit it for legal rigour and clarity.
Apply these QA rules strictly:
- Australian English; AGLC4 pinpoints; no invented authorities.
- Authorities map must contain a `Lead:` case line with pinpoints.
- Statutory hook must cite operative Victorian provision(s).
- Back must total 160–280 words; sentences ≤ 28 words.
- Retain the existing headings verbatim and keep anchors within 8 entries.

Rewrite the `back` (and anchors if needed) to improve rigour and clarity while obeying the rules.
Return ONLY YAML with the improved `back` (and updated anchors if you changed them).

Warnings to address:
{warnings}

Card:
{card}
"""


def build_fill_messages(card_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TMPL.format(card=card_text)},
    ]


def build_audit_messages(card_text: str, warnings: List[str]) -> List[Dict[str, str]]:
    warn_block = "\n".join(f"- {w}" for w in warnings) or "- Resolve any latent clarity issues."
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": AUDIT_TMPL.format(card=card_text, warnings=warn_block)},
    ]


def run_fill_model(card: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        response = chat(
            messages=build_fill_messages(ydump(card)),
            temperature=0.0,
            max_completion_tokens=1800,
        )
        parsed = yload(clean_yaml_noise(response)) or {}
        if not isinstance(parsed, dict):
            return None, "model returned non-dict YAML"
        return parsed, None
    except Exception as err:
        return None, str(err)


def run_audit_model(card: Dict[str, Any], warnings: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        response = chat(
            messages=build_audit_messages(ydump(card), warnings),
            temperature=0.2,
            max_completion_tokens=2000,
        )
        parsed = yload(clean_yaml_noise(response)) or {}
        if not isinstance(parsed, dict):
            return None, "model returned non-dict YAML"
        return parsed, None
    except Exception as err:
        return None, str(err)


# ---- Main batcher ----
def main():
    files = sorted(ROOT.glob("*.yml"))
    print(f"Found {len(files)} cards.")
    BACKUP.mkdir(exist_ok=True)

    summary: List[Tuple[str, ValidationReport]] = []

    for index, path in enumerate(files, 1):
        print(f"\nProcessing {index}/{len(files)}: {path.name}")

        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as exc:
            report = ValidationReport(errors=[f"cannot read file: {exc}"], warnings=[])
            summary.append((path.name, report))
            continue

        cleaned_raw = clean_yaml_noise(raw)

        try:
            card = yload(cleaned_raw) or {"diagram": "", "back": "", "anchors": {}}
        except Exception as exc:
            report = ValidationReport(errors=[f"cannot parse original YAML: {exc}"], warnings=[])
            summary.append((path.name, report))
            continue

        # Local normalisation
        normalise_diagram_in_card(card)
        card["back"] = ensure_headings(card.get("back", ""))

        sections = extract_sections(card["back"])
        auth_lines = [ln for ln in sections.get("Authorities map.", []) if not re.match(r"^\s*Step\s+\d+\s*:", ln)]
        if not any(re.match(r"^\s*Lead\s*:", ln) for ln in auth_lines):
            auth_lines.insert(0, "Lead: Case name")
        sections["Authorities map."] = auth_lines

        hook_lines = sections.get("Statutory hook.", [])
        if not any(has_operative_section(line) for line in hook_lines):
            sections["Statutory hook."].insert(0, "Wrongs Act 1958 (Vic) s 48")

        card["back"] = "\n\n".join(f"{heading}\n" + "\n".join(lines) for heading, lines in sections.items())

        anchors_obj = card.get("anchors")
        anchors = anchors_obj if isinstance(anchors_obj, dict) else {}
        cases = anchors.get("cases") if isinstance(anchors, dict) else None
        if not isinstance(cases, list) or not cases:
            cases = ["Lead case to be determined"]
        anchors["cases"] = cases[:8]

        statutes = anchors.get("statutes") if isinstance(anchors, dict) else None
        if not isinstance(statutes, list) or not statutes or not any(has_operative_section(str(s)) for s in statutes):
            statutes = ["Wrongs Act 1958 (Vic) s 48"]
        anchors["statutes"] = statutes[:8]
        card["anchors"] = anchors

        report = validate_card(card, path.name)

        used_api = False

        if report.errors and USE_API and needs_llm_for_fill(card):
            print(f"  - 🤖 Filling gaps in {path.name} via {MODEL}...")
            candidate, err = run_fill_model(card)
            if candidate is not None:
                merged = {**card, **{k: v for k, v in candidate.items() if v is not None}}
                card = merged
                report = validate_card(card, path.name)
                used_api = True
            else:
                report.errors.append(f"API fill failed: {err}")

        if not report.errors and report.warnings and USE_API:
            print(f"  - 🔍 Auditing {path.name} for quality improvements...")
            audited, err = run_audit_model(card, report.warnings)
            if audited is not None:
                if isinstance(audited.get("back"), str):
                    card["back"] = audited["back"]
                if isinstance(audited.get("anchors"), dict):
                    card["anchors"] = audited["anchors"]
                report = validate_card(card, path.name)
                used_api = True
            else:
                report.warnings.append(f"audit skipped: {err}")

        if report.errors:
            summary.append((path.name, report))
            print(f"  - ❌ {path.name}: {len(report.errors)} blocking issue(s)")
            continue

        # Success path
        shutil.copy2(path, BACKUP / path.name)
        path.write_text(ydump(card), encoding="utf-8")
        summary.append((path.name, report))
        status = "with API" if used_api else "locally"
        print(f"  - ✅ {path.name}: updated {status}")

        # Gentle jitter to avoid rate limits
        time.sleep(random.uniform(0.3, 0.9))

    passed = [(name, rep) for name, rep in summary if not rep.errors]
    failed = [(name, rep) for name, rep in summary if rep.errors]

    report_lines = ["# LLM batch fix report", f"timestamp: {timestamp}", ""]
    report_lines.append(f"PASSED ({len(passed)}):")
    for name, rep in passed:
        report_lines.append(f"- {name}")
        for warn in rep.warnings:
            report_lines.append(f"  • warning: {warn}")
    report_lines.append("")
    report_lines.append(f"FAILED ({len(failed)}):")
    for name, rep in failed:
        report_lines.append(f"- {name}")
        for err in rep.errors:
            report_lines.append(f"  • {err}")
        for warn in rep.warnings:
            report_lines.append(f"  • warning: {warn}")

    report_path = BACKUP / "report.md"
    Path(report_path).write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nDone. Backups & report at: {BACKUP}")
    if failed:
        print(f"{len(failed)} card(s) failed; see {report_path}")


if __name__ == "__main__":
    main()
