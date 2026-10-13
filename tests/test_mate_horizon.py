"""Exhaustive adversarial finite-horizon mate and refutation certificates."""
from __future__ import annotations

import copy
import chess
import pytest

from ches.chess_state import ChessState, replay
from ches.mate_horizon import search, verify, MATE, NO_MATE, UNKNOWN


WHITE_WIN = "7k/Q7/8/6K1/8/8/8/1R6 w - - 0 1"
BLACK_DEFENSE = "Q6k/8/8/6K1/8/8/8/1R6 b - - 1 1"


def test_white_forces_mate_and_covers_all_black_responses():
    root=ChessState(chess.Board(WHITE_WIN))
    result=search(root,attacker="white",plies=3,max_nodes=10000)
    assert result.status == MATE
    assert verify(root,result.certificate,attacker="white",plies=3)==MATE
    # At least one full defender AND node must occur.
    node=result.certificate
    assert node["kind"]=="choice"
    assert node["child"]["kind"]=="all"
    assert set(x["action"] for x in node["child"]["children"]) == {
        m.uci() for m in root.play(node["action"]).board.legal_moves
    }


def test_delete_black_defense_invalidates_white_win():
    root=ChessState(chess.Board(WHITE_WIN))
    result=search(root,attacker="white",plies=3,max_nodes=10000)
    fake=copy.deepcopy(result.certificate)
    fake["child"]["children"].pop()
    with pytest.raises(ValueError,match="Missing"):
        verify(root,fake,attacker="white",plies=3)


def test_opening_1e4e5_white_has_no_forced_mate_in_3_plies():
    root=replay(chess.STARTING_FEN,["e2e4","e7e5"])
    result=search(root,attacker="white",plies=3,max_nodes=10000)
    assert result.status==NO_MATE
    assert result.certificate["kind"]=="all"
    assert set(row["action"] for row in result.certificate["children"]) == {
        m.uci() for m in root.board.legal_moves
    }
    assert verify(root,result.certificate,attacker="white",plies=3)==NO_MATE


def test_refutation_missing_attacking_move_is_invalid():
    root=replay(chess.STARTING_FEN,["e2e4","e7e5"])
    result=search(root,attacker="white",plies=3,max_nodes=10000)
    fake=copy.deepcopy(result.certificate)
    fake["children"].pop()
    with pytest.raises(ValueError,match="Missing"):
        verify(root,fake,attacker="white",plies=3)


def test_start_white_does_not_force_mate_within_five_plies():
    root=replay(chess.STARTING_FEN,[])
    result=search(root,attacker="white",plies=5,max_nodes=50000)
    assert result.status==NO_MATE
    assert verify(root,result.certificate,attacker="white",plies=5)==NO_MATE


def test_known_terminal_mate_and_stalemate():
    finished=replay(chess.STARTING_FEN,["f2f3","e7e5","g2g4","d8h4"])
    b=search(finished,attacker="black",plies=0)
    w=search(finished,attacker="white",plies=0)
    assert b.status==MATE and w.status==NO_MATE
    assert verify(finished,b.certificate,attacker="black",plies=0)==MATE
    assert verify(finished,w.certificate,attacker="white",plies=0)==NO_MATE


def test_unfinished_budget_stays_unknown():
    root=replay(chess.STARTING_FEN,[])
    result=search(root,attacker="white",plies=7,max_nodes=1)
    assert result.status==UNKNOWN
    assert result.certificate is None
    assert result.budget_exhausted


def test_false_leaf_cannot_be_painted_as_mate():
    root=replay(chess.STARTING_FEN,[])
    with pytest.raises(ValueError,match="leaf"):
        verify(root,{"kind":"leaf","mate":True,"reason":"horizon"},
               attacker="white",plies=0)


def test_claimed_draw_is_an_optional_defense_not_force_mate():
    b=chess.Board()
    for _ in range(2):
        for u in ("g1f3","g8f6","f3g1","f6g8"):
            b.push_uci(u)
    root=ChessState(b)
    assert "claim_draw" in root.legal_actions()
    result=search(root,attacker="white",plies=1,max_nodes=1000)
    assert result.status == NO_MATE
    assert verify(root,result.certificate,attacker="white",plies=1)==NO_MATE
