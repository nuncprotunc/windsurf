import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from service.api import (
    MultiLibrarySearch,
    app,
    get_fetcher,
    get_search_aggregator,
)
from tools.legal_pinpoint_pipeline import Paragraph


class _StubClient:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def search_cases(self, query, limit=5):
        self.calls.append((query, limit))
        return list(self.outputs)


def test_multi_library_search_combines_sources():
    client_a = _StubClient(["https://a.example", "https://shared.example"])
    client_b = _StubClient(["https://shared.example", "https://b.example"])
    aggregator = MultiLibrarySearch([client_a, client_b])

    urls = aggregator.search("Rootes", limit=3)

    assert urls == ["https://a.example", "https://shared.example", "https://b.example"]
    assert client_a.calls == [("Rootes", 3)]
    assert client_b.calls == [("Rootes", 3)]


def test_search_endpoint_uses_aggregator():
    class _FakeAggregator:
        def __init__(self):
            self.queries = []

        def search(self, query, limit=5):
            self.queries.append((query, limit))
            return ["https://example.com"]

    aggregator = _FakeAggregator()
    app.dependency_overrides[get_search_aggregator] = lambda: aggregator
    client = TestClient(app)

    response = client.post("/search_cases", json={"query": "Rootes", "limit": 4})

    assert response.status_code == 200
    assert response.json() == {"urls": ["https://example.com"]}
    assert aggregator.queries == [("Rootes", 4)]

    app.dependency_overrides.clear()


def test_fetch_endpoint_serialises_paragraphs():
    class _FakeFetcher:
        def __init__(self):
            self.urls = []

        def fetch_and_normalise(self, url):
            self.urls.append(url)
            return [
                Paragraph(para_no="[1]", text="First paragraph text."),
                Paragraph(para_no="[2]", text="Second paragraph text."),
            ]

    fetcher = _FakeFetcher()
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    client = TestClient(app)

    response = client.post(
        "/fetch_and_normalise",
        json={"url": "https://austlii.example/doc.html"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "paragraphs": [
            {"para_no": "[1]", "text": "First paragraph text."},
            {"para_no": "[2]", "text": "Second paragraph text."},
        ]
    }
    assert fetcher.urls == ["https://austlii.example/doc.html"]

    app.dependency_overrides.clear()


def test_fetch_endpoint_returns_error_when_empty():
    class _EmptyFetcher:
        def fetch_and_normalise(self, url):
            return []

    app.dependency_overrides[get_fetcher] = lambda: _EmptyFetcher()
    client = TestClient(app)

    response = client.post("/fetch_and_normalise", json={"url": "https://example.com"})

    assert response.status_code == 502
    assert response.json()["detail"].startswith("Document could not be normalised")

    app.dependency_overrides.clear()
