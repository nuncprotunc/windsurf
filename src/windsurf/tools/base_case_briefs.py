import os, json, re, sys, glob, fitz, pandas as pd, time, logging
from datetime import datetime
from pathlib import Path
from striprtf.striprtf import rtf_to_text
from openai import OpenAI

# Paths
ROOT = Path(r"D:\Code\windsurf")
CASES_DIR = ROOT / "cases"
OUT_DIR = ROOT / "outputs"; OUT_DIR.mkdir(parents=True, exist_ok=True)
JSONL = OUT_DIR / "case_cards.jsonl"
CSV   = OUT_DIR / "case_cards.csv"
LOG   = OUT_DIR / "batch_status.log"
FAILED_LOG = OUT_DIR / "failed_responses.jsonl"

# Logging
logging.basicConfig(filename=LOG, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
print(f"Logging to {LOG}")

# API client
client = OpenAI()  # requires $env:OPENAI_API_KEY

# Regex to find "hot" pages
HOT_PAT = re.compile(r"\b(held|ratio|reason|foreseeab|salient|Wrongs Act|s\s*48|s\s*51|trespass|nuisance|wagon\s+mound|psychi|econ|remoteness)\b", re.I)

def read_pdf_text(path: Path):
    pages = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc):
            txt = page.get_text("text")
            if txt: pages.append((i+1, txt))
    return pages

def read_rtf_text(path: Path):
    try:
        raw = path.read_text(errors="ignore")
    except Exception as exc:
        logging.error(f"[err] failed to read RTF {path.name}: {exc}")
        return []
    return [(1, rtf_to_text(raw))]

def pick_hot_pages(pages, max_chars=6000, max_pages=4):
    picks = [pages[0]] if pages else []
    hits = [p for p in pages[1:] if HOT_PAT.search(p[1])]
    for p in hits:
        if p not in picks: picks.append(p)
        if len(picks) >= max_pages: break
    buf, kept = "", []
    for n, t in picks:
        if len(buf) + len(t) > max_chars: break
        buf += t; kept.append((n,t))
    return kept


SKIP_PAT = re.compile(r"(BarNet|jade\.io|Publication number|User:|Date:|This is not legal advice)", re.I)


def clean_page_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if SKIP_PAT.search(stripped):
            continue
        lines.append(line)
    return "\n".join(lines)

PRIMARY_PROMPT = """Return compact JSON with keys:
citation (AGLC4 if possible),
court, year, jurisdiction,
holding (<=70 words),
props (<=2; each {quote, pinpoint, gloss}),
tags (<=4 from duty, breach, causation, remoteness, psych_harm, nuisance, trespass, econ_loss, vicarious),
tripwires (0-2 distinct pitfalls, optional),
persuasive (Yes/No vs Vic/HCA),
confidence (0–1).
Rules: Only use provided text. Leave "" if missing. ≤220 tokens."""

FALLBACK_PROMPT = """Return compact JSON with keys:
citation,
court,
year,
jurisdiction,
holding (<=60 words),
ratio {proposition, support_pinpoint},
confidence (0–1).
Rules: Use only provided text. If unsure, leave fields "". ≤200 tokens."""


def call_mini(prompt: str, user: str, max_tokens: int = 320, retries: int = 3, delay: int = 5):
    """Call API with retries and basic backoff."""
    for attempt in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are an Australian torts case auditor."},
                    {"role": "user", "content": f"{prompt}\n\n{user}"},
                ],
            )
            payload = resp.choices[0].message.content
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            logging.warning(f"JSON decode failed: {exc}")
            with FAILED_LOG.open("a", encoding="utf-8") as fw:
                fw.write(
                    json.dumps(
                        {
                            "error": "bad_json",
                            "detail": str(exc),
                            "payload": payload,
                            "prompt": prompt,
                            "attempt": attempt,
                        }
                    )
                    + "\n"
                )
            )
        except Exception as e:  # includes API errors/timeouts
            logging.warning(f"Attempt {attempt} failed: {e}")
            time.sleep(delay * attempt)  # exponential-ish backoff
    return {"error": "max_retries_exceeded"}
                        continue
                except Exception as exc:
                    continue
            except Exception as exc:
                logging.error(f"[fail] {f.name}: primary prompt failed ({exc})")
                continue

            if js.get("error"):
                logging.error(f"[fail] {f.name}: {js['error']}")
                continue

            rec = {"file": f.name, **js}
            with JSONL.open("a", encoding="utf-8") as w:
                w.write(json.dumps(rec, ensure_ascii=False) + "\n")

            # Append summary row
            tags = ",".join(rec.get("tags",[])) if isinstance(rec.get("tags"), list) else ""
            tripwires = "|".join(rec.get("tripwires",[])) if isinstance(rec.get("tripwires"), list) else ""
            rows.append({
                "file": f.name,
                "citation": rec.get("citation",""),
                "holding": rec.get("holding",""),
                "tags": tags,
                "tripwires": tripwires,
                "confidence": rec.get("confidence",""),
                "run_ts": datetime.utcnow().isoformat(timespec="seconds"),
            })
            logging.info(f"[ok] {f.name}")
        except Exception as e:
            logging.error(f"[err] {f.name}: {e}")

    if rows:
        pd.DataFrame(rows).to_csv(CSV, index=False, encoding="utf-8")
        logging.info(f"Finished. Wrote {JSONL} and {CSV}")
        print(f"\nWrote {JSONL} and {CSV}")
    else:
        logging.error("No rows produced!")

if __name__ == "__main__":
    main()
