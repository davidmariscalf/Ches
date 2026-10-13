"""CLI for bounded chess certificates; never claims to solve the initial position."""
from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
import json
from pathlib import Path

import chess
import chess.syzygy
from .chess_state import replay
from .minimax import search, verify


def build_root(payload: dict, tablebase):
    return replay(payload["root_fen"], payload["moves"], tablebase)


def run(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="History-aware interval minimax; UNKNOWN stays UNKNOWN")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Generate and verify a finite proof tree")
    analyze.add_argument("--fen", default=chess.STARTING_FEN)
    analyze.add_argument("--moves", nargs="*", default=[])
    analyze.add_argument("--depth", type=int, default=2)
    analyze.add_argument("--max-nodes", type=int, default=2000)
    analyze.add_argument("--out")
    check = sub.add_parser("verify", help="Replay a saved JSON certificate")
    check.add_argument("certificate")
    for cmd in (analyze, check):
        cmd.add_argument("--syzygy-dir", default=None)
    args = parser.parse_args(argv)

    tablebase_ctx = (
        closing(chess.syzygy.open_tablebase(args.syzygy_dir))
        if args.syzygy_dir else nullcontext(None)
    )
    with tablebase_ctx as tb:
        if args.command == "analyze":
            root = replay(args.fen, list(args.moves), tb)
            result = search(root, depth=args.depth, max_nodes=args.max_nodes)
            independently_verified = verify(root, result.certificate, depth=args.depth)
            if independently_verified != result.bounds:
                raise AssertionError("Independent proof interpreter disagrees")
            packet = {
                "format": "ches-interval-v1",
                "root_fen": args.fen,
                "moves": list(args.moves),
                "depth": args.depth,
                "bounds": list(independently_verified),
                "certificate": result.certificate,
                "visited": result.visited,
                "unknown_leaves": result.unknown_leaves,
                "tablebase_assumption": bool(args.syzygy_dir),
                "disclaimer": (
                    "All nonterminal unproved branches remain UNKNOWN. "
                    "Syzygy leaves, when present, require trusted tablebase data."
                )
            }
            if args.out:
                Path(args.out).write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
            summary = {key: val for key,val in packet.items() if key != "certificate"}
            summary["status"] = (
                "white_win" if result.bounds == (1,1) else
                "black_win" if result.bounds == (-1,-1) else
                "draw" if result.bounds == (0,0) else "unknown"
            )
            print(json.dumps(summary, indent=2))
            return summary
        packet = json.loads(Path(args.certificate).read_text(encoding="utf-8"))
        if packet.get("format") != "ches-interval-v1":
            raise ValueError("Unknown certificate format")
        root = build_root(packet, tb)
        found = verify(root, packet["certificate"], depth=packet["depth"])
        if tuple(packet["bounds"]) != found:
            raise ValueError("Certificate declares a false root interval")
        print(json.dumps({"verified": True, "bounds": list(found),
                          "tablebase_assumption": packet.get("tablebase_assumption", False)}))
        return found


if __name__ == "__main__":
    run()
