"""FastAPI service exposing search and fetch endpoints for pinpoint verification."""

from __future__ import annotations

import logging
from typing import Iterable, List, Sequence

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from tools.legal_pinpoint_pipeline import (
    CaseSearchClient,
    LegalDocumentFetcher,
    Paragraph,
)

LOGGER = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    """Incoming payload for the search endpoint."""

    query: str = Field(..., min_length=1, description="Search query for case law.")
    limit: int | None = Field(
        None,
        ge=1,
        le=50,
        description="Maximum number of unique URLs to return across all sources.",
    )


class SearchResponse(BaseModel):
    """Search response payload."""

    urls: List[str]


class FetchRequest(BaseModel):
    """Incoming payload for the fetch endpoint."""

    url: str = Field(..., min_length=1, description="Absolute URL to the judgment.")


class ParagraphModel(BaseModel):
    """Serialized paragraph structure returned to clients."""

    para_no: str
    text: str


class FetchResponse(BaseModel):
    """Fetch response payload."""

    paragraphs: List[ParagraphModel]


class MultiLibrarySearch:
    """Aggregate search results from multiple library clients."""

    def __init__(self, clients: Sequence[object]) -> None:
        self._clients = list(clients)

    def search(self, query: str, *, limit: int = 5) -> List[str]:
        seen: set[str] = set()
        ordered: List[str] = []
        for client in self._clients:
            try:
                hits = _call_search(client, query, limit)
            except Exception as exc:  # pragma: no cover - network errors.
                LOGGER.warning("Search client %s failed: %s", client.__class__.__name__, exc)
                continue
            for url in hits:
                if url in seen:
                    continue
                seen.add(url)
                ordered.append(url)
                if len(ordered) >= limit:
                    return ordered
        return ordered


class JadeSearchClient:
    """Placeholder JADE search client.

    JADE requires authenticated access for programmatic search.  The implementation
    therefore returns an empty list by default while providing a hook for future
    integrations.
    """

    def search_cases(self, query: str, limit: int = 5) -> List[str]:  # pragma: no cover - stub
        LOGGER.debug("JADE search not configured; returning no results for query=%s", query)
        return []


class BailiiSearchClient:
    """Placeholder BAILII search client pending official API support."""

    def search_cases(self, query: str, limit: int = 5) -> List[str]:  # pragma: no cover - stub
        LOGGER.debug("BAILII search not configured; returning no results for query=%s", query)
        return []


def _call_search(client: object, query: str, limit: int) -> Iterable[str]:
    """Invoke ``search_cases`` while handling optional ``limit`` arguments."""

    try:
        return client.search_cases(query, limit=limit)
    except TypeError:
        return client.search_cases(query)


def get_search_aggregator() -> MultiLibrarySearch:
    return _SEARCH_AGGREGATOR


def get_fetcher() -> LegalDocumentFetcher:
    return _FETCHER


app = FastAPI(title="Windsurf Pinpoint Service", version="1.0.0")


@app.post("/search_cases", response_model=SearchResponse)
def search_cases(
    payload: SearchRequest,
    aggregator: MultiLibrarySearch = Depends(get_search_aggregator),
) -> SearchResponse:
    limit = payload.limit or 5
    urls = aggregator.search(payload.query, limit=limit)
    return SearchResponse(urls=urls)


@app.post("/fetch_and_normalise", response_model=FetchResponse)
def fetch_and_normalise(
    payload: FetchRequest,
    fetcher: LegalDocumentFetcher = Depends(get_fetcher),
) -> FetchResponse:
    paragraphs = fetcher.fetch_and_normalise(payload.url)
    if not paragraphs:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document could not be normalised or contained no paragraphs.",
        )
    return FetchResponse(paragraphs=[_serialize_paragraph(p) for p in paragraphs])


def _serialize_paragraph(paragraph: Paragraph) -> ParagraphModel:
    return ParagraphModel(para_no=paragraph.para_no, text=paragraph.text)


_AUSTLII_CLIENT = CaseSearchClient()
_JADE_CLIENT = JadeSearchClient()
_BAILII_CLIENT = BailiiSearchClient()
_SEARCH_AGGREGATOR = MultiLibrarySearch([_AUSTLII_CLIENT, _JADE_CLIENT, _BAILII_CLIENT])
_FETCHER = LegalDocumentFetcher()


__all__ = [
    "app",
    "MultiLibrarySearch",
    "SearchRequest",
    "SearchResponse",
    "FetchRequest",
    "FetchResponse",
    "get_search_aggregator",
    "get_fetcher",
]

