"""Cached public-source collection for an evidence-first company relationship graph."""

import concurrent.futures
import csv
import io
import html
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlparse

from alphacouncil.data.archive import file_sha256, sha256, utc_now, write_json

ROOT = Path("data/knowledge")
USER_AGENT = "AlphaCouncilResearch/0.1 (+https://github.com/buddhsen-tripathi/shipyard)"


class Sources:
    """Immutable URL cache, receipts for failures, at most two request starts/second."""
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.lock, self.last_start = threading.Lock(), 0.

    def get(self, url, maximum_bytes=64 * 1024 * 1024):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in {"localhost", "127.0.0.1"} or re.fullmatch(r"[\d.:]+", parsed.hostname) or parsed.username:
            raise ValueError("Only explicit public HTTPS source URLs are accepted")
        directory = self.root / "raw" / sha256(url.encode())
        receipt_path = directory / "receipt.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            body_path = Path(receipt["path"])
            if file_sha256(body_path) != receipt["sha256"]:
                raise ValueError(f"Cached source hash mismatch: {url}")
            return (body_path if receipt["ok"] else None), receipt
        directory.mkdir(parents=True, exist_ok=True)
        receipt = None
        for attempt in range(3):
            with self.lock:
                delay = .5 - (time.monotonic()-self.last_start)
                if delay > 0:
                    time.sleep(delay)
                self.last_start = time.monotonic()
            started = utc_now()
            status, error, headers, final_url = None, None, {}, url
            complete = True
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    status, final_url = response.status, response.url
                    headers = {key: response.headers.get(key) for key in ("Content-Type", "Content-Length", "Last-Modified", "ETag", "Retry-After")}
                    body = response.read(maximum_bytes+1)
                    if len(body) > maximum_bytes:
                        body, complete, error = body[:maximum_bytes], False, "response_exceeds_byte_limit"
            except urllib.error.HTTPError as exc:
                status, error, body = exc.code, str(exc), exc.read(256_000)
                headers = {"Retry-After": exc.headers.get("Retry-After")}
            except (OSError, ValueError) as exc:
                body, error = str(exc).encode(), str(exc)
            path = directory / f"attempt_{attempt}.response"
            path.write_bytes(body)
            receipt = {"url": url, "final_url": final_url, "request_started_utc": started.isoformat(), "observed_at_utc": utc_now().isoformat(),
                       "http_status": status, "ok": status == 200 and error is None, "error": error, "content_complete": complete,
                       "sha256": sha256(body), "bytes": len(body), "path": str(path), "headers": headers}
            write_json(directory / f"attempt_{attempt}.receipt.json", receipt)
            if receipt["ok"]:
                break
            retry_after = (headers.get("Retry-After") or "")
            if status not in {None, 429, 500, 502, 503, 504} or attempt == 2 or (retry_after.isdigit() and int(retry_after) > 10):
                break
            time.sleep(int(retry_after) if retry_after.isdigit() else 2**attempt)
        write_json(receipt_path, receipt)
        return (Path(receipt["path"]) if receipt["ok"] else None), receipt


def collect_catalog(sources):
    listings, receipts = [], []
    for filename, nasdaq in (("nasdaqlisted.txt", True), ("otherlisted.txt", False)):
        url = "https://www.nasdaqtrader.com/dynamic/SymDir/" + filename
        path, receipt = sources.get(url)
        receipts.append(receipt)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8-sig")
        for row in csv.DictReader(io.StringIO(text), delimiter="|"):
            ticker = row.get("Symbol" if nasdaq else "ACT Symbol", "")
            if not ticker or ticker.startswith("File Creation Time") or row.get("Test Issue") != "N" or row.get("ETF") == "Y":
                continue
            exchange = "NASDAQ" if nasdaq else {"N": "NYSE", "A": "NYSE_AMERICAN", "P": "NYSE_ARCA", "Z": "CBOE", "V": "IEX"}.get(row.get("Exchange"), row.get("Exchange"))
            name = row["Security Name"].strip()
            issuer = re.split(r"\s+-\s+|\s+(?:Class [A-Z] )?(?:Common Stock|Common Shares|Ordinary Shares|American Depositary|Depositary Shares|Preferred Stock|Warrants|Units)\b", name, maxsplit=1, flags=re.I)[0].strip()
            listings.append({"ticker": ticker, "exchange": exchange, "name": name, "issuer_name_from_listing": issuer,
                             "security_id": f"equity:{exchange}:{ticker}", "issuer_id": f"issuer:{exchange}:{ticker}",
                             "instrument_classification": "common_or_ordinary_shares" if re.search(r"common stock|common shares|ordinary shares", name, re.I) else "non_etf_listing_unclassified",
                             "source_url": url, "source_sha256": receipt["sha256"], "first_observed_at_utc": receipt["observed_at_utc"],
                             "metadata": {"identity_resolution": "listing_name_only_not_registered_legal_identity", "source_row": row}})
    write_json(sources.root / "catalog.json", {"listings": listings, "receipts": receipts,
               "scope": "Current US exchange-listed non-ETF securities, test issues excluded; includes ADRs, non-common instruments and non-US issuers. Not a historical constituent list."})
    return listings


