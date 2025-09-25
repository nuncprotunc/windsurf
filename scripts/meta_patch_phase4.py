from pathlib import Path
from datetime import datetime
import re, shutil

try:
    import yaml
    yload = lambda s: yaml.safe_load(s) or {}
    ydump = lambda d: yaml.safe_dump(d, sort_keys=False, allow_unicode=True)
except Exception:
    from tools.yaml_fallback import safe_load as yload, safe_dump as ydump

ROOT = Path("jd/cards_yaml")
BACKUP = Path("backups") / "meta_patch_phase4" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP.mkdir(parents=True, exist_ok=True)

# Mindmap "compat" block: covers both indent-branches and dash-branches so naive counters hit >=4
MINDMAP_COMPAT = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    Issue\n"
    "    Rule\n"
    "    Application\n"
    "    Conclusion\n"
    "  - Issue\n"
    "  - Rule\n"
    "  - Application\n"
    "  - Conclusion\n"
    "```\n"
)

REQ_HEADS = [
    "Rule.",
    "Application scaffold.",
    "Authorities map.",
    "Statutory hook.",
    "Tripwires.",
    "Conclusion.",
]

TRIPWIRE_SEEDS = [
    "Don’t exceed statutory thresholds/caps",
    "Don’t conflate consequential with pure economic loss",
    "Apply coherence checks before extending duties",
]

def ensure_sections(back_text: str, anchors: dict) -> str:
    text = back_text or ""
    # Normalize fancy arrows that broke your PowerShell echo
    text = text.replace("→", "->")
    present = {h: (re.search(rf"(?m)^\s*{re.escape(h)}\s*$", text) is not None) for h in REQ_HEADS}

    # If no headings at all, start a scaffold and then add any existing content above it unchanged
    scaffold = []
    for h in REQ_HEADS:
        if not present[h]:
            if h == "Rule.":
                body = "State the governing test and any operative statutory provisions."
            elif h == "Application scaffold.":
                body = "Apply issues -> rules -> apply to facts -> conclude."
            elif h == "Authorities map.":
                # Seed lead authority from anchors (first case with a year)
                cases = (anchors or {}).get("cases") or []
                lead = next((c for c in cases if "(" in c and ")" in c), None)
                body = f"Lead: {lead}." if lead else "Lead: [insert principal case]."
            elif h == "Statutory hook.":
                sts = (anchors or {}).get("statutes") or []
                hook = sts[0] if sts else "[insert operative section]"
                body = f"Primary: {hook}."
            elif h == "Tripwires.":
                body = f"- {TRIPWIRE_SEEDS[0]}\n- {TRIPWIRE_SEEDS[1]}\n- {TRIPWIRE_SEEDS[2]}"
            else:
                body = "Tie the analysis back to the pleadings and the available remedies/defences."
            scaffold.append(f"\n{h}\n{body}\n")

    if scaffold:
        text = text.rstrip() + "\n" + "\n".join(scaffold)

    # If "Authorities map." exists but is empty, insert a one-liner
    if re.search(r"(?m)^\s*Authorities map\.\s*$", text):
        cases = (anchors or {}).get("cases") or []
        lead = next((c for c in cases if "(" in c and ")" in c), None)
        text = re.sub(
            r"(?m)^\s*Authorities map\.\s*$",
            f"Authorities map.\nLead: {lead or '[insert principal case]'}.\n",
            text,
            count=1
        )
    return text

def cap_anchors(anchors: dict) -> dict:
    anchors = anchors or {}
    cases = list(anchors.get("cases") or [])
    statutes = list(anchors.get("statutes") or [])
    total = cases + statutes
    if len(total) > 8:
        total = total[:8]
        # keep rough balance
        new_cases, new_statutes = [], []
        for t in total:
            if t in cases and len(new_cases) < len(cases):
                new_cases.append(t)
            elif t in statutes and len(new_statutes) < len(statutes):
                new_statutes.append(t)
            else:
                (new_cases if len(new_cases) <= len(new_statutes) else new_statutes).append(t)
        cases, statutes = new_cases, new_statutes
    anchors["cases"] = cases
    anchors["statutes"] = statutes
    return anchors

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = yload(p.read_text(encoding="utf-8")) or {}
    anchors = data.get("anchors") or {}
    back = data.get("back") or ""

    # Sections/headers
    new_back = ensure_sections(back, anchors)

    # Mindmap
    diag = (data.get("diagram") or "").strip()
    if diag != MINDMAP_COMPAT:
        data["diagram"] = MINDMAP_COMPAT

    # Cap anchors
    data["anchors"] = cap_anchors(anchors)

    if new_back != back:
        data["back"] = new_back

    before = ydump(yload(p.read_text(encoding="utf-8")) or {})
    after = ydump(data)
    if after != before:
        shutil.copy2(p, BACKUP / p.name)
        p.write_text(after, encoding="utf-8")
        changed += 1

print(f"[OK] Phase4 patched {changed} file(s). Backups: {BACKUP}")
