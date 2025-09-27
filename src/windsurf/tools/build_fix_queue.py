# ruff: noqa
import json, sys
from pathlib import Path

IN_JSON  = Path("reports/model_eval_table.json")
OUT_MD   = Path("reports/fix_queue.md")
OUT_CSV  = Path("reports/fix_queue.csv")

if not IN_JSON.exists():
    sys.exit("Missing reports/model_eval_table.json — run parse_eval_table.py first.")

rows = json.loads(IN_JSON.read_text(encoding="utf-8"))

# Partition problem cards
bad_trip  = [r for r in rows if not r.get("tripwires_ok", False)]
bad_diag  = [r for r in rows if not r.get("diagram_ok",  False)]

def _tick(b): return "✅" if b else "❌"

# --- Write Markdown checklist
md = []
md.append("# Card Fix Queue\n")
md.append("This file is auto-generated from reports/model_eval_table.json.\n")
md.append("## Summary\n")
md.append(f"- Total cards: **{len(rows)}**")
md.append(f"- Tripwires OK: **{len(rows)-len(bad_trip)} / {len(rows)}**")
md.append(f"- Diagram OK: **{len(rows)-len(bad_diag)} / {len(rows)}**\n")

md.append("## Priority A — Tripwires not OK (must be exactly four, non-duplicative)\n")
if bad_trip:
    md.append("| Card | Score | Tripwires | Diagram | Statutes found | Anchors found |")
    md.append("| --- | ---: | :---: | :---: | --- | --- |")
    for r in bad_trip:
        md.append(f"| `{r['card']}` | {r.get('score') if r.get('score') is not None else '—'} | {_tick(r['tripwires_ok'])} | {_tick(r['diagram_ok'])} | {r.get('statutes_found','')} | {r.get('anchors_found','')} |")
else:
    md.append("_None — nice one!_\n")

md.append("\n## Priority B — Diagram not OK (must be Mermaid mindmap: 5 top-level branches, ≤12 nodes)\n")
if bad_diag:
    md.append("| Card | Score | Tripwires | Diagram | Statutes found | Anchors found |")
    md.append("| --- | ---: | :---: | :---: | --- | --- |")
    for r in bad_diag:
        md.append(f"| `{r['card']}` | {r.get('score') if r.get('score') is not None else '—'} | {_tick(r['tripwires_ok'])} | {_tick(r['diagram_ok'])} | {r.get('statutes_found','')} | {r.get('anchors_found','')} |")
else:
    md.append("_None — love your work!_\n")

md.append("\n## Definition of Done (per card)\n")
md.append("- **Tripwires**: exactly four, crisp, exam-actionable, non-duplicative.\n"
          "- **Diagram**: Mermaid mindmap with **5** top-level branches and **≤12** total nodes.\n"
          "- **Statutes_present**: whatever Wrongs Act bits you actually reference (e.g., `s 48`, `s 49`, `s 51`, `s 52`, `Pt XI`, `Pt VBA`). Not every card needs all; this is an inventory, not a failure.\n"
          "- **Anchors_present**: key authorities present for that topic (e.g., `Rogers`, `Chapman`, `Perre/Stavar/Brookfield`, `Sullivan`).\n")

OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

# --- CSV for spreadsheet folk
def csv_escape(s: str) -> str:
    s = (s or "").replace('"', '""')
    return f'"{s}"'

csv_lines = ["card,score,tripwires_ok,diagram_ok,statutes_found,anchors_found"]
for r in rows:
    csv_lines.append(",".join([
        csv_escape(r["card"]),
        str(r.get("score") if r.get("score") is not None else ""),
        "1" if r.get("tripwires_ok") else "0",
        "1" if r.get("diagram_ok") else "0",
        csv_escape(r.get("statutes_found","")),
        csv_escape(r.get("anchors_found","")),
    ]))
OUT_CSV.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

# Fail CI if anything is red
fail = bool(bad_trip or bad_diag)
print(f"Wrote {OUT_MD} and {OUT_CSV}")
if fail:
    print(f"❌ Outstanding: {len(bad_trip)} tripwires fixes, {len(bad_diag)} diagram fixes")
    sys.exit(1)
else:
    print("✅ All cards meet tripwires/diagram requirements.")
