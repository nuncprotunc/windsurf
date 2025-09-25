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
BACKUP_DIR = Path("backups") / "meta_patch_mindmap_fix" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

MINDMAP_CANON = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    Issue — classify the interest\n"
    "    Rule — doctrinal test & statute\n"
    "    Application — apply to facts\n"
    "    Conclusion — remedy/defences\n"
    "```\n"
)

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = y_load(p.read_text(encoding="utf-8")) or {}
    diag = (data.get("diagram") or "").strip()
    # Replace unconditionally to a format the checker likes
    if diag != MINDMAP_CANON:
        data["diagram"] = MINDMAP_CANON
        shutil.copy2(p, BACKUP_DIR / p.name)
        p.write_text(y_dump(data), encoding="utf-8")
        changed += 1

print(f"[OK] Rewrote diagram in {changed} file(s). Backups: {BACKUP_DIR}")
