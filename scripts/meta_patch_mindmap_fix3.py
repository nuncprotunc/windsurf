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
BACKUP = Path("backups") / "meta_patch_mindmap_fix3" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP.mkdir(parents=True, exist_ok=True)

MINDMAP_MIN = (
    "```mermaid\n"
    "mindmap\n"
    "  root((Card overview))\n"
    "    Issue\n"
    "    Rule\n"
    "    Application\n"
    "    Conclusion\n"
    "```\n"
)

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = yload(p.read_text(encoding="utf-8"))
    if (data.get("diagram") or "").strip() != MINDMAP_MIN:
        data["diagram"] = MINDMAP_MIN
        shutil.copy2(p, BACKUP / p.name)
        p.write_text(ydump(data), encoding="utf-8")
        changed += 1

print(f"[OK] Set minimal mindmap in {changed} file(s). Backups: {BACKUP}")
