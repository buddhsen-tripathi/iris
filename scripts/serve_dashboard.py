"""Serve the read-only local paper observatory."""
import argparse
from pathlib import Path

import uvicorn
from alphacouncil.api.app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("This observatory is local-only; choose a loopback host")
    uvicorn.run(create_app(args.root), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
