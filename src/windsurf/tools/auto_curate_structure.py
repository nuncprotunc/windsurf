# ruff: noqa
from __future__ import annotations
import os, json, re, argparse, traceback
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from openai import OpenAI

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parents[3] if (
    Path(__file__).parts[-3:] == ("windsurf", "tools", "auto_curate_structure.py")
) else Path.cwd()

CARDS_DIR = ROOT / "src" / "jd" / "cards_yaml"
REPORTS_DIR = ROOT / "reports"; REPORTS_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR = REPORTS_DIR / "auto_curate"; OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Config ----------
MODEL = os.environ.get("WINDSURF_GRADE_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.environ.get("WINDSURF_MAX_OUTPUT_TOKENS", "2000"))

ALLOWED_CHILD_VECTORS = [
    [1,3,3,2,3],  # sums 12
    [2,2,2,1,5],  # sums 12
    [2,3,3,3,1],  # sums 12
]

# ---------- Prompts ----------
SYSTEM_PROMPT = """SYSTEM / STRUCTURAL CURATOR — Victorian Torts Cards (deterministic, no invention)

You optimise ONE JD Torts YAML card. Read it fully. Do NOT invent new authorities/tests/sections not present in the card. Prefer Vic/HCA anchors already present.

DELIVER:
- a Mermaid mindmap with exactly 5 first-level branches and ≤12 CHILD nodes total (children across all 5 branches; exclude the 5 branch labels and the root), and
- exactly four crisp, non-overlapping tripwires.

PRIORITIES (order):
1) Preserve doctrinal coverage (operative Victorian statutes, decisive tests, HCA/Vic anchors) by compressing wording only.
2) Fit the child-node budget via summarising/clustering (umbrella labels; collapse synonyms; drop examples unless essential).
3) Each tripwire targets a distinct, common exam error (no synonyms/near-dupes).
4) Prefer HCA/Vic; mark UK/PC as “(persuasive)” inline.
5) If trade-offs are needed: keep anchors/statutes; compress illustrations.

STYLE / GUARDRAILS:
- Australian legal shorthand, e.g., “s 48 Wrongs Act 1958 (Vic)” or “s 48/51 WA (Vic)”, “HCA”.
- If the YAML lacks an anchor/test you’d normally want, DO NOT add it; instead flag under coverage.risks.
- Title ≤ 4 words and must match the card’s topic.
- JSON ONLY. No prose outside JSON. Escape newlines as \\n.

VALIDATION RULES:
- top_level_branches must equal 5.
- child_vector = number of CHILD nodes under each of the 5 branches (exclude the branch labels).
- sum(child_vector) must be ≤ 12 (prefer 12 when possible).
- total_nodes = 1 (root) + 5 (branch labels) + sum(child_vector) and must be ≤ 18.
- tripwires_new must have exactly 4 items.

ON FAILURE:
{"error":"validation_failed","reason":"<why>","observed":{"branches":<int>,"children":<int>,"total_nodes":<int>,"tripwires":<int>}}

RETURN EXACTLY this JSON schema on success:
{
  "tripwires_new": ["<t1>","<t2>","<t3>","<t4>"],
  "tripwires_rationale": ["<why t1>","<why t2>","<why t3>","<why t4>"],
  "diagram_new_mermaid": "```mermaid\\nmindmap\\n  root((<short title>))\\n  A. Issue\\n    - ...\\n  B. Rule\\n    - ...\\n  C. Application\\n    - ...\\n  D. Limits/Statutes\\n    - s 48 Wrongs Act (Vic)\\n  E. Authorities\\n    - <HCA/Vic>\\n```",
  "diagram_meta": {
    "top_level_branches": 5,
    "total_nodes": <int>,
    "child_vector": [<int,int,int,int,int>]
  },
  "coverage": {
    "kept_keywords": ["<anchors/statutes kept or summarised>"],
    "omitted_low_yield": ["<what was cut + why>"],
    "risks": ["<coverage risks from compression or missing anchors in YAML>"]
  },
  "patch": {
    "tripwires_yaml": "tripwires:\\n- ...\\n- ...\\n- ...\\n- ...\\n",
    "diagram_yaml_block": "diagram: |\\n  ```mermaid\\n  mindmap\\n    root((<short title>))\\n    A. Issue\\n      - ...\\n    B. Rule\\n      - ...\\n    C. Application\\n      - ...\\n    D. Limits/Statutes\\n      - s 48 Wrongs Act (Vic)\\n    E. Authorities\\n      - <HCA/Vic>\\n  ```\\n"
  },
  "confidence": "high|medium|low"
}
"""

REPAIR_PROMPT_TEMPLATE = """STRICT REPAIR (no invention).

You previously produced a Mermaid mindmap and meta. The diagram text currently has child counts {cur_vec} (sum={cur_sum}).
To comply with policy, adjust ONLY the child bullets so the CHILD vector becomes EXACTLY {target_vec} (sum=12), preserving content from the card and your prior diagram (merge/umbrella if you need to reduce; add missing high-yield items if you need to increase). Do NOT change branch labels or root title.

Return the SAME JSON schema as before (tripwires_new, tripwires_rationale, diagram_new_mermaid, diagram_meta, coverage, patch, confidence). Keep tripwires unchanged unless obviously duplicative.

Card file: {card_path}

FULL YAML (verbatim):
<<<CARD>>>
{card_text}
<<<END CARD>>>

PREVIOUS JSON:
<<<PREV>>>
{prev_json}
<<<END PREV>>>
"""

USER_TEMPLATE = """Card file: {card_path}

FULL YAML (verbatim):
<<<CARD>>>
{card_text}
<<<END CARD>>>
"""

# ---------- Helpers ----------
def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")

def _indent_block(block: str, spaces: int = 2) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in block.splitlines())

