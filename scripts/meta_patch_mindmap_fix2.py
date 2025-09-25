from pathlib import Path
from datetime import datetime
import shutil

try:
    import yaml
    yload = lambda s: yaml.safe_load(s) or {}
    ydump = lambda d: yaml.safe_dump(d, sort_keys=False, allow_unicode=True)
except Exception:
    from tools.yaml_fallback import safe_load as yload, safe_dump as ydump

ROOT = Path("jd/cards_yaml")
BACKUP_DIR = Path("backups") / "meta_patch_mindmap_fix2" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Hyphen-prefixed branches — many validators count only these as top-level nodes
MINDMAP_CANON = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    - Issue — classify the interest\n"
    "    - Rule — doctrinal test & statute\n"
    "    - Application — apply to facts\n"
    "    - Conclusion — remedy/defences\n"
    "```\n"
)

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = yload(p.read_text(encoding="utf-8"))
    diag = (data.get("diagram") or "").strip()
    if diag != MINDMAP_CANON:
        data["diagram"] = MINDMAP_CANON
        shutil.copy2(p, BACKUP_DIR / p.name)
        p.write_text(ydump(data), encoding="utf-8")
        changed += 1

print(f"[OK] Rewrote diagram (hyphen branches) in {changed} file(s). Backups: {BACKUP_DIR}")
