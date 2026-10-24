import io
import urllib.error
from pathlib import Path

import pytest

from alphacouncil.data.archive import sha256
from alphacouncil.knowledge.collect import Sources, collect_catalog, collect_report, extract_report


def test_access_denial_is_captured_cached_and_never_retried(monkeypatch, tmp_path):
    calls = []
    def denied(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"denied"))
    monkeypatch.setattr("urllib.request.urlopen", denied)
    sources = Sources(tmp_path)
    url = "https://www.sec.gov/files/company_tickers_exchange.json"
    assert sources.get(url)[0] is None
    _, receipt = sources.get(url)
    assert calls == [url]
    assert receipt["http_status"] == 403 and not receipt["ok"]
    Path(receipt["path"]).write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        sources.get(url)


def test_html_focus_uses_article_title_and_rejects_related_story_cards(tmp_path):
    title = "An actual production collaboration announcement"
    path = tmp_path / "source.html"
    path.write_text(f'<title>Publisher Inc. - {title}</title><nav>{"menu "*500}</nav><main><h1>{title}</h1>{"actual evidence "*100}</main><footer>footer</footer>')
    pages, _ = extract_report(path, tmp_path/"text.txt")
    assert "actual evidence" in pages[0] and "menu" not in pages[0] and "footer" not in pages[0]
    path.write_text(f'<title>{title} | Publisher</title><div>{title} {"actual evidence "*500}</div><article>{"unrelated story "*50}</article>')
    pages, _ = extract_report(path, tmp_path/"text.txt")
    assert "actual evidence" in pages[0]


def test_pdf_url_returning_http200_html_is_not_a_report(tmp_path):
    source = tmp_path / "response"
    source.write_bytes(b"<html><title>Site Map</title>"+b"not a financial report "*100+b"</html>")
    class FakeSource:
        root = tmp_path
        def get(self, url):
            return source, {"ok": True, "url": url, "path": str(source), "sha256": sha256(source.read_bytes()), "observed_at_utc": "2026-10-24T16:00:00Z"}
    result = collect_report(FakeSource(), {"ticker": "TEST", "document_url": "https://example.test/report.pdf", "document_kind": "annual_report"})
    assert result["status"] == "extraction_failed"
    assert "non-PDF" in result["error"]
    assert "pages_path" not in result


def test_listing_catalog_excludes_etfs_tests_and_footer_without_inventing_domicile(tmp_path):
    nasdaq = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nTST|Toy Company - Common Stock|Q|N|N|100|N|N\nETF|Example ETF|G|N|N|100|Y|N\nFAKE|Test|Q|Y|N|100|N|N\nFile Creation Time: 1024202618:00|||||||\n"
    other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nADR|Foreign Company American Depositary Shares|N|ADR|N|100|N|ADR\n"
    class FakeSource:
        root = tmp_path
        def get(self, url):
            body = nasdaq if url.endswith("nasdaqlisted.txt") else other
            path = tmp_path / url.rsplit("/", 1)[1];path.write_text(body)
            return path, {"ok": True, "url": url, "sha256": sha256(body.encode()), "observed_at_utc": "2026-10-24T16:00:00Z"}
    listings = collect_catalog(FakeSource())
    assert {row["ticker"] for row in listings} == {"TST", "ADR"}
    assert listings[0]["security_id"] != listings[0]["issuer_id"]
    assert "domicile" not in listings[1]