TRIPWIRES_RE = re.compile(r'(?ms)^\s*tripwires:\s*\n(?:\s*-\s.*\n)+')
DIAGRAM_RE   = re.compile(r'(?ms)^\s*diagram:\s*\|[-+]?\s*\n(?:[ \t].*\n)*')

def apply_patch(original: str, trip_yaml: str, diagram_yaml: str) -> str:
    new_text = original
    if not trip_yaml.endswith("\n"): trip_yaml += "\n"
    if not diagram_yaml.endswith("\n"): diagram_yaml += "\n"

    new_text = TRIPWIRES_RE.sub(trip_yaml, new_text, count=1) if TRIPWIRES_RE.search(new_text) else (
        (new_text + ("\n" if not new_text.endswith("\n") else "") + "\n" + trip_yaml)
    )
    new_text = DIAGRAM_RE.sub(diagram_yaml, new_text, count=1) if DIAGRAM_RE.search(new_text) else (
        (new_text + ("\n" if not new_text.endswith("\n") else "") + "\n" + diagram_yaml)
    )
    return new_text

def summarise_delta(before: str, after: str) -> Dict[str, Any]:
    b, a = before.splitlines(), after.splitlines()
    added   = sum(1 for ln in a if ln not in b)
    removed = sum(1 for ln in b if ln not in a)
    return {"lines_added": added, "lines_removed": removed}

_CTRL = re.compile(r'[\u0000-\u0008\u000B-\u000C\u000E-\u001F\u007F\u0080-\u009F]')

def _sanitize_mermaid_text(diag_block: str) -> str:
    """
    - Ensure fenced ```mermaid
    - Remove control chars
    - Ensure `mindmap` header is present (paired with _force_mindmap_line later)
    - Remove leading '- ' on children (without touching inline hyphens)
    - Normalise Wrongs Act shorthand to 'WA (Vic)'
    - Tag persuasive authorities inline
    - Force root title arrow '→' for the Protected-interests card
    """
    text = diag_block or ""

    # Ensure fenced block
    if not text.strip().startswith("```"):
        text = "```mermaid\n" + text.strip() + "\n```"

    # Extract inner (tolerate leading/trailing whitespace)
    m = re.search(r"^```mermaid\s*(.*?)\s*```$", text, flags=re.S | re.I)
    inner = m.group(1) if m else text

    # Strip control chars (kills that stray 0x7F)
    inner = _CTRL.sub("", inner)

    # Ensure mindmap header exists and is on its own line (final pass done by _force_mindmap_line)
    if "mindmap" not in inner:
        inner = "mindmap\n" + inner
    inner = re.sub(r'(?im)^\s*mindmap\s*$', 'mindmap', inner, count=1)

    # Remove leading "- " bullets from child lines ONLY (don’t touch inline hyphens)
    fixed_lines = []
    for ln in inner.splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("- "):
            indent_len = len(ln) - len(stripped)
            prefix = ln[:indent_len]
            fixed_lines.append(prefix + stripped[2:])  # drop the bullet, keep indentation
        else:
            fixed_lines.append(ln)
    inner = "\n".join(fixed_lines)

    # Normalise statute shorthand inside diagrams
    inner = inner.replace("Wrongs Act 1958 (Vic)", "WA (Vic)")
    inner = inner.replace("Wrongs Act (Vic)", "WA (Vic)")

    # Tag persuasive authorities if mentioned (idempotent)
    inner = re.sub(r"(Entick(?:\s+v\s+Carrington)?)\b(?!\s*\(persuasive\))", r"\1 (persuasive)", inner)
    inner = re.sub(r"(Wagon Mound)\b(?!\s*\(persuasive\))", r"\1 (persuasive)", inner)

    # Force root title arrow if this is the protected-interests card
    inner = re.sub(
        r'^(?P<indent>\s*)root\(\((?P<title>.*?Protected interests.*?roadmap.*?)\)\)',
        lambda m: f"{m.group('indent')}root((Protected interests \u2192 roadmap))",
        inner,
        flags=re.M
    )

    # Rebuild fenced block
    return "```mermaid\n" + inner.strip() + "\n```"

