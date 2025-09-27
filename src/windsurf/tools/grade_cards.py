# ruff: noqa: E501
from __future__ import annotations
import json, os, sys, time, traceback, re, hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple

from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parents[3] if (
    Path(__file__).parts[-3:] == ("windsurf", "tools", "grade_cards.py")
) else Path.cwd()

CARDS_DIR = ROOT / "src" / "jd" / "cards_yaml"
CARDS_GLOB = CARDS_DIR / "*.yml"

REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Persisted meta so we can compute deltas between runs
META_PATH = REPORTS_DIR / "model_eval_meta.json"

STATUTES_DIR = ROOT / "src" / "jd" / "statutes"
WRONGS_ACT_FILE = STATUTES_DIR / "wa1958111.txt"
WRONGS_ACT_TEXT = WRONGS_ACT_FILE.read_text(encoding="utf-8") if WRONGS_ACT_FILE.exists() else ""

# ---------- Settings ----------
MODEL = os.environ.get("WINDSURF_GRADE_MODEL", "gpt-4o-mini")
PASS_THRESHOLD = float(os.environ.get("WINDSURF_PASS_THRESHOLD", "5.0"))
MAX_OUTPUT_TOKENS = int(os.environ.get("WINDSURF_MAX_OUTPUT_TOKENS", "2000"))
VERBOSE = os.environ.get("WINDSURF_VERBOSE", "1") == "1"

SYSTEM_PROMPT = """SYSTEM / REVIEW BRIEF — Victorian Torts: Information-Vet Only (v2a-aligned)
You are auditing a JD flashcard for Victorian torts. Be concise, source-aware, and explicit about uncertainty. Return the JSON schema below first, then 2–3 sentences of notes.

What to verify (strict Vic focus)
- Injury: Rogers v Whitaker; Chapman v Hearse correct.
- Property: trespass protects possession/directness; nuisance = unreasonableness; Wagon Mound (No 1) persuasive only.
- Pure economic loss: no general duty; salient features (Perre; Stavar; Brookfield) with coherence (Sullivan v Moody).
- Distinguish consequential vs pure economic loss.

Statutory references (Victoria)
- Wrongs Act: s 48 (breach), s 49 (no hindsight), s 51 (causation/scope), Pt XI (mental harm), Pt VBA (thresholds/caps) — confirm correct role.

Policy checks
- Tripwires: exactly four, crisp, exam-actionable, non-duplicative.
- Diagram: Mermaid mindmap; exactly 5 top-level branches; ≤12 total nodes; child vector in {[1,3,3,2,2],[2,2,2,1,4],[2,3,3,3,1]}. If can’t fit, must be “[DIAGRAM TOO LARGE]”.

Output (JSON first, then brief notes)
{
  "overall_score_10": <number>,
  "doctrinal_findings": [
    {"claim": "<quote or summary>", "status": "ok|wrong|uncertain", "reason": "<why>", "fix": "<minimal corrected wording>"}
  ],
  "statute_check": [
    {"statute": "Wrongs Act s 48", "status": "ok|misused|missing", "fix": "<if any>"},
    {"statute": "Wrongs Act s 49", "status": "ok|misused|missing", "fix": "<if any>"},
    {"statute": "Wrongs Act s 51", "status": "ok|misused|missing", "fix": "<if any>"},
    {"statute": "Wrongs Act Pt XI", "status": "ok|misused|missing", "fix": "<if any>"},
    {"statute": "Wrongs Act Pt VBA", "status": "ok|misused|missing", "fix": "<if any>"}
  ],
  "anchors_check": [
    {"authority": "Rogers v Whitaker 175 CLR 479", "status": "ok|weak|wrong", "reason": "<why>", "replacement": "<better anchor if needed>"},
    {"authority": "Wagon Mound (No 1) [1961] AC 388 (PC)", "status": "ok|weak|wrong", "reason": "<why>", "replacement": "<AUS alternative if needed>"}
  ],
  "tripwires": {
    "status": "ok|needs_fix",
    "current_count": <int>,
    "replacement": ["<t1>","<t2>","<t3>","<t4>"]
  },
  "diagram_check": {
    "status": "ok|needs_fix",
    "top_level_branches": <int>,
    "total_nodes": <int>,
    "child_vector": "<[...]>|unknown",
    "fix": "<minimal pruning or '[DIAGRAM TOO LARGE]'>"
  },
  "sequencing_irac": {
    "issues": ["<e.g., breach imported into duty>"],
    "fix": "<one-sentence sequencing correction>"
  },
  "redundancy_prune": [
    {"text": "<redundant sentence>", "reason": "<why>", "action": "delete|merge", "merge_target": "<if merge>"}
  ],
  "missing_high_yield": ["<gap 1>", "<gap 2>"],
  "high_yield_summary": "<one sentence on exam deployment>",
  "confidence": "high|medium|low"
}
Then: 2–3 sentence critique + 3 active-recall questions.
Rules: No hallucinated citations; minimal fixes; prefer HCA/Vic; mark UK/PC as persuasive.

CRITICAL: At the TOP LEVEL of the JSON object include "overall_score_10": a number between 0 and 10.
"""