def normalized_name(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def gleif_company(sources, company, maximum_children=200):
    name, ticker = company["name"], company["ticker"]
    url = "https://api.gleif.org/api/v1/lei-records?" + urlencode({"filter[entity.legalName]": name, "page[size]": 20})
    path, receipt = sources.get(url)
    result = {"ticker": ticker, "query_name": name, "search_receipt": receipt, "exact_matches": [], "relationships": [], "coverage_gaps": []}
    if path is None:
        result["coverage_gaps"].append("legal_entity_search_unavailable")
        return result
    payload = json.loads(path.read_bytes())
    rows = payload.get("data", [])
    matches = [row for row in rows if normalized_name(row["attributes"]["entity"]["legalName"]["name"]) == normalized_name(name)]
    result["search_total"] = payload.get("meta", {}).get("pagination", {}).get("total")
    # Exact name is a candidate identity link, never definitive security/LEI proof.
    result["exact_matches"] = matches
    if len(matches) != 1:
        result["coverage_gaps"].append("no_unique_exact_legal_name_match")
        return result
    record = matches[0]
    for relationship in ("direct-parent", "ultimate-parent", "direct-children"):
        links = record.get("relationships", {}).get(relationship, {}).get("links", {})
        link = links.get("relationship-record", links.get("relationship-records"))
        if not link:
            result["coverage_gaps"].append(f"{relationship}_not_reported_or_exception")
            continue
        if urlparse(link).hostname != "api.gleif.org" or not urlparse(link).path.startswith("/api/v1/lei-records/"):
            raise ValueError("Unexpected GLEIF relationship URL")
        if relationship == "direct-children":
            link += "?" + urlencode({"page[size]": maximum_children})
        relation_path, relation_receipt = sources.get(link)
        item = {"kind": relationship, "receipt": relation_receipt, "records": []}
        if relation_path:
            relation_payload = json.loads(relation_path.read_bytes())
            data = relation_payload.get("data", [])
            item["records"] = data if isinstance(data, list) else [data] if data else []
            pagination = relation_payload.get("meta", {}).get("pagination", {})
            item["total_available"] = pagination.get("total", len(item["records"]))
            item["truncated"] = item["total_available"] > len(item["records"])
            if item["truncated"]:
                result["coverage_gaps"].append(f"{relationship}_pagination_cap")
        result["relationships"].append(item)
    return result


def collect_gleif(sources, companies):
    directory = sources.root / "gleif"
    directory.mkdir(exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(gleif_company, sources, company): company for company in companies}
        for future in concurrent.futures.as_completed(futures):
            company = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {"ticker": company["ticker"], "query_name": company["name"], "exact_matches": [], "relationships": [], "coverage_gaps": [str(error)]}
            write_json(directory / f"{company['ticker']}.json", result)
            results.append(result)
            print(f"GLEIF {company['ticker']}: {len(result['exact_matches'])} exact-name candidates, {sum(len(item['records']) for item in result['relationships'])} relationship records", flush=True)
    return results


def extract_report(path, destination):
    prefix = path.read_bytes()[:5]
    if prefix == b"%PDF-":
        if shutil.which("pdftotext"):
            subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", str(path), str(destination)], check=True, timeout=90, capture_output=True)
            pages = destination.read_text(errors="replace").split("\f")
            method = "poppler_pdftotext_layout"
        else:
            from pypdf import PdfReader
            pages = [page.extract_text() or "" for page in PdfReader(path).pages]
            method = "pypdf_text"
    else:
        from html.parser import HTMLParser

        class Reader(HTMLParser):
            def __init__(self):
                super().__init__(); self.parts, self.focus, self.hidden, self.focus_depth = [], [], 0, 0
            def add(self, text):
                self.parts.append(text)
                if self.focus_depth: self.focus.append(text)
            def handle_starttag(self, tag, attrs):
                if tag in {"main", "article"}: self.focus_depth += 1
                if tag in {"script", "style", "noscript", "nav", "footer"}: self.hidden += 1
                if not self.hidden and tag in {"p", "div", "br", "tr", "h1", "h2", "h3", "li"}: self.add("\n")
            def handle_endtag(self, tag):
                if tag in {"script", "style", "noscript", "nav", "footer"}: self.hidden = max(0, self.hidden-1)
                if tag in {"main", "article"}: self.focus_depth = max(0, self.focus_depth-1)
            def handle_data(self, data):
                if not self.hidden: self.add(data)
        raw_html = path.read_text(errors="replace")
        reader = Reader();reader.feed(raw_html)
        focused = "".join(reader.focus)
        full = "".join(reader.parts)
        # Some publisher pages use <article> only for related-story cards. A tiny
        # focus region must not replace the actual disclosure outside those cards.
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
        title_parts = re.split(r"\s+[|–—-]\s+", html.unescape(title_match.group(1))) if title_match else []
        title = re.sub(r"\W", "", max(title_parts, key=len)).casefold() if title_parts else ""
        normalized_focus = re.sub(r"\W", "", focused).casefold()
        owns_title = len(title) >= 20 and title[:min(45, len(title))] in normalized_focus
        use_focus = len(focused.strip()) >= 500 and (owns_title or len(focused.strip()) >= len(full.strip())*.25)
        pages, method = [focused if use_focus else full], "html_visible_main_or_article_v5"
    if pages and not pages[-1].strip(): pages.pop()
    if len(pages) > 600:
        raise ValueError("Report exceeds 600-page processing limit; no silent truncation")
    return pages, method


def collect_report(sources, report):
    url = report["document_url"]
    directory = sources.root / "reports" / sha256(url.encode())
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing["status"] == "complete" and file_sha256(Path(existing["pages_path"])) != existing["pages_sha256"]:
            raise ValueError("Extracted report pages were modified")
        if existing["status"] == "complete" and urlparse(url).path.lower().endswith(".pdf") and Path(existing["receipt"]["path"]).read_bytes()[:5] != b"%PDF-":
            existing.update(status="extraction_failed", error="PDF URL returned non-PDF content; rejected wrapper/error page", quality_reclassified_at_utc=utc_now().isoformat())
            write_json(manifest_path, existing)
        if existing.get("extraction_method") not in {"html_visible_text", "html_visible_main_or_article_v2", "html_visible_main_or_article_v3", "html_visible_main_or_article_v4"} or existing["status"] != "complete":
            return existing
    path, receipt = sources.get(url)
    result = {"report": report, "receipt": receipt, "status": "unavailable", "error": receipt.get("error")}
    if path:
        try:
            if urlparse(url).path.lower().endswith(".pdf") and path.read_bytes()[:5] != b"%PDF-":
                raise ValueError("PDF URL returned non-PDF content; rejected wrapper/error page")
            pages, method = extract_report(path, directory / "text.txt")
            if sum(len(page.strip()) for page in pages) < 500:
                raise ValueError("No usable document text (may require OCR)")
            first_text = " ".join(pages[0].split())[:1000].lower()
            if any(marker in first_text for marker in ("site maintenance", "access denied", "site map", "enable javascript and cookies to continue")):
                raise ValueError("Source returned a maintenance, map or access-error page")
            pages_path = directory / "pages.json"
            write_json(pages_path, {"pages": [{"page_number": i+1, "text": page} for i, page in enumerate(pages)]})
            result.update(status="complete", page_count=len(pages), text_characters=sum(map(len, pages)),
                          extraction_method=method, pages_path=str(pages_path), pages_sha256=file_sha256(pages_path),
                          document_scope="landing_or_summary_not_full_report" if report["document_kind"] in {"annual_report", "10-K", "20-F"} and sum(map(len,pages)) < 20_000 else "captured_document_text",
                          warnings=["Text/table extraction is not a verified financial interpretation", "Publication date remains unknown unless explicitly supplied"])
        except Exception as error:
            result.update(status="extraction_failed", error=str(error))
    write_json(manifest_path, result)
    return result


def collect_reports(sources, reports):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(collect_report, sources, report): report for report in reports}
        for future in concurrent.futures.as_completed(futures):
            report = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {"report": report, "status": "failed", "error": str(error)}
            results.append(result)
            print(f"REPORT {report['ticker']}: {result['status']}, {result.get('page_count',0)} pages", flush=True)
    return results
