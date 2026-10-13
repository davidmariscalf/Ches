"""CLI for selective, proof-carrying adversarial search."""
from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
import json
from pathlib import Path

import chess
import chess.syzygy

from .chess_state import replay
from .threshold import certify_bounds, verify_bounds


def run(argv: list[str] | None = None):
    p = argparse.ArgumentParser(
        description="Verified AND/OR strategy proof search, conservative bounds")
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("search")
    s.add_argument("--fen", default=chess.STARTING_FEN)
    s.add_argument("--moves", nargs="*", default=[])
    s.add_argument("--depth", type=int, default=3)
    s.add_argument("--nodes-per-threshold", type=int, default=4000)
    s.add_argument("--out", default="selective-cert.json")
    v = sub.add_parser("verify")
    v.add_argument("certificate")
    for cmd in (s, v):
        cmd.add_argument("--syzygy-dir")
    args = p.parse_args(argv)

    ctx = (closing(chess.syzygy.open_tablebase(args.syzygy_dir))
           if args.syzygy_dir else nullcontext(None))
    with ctx as tb:
        if args.action == "search":
            root = replay(args.fen, args.moves, tb)
            result = certify_bounds(root, depth=args.depth,
                                    max_nodes_per_attempt=args.nodes_per_threshold)
            proof = {"bounds": [result.lower, result.upper],
                     "proofs": list(result.proofs)}
            if verify_bounds(root, proof) != (result.lower, result.upper):
                raise AssertionError("Verifier rejected generated proof")
            packet = {
                "format": "ches-selective-v1",
                "root_fen": args.fen,
                "moves": args.moves,
                "depth": args.depth,
                "certificate": proof,
                "attempts": list(result.attempts),
                "syzygy_is_external_assumption": bool(args.syzygy_dir),
            }
            Path(args.out).write_text(json.dumps(packet, indent=2) + "\n",
                                      encoding="utf-8")
            summary = {"bounds": list(proof["bounds"]),
                       "exact": result.exact,
                       "proven_thresholds": len(result.proofs),
                       "attempts": list(result.attempts),
                       "path": args.out,
                       "root_fen": root.board.fen()}
            print(json.dumps(summary, indent=2))
            return summary
        packet = json.loads(Path(args.certificate).read_text(encoding="utf-8"))
        if packet.get("format") != "ches-selective-v1":
            raise ValueError("Unsupported certificate format")
        root = replay(packet["root_fen"], packet["moves"], tb)
        bounds = verify_bounds(root, packet["certificate"])
        print(json.dumps({"verified": True, "bounds": list(bounds),
                          "exact": bounds[0] == bounds[1]}))
        return bounds


if __name__ == "__main__":
    run()
