# ruff: noqa
import re, json, sys
from pathlib import Path

REPORT_MD = Path("reports/model_eval.md")
OUT_JSON  = Path("reports/model_eval_table.json")

if not REPORT_MD.exists():
    sys.exit("No file at reports/model_eval.md")

md = REPORT_MD.read_text(encoding="utf-8")

# Grab the table body starting after the header row
m = re.search(r"^\| Card \|.*\n(?:\|[-:\s]+\|.*\n)(?P<body>(?:\|.*\n)+)", md, re.M)
if not m:
    sys.exit("No table found in reports/model_eval.md")

rows = []
body = m.group("body").splitlines()

def _to_float_or_none(s: str):
    s = s.strip()
    # accept plain ints/floats; ignore header junk like '---:' and em-dashes
    if s in {"", "—", "–"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _norm_statutes(s: str) -> str:
    # Normalise common typos/variants -> Pt VBA
    s = s.replace("Pt VBAAA", "Pt VBA").replace("Pt VBAA", "Pt VBA").replace("Pt VB", "Pt VBA")
    # Compact spacing
    return re.sub(r"\s+", " ", s).strip(" .;,")

def _extract(field: str, notes: str) -> str:
    m = re.search(rf"{re.escape(field)}:\s*([^·]+)", notes)
    return (m.group(1).strip() if m else "")

for line in body:
    line_stripped = line.strip()
    # Only process real data rows; your card rows start with a backticked path
    if not line_stripped.startswith("| `"):
        continue

    parts = [p.strip() for p in line_stripped.split("|")[1:-1]]
    if len(parts) != 4:
        continue

    card, score, passed, notes = parts

    score_val = _to_float_or_none(score)
    pass_flag = (passed == "✅")

    trip_ok = "tripwires_ok ✅" in notes
    diag_ok = "diagram_ok ✅" in notes

    statutes_found = _norm_statutes(_extract("statutes", notes))
    anchors_found  = _extract("anchors", notes)

    rows.append({
        "card": card.strip("` "),
        "score": score_val,
        "pass": pass_flag,
        "tripwires_ok": trip_ok,
        "diagram_ok": diag_ok,
        "statutes_found": statutes_found,
        "anchors_found": anchors_found,
        "notes": notes,
    })

OUT_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"Wrote {OUT_JSON} ({len(rows)} rows)")
