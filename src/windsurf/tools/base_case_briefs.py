"""Robust batch generator for Windsurf base case briefs.

The module is designed to run unattended for long stretches.  It keeps
running even if individual cases fail, records useful telemetry, and can be
safely resumed after an interruption.  The code is intentionally defensive
and keeps side-effects (file system + API calls) contained in the higher
level helpers so that individual components remain testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

try:  # pragma: no cover - exercised in integration only
    from openai import OpenAI  # type: ignore
except Exception as exc:  # pragma: no cover - exercised in integration only
    raise RuntimeError(
        "OpenAI SDK not available. Install with `pip install openai`."
    ) from exc


# ---------------------------------------------------------------------------
# Configuration knobs (tuned for reliability)
# ---------------------------------------------------------------------------
MAX_CHARS_PRIMARY = 4000  # first attempt excerpt cap
MAX_CHARS_RETRY = 2500  # fallback excerpt cap
MAX_PAGES = 4  # cap hot pages sampled
MODEL = "gpt-4o-mini"
MAX_TOKENS_FULL = 340
MAX_TOKENS_MIN = 220

PROJECT_ROOT = Path.cwd()
OUT_DIR = PROJECT_ROOT / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OK_PATH = OUT_DIR / "case_briefs.jsonl"
FAIL_PATH = OUT_DIR / "failed_responses.jsonl"
STATUS_LOG = OUT_DIR / "batch_status.log"


# ---------------------------------------------------------------------------
# Prompt templates (primary + deterministic fallback)
# ---------------------------------------------------------------------------
PROMPT_FULL = """Return compact JSON with keys:
citation, court, year, jurisdiction,
holding (<=80 words),
props (<=2; each {{quote, pinpoint, gloss}}),
tags (<=4 from duty, breach, causation, remoteness, psych_harm, nuisance, trespass, econ_loss, vicarious),
tripwires (<=1 pitfall),
persuasive (Yes/No vs Vic/HCA),
confidence (0–1).
Rules: Only use provided text. Leave "" if missing. ≤220 tokens.

FILE: {filename}
EXCERPT:
<<<{excerpt}>>>"""

PROMPT_MIN = """Return compact JSON with keys:
citation, court, year, jurisdiction, holding (<=60 words), confidence (0–1).
Rules: Only use provided text. Leave "" if missing. ≤160 tokens.

FILE: {filename}
EXCERPT:
<<<{excerpt}>>>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def trim_excerpt(text: str, limit: int) -> str:
    """Trim *text* to *limit* characters trying not to cut mid-sentence."""

    if len(text) <= limit:
        return text

    cut = text[:limit]
    dot = cut.rfind(". ")
    if dot > 0:
        return cut[: dot + 1]
    return cut


def log_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    """Append *obj* as JSON to *path*, creating the file if required."""

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_done(path: Path) -> set[str]:
    """Return set of file names that already have an entry in *path*."""

    done: set[str] = set()
    if not path.exists():
        return done

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                done.add(json.loads(line)["file"])
            except Exception:
                # Ignore malformed lines – they are logged separately.
                continue
    return done


# ---------------------------------------------------------------------------
# Page selection
# ---------------------------------------------------------------------------
def score_pages_for_relevance(pages: Sequence[str]) -> List[Tuple[float, str]]:
    """Simple relevance proxy used if the project does not provide one.

    The default prefers longer pages (up to 5k characters).  Projects that
    maintain their own scorer can monkey-patch or replace this function.
    """

    scored: List[Tuple[float, str]] = []
    for page in pages:
        score = min(len(page), 5000) / 5000.0
        scored.append((score, page))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def pick_hot_pages(pages: Sequence[str], max_pages: int = MAX_PAGES) -> List[str]:
    """Return the *max_pages* highest scoring pages."""

    scored = score_pages_for_relevance(pages)
    return [page for _, page in scored[:max_pages]]


# ---------------------------------------------------------------------------
# Model wrapper
# ---------------------------------------------------------------------------
_client = OpenAI()


