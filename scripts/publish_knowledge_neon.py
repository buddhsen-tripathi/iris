#!/usr/bin/env python3
"""Publish the local evidence snapshot and optional semantic embeddings to Neon."""
import argparse
import json
from pathlib import Path
from alphacouncil.knowledge.neon import import_snapshot,configure_reader,embed_missing

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--embed',action='store_true')
    parser.add_argument('--max-chunks',type=int,default=15000)
    args=parser.parse_args()
    result={'import':import_snapshot(),'access':configure_reader()}
    if args.embed:result['embeddings']=embed_missing(max_chunks=args.max_chunks)
    Path('data/manifests/knowledge_neon_latest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:main()
    except Exception as error:
        # Credentials/connection strings can occur in driver exceptions. Keep stdout safe.
        print(json.dumps({'error_type':type(error).__name__,'message':'Neon publish failed; credentials and raw driver messages withheld.'}))
        raise SystemExit(1)
