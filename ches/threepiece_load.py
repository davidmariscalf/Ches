"""Reopen a generated three-piece table only after a full independent re-audit.

The file SHA-256 is an integrity check, NOT a proof. Loading regenerates all
legal KQK/KRK positions and validates the minimax rank on EVERY transition.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import struct

import chess

from .threepiece import (
    Table, SIZE, UNRESOLVED, WHITE_WIN, DRAW,
    PIECE_TYPES, enumerate_legal, pack, verify
)

_AUDIT_SEAL = object()


@dataclass(frozen=True)
class VerifiedThreePiece:
    piece: str
    table: Table
    raw_sha256: str
    _seal: object

    def __post_init__(self):
        if self._seal is not _AUDIT_SEAL:
            raise ValueError("Full endgame audit required before constructing a leaf oracle")

    def lookup(self, board: chess.Board) -> tuple[int, str] | None:
        if (not board.is_valid() or board.halfmove_clock != 0 or
                board.castling_rights or board.ep_square is not None or
                board.is_repetition(2) or len(board.piece_map()) != 3):
            return None
        cells = board.piece_map()
        whites = [(sq,p.piece_type) for sq,p in cells.items() if p.color == chess.WHITE]
        blacks = [(sq,p.piece_type) for sq,p in cells.items() if p.color == chess.BLACK]
        expected = PIECE_TYPES[self.piece]
        if sorted(t for _,t in whites) != sorted((chess.KING,expected)):
            return None
        if len(blacks) != 1 or blacks[0][1] != chess.KING:
            return None
        wk = next(sq for sq,t in whites if t == chess.KING)
        extra = next(sq for sq,t in whites if t == expected)
        idx = pack(wk,extra,blacks[0][0],board.turn)
        result = self.table.status[idx]
        if result == WHITE_WIN:
            return 1, "audited-k"+self.piece[0]+"k:"+self.raw_sha256
        if result == DRAW:
            return 0, "audited-k"+self.piece[0]+"k:"+self.raw_sha256
        raise ValueError("Audited table is missing legal chess state")


def load_verified(compressed_file: str | Path,
                  manifest_file: str | Path) -> VerifiedThreePiece:
    manifest = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
    piece = manifest.get("piece")
    if piece not in PIECE_TYPES or manifest.get("result") != "EXACT_THREE_PIECE_SUBGAME_ONLY":
        raise ValueError("Not a supported full three-piece endgame manifest")
    metadata = manifest.get("export", {})
    raw = gzip.decompress(Path(compressed_file).read_bytes())
    if (type(metadata.get("records")) is not int or
            metadata.get("record_bytes") != 6 or
            len(raw) != metadata["records"] * 6 or
            hashlib.sha256(raw).hexdigest() != metadata.get("uncompressed_sha256")):
        raise ValueError("Truncated or manipulated three-piece table")
    states, valid = enumerate_legal(PIECE_TYPES[piece])
    if len(valid) != metadata["records"]:
        raise ValueError("Table omitted legal states")
    dtm = array("h", [-1]) * SIZE
    last = -1
    from_file = set()
    for idx, distance in struct.iter_unpack("<Ih", raw):
        if idx <= last or idx >= SIZE or distance < -1 or distance >= 100:
            raise ValueError("Invalid sorted table record")
        last = idx
        from_file.add(idx)
        states[idx] = WHITE_WIN if distance >= 0 else DRAW
        dtm[idx] = distance
    if from_file != set(valid):
        raise ValueError("Table coverage differs from legal chess states")
    edge_count = manifest.get("statistics", {}).get("verified_successor_edges")
    if type(edge_count) is not int or edge_count < 1:
        raise ValueError("Missing verifiable edge count")
    table = Table(piece, states, dtm, valid, edge_count)
    audited = verify(table)
    if audited != manifest.get("statistics"):
        raise ValueError("The claimed audit statistics are incorrect")
    return VerifiedThreePiece(piece, table, metadata["uncompressed_sha256"], _AUDIT_SEAL)
