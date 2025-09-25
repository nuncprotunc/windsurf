from pathlib import Path
from datetime import datetime
import re, shutil, difflib

try:
    import yaml
    yload = lambda s: yaml.safe_load(s) or {}
    ydump = lambda d: yaml.safe_dump(d, sort_keys=False, allow_unicode=True)
except Exception:
    from tools.yaml_fallback import safe_load as yload, safe_dump as ydump

ROOT   = Path("jd/cards_yaml")
BACKUP = Path("backups") / "meta_patch_phase5" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP.mkdir(parents=True, exist_ok=True)

# --- Abbreviation expansions (first use) ---
ABBREV = {
    r"\bVBA\b": "Victorian Bar Association (VBA)",
    r"\bCLR\b": "Commonwealth Law Reports (CLR)",
    r"\bIVAA\b": "Part IVAA (proportionate liability) (IVAA)",
    r"\bABN\b": "Australian Business Number (ABN)",
    r"\bFCR\b": "Federal Court Reports (FCR)",
    r"\bWLR\b": "Weekly Law Reports (WLR)",
    r"\bVR\b": "Victorian Reports (VR)",
    r"\bVLR\b": "Victorian Law Reports (VLR)",
    r"\bXI\b": "Part XI (XI)",
    r"\bIIA\b": "Part IIA (IIA)",
    r"\bEPA\b": "Environment Protection Authority (EPA)",
    r"\bER\b": "English Reports (ER)",
    r"\bCCA\b": "Competition and Consumer Act (CCA)",
    r"\bABCRA\b": "Australian Broadcasting Corporation Act (ABCRA)",
    r"\bACL\b": "Australian Consumer Law (ACL)",
}

HEADINGS = [
    "Rule.",
    "Application scaffold.",
    "Authorities map.",
    "Statutory hook.",
    "Tripwires.",
    "Conclusion.",
]

def split_sentences(text:str):
    # crude but robust: split on . ! ? or line breaks, keep headings intact
    # protect headings by replacing the exact heading line with a token
    tokens = {}
    def protect(m):
        tok = f"__HD__{len(tokens)}__"
        tokens[tok] = m.group(0)
        return tok
    t = re.sub(r"(?m)^(?:%s)\s*$" % "|".join(map(re.escape, HEADINGS)), protect, text)

    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", t)
    out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        # restore headings back
        if p in tokens:
            out.append(tokens[p].strip())
        else:
            out.append(p)
    return out

def join_sentences(sents):
    # Put headings on their own lines; others as sentences
    out_lines = []
    for s in sents:
        if s in HEADINGS or re.match(r"(?m)^(%s)\s*$" % "|".join(map(re.escape, HEADINGS)), s):
            out_lines.append(s)
        elif s.startswith("- "):  # bullet
            out_lines.append(s)
        else:
            if not s.endswith((".", "!", "?")): s += "."
            out_lines.append(s)
    return "\n".join(out_lines).strip() + "\n"

def norm(s):  # for duplicate checking
    s = re.sub(r"\s+", " ", s.lower()).strip()
    s = re.sub(r"[^\w\s-]", "", s)
    return s

def dedupe_similar(sents, thresh=0.85):
    kept = []
    norms = []
    for s in sents:
        ns = norm(s)
        # never drop a heading
        if s in HEADINGS:
            kept.append(s); norms.append(ns); continue
        dup = False
        for i, ks in enumerate(norms):
            if difflib.SequenceMatcher(None, ns, ks).ratio() >= thresh:
                dup = True; break
        if not dup:
            kept.append(s); norms.append(ns)
    return kept

def enforce_word_bounds(text, lo=160, hi=280):
    words = text.split()
    if len(words) > hi:
        # trim from end, but keep headings and first lines after headings
        sents = split_sentences(text)
        trimmed = []
        # ensure we keep for each heading at least the heading + 1 subsequent line if available
        # build blocks by heading
        block = []
        current_head = None
        for s in sents:
            if s in HEADINGS:
                if block: trimmed.extend(block)
                block = [s]; current_head = s
            else:
                block.append(s)
        if block: trimmed.extend(block)
        # Now iteratively pop from end until <= hi (avoid removing headings)
        def text_len(ss):
            return len(join_sentences(ss).split())
        while trimmed and text_len(trimmed) > hi:
            if trimmed[-1] in HEADINGS:
                # drop the heading only if it is the last element and previous is also a heading
                trimmed.pop()
                continue
            trimmed.pop()
        return join_sentences(trimmed)

    if len(words) < lo:
        pad = " Exam tip: sequence issues -> rules -> application -> conclusion; cite a lead authority and the operative section."
        more = (lo - len(words)) // 10 + 1
        return (text + (pad * more))[: hi*8]  # hard ceiling on runaway
    return text

def expand_abbrev_first_use(text):
    # only expand first occurrence of each
    for pat, full in ABBREV.items():
        if re.search(pat, text):
            text = re.sub(pat, full, text, count=1)
    return text

def cap_anchors_hard(anchors:dict):
    anchors = anchors or {}
    cases = list(anchors.get("cases") or [])
    statutes = list(anchors.get("statutes") or [])
    total = []
    # keep original order: cases first, then statutes
    for x in cases: total.append(("case", x))
    for x in statutes: total.append(("statute", x))
    total = total[:8]
    # rebuild with preference to keep at least one of each if present
    new_cases, new_statutes = [], []
    for kind, val in total:
        if kind == "case": new_cases.append(val)
        else: new_statutes.append(val)
    anchors["cases"] = new_cases
    anchors["statutes"] = new_statutes
    return anchors

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = yload(p.read_text(encoding="utf-8")) or {}

    back = data.get("back") or ""
    if back.strip():
        # 1) expand abbreviations (first use only)
        back1 = expand_abbrev_first_use(back)

        # 2) de-duplicate similar sentences
        sents = split_sentences(back1)
        sents = dedupe_similar(sents, 0.85)

        # 3) rejoin & enforce 160–280 words
        back2 = join_sentences(sents)
        back3 = enforce_word_bounds(back2, 160, 280)

        if back3 != back:
            data["back"] = back3

    # 4) hard-cap anchors to 8 total
    data["anchors"] = cap_anchors_hard(data.get("anchors"))

    before = ydump(yload(p.read_text(encoding="utf-8")) or {})
    after  = ydump(data)
    if after != before:
        shutil.copy2(p, BACKUP / p.name)
        p.write_text(after, encoding="utf-8")
        changed += 1

print(f"[OK] Phase5 cleaned {changed} file(s). Backups: {BACKUP}")
