"""Adversarial semantics: terminal proofs, uncertain siblings, tamper rejection."""
import copy

import chess
import pytest

from ches.chess_state import ChessState, replay
from ches.minimax import propagate, search, verify


def test_interval_logic_does_not_assign_unknown():
    assert propagate(True, [(1, 1), (-1, 1)]) == (1, 1)
    assert propagate(False, [(1, 1), (-1, 1)]) == (-1, 1)
    assert propagate(False, [(1, 1), (1, 1)]) == (1, 1)
    assert propagate(True, [(0, 0), (-1, 1)]) == (0, 1)
    assert propagate(False, [(0, 0), (-1, 1)]) == (-1, 0)


def test_initial_game_value_remains_unknown():
    root = replay(chess.STARTING_FEN, [])
    proof = search(root, depth=2, max_nodes=1000)
    assert proof.bounds == (-1, 1)
    assert proof.unknown_leaves == 400
    assert verify(root, proof.certificate, depth=2) == (-1, 1)


def test_known_terminal_checkmates_are_exact():
    root = replay(chess.STARTING_FEN, ["f2f3", "e7e5", "g2g4", "d8h4"])
    proof = search(root, depth=0)
    assert proof.bounds == (-1, -1)
    assert verify(root, proof.certificate, depth=0) == (-1, -1)


def test_white_win_propagates_through_unknown_siblings():
    root = ChessState(chess.Board("7k/Q7/8/6K1/8/8/8/1R6 w - - 0 1"))
    proof = search(root, depth=1, max_nodes=1000)
    assert proof.bounds == (1, 1)
    assert any(r["child"]["type"] == "terminal" and r["child"]["value"] == 1
               for r in proof.certificate["children"])
    assert any(r["child"]["type"] == "unknown"
               for r in proof.certificate["children"])
    assert verify(root, proof.certificate, depth=1) == (1, 1)


def test_missing_opponent_reply_is_detected():
    root = ChessState(chess.Board("7k/Q7/8/6K1/8/8/8/1R6 w - - 0 1"))
    proof = search(root, depth=1, max_nodes=1000)
    false_proof = copy.deepcopy(proof.certificate)
    false_proof["children"].pop()
    with pytest.raises(ValueError, match="Missing"):
        verify(root, false_proof, depth=1)


def test_forged_terminal_and_oracle_rejected():
    root = ChessState(chess.Board())
    with pytest.raises(ValueError, match="terminal"):
        verify(root, {"type": "terminal", "value": 1}, depth=0)
    with pytest.raises(ValueError, match="oracle"):
        verify(root, {"type": "oracle", "value": 0, "source": "syzygy-wdl-trusted-50move"}, depth=0)


def test_claim_draw_is_optional_action_and_tightens_one_bound():
    board = chess.Board()
    for _ in range(2):
        for move in ("g1f3","g8f6","f3g1","f6g8"):
            board.push_uci(move)
    root = ChessState(board)
    assert "claim_draw" in root.legal_actions()
    proof = search(root, depth=1, max_nodes=200)
    assert proof.bounds == (0, 1)
    assert verify(root, proof.certificate, depth=1) == (0, 1)


def test_insufficient_budget_never_makes_result_up():
    root = replay(chess.STARTING_FEN, [])
    proof = search(root, depth=8, max_nodes=1)
    assert proof.bounds == (-1, 1)
    assert proof.unknown_leaves > 0
    assert verify(root, proof.certificate, depth=8) == (-1, 1)


def test_tablebase_is_trusted_oracle_only_at_safe_fresh_root():
    class DummySyzygy:
        def probe_wdl(self, position):
            return 2 if position.turn == chess.WHITE else -2

    board = chess.Board("7k/5K2/6Q1/8/8/8/8/8 w - - 0 1")
    root = ChessState(board, DummySyzygy())
    assert root.oracle_value() == (1, "syzygy-wdl-trusted-50move")
    board.halfmove_clock = 1
    assert ChessState(board, DummySyzygy()).oracle_value() is None


def test_source_move_illegality_rejected():
    with pytest.raises((ValueError, AssertionError)):
        replay(chess.STARTING_FEN, ["e2e5"])