# ---------- Helpers: IO ----------
def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def load_meta() -> Dict[str, Any]:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_meta(meta: Dict[str, Any]) -> None:
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")

# ---------- Model ----------
@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(4))
def call_model(client: OpenAI, card_text: str) -> str:
    statute_block = WRONGS_ACT_TEXT[:4000] if WRONGS_ACT_TEXT else ""
    user_content = f"""Please audit the following card.
Return ONE JSON object first, then notes.

Use this Wrongs Act text to verify statute references (trimmed if long):
<<<STATUTE>>>
{statute_block}
<<<END STATUTE>>>

Card:
<<<
{card_text}
>>>"""
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    return resp.choices[0].message.content or "{}"

def _coerce_score(obj: Dict[str, Any]) -> float | None:
    for path in [("overall_score_10",), ("audit","overall_score_10"), ("result","overall_score_10")]:
        cur = obj
        try:
            for k in path: cur = cur[k]
            if isinstance(cur, (int, float)): return float(cur)
            if isinstance(cur, str): return float(cur)
        except Exception:
            pass
    return None

# ---------- Checklist aggregation ----------
def _norm_statute_label(s: str) -> str:
    s2 = s.replace("Wrongs Act", "").replace("(Vic)", "").replace("Part", "Pt").strip()
    s2 = re.sub(r"\s+", " ", s2)
    # Canonicalise common variants
    s2 = s2.replace("Pt VB", "Pt VBA")  # treat VB/VBA together for your summary tick
    return s2

def _extract_statutes_present(card: Dict[str, Any]) -> List[str]:
    items = []
    for it in card.get("statute_check", []) or []:
        if (it.get("status") == "ok") and it.get("statute"):
            items.append(_norm_statute_label(str(it["statute"])))
    # Dedup, stable
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _extract_anchors_present(card: Dict[str, Any]) -> List[str]:
    items = []
    for it in card.get("anchors_check", []) or []:
        if it.get("status") == "ok" and it.get("authority"):
            items.append(str(it["authority"]))
    # Dedup, stable
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _tripwires_info(card: Dict[str, Any]) -> Tuple[bool, List[str], int]:
    tw = card.get("tripwires", {}) or {}
    count = int(tw.get("current_count") or 0)
    # Use replacement list if present; otherwise fall back to empty list
    tw_list = [str(x).strip() for x in (tw.get("replacement") or [])]
    uniq = {t.lower() for t in tw_list if t}
    ok = (count == 4) and (len(uniq) == 4)
    return ok, tw_list, count

def _diagram_ok(card: Dict[str, Any]) -> Tuple[bool, Dict[str, int]]:
    dg = card.get("diagram_check", {}) or {}
    top = int(dg.get("top_level_branches") or 0)
    total = int(dg.get("total_nodes") or 0)
    ok = (dg.get("status") == "ok") and (top == 5) and (total <= 12)
    return ok, {"top_branches": top, "total_nodes": total}

def _hash_list(items: List[str]) -> str:
    return hashlib.md5("|".join(items).encode("utf-8")).hexdigest() if items else ""

def _compute_delta(prev_meta: Dict[str, Any], card_id: str, now_meta: Dict[str, Any]) -> List[str]:
    bits: List[str] = []
    prev = prev_meta.get(card_id, {})

    def list_delta(label: str, cur: List[str], prev_list: List[str]):
        add = sorted(set(cur) - set(prev_list))
        rem = sorted(set(prev_list) - set(cur))
        if add or rem:
            # Normalise a touch for readability
            def nn(x: str) -> str:
                return _norm_statute_label(x) if label == "statutes" else x
            bits.append(label + " " + " ".join(["+"+nn(x) for x in add] + ["-"+nn(x) for x in rem]))

    list_delta("statutes", now_meta.get("statutes_present", []), prev.get("statutes_present", []))
    list_delta("anchors",  now_meta.get("anchors_present",  []), prev.get("anchors_present",  []))

    if now_meta.get("tripwires_hash") and now_meta["tripwires_hash"] != prev.get("tripwires_hash"):
        bits.append("tripwires Δ")

    return bits

