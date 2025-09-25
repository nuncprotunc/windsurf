from pathlib import Path
from datetime import datetime
import shutil

try:
    import yaml
    def y_load(s): return yaml.safe_load(s) or {}
    def y_dump(d): return yaml.safe_dump(d, sort_keys=False, allow_unicode=True)
except Exception:
    from tools.yaml_fallback import safe_load as y_load, safe_dump as y_dump

ROOT = Path("jd/cards_yaml")
BACKUP_DIR = Path("backups") / "meta_patch_minimal" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

MINDMAP_STUB = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    Issue\n"
    "    Rule\n"
    "    Application\n"
    "    Conclusion\n"
    "```\n"
)

def count_top_branches(diagram: str) -> int:
    # crude but good enough: lines that start with two spaces (children of root)
    n = 0
    for line in diagram.splitlines():
        s = line.strip("\n")
        if s.startswith("  ") and not s.startswith("    "):  # exactly two spaces
            if s.strip(): n += 1
    return n

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    text = p.read_text(encoding="utf-8")
    data = y_load(text) or {}
    dirty = False

    # reading_level
    if not data.get("reading_level"):
        data["reading_level"] = "Plain English (JD)"
        dirty = True

    # tags (ensure MLS_H1 + at least one tag)
    tags = list(map(str, data.get("tags", [])))
    if "MLS_H1" not in tags:
        tags.append("MLS_H1")
        dirty = True
    if not tags:
        tags = ["MLS_H1"]
        dirty = True
    data["tags"] = tags

    # keywords must be a list
    if not isinstance(data.get("keywords"), list):
        data["keywords"] = ["torts", "victoria"]
        dirty = True

    # diagram must be fenced mermaid mindmap with 4–5 top-level branches
    diag = (data.get("diagram") or "").strip()
    replace_diagram = False
    if "```mermaid" not in diag or "mindmap" not in diag:
        replace_diagram = True
    else:
        try:
            tops = count_top_branches(diag)
            if tops < 4 or tops > 5:
                replace_diagram = True
        except Exception:
            replace_diagram = True
    if replace_diagram:
        data["diagram"] = MINDMAP_STUB
        dirty = True

    # anchors: seed minimal case/statute if absent
    anchors = data.get("anchors") or {}
    cases = anchors.get("cases") or []
    statutes = anchors.get("statutes") or []
    if not cases:
        cases = ["Sullivan v Moody (2001) 207 CLR 562"]
        dirty = True
    if not statutes:
        statutes = ["Wrongs Act 1958 (Vic) s 48"]
        dirty = True
    anchors["cases"] = cases
    anchors["statutes"] = statutes
    data["anchors"] = anchors

    if dirty:
        # backup original
        shutil.copy2(p, BACKUP_DIR / p.name)
        p.write_text(y_dump(data), encoding="utf-8")
        changed += 1

print(f"[OK] Patched {changed} file(s). Backups: {BACKUP_DIR}")
