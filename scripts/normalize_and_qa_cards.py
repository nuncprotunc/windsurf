#!/usr/bin/env python3
import sys
import re
import codecs
import json
import yaml
from collections import defaultdict
from pathlib import Path

ROOT = Path("jd/cards_yaml")
JD_ROOT = Path("jd")
SUBJECT_DIRS = sorted(JD_ROOT.glob("LAWS*/cards_yaml"))
REPORT_MD = Path("reports/cards_qareport_batch_0001_0009.md")
REPORT_JSON = Path("reports/cards_qareport_batch_0001_0009.json")
POLICY_PATH = Path("jd/policy/cards_policy.yml")

BATCH = [
  "0001-torts-protected-interests-overview.yml",
  "0002-duty-existence-vs-scope.yml",
  "0003-breach-what-is-the-shirt-calculus.yml",
  "0004-causation-s51-factual-vs-scope.yml",
  "0005-trespass-to-land-elements.yml",
  "0006-private-nuisance-unreasonableness-factors.yml",
  "0009-proportionate-liability-economic-loss-property-damage.yml",
  "0010-trespass-person-detention-analysis.yml",
  "0017-breach-wrongs-act-s48-checklist.yml",
 ]

ALLOWED_DIRS = {str(ROOT), "scripts", "reports", *[str(d) for d in SUBJECT_DIRS]}

def resolve_path(fname: str) -> Path | None:
    """Find a card by filename in jd/cards_yaml, else in jd/LAWS*/cards_yaml.
{{ ... }}
    Returns None if not found.
    """
    p = ROOT / fname
    if p.exists():
        return p
    for d in SUBJECT_DIRS:
        q = d / fname
        if q.exists():
            return q
    return None

# Mojibake fixes
REPL = {
    "â€“": "–",
    "â€”": "—",
    "â€‘": "-",
    "â€™": "’",
    "â€œ": "“",
    "â€\x9d": "”",
}

# Topics: enforce one alongside Torts
TOPIC_WHITELIST = {"Duty","Breach","Causation","Property","Defamation","Contract","Apportionment","Protected_Interests"}

# Per-card policy phrases / expectations (light-weight content checks)
CARD_POLICY = {
    "0002": [
        r"foreseeability.*gateway",
        r"salient features",
        r"coherence",
        r"(?!.*Shirt).*",  # no conflation with Shirt
    ],
    "0003": [
        r"Rogers v Whitaker",
        r"\bs\s*59\b|\bsection\s*59\b",
        r"peer.*professional.*opinion",
    ],
    "0004": [
        r"\bs\s*51\(2\)\b",
        r"Wallace v Kam",
        r"March v Stramare",
    ],
    "0005": [
        r"Plenty v Dillon",
        r"Halliday v Nevill",
        r"Kuru v (State of )?NSW",
    ],
    "0006": [
        r"gravity of harm",
        r"locality",
        r"sensitivity",
        r"duration",
        r"malice",
        r"utility",
    ],
    "0007": [
        r"Defamation Act 2005 \(Vic\)",
        r"publication",
        r"identification",
        r"defamatory meaning",
        r"serious harm",
    ],
    "0008": [
        r"Carlill",
        r"Masters v Cameron|Masters v\.? Cameron",
        r"R v Clarke",
        r"Ermogenous",
    ],
    "0009": [
        r"Pt\s*IVAA",
        r"economic loss|property damage",
        r"concurrent wrongdoers?|apportionment",
        r"contribution",
    ],
}

AUTHORITY_HINTS = {
    "Duty": [r"Sullivan v Moody", r"Perre v Apand", r"Woolcock Street"],
    "Breach": [r"Wyong.*Shirt", r"Rogers v Whitaker", r"\bs\s*59\b"],
    "Causation": [r"\bs\s*51\(1\)\(a\)", r"March v Stramare", r"Strong v Woolworths", r"Wallace v Kam"],
    "Property": [r"Plenty v Dillon|Halliday v Nevill|Kuru v (State of )?NSW"],
    "Defamation": [r"Defamation Act 2005 \(Vic\)"],
    "Apportionment": [r"Pt\s*IVAA"],
}

def is_contract_card(fname, doc):
    tags = set((doc.get("tags") or []))
    front = (doc.get("front") or "").lower()
    if fname.startswith("0008-"):
        return True
    if any(t.lower()=="contract" for t in tags):
        return True
    if "contract" in front:
        return True
    return False

def read_text_bytes(p: Path) -> bytes:
    return p.read_bytes()

def write_bytes_utf8_no_bom(p: Path, b: bytes):
    if b.startswith(codecs.BOM_UTF8):
        b = b[len(codecs.BOM_UTF8):]
    p.write_bytes(b)