def build_checklist_note(card: Dict[str, Any], prev_meta: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    # Gather current
    statutes_present = _extract_statutes_present(card)
    anchors_present  = _extract_anchors_present(card)
    tripwires_ok, tw_list, tw_count = _tripwires_info(card)
    diagram_ok, diag_info = _diagram_ok(card)

    card_id = str(card.get("card_file", "")).replace("\\", "/")

    # Meta to persist
    cur_meta = {
        "statutes_present": statutes_present,
        "anchors_present": anchors_present,
        "tripwires_hash": _hash_list(tw_list),
    }
    deltas = _compute_delta(prev_meta, card_id, cur_meta)

    # Render human one-liner
    tick = lambda b: "✅" if b else "❌"

    # Spotlight the core four (presence, not completeness)
    core = ["s 48", "s 49", "s 51", "s 52"]
    core_found = [c for c in core if any(c in _norm_statute_label(s) for s in statutes_present)]
    core_ok = bool(core_found)
    core_str = ",".join(c.replace(" ", "") for c in core_found) if core_found else "—"

    # Pt XI / Pt VBA quick flags
    has_pt_xi  = any("Pt XI"  in _norm_statute_label(s) for s in statutes_present)
    has_pt_vba = any("Pt VBA" in _norm_statute_label(s) for s in statutes_present)

    anchors_str = ", ".join(anchors_present) if anchors_present else "—"
    delta_str = (" · " + " · ".join(deltas)) if deltas else ""

    note = (
        f"tripwires_ok {tick(tripwires_ok)} "
        f"· diagram_ok {tick(diagram_ok)} "
        f"· statutes: {core_str} {tick(core_ok)} "
        f"· {'Pt XI' if has_pt_xi else 'Pt XI — n/a'}; {'Pt VBA' if has_pt_vba else 'Pt VBA — n/a'} "
        f"· anchors: {anchors_str}{delta_str}"
    )

    # Return note plus meta we’ll persist under card_id
    persisted = {card_id: cur_meta}
    return note, persisted

# ---------- Main ----------
def main() -> int:
    print(f"[info] ROOT: {ROOT}")
    print(f"[info] Model: {MODEL}")
    print(f"[info] Cards dir: {CARDS_DIR}")
    print(f"[info] Wrongs Act: {WRONGS_ACT_FILE} (exists={WRONGS_ACT_FILE.exists()})")

    cards = sorted(CARDS_GLOB.parent.glob(CARDS_GLOB.name))
    print(f"[info] Found {len(cards)} card(s).")

    if not cards:
        print("[error] No cards found. Check CARDS_DIR.")
        return 2

    client = OpenAI()
    results: List[Dict[str, Any]] = []
    failures = 0

    for p in cards:
        try:
            if VERBOSE:
                print(f"[run] Auditing: {p.name}")
            raw = read_text(p)
            out = call_model(client, raw)

            # First line is JSON by contract; if notes included after, split
            json_part = out.split("\n\n", 1)[0].strip()
            data = json.loads(json_part)

        except Exception as e:
            failures += 1
            print(f"[error] {p.name}: {e}")
            if VERBOSE:
                traceback.print_exc()
            data = {"overall_score_10": 0, "error": str(e)}

        data["card_file"] = str(p.relative_to(ROOT)).replace("\\", "/")
        results.append(data)
        time.sleep(0.2)

    # Write raw JSON report
    json_path = REPORTS_DIR / "model_eval.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Load previous meta for delta computation
    prev_meta_all = load_meta()
    next_meta_all: Dict[str, Any] = {}

    # Build Markdown summary with checklist notes
    md_lines = [
        "# Model Eval Report\n",
        f"- Model: `{MODEL}`",
        f"- Pass threshold (out of 10): {PASS_THRESHOLD}\n",
        "| Card | Score | Pass? | Notes |",
        "| --- | ---: | :---: | --- |",
    ]

    missing_scores = 0
    for r in results:
        score = _coerce_score(r)
        score_disp = f"{int(score) if isinstance(score, float) and score.is_integer() else score}" if isinstance(score, (int,float)) else "—"
        if score is None:
            missing_scores += 1
        pass_flag = "✅" if isinstance(score, (int,float)) and score >= PASS_THRESHOLD else "❌"

        # Checklist note (replaces boilerplate)
        note, per_card_meta = build_checklist_note(r, prev_meta_all)
        next_meta_all.update(per_card_meta)

        md_lines.append(f"| `{r['card_file']}` | {score_disp} | {pass_flag} | {note} |")

    md_path = REPORTS_DIR / "model_eval.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # Persist meta for next run (so deltas appear)
    save_meta(next_meta_all)

    print(f"[done] Wrote: {json_path}")
    print(f"[done] Wrote: {md_path}")
    print(f"[done] Wrote meta: {META_PATH}")
    if missing_scores:
        print(f"[warn] {missing_scores} card(s) had no 'overall_score_10' — showed '—' in the table.")
    if failures:
        print(f"[warn] {failures} card(s) failed; see errors above.")

    # Guard-rails (fail CI if obvious problems)
    zero_like = [r for r in results if _coerce_score(r) in (None, 0.0)]
    if len(results) and len(zero_like) == len(results):
        print("[fail] All cards scored 0/—; evaluator likely misconfigured.")
        return 3

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
