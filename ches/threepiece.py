"""Exhaustive *three-piece* retrograde endgames (K+Q/K+R versus K).

Build from all legal square placements, solve finite WDL via retrograde AND/OR
propagation, and separately re-enumerate EVERY chess move to check the final
winning distances and the closed drawing region.

Exact scope: subgames with only White king+queen/rook and Black king,
no castling or en-passant, and zero halfmove clock at entry. This does
NOT solve arbitrary 32-piece chess.
"""
from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct

import chess

CAPTURE_DRAW = -1
NONEXISTENT, UNRESOLVED, WHITE_WIN, DRAW = 0, 1, 2, 3
SIZE = 1 << 19
PIECE_TYPES = {"queen": chess.QUEEN, "rook": chess.ROOK}


def pack(wk: int, extra: int, bk: int, turn: bool) -> int:
    return (wk << 13) | (extra << 7) | (bk << 1) | (0 if turn else 1)


def unpack(idx: int) -> tuple[int, int, int, bool]:
    return (idx >> 13, (idx >> 7) & 63, (idx >> 1) & 63, idx % 2 == 0)


def position(idx: int, piece_type: int) -> chess.Board:
    wk, extra, bk, turn = unpack(idx)
    board = chess.Board(None)
    board.set_piece_at(wk, chess.Piece(chess.KING, chess.WHITE))
    board.set_piece_at(extra, chess.Piece(piece_type, chess.WHITE))
    board.set_piece_at(bk, chess.Piece(chess.KING, chess.BLACK))
    board.turn = turn
    return board


def enumerate_legal(piece_type: int) -> tuple[bytearray, list[int]]:
    status = bytearray(SIZE)
    valid = []
    for wk in chess.SQUARES:
        for bk in chess.SQUARES:
            if wk == bk or chess.square_distance(wk, bk) <= 1:
                continue
            for extra in chess.SQUARES:
                if extra == wk or extra == bk:
                    continue
                # Board.is_valid() also checks that the side NOT on turn
                # is not in check and that kings are legal.
                for turn in (chess.WHITE, chess.BLACK):
                    idx = pack(wk, extra, bk, turn)
                    p = position(idx, piece_type)
                    if p.is_valid():
                        status[idx] = UNRESOLVED
                        valid.append(idx)
    return status, valid


def successors(p: chess.Board, wk: int, extra: int, bk: int) -> list[int]:
    choices = []
    for m in p.legal_moves:
        if p.turn == chess.WHITE:
            if m.from_square == wk:
                nxt = pack(m.to_square, extra, bk, chess.BLACK)
            elif m.from_square == extra:
                nxt = pack(wk, m.to_square, bk, chess.BLACK)
            else:
                raise AssertionError("unexpected White piece")
        elif m.to_square == extra:
            # Capturing the final White major piece leads to bare kings.
            nxt = CAPTURE_DRAW
        else:
            if m.from_square != bk:
                raise AssertionError("unexpected Black piece")
            nxt = pack(wk, extra, m.to_square, chess.WHITE)
        choices.append(nxt)
    return choices


@dataclass
class Table:
    piece: str
    status: bytearray
    dtm: array
    legal: list[int]
    edges: int


def solve(piece: str) -> Table:
    if piece not in PIECE_TYPES:
        raise ValueError("Only queen/rook vs bare king are supported")
    kind = PIECE_TYPES[piece]
    status, legal = enumerate_legal(kind)
    predecessors: list[list[int] | None] = [None] * SIZE
    not_yet_winning = array("H", [0]) * SIZE
    dtm = array("h", [-1]) * SIZE
    todo = deque()
    edges = 0

    for idx in legal:
        wk, extra, bk, _ = unpack(idx)
        board = position(idx, kind)
        children = successors(board, wk, extra, bk)
        edges += len(children)
        not_yet_winning[idx] = len(children)
        if not children:
            if board.is_checkmate():
                if board.turn != chess.BLACK:
                    raise AssertionError("unexpected White mate")
                status[idx] = WHITE_WIN
                dtm[idx] = 0
                todo.append(idx)
            elif not board.is_stalemate():
                raise AssertionError("unknown terminal state")
        for dst in children:
            if dst == CAPTURE_DRAW:
                continue
            if status[dst] != UNRESOLVED:
                raise AssertionError("Transition outside enumerated legal states")
            if predecessors[dst] is None:
                predecessors[dst] = [idx]
            else:
                predecessors[dst].append(idx)

    # A White predecessor needs ONE proven-winning child; a Black
    # predecessor needs EVERY legal child to be a proven White win.
    while todo:
        child = todo.popleft()
        for prev in predecessors[child] or ():
            if status[prev] != UNRESOLVED:
                continue
            if unpack(prev)[3] == chess.WHITE:
                status[prev] = WHITE_WIN
                dtm[prev] = dtm[child] + 1
                todo.append(prev)
            else:
                not_yet_winning[prev] -= 1
                if not_yet_winning[prev]:
                    continue
                status[prev] = WHITE_WIN
                dtm[prev] = dtm[child] + 1
                todo.append(prev)

    for idx in legal:
        if status[idx] == UNRESOLVED:
            status[idx] = DRAW
    return Table(piece, status, dtm, legal, edges)


