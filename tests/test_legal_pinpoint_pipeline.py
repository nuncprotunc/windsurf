import textwrap
from pathlib import Path

import pytest

import tools.legal_pinpoint_pipeline as pipeline

from tools.legal_pinpoint_pipeline import (
    CaseSearchClient,
    LegalDocumentFetcher,
    Paragraph,
    PinpointResult,
    PinpointVerifier,
    build_pinpoint_prompt,
    slice_candidate_paragraphs,
)


network = pytest.mark.network
openai_mark = pytest.mark.openai


class DummyResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/html"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class DummySession:
    def __init__(self, response: DummyResponse):
        self._response = response
        self.requested = False

    def get(self, *_args, **_kwargs):
        self.requested = True
        return self._response


@network
def test_search_client_extracts_austlii_links():
    html = textwrap.dedent(
        """
        <html>
            <body>
                <a href="/cgi-bin/viewdoc/au/cases/cth/HCA/1966/8.html">Rootes v Shelton</a>
                <a href="https://www.example.com/not-a-case">Ignore me</a>
                <a href="/cgi-bin/viewdoc/au/cases/cth/HCA/1964/64.pdf">PDF Result</a>
            </body>
        </html>
        """
    )
    session = DummySession(DummyResponse(html))
    client = CaseSearchClient(session=session)
    results = client.search_cases("Rootes v Shelton")

    assert session.requested is True
    assert len(results) == 2
    assert results[0].endswith("HCA/1966/8.html")
    assert results[1].endswith("HCA/1964/64.pdf")


def test_search_client_extracts_links_offline():
    html = textwrap.dedent(
        """
        <html>
            <body>
                <a href="/cgi-bin/viewdoc/au/cases/cth/HCA/1966/8.html">Rootes v Shelton</a>
                <a href="https://www.example.com/not-a-case">Ignore me</a>
            </body>
        </html>
        """
    )
    session = DummySession(DummyResponse(html))
    client = CaseSearchClient(session=session)

    results = client.search_cases("Rootes v Shelton")

    assert results == [
        "https://www.austlii.edu.au/cgi-bin/viewdoc/au/cases/cth/HCA/1966/8.html"
    ]


def test_fetcher_extracts_html_paragraphs():
    html = textwrap.dedent(
        """
        <html>
            <body>
                <div class="nav">Navigation</div>
                <p>[1] Volenti requires knowledge of the risk.</p>
                <p>[2] [sic] Another paragraph.</p>
                <footer>© AustLII</footer>
            </body>
        </html>
        """
    )
    fetcher = LegalDocumentFetcher(session=DummySession(DummyResponse(html)))
    paragraphs = fetcher.parse_html(html)

    assert paragraphs == [
        Paragraph(para_no="[1]", text="Volenti requires knowledge of the risk."),
        Paragraph(para_no="[2]", text="[sic] Another paragraph."),
    ]


def test_slice_candidate_paragraphs_limits_results():
    paragraphs = [
        Paragraph(para_no=f"[{idx}]", text=f"Paragraph {idx} tort law")
        for idx in range(1, 8)
    ]
    result = slice_candidate_paragraphs(paragraphs, keywords=["tort"], window=1, max_total=3)

    assert len(result) == 3
    assert result[0].para_no == "[1]"
    assert result[-1].para_no == "[3]"


def test_build_pinpoint_prompt_requires_paragraphs():
    paragraphs = [Paragraph(para_no="[12]", text="Test paragraph for volenti.")]
    prompt = build_pinpoint_prompt(paragraphs, "Rootes v Shelton", "Volenti defence")

    assert "Rootes v Shelton" in prompt
    assert "[12] Test paragraph" in prompt

    with pytest.raises(ValueError):
        build_pinpoint_prompt([], "Rootes v Shelton", "Volenti defence")


def test_pinpoint_verifier_returns_result_when_target_found():
    long_text = (
        "Knowledge of the precise risk is emphasised repeatedly in this paragraph, "
        "explaining that a plaintiff who understands the danger and willingly "
        "accepts it cannot later complain about the outcome of that risk materialising "
        "during the activity they chose to undertake."
    )
    paragraphs = [
        Paragraph(para_no="[1]", text="Introductory material that sets context."),
        Paragraph(para_no="[2]", text=long_text),
    ]

    def fake_searcher(_query: str):
        return ["https://example.com/case"]

    def fake_fetcher(_url: str):
        return paragraphs

    verifier = PinpointVerifier(searcher=fake_searcher, fetcher=fake_fetcher)
    result = verifier.verify(
        query="Rootes v Shelton volenti",
        case_name="Rootes v Shelton",
        citation="(1966) 116 CLR 383",
        target_para="[2]",
        proposition="Volenti requires conscious acceptance of the risk",
        keywords=["risk"],
    )

    assert result is not None
    assert isinstance(result, PinpointResult)
    assert result.pinpoint == "[2]"
    assert result.source_url == "https://example.com/case"
    assert 20 <= len(result.quote.split()) <= 40


def test_select_verbatim_quote_raises_when_too_short():
    with pytest.raises(ValueError):
        pipeline._select_verbatim_quote("Too short for requirement", min_words=20, max_words=40)


def test_pinpoint_verifier_with_fixture_offline():
    html = Path("tests/fixtures/rootes.html").read_text(encoding="utf-8")
    fetcher = LegalDocumentFetcher()
    paragraphs = fetcher.parse_html(html)

    def fake_searcher(_query: str):
        return ["file://tests/fixtures/rootes.html"]

    def fake_fetcher(_url: str):
        return paragraphs

    verifier = PinpointVerifier(searcher=fake_searcher, fetcher=fake_fetcher)
    result = verifier.verify(
        query="Rootes v Shelton volenti",
        case_name="Rootes v Shelton",
        citation="(1966) 116 CLR 383",
        target_para="[12]",
        proposition="Volenti requires acceptance of obvious sporting risks",
        keywords=["volenti", "risk"],
    )

    assert result is not None
    assert result.quote.startswith("The High Court noted that volenti")
    assert result.source_url.startswith("file://")

