from pathlib import Path
from scripts.legal_pinpoint_fetcher import LegalDocumentFetcher, PinpointVerifier


def test_pinpoint_offline_fixture():
    html = Path("tests/fixtures/rootes.html").read_text(encoding="utf-8")
    fetcher = LegalDocumentFetcher()
    paragraphs = fetcher.parse_html(html)

    def fake_searcher(_q):
        return ["file://tests/fixtures/rootes.html"]

    def fake_fetcher(_u):
        return paragraphs

    verifier = PinpointVerifier(searcher=fake_searcher, fetcher=fake_fetcher)
    result = verifier.verify(
        query="Rootes v Shelton volenti",
        case_name="Rootes v Shelton",
        citation="(1966) 116 CLR 383",
        target_para="[12]",
        proposition="Volenti requires acceptance of the risk",
        keywords=["volenti", "risk"],
    )

    assert result is not None
    assert result.pinpoint == "[12]"
    assert "volenti" in result.quote.lower()
