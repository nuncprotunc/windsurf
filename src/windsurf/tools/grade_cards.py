# ruff: noqa: E501
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from typing import Dict, Any, List

import yaml
from tenacity import retry, stop_after_attempt, wait_exponential

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[3] if (Path(__file__).parts[-3:] == ("windsurf","tools","grade_cards.py")) else Path.cwd()
CARDS_GLOB = ROOT / "src" / "jd" / "cards_yaml" / "*.yml"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL = os.environ.get("WINDSURF_GRADE_MODEL", "gpt-4o-mini")  # use a small cheap model; switch if you like
PASS_THRESHOLD = float(os.environ.get("WINDSURF_PASS_THRESHOLD", "5.0"))  # out of 7 in the prompt below
MAX_OUTPUT_TOKENS = int(os.environ.get("WINDSURF_MAX_OUTPUT_TOKENS", "2000"))

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
"""

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(4))
def call_model(client: OpenAI, card_text: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Please audit the following card. Return ONE JSON object first, then notes.\n<<<\n" + card_text + "\n>>>"},
        ],
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    return resp.choices[0].message.content or "{}"

def main() -> int:
    client = OpenAI()
    results: List[Dict[str, Any]] = []
    for p in sorted(CARDS_GLOB.parent.glob(CARDS_GLOB.name)):
        try:
            raw = read_text(p)
            out = call_model(client, raw)
            # split JSON (first) and notes (after blank line) if author adds notes
            json_part, *_notes = out.split("\n\n", 1)
            data = json.loads(json_part)
        except Exception as e:
            data = {"overall_score_10": 0, "error": str(e)}
        data["card_file"] = str(p.relative_to(ROOT))
        results.append(data)
        time.sleep(0.2)

    # Write JSON report
    json_path = REPORTS_DIR / "model_eval.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Write Markdown summary
    md_lines = ["# Model Eval Report\n", f"- Model: `{MODEL}`",
                f"- Pass threshold (out of 10): {PASS_THRESHOLD}\n",
                "| Card | Score | Pass? | Notes |",
                "| --- | ---: | :---: | --- |"]
    for r in results:
        score = r.get("overall_score_10", 0)
        pass_flag = "✅" if isinstance(score, (int, float)) and score >= PASS_THRESHOLD else "❌"
        hi = (r.get("high_yield_summary") or "").replace("\n"," ")
        md_lines.append(f"| `{r['card_file']}` | {score} | {pass_flag} | {hi} |")
    (REPORTS_DIR / "model_eval.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Wrote: {json_path}")
    print(f"Wrote: {REPORTS_DIR / 'model_eval.md'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
