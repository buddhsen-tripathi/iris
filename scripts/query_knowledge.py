#!/usr/bin/env python3
"""Read-only evidence graph and lexical search. No generated financial claims."""

import argparse
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path

from alphacouncil.knowledge.retrieve import retrieve_context


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--database",type=Path,default=Path("data/knowledge/graph.sqlite3"))
    parser.add_argument("--entity",help="Explicit stable entity ID for ambiguous tickers/names")
    parser.add_argument("--as-of",default=None,help="Timezone-aware ISO timestamp; defaults to actual UTC now")
    parser.add_argument("--max-hops",type=int,default=2)
    parser.add_argument("--max-passages",type=int,default=10)
    parser.add_argument("--include-candidates",action="store_true",help="Explicitly include hypotheses, retaining their candidate status")
    args=parser.parse_args()
    db=sqlite3.connect(args.database.resolve().as_uri()+"?mode=ro",uri=True,timeout=30)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    result=retrieve_context(db,args.query,args.as_of or datetime.now(timezone.utc),entity_id=args.entity,
        max_hops=args.max_hops,max_passages=args.max_passages,include_candidates=args.include_candidates)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    db.close()


if __name__=="__main__":
    main()