BRANCH_RE = re.compile(r'^\s*([A-E])\.\s')

def _parse_mermaid_child_vector(diag_text: str) -> Tuple[List[int], int, int]:
    """
    Count children under A..E:
      - A branch line matches '^[A-E]\. '
      - Any non-empty line with indent > branch indent (until next branch) counts as ONE child
      - bullets are optional (no dependence on '- ')
    """
    lines = diag_text.splitlines()
    # strip code fence and leading 'mindmap' if present
    core = []
    for ln in lines:
        if ln.strip().startswith("```"):
            continue
        if ln.strip() == "mermaid":
            continue
        core.append(ln)
    text = "\n".join(core)
    # find start of mindmap section
    if "mindmap" in text:
        text = text.split("mindmap", 1)[1]
    vec = [0,0,0,0,0]
    branches = 0
    cur = -1
    cur_indent = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = BRANCH_RE.match(raw)
        if m:
            cur = ord(m.group(1)) - ord('A')
            branches += 1
            cur_indent = len(raw) - len(raw.lstrip(" "))
            continue
        # child if indented more than branch, not a new branch, not 'root(('
        if cur != -1:
            indent = len(raw) - len(raw.lstrip(" "))
            if indent > cur_indent and not BRANCH_RE.match(raw) and "root((" not in raw:
                # avoid counting grandkids twice: count each line as a child (Mermaid node per line)
                vec[cur] += 1
    return vec, sum(vec), branches

def _choose_target_vector(cur_vec: List[int]) -> List[int]:
    best = None; best_score = (10**9, 10**9)
    for cand in ALLOWED_CHILD_VECTORS:
        reductions = sum(max(0, cur_vec[i] - cand[i]) for i in range(5))
        l1 = sum(abs(cur_vec[i] - cand[i]) for i in range(5))
        score = (reductions, l1)
        if score < best_score:
            best_score, best = score, cand
    return best or ALLOWED_CHILD_VECTORS[0]

def _call_openai_json(client: OpenAI, model: str, sys_prompt: str, user_prompt: str) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user",   "content": user_prompt}],
            max_tokens=MAX_TOKENS,
        )
        content = resp.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception:
        print("[fatal] model call failed:\n" + traceback.format_exc())
        raise

# ---------- Target discovery ----------
def load_targets(args) -> List[Path]:
    if args.only:
        p = Path(args.only)
        return [p if p.is_absolute() else (ROOT / p).resolve()]
    table = REPORTS_DIR / "model_eval_table.json"
    if args.all or not table.exists():
        return sorted(CARDS_DIR.glob("*.yml"))
    rows = json.loads(table.read_text(encoding="utf-8"))
    targets = []
    for r in rows:
        if (not r.get("tripwires_ok")) or (not r.get("diagram_ok")):
            targets.append(ROOT / r["card"])
    return sorted(set(targets))

def _force_mindmap_line(block: str) -> str:
    """
    Ensure 'mindmap' is on its own line inside the fenced mermaid block.
    Works whether the model returned proper newlines or everything jammed on one line.
    """
    # If it's already fenced, extract inner; otherwise treat whole string as inner
    m = re.search(r"^```mermaid\s*(.*)```$", block, flags=re.S | re.I)
    inner = m.group(1) if m else block

    # Put 'mindmap' on its own line at the start of the inner payload
    inner = re.sub(r'(?im)^\s*mindmap\s*', 'mindmap\n', inner, count=1)

    # Rebuild fenced block
    return "```mermaid\n" + inner.strip() + "\n```"

