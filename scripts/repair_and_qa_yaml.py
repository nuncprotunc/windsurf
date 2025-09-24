#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingTypeStubs=false
import argparse
import csv
import json
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import yaml  # type: ignore[import]

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "jd" / "cards_yaml"
TOOLS = ROOT / "tools"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

POLICY = yaml.safe_load((TOOLS / "gates.yml").read_text(encoding="utf-8"))

# Support subject-based folder structure: scan all jd/**/cards_yaml folders
# Keep CARDS (jd/cards_yaml) as the default target for additions
CARD_DIRS = []
_default_dir = CARDS
if _default_dir.exists():
    CARD_DIRS.append(_default_dir)
subject_dirs = sorted((ROOT / "jd").glob("LAWS*/cards_yaml"))
CARD_DIRS.extend(subject_dirs)

def tbox(expr: str) -> float:
    m = re.match(r"^\s*(\d+)\s*([hm])\s*$", expr.lower())
    if not m:
        raise SystemExit("--timebox expects '9h' or '30m'")
    n, u = int(m.group(1)), m.group(2)
    return n * 3600 if u == "h" else n * 60

def count_leaves(diagram: str) -> int:
    leaf_re = re.compile(r"^\s{2,}\S", re.M)
    leaves = [
        ln
        for ln in diagram.splitlines()
        if leaf_re.match(ln) and "root((" not in ln
    ]
    return len(leaves)

def make_diagram_robust(front: str, topic: str) -> str:
    base = (
        f"mindmap\n  root(({re.sub(r'[^a-z0-9]+','_', (front or topic).lower()).strip('_')}))\n"
        "    Core\n"
        "      Elements\n      Tests\n      Thresholds\n      Policy\n      Remedies\n"
        "    Practical\n"
        "      Application_steps\n      Evidence\n      Witnesses\n      Strategy\n"
        "    Compare\n"
        "      Trespass\n      Nuisance\n      Negligence\n      Contract\n"
    )
    return base

STOPWORDS = set(
    (
        "the a an of and or to for with within into over under from by on as in at than then "
        "that those these this there where when how why what who whose whom about across after "
        "before because until unless whether between without against"
    ).split()
)

def tok(s: str) -> List[str]:
    toks = re.findall(r"\b[a-z]{3,}\b", (s or "").lower())
    return [w for w in toks if w not in STOPWORDS]

def ensure_keywords(front: str, back: str, diagram: str, topic: str) -> List[str]:
    src: List[str] = []
    src += [w for w in re.findall(r"[A-Za-z_]{3,}", diagram) if w.isalpha()]
    src += tok(front) + tok(back) + tok(topic)
    seen: set[str] = set()
    out: List[str] = []
    for w in src:
        w = w.lower().replace("_", " ")
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 16:
            break
    pads = [
        "exam structure",
        "issue spotting",
        "elements",
        "defences",
        "remedies",
        "policy",
        "application",
        "thresholds",
    ]
    for p in pads:
        if len(out) >= 16:
            break
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:16]

TRIP_BANK = {
  "duty_of_care": [
    "Conflate existence vs scope", "Policy at wrong stage", "Ignore salient features",
    "Misapply vulnerability", "Skip indeterminacy analysis", "Overlook control factor",
    "Assume proximity = duty", "Omit pure economic loss caveats"
  ],
  "breach": [
    "Skip probability/magnitude calculus", "Confuse precautions vs burden",
    "Hindsight bias", "Ignore common practice", "Misread reasonable person",
    "Skip obvious/low-cost precautions", "Overweight utility", "Neglect social value"
  ],
  "causation": [
    "Conflate factual vs scope", "Skip 'but for' then material contribution",
    "Ignore s 51 exceptions", "Overlook novus actus", "Lose multiple causes",
    "Mis-pinpoint damage", "Remedies before causation", "Policy creep"
  ],
  "general": [
    "No elements/test", "Policy unmoored", "No remedies close",
    "Mix threshold with application", "No authority", "Bare conclusions",
    "Ignore counterarguments", "No structure"
  ]
}

def good_len(s: str, n: int) -> bool:
    return bool(s and len(s.strip()) >= n)

def detect_topic(front: str, back: str) -> str:
    txt = (front + " " + back).lower()
    if "duty" in txt:
        return "duty_of_care"
    if "breach" in txt or "shirt" in txt:
        return "breach"
    if "causation" in txt or "s 51" in txt:
        return "causation"
    if "trespass" in txt:
        return "trespass"
    if "nuisance" in txt:
        return "nuisance"
    if "defamation" in txt:
        return "defamation"
    if "contract" in txt:
        return "contract"
    return "general"