def ask_model(prompt: str, *, model: str = MODEL, max_tokens: int = MAX_TOKENS_FULL) -> str:
    """Call the chat completion endpoint and return the raw JSON string."""

    response = _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are an Australian torts case auditor."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def parse_json_or_raise(raw: str) -> Dict[str, Any]:
    """Normalise and validate the model response."""

    data = json.loads(raw.strip())
    data.setdefault("props", [])
    data.setdefault("tags", [])
    data.setdefault("tripwires", [])
    return data


@dataclass
class QueryMeta:
    attempt: str
    raw_len: int


def query_case(filename: str, sample_text: str) -> Tuple[Dict[str, Any], QueryMeta]:
    """Query the model with progressively simpler prompts/excerpts."""

    prompt_full_primary = PROMPT_FULL.format(
        filename=filename, excerpt=trim_excerpt(sample_text, MAX_CHARS_PRIMARY)
    )
    try:
        raw1 = ask_model(prompt_full_primary, max_tokens=MAX_TOKENS_FULL)
        data1 = parse_json_or_raise(raw1)
        return data1, QueryMeta("full/4k", len(raw1))
    except Exception:
        prompt_full_retry = PROMPT_FULL.format(
            filename=filename, excerpt=trim_excerpt(sample_text, MAX_CHARS_RETRY)
        )
        try:
            raw2 = ask_model(prompt_full_retry, max_tokens=MAX_TOKENS_FULL)
            data2 = parse_json_or_raise(raw2)
            return data2, QueryMeta("full/2.5k", len(raw2))
        except Exception:
            prompt_min = PROMPT_MIN.format(
                filename=filename, excerpt=trim_excerpt(sample_text, MAX_CHARS_RETRY)
            )
            raw3 = ask_model(prompt_min, max_tokens=MAX_TOKENS_MIN)
            data3 = parse_json_or_raise(raw3)
            return data3, QueryMeta("min/2.5k", len(raw3))


def run_case(doc: Dict[str, Any]) -> None:
    """Process a single case document, logging success or failure."""

    filename = doc["filename"]
    pages: Sequence[str] = doc.get("pages", [])
    hot_pages = pick_hot_pages(pages, MAX_PAGES)
    sample = "\n\n".join(hot_pages)

    try:
        data, meta = query_case(filename, sample)
        log_jsonl(OK_PATH, {"file": filename, "data": data})
        log_jsonl(STATUS_LOG, {"file": filename, "status": "ok", "attempt": meta.attempt})
    except Exception as exc:  # Broad by design – we log & continue.
        log_jsonl(
            FAIL_PATH,
            {
                "file": filename,
                "error": str(exc),
                "sample_len": len(sample),
                "sample_head": sample[:200],
            },
        )
        log_jsonl(
            STATUS_LOG,
            {"file": filename, "status": "fail", "error": str(exc)},
        )


def _load_docs_from_jsonl(path: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict) and "filename" in item and "pages" in item:
                docs.append(item)
    return docs


def load_documents() -> List[Dict[str, Any]]:
    """Load case documents using the preferred project mechanism."""

    try:
        from src.windsurf.tools.doc_loader import load_case_pdfs  # type: ignore

        docs = load_case_pdfs()
        if not isinstance(docs, Iterable):  # pragma: no cover - defensive
            raise TypeError("load_case_pdfs() must return an iterable")
        return list(docs)
    except Exception:
        fallback = OUT_DIR / "cases.jsonl"
        if not fallback.exists():
            raise RuntimeError(
                "No document loader found. Provide `load_case_pdfs()` or create "
                "outputs/cases.jsonl with objects: {\"filename\": str, \"pages\": [str, ...]}"
            )
        return _load_docs_from_jsonl(fallback)


def main() -> None:
    """Entry point used by the CLI script."""

    docs = load_documents()
    done_ok = load_done(OK_PATH)

    for doc in docs:
        filename = doc.get("filename")
        if not filename:
            continue
        if filename in done_ok:
            continue
        run_case(doc)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
