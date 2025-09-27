# D:\Code\windsurf\src\windsurf\tools\parse_wrongs_act.py
import re, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # ...\src
act_path = ROOT / "jd" / "statutes" / "wa1958111.txt"
text = act_path.read_text(encoding="utf-8")

# 0) Normalise whitespace / weird spaces
text = (text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00A0", " ")  # non-breaking space
        )

# Build a single regex that captures each target block from its heading
# until the next target heading (or EOF). We support: s 48 / s. 48 / section 48,
# and Part/Pt XI/VBA with any spacing/case.
target_headings = (
    r"(?:^|\n)"                                     # line start
    r"(?P<head>"
      r"(?:(?:s(?:ection)?\.?\s*)(?:48|49|51)\b)"   # s 48 / s. 48 / section 48
      r"|"
      r"(?:(?:Part|Pt)\s+(?:XI|VBA)\b)"             # Part XI / Pt XI / Part VBA / Pt VBA
    r")"
)

# Next-head marker for lookahead
next_head = (
    r"(?=(?:^|\n)(?:"
    r"(?:s(?:ection)?\.?\s*(?:48|49|51)\b)"
    r"|"
    r"(?:(?:Part|Pt)\s+(?:XI|VBA)\b)"
    r")|\Z)"
)

pattern = re.compile(target_headings + r".*?" + next_head,
                     flags=re.IGNORECASE | re.DOTALL)

sections = {}
for m in pattern.finditer(text):
    block = m.group(0).lstrip("\n")
    # Title = first line (trim extra spaces)
    title = block.splitlines()[0].strip()
    # Normalise title a bit for consistent keys
    norm = (title
            .replace("Section", "s")
            .replace("section", "s")
            .replace("S.", "s.")
            .replace("Part", "Pt")
            ).strip()
    sections[norm] = block.strip()

out_path = Path(__file__).resolve().parent / "wrongs_sections.json"
out_path.write_text(json.dumps(sections, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"Matched sections: {list(sections.keys())}")
print(f"Wrote {len(sections)} sections to {out_path}")