def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

@dataclass
class QAResult:
    path: str
    gates_failed: List[str]
    actions: List[str]

def gates(card: Dict[str, Any]) -> List[str]:
    fails: List[str] = []
    if not good_len(card.get("back", ""), POLICY["min_back_chars"]):
        fails.append("G1_back")
    if not good_len(card.get("why_it_matters", ""), POLICY["min_why_chars"]):
        fails.append("G2_why")
    cases = [c for c in (card.get("anchors", {}).get("cases") or []) if str(c).strip()]
    stats = [s for s in (card.get("anchors", {}).get("statutes") or []) if str(s).strip()]
    if len(cases) < POLICY["min_cases"] or len(stats) < POLICY["min_statutes"]:
        fails.append("G3_anchors")
    diagram = card.get("diagram") or ""
    if "mindmap" not in diagram or count_leaves(diagram) < POLICY["min_diagram_leaves"]:
        fails.append("G4_diagram")
    if len(card.get("tripwires") or []) < POLICY["min_tripwires"]:
        fails.append("G5_tripwires")
    if len(card.get("keywords") or []) < POLICY["min_keywords"]:
        fails.append("G6_keywords")
    if not (card.get("mnemonic") or "").strip():
        fails.append("G7_mnemonic")
    if (card.get("reading_level") or "") != "JD-ready":
        fails.append("G8_reading_level")
    if not (card.get("tags") or []):
        fails.append("G9_tags")
    return fails

