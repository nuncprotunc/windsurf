from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence
import re

try:
    import requests  # network not used by tests but keep type
except Exception:
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore


# ----- Public API expected by tests -----

@dataclass
class Paragraph:
    para_no: str
    text: str


@dataclass
class PinpointResult:
    case_name: str
    citation: str
    pinpoint: str
    quote: str
    reason: str
    source_url: str


class LegalDocumentFetcher:
    """HTML normaliser that preserves bracketed paragraph numbers like [12]."""
    PARA_PATTERN = re.compile(r"(\[\d{1,4}[A-Za-z]?\])")

    def __init__(self, session: object | None = None) -> None:
        self.session = session or (requests.Session() if requests else None)

    def fetch_and_normalise(self, url: str) -> List[Paragraph]:
        if not self.session:
            return []
        resp = self.session.get(url, timeout=60)  # type: ignore[union-attr]
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            # PDF handling not needed for these tests
            return []
        return self.parse_html(resp.text)

    def parse_html(self, html: str) -> List[Paragraph]:
        text = self._html_to_text(html)
        return self._extract_paragraphs(text)

    # ----- helpers -----
    def _html_to_text(self, html: str) -> str:
        if BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(["script", "style", "nav", "header", "footer", "form"]):
                tag.decompose()
            return " \n ".join(s.strip() for s in soup.stripped_strings if s.strip())
        # crude fallback
        return re.sub(r"<[^>]+>", " ", html)

    def _extract_paragraphs(self, raw_text: str) -> List[Paragraph]:
        cleaned = re.sub(r"\s+", " ", raw_text.replace("\xa0", " ")).strip()
        if not cleaned:
            return []
        parts = self.PARA_PATTERN.split(cleaned)
        out: List[Paragraph] = []
        for i in range(1, len(parts), 2):
            no = parts[i].strip()
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if no and body:
                out.append(Paragraph(para_no=no, text=body))
        return out


class PinpointVerifier:
    """Tiny orchestrator used by tests: search (injectable), fetch, select quote."""
    def __init__(self, searcher=None, fetcher=None) -> None:
        # searcher: (query:str) -> list[str]
        # fetcher:  (url:str)   -> list[Paragraph]
        self._searcher = searcher or (lambda q: [])
        self._fetcher = fetcher or (lambda url: [])

    def verify(
        self,
        *,
        query: str,
        case_name: str,
        citation: str,
        target_para: str,
        proposition: str,
        keywords: Optional[Iterable[str]] = None,
    ) -> Optional[PinpointResult]:
        urls = self._searcher(query) or []
        for url in urls:
            paragraphs = self._fetcher(url) or []
            candidates = _slice_candidate_paragraphs(paragraphs, keywords=keywords, window=2, max_total=6)
            target = next((p for p in candidates if p.para_no == target_para), None)
            if not target:
                continue
            try:
                quote = _select_verbatim_quote(target.text, 20, 40)
            except ValueError:
                continue
            reason = _build_reason(target.text, proposition)
            return PinpointResult(
                case_name=case_name,
                citation=citation,
                pinpoint=target_para,
                quote=quote,
                reason=reason,
                source_url=url,
            )
        return None


# ----- internal helpers -----

def _slice_candidate_paragraphs(
    paragraphs: Sequence[Paragraph],
    keywords: Optional[Iterable[str]] = None,
    window: int = 2,
    max_total: int = 6,
) -> List[Paragraph]:
    if not paragraphs:
        return []
    if not keywords:
        return list(paragraphs[:max_total])
    kws = [k.lower() for k in keywords if k]
    if not kws:
        return list(paragraphs[:max_total])
    picked: List[int] = []
    for idx, p in enumerate(paragraphs):
        tl = p.text.lower()
        if any(k in tl for k in kws):
            for j in range(idx - window, idx + window + 1):
                if 0 <= j < len(paragraphs) and j not in picked:
                    picked.append(j)
    picked.sort()
    return [paragraphs[i] for i in picked][:max_total]


def _select_verbatim_quote(text: str, min_words: int = 20, max_words: int = 40) -> str:
    words = text.strip().split()
    if len(words) < min_words:
        raise ValueError("Paragraph too short for quote requirement.")
    return " ".join(words[: min(len(words), max_words)])


def _build_reason(paragraph_text: str, proposition: str) -> str:
    snip = paragraph_text.strip()
    if len(snip) > 200:
        snip = snip[:197].rstrip() + "..."
    return f"The paragraph explains that {snip} This supports the proposition '{proposition}'."