def verify(table: Table) -> dict:
    """Check every legal successor, not merely hashes of the generated output."""
    kind = PIECE_TYPES[table.piece]
    edges = 0
    wins = 0
    draws = 0
    checkmates = 0
    max_dtm = 0
    for idx in table.legal:
        wk, extra, bk, turn = unpack(idx)
        board = position(idx, kind)
        if not board.is_valid():
            raise AssertionError("illegal table state")
        child_keys = successors(board, wk, extra, bk)
        edges += len(child_keys)
        child_status = [DRAW if nxt == CAPTURE_DRAW else table.status[nxt]
                        for nxt in child_keys]
        win_depths = [table.dtm[nxt] for nxt in child_keys
                      if nxt != CAPTURE_DRAW and table.status[nxt] == WHITE_WIN]
        v = table.status[idx]
        d = table.dtm[idx]
        if not child_keys:
            if v == WHITE_WIN:
                if not board.is_checkmate() or turn != chess.BLACK or d != 0:
                    raise AssertionError("false terminal checkmate")
                checkmates += 1
            elif v == DRAW:
                if not board.is_stalemate() or d != -1:
                    raise AssertionError("false terminal draw")
            else:
                raise AssertionError("invalid leaf")
        elif v == WHITE_WIN:
            if d <= 0:
                raise AssertionError("nonterminal win distance must be positive")
            if turn == chess.WHITE:
                if not win_depths or min(win_depths) != d-1:
                    raise AssertionError("missing White winning choice")
            else:
                if any(s != WHITE_WIN for s in child_status) or not win_depths:
                    raise AssertionError("Black has an uncaptured drawing defense")
                if max(win_depths) != d-1:
                    raise AssertionError("Black depth-to-mate mismatch")
        elif v == DRAW:
            if d != -1:
                raise AssertionError("draw state has winning distance")
            if turn == chess.WHITE and any(s != DRAW for s in child_status):
                raise AssertionError("White could force mate from alleged draw")
            if turn == chess.BLACK and not any(s == DRAW for s in child_status):
                raise AssertionError("Black lacks drawing response")
        else:
            raise AssertionError("table leaves a legal state unclassified")
        if v == WHITE_WIN:
            wins += 1
            max_dtm = max(max_dtm, d)
        else:
            draws += 1

    if edges != table.edges or wins+draws != len(table.legal):
        raise AssertionError("solution edge/state counts disagree")
    # At a fresh 0-clock position all these wins finish before the first
    # possible 50-move draw claim. Otherwise the WDL cannot be used.
    if max_dtm >= 100:
        raise AssertionError("the no-50-move-claim guarantee is violated")
    return {"legal_positions": len(table.legal),
            "white_wins": wins, "draws": draws,
            "verified_successor_edges": edges,
            "terminal_checkmates": checkmates, "max_mate_plies": max_dtm}


def export(table: Table, filename: str | Path) -> dict:
    output = Path(filename)
    h = hashlib.sha256()
    with output.open("wb") as compressed:
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as z:
            for idx in sorted(table.legal):
                blob = struct.pack("<Ih", idx, table.dtm[idx])
                z.write(blob)
                h.update(blob)
    return {"records": len(table.legal),
            "record_bytes": 6,
            "uncompressed_sha256": h.hexdigest(),
            "filename": output.name}


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Solve and audit full KQK/KRK three-piece subgame")
    parser.add_argument("--piece", choices=("queen", "rook"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    table = solve(args.piece)
    statistics = verify(table)
    info = {
        "scope": f"White K+{args.piece}/Black K, zero halfmove clock at entry",
        "result": "EXACT_THREE_PIECE_SUBGAME_ONLY",
        "limitations": ["Not standard chess starting position",
                        "Uses python-chess legal move generator",
                        "No arbitrary historic 50-move or repetition rights"],
        "piece": args.piece, "statistics": statistics,
        "export": export(table, args.output),
    }
    Path(args.manifest).write_text(json.dumps(info, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(info, indent=2))
    return info


if __name__ == "__main__":
    main()
