"""Utilities for building a legal pinpoint verification pipeline.

The module exposes a small toolkit that mirrors the workflow described in the
user brief:

1. ``CaseSearchClient`` performs a lightweight AustLII style search and returns
   a ranked list of candidate URLs.
2. ``LegalDocumentFetcher`` downloads a judgment (HTML or PDF) and normalises it
   into ``Paragraph`` instances while preserving bracketed paragraph markers.
3. ``slice_candidate_paragraphs`` narrows the document to a handful of
   paragraphs around keyword hits in order to keep token usage low when the
   paragraphs are handed to an LLM.
4. ``build_pinpoint_prompt`` produces a deterministic instruction string that
   forces the model to verify the pinpoint using the provided paragraphs only.

All functionality is synchronous and dependency free beyond the standard Python
libraries listed in ``requirements.txt``.  The public API favours pure
functions to make the behaviours easy to unit test and to integrate into an
OpenAI function-calling loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Iterable, List, Sequence
from urllib.parse import urlencode, urljoin
import logging
import re

try:  # ``requests`` keeps the API ergonomic but is optional.
    import requests  # type: ignore
except Exception:  # pragma: no cover - fallback to urllib when requests missing.
    requests = None
from urllib import request as urllib_request
from urllib.error import HTTPError

try:  # PyMuPDF is preferred because it retains paragraph structure.
    import fitz  # type: ignore
except Exception:  # pragma: no cover - fall back to pdfminer when unavailable.
    fitz = None

try:  # pdfminer.six is the secondary PDF text extractor.
    from pdfminer.high_level import extract_text
except Exception:  # pragma: no cover - pdfminer is optional.
    extract_text = None


LOGGER = logging.getLogger(__name__)


@dataclass
class Paragraph:
    """A normalised paragraph extracted from a judgment."""

    para_no: str
    text: str


@dataclass(frozen=True)
class PinpointResult:
    """Structured response describing a verified pinpoint."""

    case_name: str
    citation: str
    pinpoint: str
    quote: str
    reason: str
    source_url: str


class PinpointVerifier:
    """Orchestrate search, fetch and quote selection for batch verification."""

    def __init__(self, searcher=None, fetcher=None) -> None:
        self._searcher = searcher or CaseSearchClient().search_cases
        self._fetcher = fetcher or LegalDocumentFetcher().fetch_and_normalise

    def verify(
        self,
        *,
        query: str,
        case_name: str,
        citation: str,
        target_para: str,
        proposition: str,
        keywords: Iterable[str] | None = None,
    ) -> PinpointResult | None:
        """Return a ``PinpointResult`` when a matching paragraph is found."""

        urls = self._searcher(query)
        for url in urls:
            try:
                paragraphs = self._fetcher(url)
            except Exception:  # pragma: no cover - network/parse errors handled upstream.
                continue
            candidates = slice_candidate_paragraphs(
                paragraphs,
                keywords=keywords or [],
                window=2,
                max_total=6,
            )
            target = next((para for para in candidates if para.para_no == target_para), None)
            if not target:
                continue
            try:
                quote = _select_verbatim_quote(target.text, min_words=20, max_words=40)
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


class CaseSearchClient:
    """Minimal AustLII style search client.

    The client intentionally keeps the implementation small.  It issues a
    single HTTP request to the AustLII search endpoint and extracts viewable
    document links from the response.  Consumers can subclass or inject a
    custom ``requests.Session`` when they need caching, retries or additional
    logging.
    """

    SEARCH_ENDPOINT = "https://www.austlii.edu.au/cgi-bin/sinosrch.cgi"

    def __init__(self, session: object | None = None) -> None:
        self.session = session or _build_default_session()

    def search_cases(self, query: str, limit: int = 5) -> List[str]:
        """Return up to ``limit`` candidate URLs for ``query``.

        The AustLII search endpoint returns HTML where each search hit lives in
        an ``<a>`` tag pointing at ``/cgi-bin/viewdoc`` (HTML) or ``.pdf``
        documents.  The parser keeps the implementation resilient by accepting
        both patterns and normalising them into absolute URLs.
        """

        params = {
            "query": query,
            "rank": "on",
            "meta": "",
            "mask_path": "au/cases",
        }
        LOGGER.debug("Searching AustLII for query=%s", query)
        try:
            response = self.session.get(self.SEARCH_ENDPOINT, params=params, timeout=30)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - requires network failure.
            LOGGER.warning("Search failed: %s", exc)
            return []
        urls = self._parse_result_links(response.text)
        return urls[:limit]

    def _parse_result_links(self, html: str) -> List[str]:
        parser = _AnchorExtractor()
        parser.feed(html)
        return [urljoin(self.SEARCH_ENDPOINT, link) for link in parser.links]


class LegalDocumentFetcher:
    """Fetch and normalise AustLII/BAILII/JADE documents into paragraphs."""

    PARA_PATTERN = re.compile(r"(\[\d{1,4}[A-Za-z]?\])")

    def __init__(self, session: object | None = None) -> None:
        self.session = session or _build_default_session()

    def fetch_and_normalise(self, url: str) -> List[Paragraph]:
        LOGGER.debug("Fetching document url=%s", url)
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - requires network failure.
            LOGGER.warning("Fetch failed for %s: %s", url, exc)
            return []
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return self._extract_from_pdf(response.content)
        return self.parse_html(response.text)

    def parse_html(self, html: str) -> List[Paragraph]:
        """Normalise HTML text while preserving paragraph numbers."""

        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()
        return self._extract_paragraphs(text)

    def _extract_from_pdf(self, data: bytes) -> List[Paragraph]:
        """Extract and normalise PDF content using PyMuPDF or pdfminer."""

        if fitz is not None:  # pragma: no cover - PyMuPDF is optional in CI.
            with fitz.open(stream=data, filetype="pdf") as doc:
                pages = [page.get_text("text") for page in doc]
            text = "\n".join(pages)
        elif extract_text is not None:
            from io import BytesIO

            text = extract_text(BytesIO(data))
        else:  # pragma: no cover - executed only when both libs missing.
            raise RuntimeError(
                "No PDF extraction backend available. Install PyMuPDF or pdfminer.six."
            )
        return self._extract_paragraphs(text)

    def _extract_paragraphs(self, raw_text: str) -> List[Paragraph]:
        cleaned = re.sub(r"\s+", " ", raw_text.replace("\xa0", " ")).strip()
        if not cleaned:
            return []
        parts = self.PARA_PATTERN.split(cleaned)
        paragraphs: List[Paragraph] = []
        for idx in range(1, len(parts), 2):
            para_no = parts[idx].strip()
            if not para_no:
                continue
            body = parts[idx + 1].strip() if idx + 1 < len(parts) else ""
            if body:
                paragraphs.append(Paragraph(para_no=para_no, text=body))
        return paragraphs


def slice_candidate_paragraphs(
    paragraphs: Sequence[Paragraph],
    keywords: Iterable[str] | None = None,
    window: int = 2,
    max_total: int = 5,
) -> List[Paragraph]:
    """Return a compact list of paragraphs around keyword hits.

    ``keywords`` is case-insensitive.  Every matching paragraph pulls ``window``
    neighbours on both sides.  The resulting slice preserves the document order
    and trims the output to ``max_total`` items to control downstream token
    consumption.
    """

    if not paragraphs:
        return []

    if not keywords:
        return list(paragraphs[:max_total])

    keywords_lower = [kw.lower() for kw in keywords if kw]
    if not keywords_lower:
        return list(paragraphs[:max_total])

    selected: List[int] = []
    for idx, para in enumerate(paragraphs):
        text_lower = para.text.lower()
        if any(keyword in text_lower for keyword in keywords_lower):
            for neighbour in range(idx - window, idx + window + 1):
                if 0 <= neighbour < len(paragraphs) and neighbour not in selected:
                    selected.append(neighbour)

    selected.sort()
    sliced = [paragraphs[i] for i in selected]
    return sliced[:max_total]


def build_pinpoint_prompt(
    paragraphs: Sequence[Paragraph],
    case_name: str,
    proposition: str,
) -> str:
    """Create a deterministic prompt instructing the model to verify a pinpoint."""

    if not paragraphs:
        raise ValueError("No paragraphs supplied for pinpoint verification.")

    para_lines = [f"{para.para_no} {para.text}" for para in paragraphs]
    para_blob = "\n".join(para_lines)
    return (
        "You verify legal pinpoints.\n"
        "Only use the provided paragraphs to respond.\n"
        "Return: case_name, citation (if available), pinpoint (e.g. [42] or [42]-[44]),\n"
        "a 20-40 word verbatim quote, and a justification.\n"
        "If you cannot verify, respond with NO_VERIFIED_AUTHORITY_FOUND.\n\n"
        f"case_name: {case_name}\n"
        f"proposition: {proposition}\n"
        "paragraphs:\n"
        f"{para_blob}"
    )


def build_tool_specification() -> List[dict]:
    """Return a minimal tool specification for OpenAI function-calling."""

    return [
        {
            "type": "function",
            "function": {
                "name": "search_cases",
                "description": "Search AustLII/BAILII/JADE",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_and_normalise",
                "description": "Fetch URL and return [{para_no,text}]",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
    ]


__all__ = [
    "Paragraph",
    "PinpointResult",
    "PinpointVerifier",
    "CaseSearchClient",
    "LegalDocumentFetcher",
    "slice_candidate_paragraphs",
    "build_pinpoint_prompt",
    "build_tool_specification",
]


def _build_default_session() -> object:
    if requests is not None:
        return requests.Session()
    return _UrllibSession()


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        if "viewdoc" not in href and not href.lower().endswith(".pdf"):
            return
        if href not in self.links:
            self.links.append(href)


class _TextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "nav", "header", "footer", "form"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._parts.append(unescape(text))

    def get_text(self) -> str:
        return " \n ".join(self._parts)


class _UrllibResponse:
    def __init__(self, data: bytes, status_code: int, headers: dict[str, str]) -> None:
        self.content = data
        self.status_code = status_code
        self.headers = headers

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="ignore")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP error {self.status_code}")


class _UrllibSession:
    def get(self, url: str, params: dict | None = None, timeout: int = 30) -> _UrllibResponse:
        if params:
            query = urlencode(params)
            url = f"{url}?{query}"
        req = urllib_request.Request(url)
        try:
            with urllib_request.urlopen(req, timeout=timeout) as resp:  # type: ignore[arg-type]
                data = resp.read()
                headers = {k.lower(): v for k, v in resp.headers.items()}
                status = getattr(resp, "status", 200)
        except HTTPError as exc:  # pragma: no cover - network errors are rare in tests.
            data = exc.read()
            headers = {k.lower(): v for k, v in exc.headers.items()}
            status = exc.code
        return _UrllibResponse(data=data, status_code=status, headers=headers)


def _select_verbatim_quote(text: str, *, min_words: int, max_words: int) -> str:
    """Return a verbatim slice of ``text`` containing between ``min`` and ``max`` words."""

    words = text.strip().split()
    if len(words) < min_words:
        raise ValueError("Paragraph text is too short for the verbatim quote requirement.")
    end = min(len(words), max_words)
    quote_words = words[:end]
    return " ".join(quote_words)


def _build_reason(paragraph_text: str, proposition: str) -> str:
    """Compose a short justification linking ``paragraph_text`` to ``proposition``."""

    snippet = paragraph_text.strip()
    if len(snippet) > 200:
        snippet = snippet[:197].rstrip() + "..."
    return (
        f"The paragraph explains that {snippet} This supports the proposition "
        f"'{proposition}'."
    )


