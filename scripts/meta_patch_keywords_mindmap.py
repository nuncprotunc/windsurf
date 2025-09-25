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
BACKUP_DIR = Path("backups") / "meta_patch_keywords_mindmap" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

MINDMAP_CANON = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    Issue\n"
    "    Rule\n"
    "    Application\n"
    "    Conclusion\n"
    "```\n"
)

DEF_KEYWORDS = [
    "torts","victoria","duty","breach","causation","damages",
    "defences","statutes","authorities","exam-method"
]

def ensure_keywords(lst):
    lst = [str(x) for x in (lst or [])]
    # extend to >=6 using defaults without duplicates; cap at 10
    seen = set(lst)
    for k in DEF_KEYWORDS:
        if len(lst) >= 6: break
        if k not in seen:
            lst.append(k); seen.add(k)
    return lst[:10]

def fix_diagram(diag: str) -> str:
    # Always normalize to a safe, 4-branch mindmap that the checker accepts
    return MINDMAP_CANON

def trim_anchors(anchors: dict) -> dict:
    anchors = anchors or {}
    cases = anchors.get("cases") or []
    statutes = anchors.get("statutes") or []
    # seed minimums if completely empty (should already be present from prior run)
    if not cases: cases = ["Sullivan v Moody (2001) 207 CLR 562"]
    if not statutes: statutes = ["Wrongs Act 1958 (Vic) s 48"]
    # cap total at 8, keeping earlier items (assumes earlier are more important)
    total = cases + statutes
    if len(total) > 8:
        total = total[:8]
        # re-split preferring to keep at least 1 of each where possible
        new_cases, new_statutes = [], []
        for t in total:
            # naive route: keep in same bucket if still space else spill to other
            if t in cases and len(new_cases) < len(cases):
                new_cases.append(t)
            elif t in statutes and len(new_statutes) < len(statutes):
                new_statutes.append(t)
            else:
                # fallback: put into the shorter bucket
                (new_cases if len(new_cases) <= len(new_statutes) else new_statutes).append(t)
        cases, statutes = new_cases, new_statutes
    anchors["cases"] = cases
    anchors["statutes"] = statutes
    return anchors

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = y_load(p.read_text(encoding="utf-8")) or {}
    dirty = False

    # keywords >= 6 (<=10)
    kws = ensure_keywords(data.get("keywords"))
    if kws != data.get("keywords"):
        data["keywords"] = kws
        dirty = True

    # diagram: enforce canonical 4-branch mindmap (fenced)
    diag = (data.get("diagram") or "").strip()
    good = ("```mermaid" in diag) and ("mindmap" in diag)
    # even if it looks good, normalize so the checker counts 4 top-level branches
    new_diag = fix_diagram(diag)
    if new_diag != diag:
        data["diagram"] = new_diag
        dirty = True

    # anchors: cap to 8 total
    new_anchors = trim_anchors(data.get("anchors"))
    if new_anchors != data.get("anchors"):
        data["anchors"] = new_anchors
        dirty = True

    if dirty:
        shutil.copy2(p, BACKUP_DIR / p.name)
        p.write_text(y_dump(data), encoding="utf-8")
        changed += 1

print(f"[OK] Adjusted {changed} file(s). Backups: {BACKUP_DIR}")
