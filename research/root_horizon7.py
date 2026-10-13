"""Reproducible exact finite-horizon mate refutation from initial position.

A proven NO_FORCED_MATE result does not say the full chess game is drawn,
only that White cannot force checkmate within the supplied number of plies.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import chess
from ches.chess_state import replay
from ches.mate_horizon import search,verify,NO_MATE,summarize


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--plies",type=int,default=7)
    p.add_argument("--max-nodes",type=int,default=1_000_000)
    p.add_argument("--output",default="root-horizon7.json.gz")
    args=p.parse_args()
    root=replay(chess.STARTING_FEN,[])
    result=search(root,attacker="white",plies=args.plies,max_nodes=args.max_nodes)
    print(json.dumps({k:v for k,v in summarize(result).items() if k!="certificate"},indent=2),flush=True)
    if result.certificate is None:
        if result.status=="UNKNOWN":
            print("INCONCLUSIVE: no proof; budget exhausted.",flush=True)
            return 2
        raise AssertionError("Proof missing despite exact verdict")
    independently=verify(root,result.certificate,attacker="white",plies=args.plies)
    if independently!=result.status:
        raise AssertionError("Independent verifier rejected tree")
    payload={"root_fen":chess.STARTING_FEN,"moves":[],
             "result":summarize(result),"reverified":independently}
    with gzip.GzipFile(args.output,"wb",mtime=0) as f:
        f.write(json.dumps(payload,separators=(',',':'),sort_keys=True).encode())
    if result.status!=NO_MATE:
        print("The initial position is NOT certified as no forced mate at this horizon.")
        return 3
    print("SUCCESS: finite-horizon refutation proved and rechecked. The full game is UNSOLVED.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
