"""Fast correctness controls for state encoding and real mate rules."""
import chess
import pytest

from ches.threepiece import (
    pack, unpack, position, successors, PIECE_TYPES
)


def test_roundtrip_injective_piece_positions():
    for wk in (chess.F7,chess.E1,chess.A1):
        for extra in (chess.G7,chess.H7,chess.D4):
            for bk in (chess.H8,chess.A8):
                for turn in (chess.WHITE,chess.BLACK):
                    assert unpack(pack(wk,extra,bk,turn)) == (wk,extra,bk,turn)


@pytest.mark.parametrize("piece, wk, extra", [
    ("queen",chess.F7,chess.G7),
    ("rook",chess.G6,chess.A8)
])
def test_valid_threepiece_terminal_mate(piece,wk,extra):
    # Both pieces must be protected, and EVERY Black escape square covered.
    p=position(pack(wk,extra,chess.H8,chess.BLACK), PIECE_TYPES[piece])
    assert p.is_valid()
    assert p.is_checkmate()
    assert successors(p,wk,extra,chess.H8)==[]


def test_rook_capture_is_draw_transition():
    # Black king takes an unprotected rook: bare kings draw.
    board=chess.Board("8/8/8/8/8/3k4/3R4/7K b - - 0 1")
    # Black king on d3 and rook d2; black cannot immediately take rook
    # because rook on d2 attacks d3. Use K e3 and rook d2 (no same file).
    board=chess.Board("8/8/8/8/8/4k3/3R4/7K b - - 0 1")
    assert board.is_valid()
    assert any(m.to_square==chess.D2 for m in board.legal_moves)
    wk=chess.H1; extra=chess.D2; bk=chess.E3
    assert -1 in successors(board,wk,extra,bk)
