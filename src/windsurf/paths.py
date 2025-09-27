from __future__ import annotations
from pathlib import Path

# Repo/pipeline roots
REPO_ROOT   = Path(__file__).resolve().parents[2]
SRC_DIR     = REPO_ROOT / "src"
PKG_ROOT    = SRC_DIR / "windsurf"
JD_ROOT     = REPO_ROOT / "src" / "jd"
REPORTS_DIR = REPO_ROOT / "reports"

# Domain-specific roots (adjust to taste)
JD_ROOT = REPO_ROOT / "jd"
JD_CARDS_DIR = JD_ROOT / "LAWS50025 - Torts"


def ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Back-compat aliases
SRC_ROOT    = SRC_DIR
POLICY_PATH = REPO_ROOT / "src" / "jd" / "policy" / "cards_policy.yml"