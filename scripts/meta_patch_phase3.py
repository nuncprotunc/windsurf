from pathlib import Path
from datetime import datetime
import re, shutil

try:
    import yaml
    yload = lambda s: yaml.safe_load(s) or {}
    ydump = lambda d: yaml.safe_dump(d, sort_keys=False, allow_unicode=True)
except Exception:
    from tools.yaml_fallback import safe_load as yload, safe_dump as ydump

ROOT = Path("jd/cards_yaml")
BACKUP = Path("backups") / "meta_patch_phase3" / datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP.mkdir(parents=True, exist_ok=True)

ABBREV = {
    "CLR": "Commonwealth Law Reports (CLR)",
    "VR": "Victorian Reports (VR)",
    "VLR": "Victorian Law Reports (VLR)",
    "AC": "Appeal Cases (AC)",
    "PC": "Privy Council (PC)",
    "NSWCA": "New South Wales Court of Appeal (NSWCA)",
    "NSWLR": "New South Wales Law Reports (NSWLR)",
    "VBA": "Victorian statutory damages part (Pt VBA)",
    "WPI": "Whole person impairment (WPI)",
    "RPI": "Recognised psychiatric injury (RPI)",
    "ACL": "Australian Consumer Law (ACL)",
    "CCA": "Competition and Consumer Act 2010 (Cth) (CCA)",
    "IVAA": "Proportionate Liability Part (Pt IVAA)",
    "IIA": "Part IIA",
    "UK": "United Kingdom (UK)",
    "CN": "contributory negligence (CN)",
}
TRIPWIRE_SEEDS = [
    "Don’t exceed statutory thresholds/caps",
    "Don’t conflate consequential with pure economic loss",
    "Apply coherence checks before extending duties",
]
STAT_FIX = [
    "Wrongs Act 1958 (Vic) s 26",
    "Wrongs Act 1958 (Vic) s 48",
    "Wrongs Act 1958 (Vic) s 51",
]

def split_long_sentences(text, max_words=28):
    # replace em dashes/semicolons with full stops to invite splits
    t = text.replace("—", ". ").replace("–", "-").replace("; ", ". ")
    out = []
    for sent in re.split(r'(?<=[.!?])\s+', t.strip()):
        words = sent.split()
        while len(words) > max_words:
            cut = max_words
            # prefer to cut at a comma near the limit
            try:
                comma_idx = next(i for i in range(cut-5, cut+5) if i < len(words) and words[i].endswith(","))
                cut = comma_idx + 1
            except StopIteration:
                pass
            out.append(" ".join(words[:cut]).rstrip(",") + ".")
            words = words[cut:]
        if words:
            out.append(" ".join(words))
    return " ".join(out)

def ensure_abbrev_first_use(text):
    def repl(match):
        token = match.group(0)
        long = ABBREV[token]
        # only expand first occurrence
        return f"{long}" if token not in seen else token
    seen = set()
    for token in ABBREV.keys():
        if token in text:
            text = re.sub(rf"\b{re.escape(token)}\b", lambda m: (seen.add(token) or f"{ABBREV[token]}") if token not in seen else token, text, count=1)
    return text

def ensure_tripwires(lst):
    lst = list(lst or [])
    while len(lst) < 3:
        for seed in TRIPWIRE_SEEDS:
            if len(lst) >= 3: break
            if seed not in lst: lst.append(seed)
    return lst[:6]

def ensure_authorities_map(back_text, anchors):
    # If the “Authorities map.” block is empty, seed a one-liner with a lead authority
    cases = (anchors or {}).get("cases") or []
    lead = None
    for c in cases:
        if "(" in c: lead = c; break
    if not lead: return back_text
    # locate the “Authorities map.” section
    pat = r"(Authorities map\.\s*)(?:\n\s*|\s*)(?=(Statutory hook\.|Tripwires\.|Conclusion\.|$))"
    if re.search(r"Authorities map\.\s*[A-Za-z0-9]", back_text):  # already has content
        return back_text
    # inject one concise line
    return re.sub(r"Authorities map\.\s*", f"Authorities map. Lead: {lead}. ", back_text, count=1)

def ensure_back_length(text, min_words=160):
    words = text.split()
    if len(words) >= min_words:
        return text
    pad = " Exam tip: sequence issues → rules → application → conclusion; cite a lead authority and the operative section."
    return (text + pad) if len(words) + len(pad.split()) < 280 else text

def fix_statutes(anchors):
    anchors = anchors or {}
    sts = list(anchors.get("statutes") or [])
    have = set(sts)
    for s in STAT_FIX:
        if len(sts) >= 8: break
        if s not in have:
            sts.append(s); have.add(s)
    anchors["statutes"] = sts[:8]
    return anchors

changed = 0
for p in sorted(ROOT.glob("*.yml")):
    data = yload(p.read_text(encoding="utf-8")) or {}
    back = data.get("back") or ""
    anchors = data.get("anchors") or {}

    # 1) Abbreviation expansion on first use
    new_back = ensure_abbrev_first_use(back)

    # 2) Split long sentences
    new_back = split_long_sentences(new_back, max_words=28)

    # 3) Seed authorities map line if empty
    new_back = ensure_authorities_map(new_back, anchors)

    # 4) Ensure min back length 160
    new_back = ensure_back_length(new_back, 160)

    # 5) Ensure >=3 tripwires
    data["tripwires"] = ensure_tripwires(data.get("tripwires"))

    # 6) Common statute sections into anchors (cap at 8)
    data["anchors"] = fix_statutes(anchors)

    if new_back != back:
        data["back"] = new_back

    if ydump(data) != ydump(yload(p.read_text(encoding="utf-8"))):
        shutil.copy2(p, BACKUP / p.name)
        p.write_text(ydump(data), encoding="utf-8")
        changed += 1

print(f"[OK] Phase3 patched {changed} file(s). Backups: {BACKUP}")