# ---------- Main ----------
def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-curate diagram + tripwires from full YAML.")
    ap.add_argument("--model", default=None, help="Override model name")
    ap.add_argument("--apply", action="store_true", help="Apply patches to YAML files (in-place).")
    ap.add_argument("--all", action="store_true", help="Run on all cards, not just failing ones.")
    ap.add_argument("--only", help="Run on a single YAML file (absolute or relative path)")
    args = ap.parse_args()

    client = OpenAI()
    model = args.model or MODEL

    targets = load_targets(args)
    if not targets:
        print("No targets found. Nothing to do.")
        return 0

    failures = 0
    for p in targets:
        rel = p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p
        print(f"[curate] {rel}")
        original = _read(p)

        # ---- First pass
        data = _call_openai_json(client, model, SYSTEM_PROMPT,
                                 USER_TEMPLATE.format(card_path=str(p), card_text=original))

        tw = data.get("tripwires_new", []) or []
        raw_block = (data.get("diagram_new_mermaid") or "").strip()
        if not raw_block:
            print("  [warn] model returned empty diagram.")
            continue
        diag_block = _sanitize_mermaid_text(raw_block)
        diag_block = _force_mindmap_line(diag_block)  # ensure 'mindmap' is on its own line

        # recompute meta from (sanitised) text
        vec_text, sum_text, branches_text = _parse_mermaid_child_vector(diag_block)

        # ---- If not exactly 12 children or not 5 branches, attempt one strict repair
        need_repair = (sum_text != 12) or (branches_text != 5)
        if need_repair:
            target_vec = _choose_target_vector(vec_text)
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(
                cur_vec=vec_text, cur_sum=sum_text, target_vec=target_vec,
                card_path=str(p), card_text=original,
                prev_json=json.dumps(data, indent=2),
            )
            data = _call_openai_json(client, model, SYSTEM_PROMPT, repair_prompt)
            tw = data.get("tripwires_new", []) or []
            raw_block = (data.get("diagram_new_mermaid") or "").strip()
            diag_block = _sanitize_mermaid_text(raw_block)
            diag_block = _force_mindmap_line(diag_block)  # ensure proper line break again
            vec_text, sum_text, branches_text = _parse_mermaid_child_vector(diag_block)

        # ---- Final validation (from text, not model meta)
        total_nodes_text = 1 + 5 + sum_text
        if len(tw) != 4:
            print("  [warn] need exactly 4 tripwires.")
        if branches_text != 5:
            print(f"  [warn] need 5 branches, found {branches_text}.")
        if sum_text != 12:
            print(f"  [warn] need exactly 12 child nodes, found {sum_text}.")
        if total_nodes_text > 18:
            print(f"  [warn] total nodes {total_nodes_text} > 18.")

        # ---- Build YAML pieces
        trip_yaml = "tripwires:\n" + "".join(f"- {t}\n" for t in tw)
        diagram_yaml = "diagram: |\n" + _indent_block(diag_block, 2) + "\n"

        # ---- Save suggestions
        base = p.stem
        (OUT_DIR / f"{base}.suggestion.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        md = []
        md.append(f"# {p.name} — Auto-curated structure\n")
        md.append("## Tripwires (exactly four)\n")
        for i, t in enumerate(tw, 1):
            md.append(f"{i}. {t}")
        if data.get("tripwires_rationale"):
            md.append("\n### Rationale\n- " + "\n- ".join(data["tripwires_rationale"]))
        md.append("\n## Diagram (Mermaid • 5 branches • exactly 12 children • ≤18 total nodes)\n")
        md.append(diag_block)
        md.append("\n### Meta (recomputed from diagram text)\n\n")
        md.append(json.dumps({
            "top_level_branches_text": branches_text,
            "child_vector_text": vec_text,
            "children_sum_text": sum_text,
            "total_nodes_text": total_nodes_text
        }, indent=2))
        md.append("\n### Coverage notes\n")
        md.append(json.dumps(data.get("coverage", {}), indent=2))
        (OUT_DIR / f"{base}.suggestion.md").write_text("\n".join(md) + "\n", encoding="utf-8")

        # ---- Apply if compliant
        if (args.apply and len(tw) == 4 and branches_text == 5 and sum_text == 12 and total_nodes_text <= 18):
            patched = apply_patch(original, trip_yaml, diagram_yaml)
            delta = summarise_delta(original, patched)
            (OUT_DIR / f"{base}.patched.preview.yml").write_text(patched, encoding="utf-8")
            Path(p).write_text(patched, encoding="utf-8")
            print(f"  [applied] tripwires+diagram patched ({delta})")
        else:
            print("  [saved] suggestion files; validator not satisfied (need 5 branches, =12 children, ≤18 total).")

    if failures:
        print(f"[done] Completed with {failures} model error(s).")
        return 1
    print("[done] Suggestions generated.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