def mojibake_clean(b: bytes) -> bytes:
    s = b.decode("utf-8", errors="ignore")
    for bad, good in REPL.items():
        s = s.replace(bad, good)
    return s.encode("utf-8")

def ensure_list(x):
    return [] if x is None else (x if isinstance(x, list) else [x])

def count_mindmap_children(mm: str) -> int:
    lines = mm.splitlines()
    try:
        i = next(i for i, line in enumerate(lines) if "mindmap" in line)
    except StopIteration:
        return 0
    child_count = 0
    for line in lines[i + 1 :]:
        if re.match(r"^\s{2,6}[^\s#-].*", line):
            child_count += 1
    return child_count

def count_top_level_mindmap_branches(mm: str) -> int:
    """Count the number of first-level branches under the root((..)) node in a Mermaid mindmap."""
    lines = mm.splitlines()
    try:
        i_mm = next(i for i, line in enumerate(lines) if "mindmap" in line)
    except StopIteration:
        return 0
    # Find the root line after the mindmap line
    try:
        i_root = next(
            i for i, line in enumerate(lines[i_mm + 1 :], start=i_mm + 1) if re.search(r"root\s*\(\(", line)
        )
    except StopIteration:
        return 0
    root_indent = len(lines[i_root]) - len(lines[i_root].lstrip(" "))
    target_indent = root_indent + 2
    pattern = re.compile(rf"^\s{{{target_indent}}}[^\s#-].*")
    count = 0
    for line in lines[i_root + 1 :]:
        if not line.strip():
            continue
        if pattern.match(line):
            count += 1
        # Stop if indentation decreases back to root level
        cur_indent = len(line) - len(line.lstrip(" "))
        if cur_indent <= root_indent and count > 0:
            break
    return count

def tidy_keywords(kw):
    out = []
    seen = set()
    for k in kw:
        k = str(k).strip().lower()
        k = re.sub(r"[^\w\s\-/]+", "", k)
        k = re.sub(r"\s+", "-", k)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out

def check_pinpoints(stats_list):
    errs = []
    for s in stats_list:
        s_norm = str(s)
        # Accept s or ss, and also allow Part references (e.g., Pt VBA)
        # Allow single section or ranges with hyphen/en-dash, e.g., s 51 or ss 43–48; also allow Pt references
        if "Wrongs Act" in s_norm and not re.search(r"\bs{1,2}\s*\d+(\s*[–-]\s*\d+)?\b|\bPt\s*[A-Za-z0-9]+\b", s_norm):
            errs.append(f"statute lacks section pinpoints: {s_norm}")
    return errs

def load_policy():
    try:
        if POLICY_PATH.exists():
            with POLICY_PATH.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}

def safe_write_guard(p: Path):
    rp = p.resolve()
    for base in ALLOWED_DIRS:
        if str(rp).startswith(str(Path(base).resolve())):
            return
    raise RuntimeError(f"Refusing to write outside allowed dirs: {p}")

