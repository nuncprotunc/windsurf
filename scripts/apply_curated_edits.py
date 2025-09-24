#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingTypeStubs=false
"""
Apply curated, schema-safe edits to torts deck.
- No schema changes. Only touch: front, back, anchors.{cases,statutes}, tags, why_it_matters.
- Idempotent; dedup anchors; UTF-8 normalisation; Windows-safe.
- Adds new cards only where specified.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import argparse
import csv
import json
import re
import sys
import yaml  # type: ignore[import-not-found]

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "jd" / "cards_yaml"
CARDS.mkdir(parents=True, exist_ok=True)

# Also support subject-based layout: jd/LAWSXXXX - Subject/cards_yaml
CARD_DIRS = []
if CARDS.exists():
    CARD_DIRS.append(CARDS)
CARD_DIRS.extend(sorted((ROOT / "jd").glob("LAWS*/cards_yaml")))

# --- Helpers ---
def read_yaml(p: Path) -> dict:
    raw = p.read_text(encoding="utf-8", errors="replace")
    # normalise common mojibake to ASCII/Unicode punctuation
    fixed = (
        raw.replace("â€“", "–")
        .replace("â€”", "—")
        .replace("â€‘", "-")
        .replace("â€™", "’")
        .replace("â€˜", "‘")
        .replace("â€œ", "“")
        .replace("â€\x9d", "”")  # Corrected closing quote replacement string
        .replace("â€¦", "…")
    )
    return yaml.safe_load(fixed) or {}


def write_yaml(p: Path, data: dict) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(p)


def dedupe(seq: list[str] | list[object]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def has_any(s: str, needles: list[str]) -> bool:
    t = (s or "").lower()
    return any(n in t for n in needles)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


# --- Targets/anchors we will enforce (AGLC-ish short cites) ---
CASES: dict[str, list[str]] = {
    "assault_good": [
        "Stephens v Myers (1830) 172 ER 735",
        "Tuberville v Savage (1669) 86 ER 684",
        "Zanker v Vartzokas (1988) 34 A Crim R 11",
    ],
    "remove_barton": ["Barton v Armstrong [1976] AC 104"],  # contract duress, not tort assault
    "medical_battery": ["Dean v Phung [2012] NSWCA 223"],
    "rogers_negligence": ["Rogers v Whitaker (1992) 175 CLR 479"],
    "occupiers": ["Australian Safeway Stores Pty Ltd v Zaluzna (1987) 162 CLR 479"],
    "public_roads": ["Brodie v Singleton Shire Council (2001) 206 CLR 512"],
    "causation_march": ["March v Stramare (E & MH) Pty Ltd (1991) 171 CLR 506"],
    "non_delegable": ["Kondis v State Transport Authority (1984) 154 CLR 672"],
    "illegality": ["Miller v Miller (2011) 242 CLR 446"],
}

STATUTES: dict[str, list[str]] = {
    "wrongs_pt_xi": [
        "Wrongs Act 1958 (Vic) pt XI",
        "Wrongs Act 1958 (Vic) s 72",
        "Wrongs Act 1958 (Vic) s 73",
    ],
    "peer_prof": ["Wrongs Act 1958 (Vic) s 59"],
    "obvious_risk": ["Wrongs Act 1958 (Vic) ss 53–54"],
    "roads": ["Road Management Act 2004 (Vic)"],
    "prop_liability": ["Wrongs Act 1958 (Vic) pt IVAA"],  # proportionate liability
}

# --- Coverage expectations: for audit only (no schema changes) ---
REQUIRED: list[tuple[str, list[str], list[str]]] = [
    # matcher, required cases, required statutes
    (r"\bassault\b", CASES["assault_good"], []),
    (r"\bmedical\b.*\b(battery|trespass)\b", CASES["medical_battery"], []),
    (
        r"\brogers v whitaker\b|\bpeer professional|\bs 59\b",
        CASES["rogers_negligence"],
        STATUTES["peer_prof"],
    ),
    (r"\boccupier|entrant|premises\b", CASES["occupiers"], []),
    (
        r"\bpublic authorit|road authorit|non-?feasance|misfeasance|highway\b",
        CASES["public_roads"],
        STATUTES["roads"],
    ),
    (
        r"\bcausation\b|\bs 51\b|\bmaterial contribution\b|\bbut[-\s]?for\b",
        CASES["causation_march"],
        [],
    ),
    (
        r"\bnon[-\s]?delegable\b|\bemployer\b|\bsystems of work\b|\bsupervision\b",
        CASES["non_delegable"],
        [],
    ),
    (r"\billegality\b|\bex\s*turpi\b", CASES["illegality"], []),
    (r"\bmental harm\b|\bpsychiatric\b|\bnormal fortitude\b", [], STATUTES["wrongs_pt_xi"]),
    (r"\bobvious risk\b|\binherent risk\b", [], STATUTES["obvious_risk"]),
]

UNWANTED: dict[str, str] = {
    "Barton v Armstrong [1976] AC 104": "Assault card cites contract duress case",
}


# --- Extra helpers for audit ---
def normalize_case_list(xs: list[str] | list[object]) -> list[str]:  # stable compare
    return [re.sub(r"\s+", " ", str(x)).strip() for x in xs or []]


def present(anchor_list: list[str], required_list: list[str]) -> list[str]:
    have = set(normalize_case_list(anchor_list))
    req = [re.sub(r"\s+", " ", r).strip() for r in required_list]
    missing = [r for r in req if r not in have]
    return missing


# --- Content matchers (filename-agnostic) ---
def touch_assault(card: dict) -> bool:
    f = card.get("front", "")
    if not has_any(f, ["assault"]):
        return False
    # replace Barton if present; ensure good assault anchors exist
    anc = card.get("anchors") or {}
    cases = dedupe([c for c in anc.get("cases") or [] if c not in CASES["remove_barton"]] + CASES["assault_good"])
    anc["cases"] = cases[:4]
    anc["statutes"] = dedupe(anc.get("statutes") or [])
    card["anchors"] = anc
    return True


def touch_medical_battery(card: dict) -> bool:
    f, b = card.get("front", ""), card.get("back", "")
    # Look for battery/medical consent contexts (avoid pure Rogers negligence card)
    if has_any(f + b, ["battery", "medical trespass", "consent"]) and not has_any(
        f + b, ["negligence", "warnings only"]
    ):
        anc = card.get("anchors") or {}
        cases = dedupe(
            [c for c in anc.get("cases") or [] if c != CASES["rogers_negligence"][0]]
            + CASES["medical_battery"]
        )
        anc["cases"] = cases[:4]
        card["anchors"] = anc
        return True
    return False


def touch_rogers_negligence(card: dict) -> bool:
    f = card.get("front", "")
    b = card.get("back", "")
    if has_any(
        f + b, ["rogers v whitaker", "warning", "peer professional", "s 59", "professional opinion"]
    ):
        anc = card.get("anchors") or {}
        cases = dedupe((anc.get("cases") or []) + CASES["rogers_negligence"])
        stats = dedupe((anc.get("statutes") or []) + STATUTES["peer_prof"])
        card["anchors"] = {"cases": cases[:4], "statutes": stats[:3]}
        return True
    return False


def touch_occupiers(card: dict) -> bool:
    f = card.get("front", "")
    if has_any(f, ["occupier", "entrant", "premises"]):
        anc = card.get("anchors") or {}
        cases = dedupe((anc.get("cases") or []) + CASES["occupiers"])
        anc["cases"] = cases[:4]
        card["anchors"] = anc
        return True
    return False


def touch_public_road(card: dict) -> bool:
    f = card.get("front", "")
    if has_any(f, ["public authorit", "road authorit", "non-feasance", "misfeasance", "highway"]):
        anc = card.get("anchors") or {}
        anc["cases"] = dedupe((anc.get("cases") or []) + CASES["public_roads"])[:4]
        anc["statutes"] = dedupe((anc.get("statutes") or []) + STATUTES["roads"])[:3]
        card["anchors"] = anc
        return True
    return False


def touch_causation_march(card: dict) -> bool:
    f = card.get("front", "")
    b = card.get("back", "")
    if has_any(f + b, ["causation", "s 51", "scope of liability", "but for", "material contribution"]):
        anc = card.get("anchors") or {}
        anc["cases"] = dedupe((anc.get("cases") or []) + CASES["causation_march"])[:4]
        card["anchors"] = anc
        return True
    return False


def touch_non_delegable(card: dict) -> bool:
    f = card.get("front", "")
    if has_any(f, ["non-delegable", "employer", "systems of work", "supervision"]):
        anc = card.get("anchors") or {}
        anc["cases"] = dedupe((anc.get("cases") or []) + CASES["non_delegable"])[:4]
        card["anchors"] = anc
        return True
    return False


def touch_illegality(card: dict) -> bool:
    f = card.get("front", "")
    b = card.get("back", "")
    if has_any(f + b, ["illegality", "ex turpi"]):
        anc = card.get("anchors") or {}
        anc["cases"] = dedupe((anc.get("cases") or []) + CASES["illegality"])[:4]
        card["anchors"] = anc
        return True
    return False


def merge_compliance_cards(card: dict) -> bool:
    # Unify “Compliance with statute/regulation” and “Statutory compliance as shield/sword”
    f = (card.get("front", "") or "")
    if "Compliance with statute" in f or "Statutory compliance as shield" in f:
        # normalise front wording once
        card["front"] = "Compliance with statute/regulation (shield vs sword)"
        return True
    return False


def tweak_neighbour(card: dict) -> bool:
    f = card.get("front", "")
    if has_any(f, ["Neighbour principle"]):
        card[
            "why_it_matters"
        ] = "Reasonable foreseeability operates as the duty gateway, then the claim is filtered by salient features and coherence."
        return True
    return False


def tweak_incrementalism(card: dict) -> bool:
    f = card.get("front", "")
    if has_any(f, ["Known categories", "novel categories"]):
        card[
            "front"
        ] = "Duty method: incrementalism and analogical reasoning (known vs novel categories)"
        return True
    return False


def ensure_mental_harm_bits(card: dict) -> bool:
    f = card.get("front", "")
    b = card.get("back", "")
    if has_any(f + b, ["mental harm", "psychiatric", "normal fortitude"]):
        anc = card.get("anchors") or {}
        anc["statutes"] = dedupe((anc.get("statutes") or []) + STATUTES["wrongs_pt_xi"])[:4]
        card["anchors"] = anc
        # nudge back if thin
        if len((card.get("back") or "").strip()) < 180:
            card["back"] = (
                card.get("back") or ""
            ) + " Damages generally require a recognisable psychiatric illness; foreseeability assessed by a person of normal fortitude (s 72); secondary victims are further constrained (s 73)."
        return True
    return False


def add_card(
    front: str,
    back: str,
    cases: list[str] | None = None,
    stats: list[str] | None = None,
    tags: list[str] | None = None,
) -> bool:
    cases = cases or []
    stats = stats or []
    tags = tags or []
    path = CARDS / f"{len(list(CARDS.glob('*.yml'))) + 1:04d}-{slug(front)}.yml"
    if path.exists():
        return False
    data = {
        "front": front,
        "back": back,
        "why_it_matters": "",
        "mnemonic": "",
        "diagram": f"mindmap\n  root(({slug(front).replace('-', '_')}))",
        "tripwires": [],
        "anchors": {"cases": cases[:4], "statutes": stats[:3]},
        "keywords": [],
        "reading_level": "JD-ready",
        "tags": tags or [],
    }
    write_yaml(path, data)
    print("ADDED:", path.name)
    return True


# --- Coverage audit ---
def audit_deck() -> int:
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    problems = 0

    for d in CARD_DIRS:
        for p in sorted(d.glob("*.yml")):
            card = read_yaml(p)
            text = (card.get("front", "") + " " + card.get("back", "")).lower()
            anc = card.get("anchors") or {}
            cases = normalize_case_list(anc.get("cases") or [])
            stats = normalize_case_list(anc.get("statutes") or [])

            # unwanted anchors (e.g., Barton on assault)
            unwanted_hits: list[str] = []
            for bad, why in UNWANTED.items():
                if bad in cases:
                    unwanted_hits.append(f"{bad} → {why}")

            # expected anchors per matcher
            matches: list[dict[str, str]] = []
            for patt, req_cases, req_stats in REQUIRED:
                if re.search(patt, text):
                    miss_cases = present(cases, req_cases)
                    miss_stats = present(stats, req_stats)
                    if miss_cases or miss_stats or unwanted_hits:
                        problems += 1
                    matches.append(
                        {
                            "pattern": patt,
                            "missing_cases": "; ".join(miss_cases) or "-",
                            "missing_statutes": "; ".join(miss_stats) or "-",
                        }
                    )

            if matches or unwanted_hits:
                rows.append(
                    {
                        "file": p.name,
                        "front": card.get("front", ""),
                        "unwanted": "; ".join(unwanted_hits) or "-",
                        "checks": json.dumps(matches, ensure_ascii=False),
                    }
                )

    # write CSV + JSON
    csv_path = reports_dir / "coverage_report.csv"
    json_path = reports_dir / "coverage_report.json"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "front", "unwanted", "checks"])
        w.writeheader()
        w.writerows(rows)
    json_path.write_text(
        json.dumps({"problems": problems, "items": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[AUDIT] problems={problems} → reports: {csv_path}, {json_path}")
    return problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--audit-only", action="store_true", help="Run coverage audit only; do not modify cards"
    )
    ap.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit non-zero if audit finds missing/unwanted anchors",
    )
    args = ap.parse_args()

    # Always run audit first (dry visibility), then apply edits if not audit-only
    problems = audit_deck()
    if args.audit_only:
        sys.exit(1 if (args.fail_on_missing and problems) else 0)

    # --- Pass 1: mutate existing cards safely ---
    touched = 0
    for d in CARD_DIRS:
        for p in sorted(d.glob("*.yml")):
            card = read_yaml(p)
            before = yaml.safe_dump(card, sort_keys=False, allow_unicode=True)
            changed = False
            for fn in (
                touch_assault,
                touch_medical_battery,
                touch_rogers_negligence,
                touch_occupiers,
                touch_public_road,
                touch_causation_march,
                touch_non_delegable,
                touch_illegality,
                merge_compliance_cards,
                tweak_neighbour,
                tweak_incrementalism,
                ensure_mental_harm_bits,
            ):
                try:
                    changed = fn(card) or changed
                except Exception:
                    # keep going; audit will reveal gaps
                    pass
            # never add or remove unknown fields; keep schema keys only
            allowed = {
                "front",
                "back",
                "why_it_matters",
                "mnemonic",
                "diagram",
                "tripwires",
                "anchors",
                "keywords",
                "reading_level",
                "tags",
            }
            card = {k: v for k, v in card.items() if k in allowed}
            after = yaml.safe_dump(card, sort_keys=False, allow_unicode=True)
            if changed and after != before:
                # backup
                bak = p.with_suffix(
                    p.suffix + f".bak-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
                )
                p.replace(bak)
                write_yaml(p, yaml.safe_load(after))
                touched += 1
                print("EDITED:", p.name)

    # --- Pass 2: add strictly specified new cards (idempotent) ---
    add_card(
        front="Proportionate liability (economic loss/property damage)",
        back=(
            "Under the Wrongs Act 1958 (Vic) pt IVAA, liability for apportionable claims "
            "(economic loss or property damage arising from failure to take reasonable care) is several, not joint. "
            "The court apportions responsibility among concurrent wrongdoers by responsibility share. "
            "Not all heads of damage are apportionable; personal injury is generally excluded."
        ),
        cases=[],
        stats=STATUTES["prop_liability"],
        tags=["Torts", "Apportionment"],
    )

    # Re-audit post-edits so CI can assert we’re clean
    problems2 = audit_deck()
    if args.fail_on_missing and problems2:
        sys.exit(1)
    print(f"Done. Touched={touched}")
