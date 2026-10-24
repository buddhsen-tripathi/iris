"""Bounded public GET captures; no authentication or order submission."""

import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from alphacouncil.data.archive import sha256, utc_now, write_json

ALLOWED = {
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://api.truemarkets.co/v1/gateway/assets",
    "https://api.truemarkets.co/v1/gateway/assets/availability",
}


def capture(url: str, directory: Path, name: str, maximum_bytes=5_000_000):
    if url not in ALLOWED or Path(name).name != name:
        raise ValueError("Unsupported public context request")
    directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        start = utc_now()
        status, error, headers = None, None, {}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "AlphaCouncilContext/0.1", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=10) as response:
                if urlparse(response.url).hostname != urlparse(url).hostname:
                    raise ValueError("Unexpected public source redirect")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("Public context response exceeds byte limit")
                status = response.status
                headers = {key: response.headers.get(key) for key in ("Date", "Age", "ETag", "Last-Modified")}
        except urllib.error.HTTPError as exc:
            body, status, error = exc.read(maximum_bytes), exc.code, str(exc)
            headers = {"Retry-After": exc.headers.get("Retry-After")}
        except (OSError, ValueError) as exc:
            body, error = str(exc).encode(), str(exc)
        observed = utc_now()
        path = directory / f"{name}_{attempt}.response"
        path.write_bytes(body)
        receipt = {"url": url, "request_started_utc": start.isoformat(), "observed_at_utc": observed.isoformat(),
                   "http_status": status, "sha256": sha256(body), "bytes": len(body), "path": str(path), "headers": headers, "error": error}
        write_json(directory / f"{name}_{attempt}.receipt.json", receipt)
        if status == 200:
            return body, receipt
        retry_after = headers.get("Retry-After", "") or ""
        if status not in {None, 429, 500, 502, 503, 504} or attempt == 2 or (retry_after.isdigit() and int(retry_after) > 10):
            return None, receipt
        time.sleep(int(retry_after) if retry_after.isdigit() else 2 ** attempt)
    raise RuntimeError("Unreachable retry state")