def gate(doc, fname, content, strict=True, fix=False):
    errs = []
    fixes = []
    policy = load_policy()
    warnings = []

    # Required schema (include mnemonic as per policy)
    required = ["front","back","why_it_matters","mnemonic","diagram","tripwires","anchors","keywords","reading_level","tags"]
    for k in required:
        if k not in doc:
            errs.append(f"missing field: {k}")

    if errs:
        return errs, fixes, doc, warnings

    # Back: enforce minimum word count (default 200 words)
    back_text = (doc.get("back") or "")
    back_words = len(re.findall(r"\b\w+\b", back_text))
    min_words = int(policy.get("global_rules", {}).get("back", {}).get("min_words", 200))
    if back_words < min_words:
        errs.append(f"back < {min_words} words (found {back_words})")
    # Ensure back references key concepts if policy demands
    must_terms = policy.get("global_rules", {}).get("back", {}).get("must_include_terms", ["duty","breach","defences|defenses","damages","statutory|Wrongs Act"])
    for term in must_terms:
        if not re.search(term, back_text, flags=re.IGNORECASE):
            errs.append(f"back missing required concept: {term}")
    # Ensure category mentions appear in back (only for Protected_Interests/0001)
    fid_local = fname.split("-")[0]
    tags_current = ensure_list(doc.get("tags"))
    enforce_categories = ("Protected_Interests" in tags_current) or (fid_local == "0001")
    if enforce_categories:
        categories_required = policy.get("global_rules", {}).get("back", {}).get("must_include_categories", ["Personal Injury","Property","Pure Economic Loss"])
        for cat in categories_required:
            if not re.search(rf"\b{re.escape(cat)}\b", back_text, flags=re.IGNORECASE):
                errs.append(f"back missing category mention: {cat}")
    if len((doc.get("why_it_matters") or "")) < 120:
        errs.append("why_it_matters < 120 chars")

    if (doc.get("reading_level") or "") != "JD-ready":
        if fix:
            doc["reading_level"] = "JD-ready"
            fixes.append("set reading_level=JD-ready")
        else:
            errs.append("reading_level != JD-ready")

    tags = ensure_list(doc.get("tags"))
    has_torts = any(t == "Torts" for t in tags)
    topic_candidates = [t for t in tags if t in TOPIC_WHITELIST and t != "Torts"]
    if not has_torts:
        if fix:
            tags.append("Torts")
            fixes.append("added tag Torts")
        else:
            errs.append("tags must include 'Torts'")
    if not topic_candidates:
        errs.append(f"tags must include one topic in {sorted(TOPIC_WHITELIST)} (besides 'Torts')")
    # Required exam tags
    req_tags = policy.get("tags", {}).get("required", ["Exam_Fundamentals","MLS_H1"])
    for rt in req_tags:
        if rt not in tags:
            errs.append(f"tags missing required: {rt}")
    doc["tags"] = tags

    diag = doc.get("diagram") or ""
    if not isinstance(diag, str) or "mindmap" not in diag:
        errs.append("diagram not mindmap")
    else:
        expected_top = int(policy.get("diagram", {}).get("top_level_branches", 4))
        n_top = count_top_level_mindmap_branches(diag)
        if n_top != expected_top:
            errs.append(f"mindmap top-level branches {n_top} != {expected_top}")
        overlap_regex = policy.get("diagram", {}).get("require_overlaps_branch_name_regex")
        if overlap_regex and not re.search(overlap_regex, diag, flags=re.IGNORECASE):
            errs.append("mindmap missing required Overlaps/Borderlines branch label")

    tw = ensure_list(doc.get("tripwires"))
    if not (4 <= len(tw) <= 8):
        errs.append(f"tripwires count {len(tw)} not in 4–8")
    else:
        bad_len = [t for t in tw if len(str(t)) > 90]
        if bad_len:
            if fix:
                doc["tripwires"] = [str(t)[:90].rstrip(". ") for t in tw]
                fixes.append("trimmed long tripwires")
            else:
                errs.append("some tripwires > 90 chars")
        trailing = [t for t in tw if str(t).strip().endswith(".")]
        if trailing and not fix:
            errs.append("some tripwires end with a period (imperative style preferred)")
        elif trailing and fix:
            doc["tripwires"] = [str(t).rstrip(". ") for t in doc["tripwires"]]
            fixes.append("removed trailing periods from tripwires")

    kw = ensure_list(doc.get("keywords"))
    kw2 = tidy_keywords(kw)
    if fix and kw2 != kw:
        doc["keywords"] = kw2
        fixes.append("normalised keywords (lowercase, hyphenate, dedup)")
    if not (10 <= len(doc["keywords"]) <= 16):
        errs.append(f"keywords count {len(doc['keywords'])} not in 10–16")
    # Required keywords (space variants acceptable)
    kw_norm_blob = " ".join([str(k).lower().replace("-"," ") for k in ensure_list(doc.get("keywords"))])
    for req_kw in policy.get("keywords", {}).get("required", ["salient features","exclusive possession","relational loss"]):
        if req_kw.lower() not in kw_norm_blob:
            errs.append(f"missing required keyword: {req_kw}")

    anc = doc.get("anchors") or {}
    cases = ensure_list(anc.get("cases"))
    stats = ensure_list(anc.get("statutes"))
    # Cases: require at least 4 beyond obvious trio
    trio = {"donoghue v stevenson", "entick v carrington", "perre v apand"}
    def norm_case(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip().lower()
    beyond = [c for c in cases if all(t not in norm_case(str(c)) for t in trio)]
    if len(beyond) < int(policy.get("anchors", {}).get("min_cases_beyond_trio", 4)):
        errs.append(f"anchors.cases must include at least 4 beyond Donoghue/Entick/Perre (found {len(beyond)})")
    # Statutes: conditional enforcement per policy
    has_wrongs = any("wrongs act 1958 (vic)" in norm_case(str(s)) for s in stats)
    has_cth = any("(cth)" in norm_case(str(s)) for s in stats)
    # Determine negligence context for Wrongs Act requirement
    blob_for_context = "\n".join([
        str(doc.get("front", "")),
        str(doc.get("back", "")),
        str(doc.get("why_it_matters", "")),
        " ".join(map(str, ensure_list(doc.get("keywords"))))
    ]).lower()
    negl_tag_set = {"Duty","Breach","Causation","Apportionment","Negligence"}
    has_negligence_context = (
        "negligen" in blob_for_context
        or "wrongs act" in blob_for_context
        or any(t in negl_tag_set for t in ensure_list(doc.get("tags")))
    )
    if policy.get("statutes", {}).get("must_include_wrongs_act_when_negligence_or_damages", True):
        if has_negligence_context and not has_wrongs:
            errs.append("anchors.statutes must include Wrongs Act 1958 (Vic) when negligence context is engaged")
    # Commonwealth: only require if engaged (signals)
    engaged_cth = bool(re.search(r"\b(ACL|Australian Consumer Law|Competition and Consumer Act)\b", blob_for_context, flags=re.IGNORECASE))
    if policy.get("statutes", {}).get("require_commonwealth_if_engaged", True):
        if engaged_cth and not has_cth:
            errs.append("anchors.statutes must include at least one Commonwealth statute (Cth) when engaged (e.g., ACL/CCA)")
    # Pinpoints check for Wrongs Act
    errs.extend(check_pinpoints(stats))

    hay = (doc.get("back","") + doc.get("why_it_matters","") + diag)
    bads = [k for k in REPL.keys() if k in hay]
    if bads:
        errs.append(f"mojibake remains: {sorted(set(bads))}")

    # Style: basic AU English and AGLC-ish signal checks
    blob_lower = (doc.get("back","") + "\n" + "\n".join(stats)).lower()
    if "neighbor" in blob_lower:
        errs.append("use Australian English: 'neighbour' not 'neighbor'")
    if re.search(r"\bdefenses\b", blob_lower):
        warnings.append("prefer 'defences' (Australian English)")

    topic = next(iter([t for t in tags if t in TOPIC_WHITELIST and t!="Torts"]), None)
    if topic and topic in AUTHORITY_HINTS:
        pattern_any = re.compile("|".join(AUTHORITY_HINTS[topic]))
        blob = "\n".join([*cases, *stats, doc.get("back",""), doc.get("why_it_matters","")])
        if not pattern_any.search(blob):
            warnings.append(f"authority hint not detected for topic {topic}")

    if strict:
        fid = fname.split("-")[0]
        patterns = CARD_POLICY.get(fid, [])
        text = "\n".join([doc.get("back",""), doc.get("why_it_matters","")])
        for pat in patterns:
            if not re.search(pat, text, flags=re.IGNORECASE):
                errs.append(f"policy phrase/check missing: /{pat}/")
        if fid == "0007":
            if re.search(r"s\s*26|Stage\s*2|2021 amendments", text, re.IGNORECASE):
                errs.append("too-specific Stage-2 pinpoints found in defamation card (keep generic)")

    return errs, fixes, doc, warnings

def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def dump_yaml(path: Path, doc):
    safe_write_guard(path)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)