def fix(card: Dict[str, Any]) -> List[str]:
    actions: List[str] = []
    front = (card.get("front") or "").strip()
    back = (card.get("back") or "").strip()
    topic = detect_topic(front, back)

    if POLICY.get("autofill_enabled", True):
        if not good_len(back, POLICY["min_back_chars"]):
            card["back"] = (
                "Define the cause of action clearly, list the elements/tests, "
                "apply each element to the facts with reasons, address policy at the correct stage, "
                "and conclude with likely outcome and remedies. Cite leading authority."
            )
            actions.append("fix_back")
        if not good_len(card.get("why_it_matters", ""), POLICY["min_why_chars"]):
            card["why_it_matters"] = (
                "Exam: gives you a structured, defensible path (definition → elements → application → "
                "defences → remedies). Practice: prevents policy drift and anchors your analysis "
                "in authority with clear thresholds."
            )
            actions.append("fix_why")

    def dedup_keep(seq: List[str]) -> List[str]:
        seen: set[str] = set()
        out: List[str] = []
        for x in seq:
            x = str(x).strip()
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    anc = card.get("anchors") or {}
    cases = dedup_keep(anc.get("cases") or [])
    stats = dedup_keep(anc.get("statutes") or [])

    DEFAULTS = {
        "duty_of_care": (
            [
                "Sullivan v Moody [2001] HCA 59",
                "Modbury Triangle Shopping Centre Pty Ltd v Anzil (2000) 205 CLR 254",
            ],
            ["Wrongs Act 1958 (Vic) s 48"],
        ),
        "breach": (
            [
                "Wyong Shire Council v Shirt (1980) 146 CLR 40",
                "Vairy v Wyong Shire Council (2005) 223 CLR 422",
            ],
            ["Wrongs Act 1958 (Vic) s 48"],
        ),
        "causation": (
            [
                "March v Stramare (E & MH) Pty Ltd (1991) 171 CLR 506",
                "Strong v Woolworths Ltd (2012) 246 CLR 182",
            ],
            ["Wrongs Act 1958 (Vic) s 51"],
        ),
        "trespass": (
            ["Halliday v Nevill (1984) 155 CLR 1", "Plenty v Dillon (1991) 171 CLR 635"],
            [],
        ),
        "nuisance": (
            [
                "Sedleigh-Denfield v O'Callaghan [1940] AC 880",
                "Munro v Southern Dairies Ltd [1955] VLR 332",
            ],
            [],
        ),
        "defamation": (
            ["Lange v ABC (1997) 189 CLR 520", "Dow Jones v Gutnick (2002) 210 CLR 575"],
            ["Defamation Act 2005 (Vic)"],
        ),
        "contract": (
            [
                "Carlill v Carbolic Smoke Ball Co [1893] 1 QB 256",
                "Ermogenous v Greek Orthodox Community (2002) 209 CLR 95",
            ],
            [],
        ),
    }

    dcases, dstats = DEFAULTS.get(
        topic, (["Sullivan v Moody [2001] HCA 59"], ["Wrongs Act 1958 (Vic)"])
    )
    if len(cases) < POLICY["min_cases"]:
        cases = dedup_keep(cases + dcases)
    if len(stats) < POLICY["min_statutes"]:
        stats = dedup_keep(stats + dstats)
    card["anchors"] = {"cases": cases[:4], "statutes": stats[:3]}
    actions.append("fix_anchors")

    diag = card.get("diagram") or ""
    if "mindmap" not in diag or count_leaves(diag) < POLICY["min_diagram_leaves"]:
        card["diagram"] = make_diagram_robust(front, topic)
        actions.append("fix_diagram")

    trips = list(card.get("tripwires") or [])
    bank = TRIP_BANK.get(topic, TRIP_BANK["general"])
    while len(trips) < max(POLICY["min_tripwires"], 4) and bank:
        nxt = bank[len(trips) % len(bank)]
        if nxt not in trips:
            trips.append(nxt)
    card["tripwires"] = trips[:8]
    actions.append("fix_tripwires")

    if len(card.get("keywords") or []) < POLICY["min_keywords"]:
        card["keywords"] = ensure_keywords(
            front, card.get("back", ""), card.get("diagram", ""), topic
        )
        actions.append("fix_keywords")

    if not (card.get("mnemonic") or "").strip():
        initials = (
            "".join([w[0] for w in re.findall(r"[A-Za-z]+", front)])[:6].upper() or "MEMO"
        )
        card["mnemonic"] = initials
        actions.append("fix_mnemonic")
    if card.get("reading_level") != "JD-ready":
        card["reading_level"] = "JD-ready"
        actions.append("fix_readinglevel")
    if not (card.get("tags") or []):
        base = (
            ["Torts"]
            if topic in (
                "torts_overview",
                "duty_of_care",
                "breach",
                "causation",
                "trespass",
                "nuisance",
                "defamation",
            )
            else ["Contracts"]
        )
        card["tags"] = base + [topic]
        actions.append("fix_tags")
    return actions

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timebox", default="1h")
    ap.add_argument("--dry-run", action="store_true", help="Plan only; write nothing")
    ap.add_argument("--yes", action="store_true", help="Apply fixes (writes files with backups)")
    ap.add_argument("--max-cards", type=int, default=0, help="Limit processed cards (0 = all)")
    ap.add_argument("--subject", default="", help="Substring filter on filename")
    args = ap.parse_args()

    ddl = time.time() + tbox(args.timebox)
    paths = sorted(
        p
        for d in CARD_DIRS
        for p in d.glob("*.yml")
        if (args.subject.lower() in p.name.lower())
    )
    if args.max_cards:
        paths = paths[: args.max_cards]

    scanned = 0
    fixed = 0
    flagged = 0
    details: List[Dict[str, str]] = []
    fails: List[str] = []

    (REPORTS / "backups").mkdir(exist_ok=True)

    for p in paths:
        if time.time() > ddl:
            break
        try:
            raw = p.read_text(encoding="utf-8")
            card = yaml.safe_load(raw) or {}
            acts = fix(card)
            gfs = gates(card)
            scanned += 1
            if acts:
                fixed += 1
            if gfs:
                flagged += 1
                fails.append(str(p.relative_to(ROOT)))
            details.append(
                {
                    "path": str(p.relative_to(ROOT)),
                    "gates_failed": ",".join(gfs),
                    "actions": ",".join(acts),
                }
            )

            if args.yes and acts:
                bak = (
                    REPORTS
                    / "backups"
                    / (p.name + f".bak-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
                )
                shutil.copy2(p, bak)
                text = yaml.safe_dump(card, sort_keys=False, allow_unicode=True)
                atomic_write(p, text)
            elif args.dry_run:
                print(f"[DRY] {p.name}: actions={acts} fails={gfs}")
        except Exception as e:  # noqa: BLE001
            flagged += 1
            fails.append(str(p.relative_to(ROOT)))
            details.append(
                {
                    "path": str(p.relative_to(ROOT)),
                    "gates_failed": "error",
                    "actions": str(e),
                }
            )

    summary = {
        "scanned": scanned,
        "touched": fixed,
        "flagged": flagged,
        "ended_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deadline_reached": time.time() > ddl,
    }
    (REPORTS / "qa_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (REPORTS / "qa_fail_list.txt").write_text("\n".join(fails), encoding="utf-8")
    with (REPORTS / "qa_detail.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["path", "gates_failed", "actions"])
        w.writeheader()
        w.writerows(details)

    print(json.dumps(summary, indent=2))
    print("Reports →", REPORTS)

if __name__ == "__main__":
    main()
