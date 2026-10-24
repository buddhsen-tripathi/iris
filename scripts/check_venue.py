#!/usr/bin/env python3
"""Read-only True Markets discovery. Never requests balances, keys, or orders."""

import json
from pathlib import Path

from alphacouncil.data.archive import utc_now, write_json
from alphacouncil.integrations.public import capture


def main():
    directory = Path("data/venue") / utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    results = {}
    for endpoint, name in (("assets/availability", "availability"), ("assets", "catalog")):
        body, receipt = capture("https://api.truemarkets.co/v1/gateway/" + endpoint, directory, name)
        try:
            payload = json.loads(body) if body else None
            results[name] = {"status": "available" if body else "unavailable", "receipt": receipt, "payload": payload}
        except (ValueError, TypeError) as error:
            results[name] = {"status": "unavailable", "receipt": receipt, "error": str(error), "payload": None}
    catalog = results["catalog"]["payload"]
    rows = catalog.get("data", []) if isinstance(catalog, dict) else catalog if isinstance(catalog, list) else []
    if not isinstance(rows, list):
        rows = []
    selected = [{key: row.get(key) for key in ("id", "symbol", "name", "chain", "venue", "type", "asset_class", "status")}
                for row in rows if isinstance(row, dict) and row.get("symbol") in {"BTC", "ETH", "SOL"}]
    manifest = {"schema_version": 1, "created_at_utc": utc_now().isoformat(), "mode": "PUBLIC_CAPABILITIES_ONLY",
                "status": "complete" if all(row["status"] == "available" for row in results.values()) else "partial",
                "venue": "truemarkets", "selected_assets": selected, "catalog_asset_count": len(rows),
                "availability": results["availability"]["payload"], "requests": [{"endpoint": key, "status": row["status"], "receipt": row["receipt"]} for key, row in results.items()],
                "private_account_verified": False, "live_order_transport_implemented": False, "live_trading_enabled": False,
                "interpretation": "Public catalog and caller-location metadata are not proof of authenticated account eligibility, balances, fees, or executable quotes. Binance model prices are not substituted for True Markets fills."}
    write_json(directory / "manifest.json", manifest)
    write_json(Path("data/manifests/venue_latest.json"), manifest)
    print(json.dumps({key: manifest[key] for key in ("status", "catalog_asset_count", "selected_assets", "private_account_verified")}))


if __name__ == "__main__":
    main()