def main():
    fix = "--fix" in sys.argv
    strict = "--no-strict" not in sys.argv  # strict by default
    problems = defaultdict(list)
    warnings_all = defaultdict(list)
    fixes_all = defaultdict(list)

    for fname in BATCH:
        p = resolve_path(fname)
        if p is None:
            problems[fname].append("file missing")
            continue
        raw = read_text_bytes(p)
        cleaned = mojibake_clean(raw)
        if cleaned != raw:
            write_bytes_utf8_no_bom(p, cleaned)

    for fname in BATCH:
        p = resolve_path(fname)
        if p is None or not p.exists():
            continue
        try:
            doc = load_yaml(p)
        except Exception as ex:
            problems[fname].append(f"YAML parse error: {ex}")
            continue
        content_concat = (p.read_text(encoding="utf-8", errors="ignore"))
        errs, fixes, newdoc, warns = gate(doc, fname, content_concat, strict=strict, fix=fix)
        if fix and fixes:
            dump_yaml(p, newdoc)
            fixes_all[fname].extend(fixes)
        if errs:
            problems[fname].extend(errs)
        if warns:
            warnings_all[fname].extend(warns)

    ok = all(len(v)==0 for v in problems.values())

    lines = ["# QA Report: Cards 0001–0009", ""]
    payload = {"results": []}

    for fname in BATCH:
        errs = problems.get(fname, [])
        fixlist = fixes_all.get(fname, [])
        warnlist = warnings_all.get(fname, [])
        if errs:
            lines.append(f"## {fname}\n- FAIL")
            for e in errs:
                lines.append(f"- {e}")
        else:
            lines.append(f"## {fname}\n- PASS")
        if fixlist:
            lines.append("- fixes: " + "; ".join(fixlist))
        if warnlist:
            lines.append("- warnings: " + "; ".join(warnlist))
        payload["results"].append({
            "file": fname,
            "status": "PASS" if not errs else "FAIL",
            "errors": errs,
            "fixes": fixlist,
            "warnings": warnlist,
        })

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n".join(lines))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
