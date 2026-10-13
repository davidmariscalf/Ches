"""Independently checked AND/OR threshold proof witnesses."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json

import chess
import pytest

from ches.chess_state import ChessState, replay
from ches.threshold import (
    prove_threshold, verify_threshold, certify_bounds, verify_bounds
)


@dataclass
class Toy:
    turn_white: bool
    outcome: int | None = None
    children: dict[str, "Toy"] = field(default_factory=dict)

    def terminal_value(self):
        return self.outcome

    def oracle_value(self):
        return None

    def legal_actions(self):
        return list(self.children)

    def play(self, action):
        return self.children[action]


def bundle(result):
    return {"bounds": [result.lower, result.upper],
            "proofs": list(result.proofs)}


def test_white_can_prove_win_without_expanding_unknown_siblings():
    root = Toy(True, children={
        "a": Toy(False, outcome=1),
        "b": Toy(False, children={"unexplored": Toy(True, outcome=0)}),
    })
    attempt = prove_threshold(root, kind="lower", threshold=1, depth=1)
    assert attempt.proven
    assert attempt.witness == {
        "type": "choice", "action": "a",
        "child": {"type": "terminal", "value": 1}
    }
    assert verify_threshold(root, attempt.witness, kind="lower",
                            threshold=1, depth=1)


def test_black_defender_must_have_every_reply_checked_for_white_win():
    root = Toy(False, children={
        "a": Toy(True, outcome=1), "b": Toy(True, outcome=1),
        "c": Toy(True, outcome=1)
    })
    attempt = prove_threshold(root, kind="lower", threshold=1, depth=1)
    assert attempt.proven
    assert len(attempt.witness["children"]) == 3
    forged = copy.deepcopy(attempt.witness)
    forged["children"].pop()
    with pytest.raises(ValueError, match="Missing"):
        verify_threshold(root, forged, kind="lower", threshold=1, depth=1)


def test_unknown_defender_branch_prevents_false_win():
    root = Toy(False, children={
        "a": Toy(True, outcome=1),
        "b": Toy(True, children={"unexplored": Toy(False, outcome=0)})
    })
    proof = certify_bounds(root, depth=1)
    assert proof.lower == -1
    assert proof.upper == 1
    assert verify_bounds(root, bundle(proof)) == (-1, 1)


def test_white_choice_proves_nonloss_but_not_draw_if_sibling_unknown():
    root = Toy(True, children={
        "a": Toy(False, outcome=0),
        "b": Toy(False, children={"x": Toy(True, outcome=1)})
    })
    proof = certify_bounds(root, depth=1)
    assert (proof.lower, proof.upper) == (0, 1)
    assert verify_bounds(root, bundle(proof)) == (0, 1)


def test_two_separate_threshold_witnesses_prove_exact_draw():
    root = Toy(True, children={
        "a": Toy(False, outcome=0),
        "b": Toy(False, outcome=-1)
    })
    proof = certify_bounds(root, depth=1)
    assert (proof.lower, proof.upper) == (0, 0)
    assert len(proof.proofs) == 2
    assert verify_bounds(root, bundle(proof)) == (0, 0)


def test_bad_leaf_outcome_rejected():
    root = Toy(False, outcome=-1)
    fake = {"type": "terminal", "value": 1}
    with pytest.raises(ValueError, match="False terminal"):
        verify_threshold(root, fake, kind="lower", threshold=1, depth=0)


def test_cannot_manipulate_json_upper_lower_without_witness():
    root = Toy(True, children={"a": Toy(False, outcome=1)})
    proof = certify_bounds(root, depth=1)
    data = bundle(proof)
    data["bounds"] = [0, 0]
    with pytest.raises(ValueError, match="not supported"):
        verify_bounds(root, data)


def test_real_chess_direct_mate_and_unknown_root():
    white = ChessState(chess.Board("7k/Q7/8/6K1/8/8/8/1R6 w - - 0 1"))
    proof = certify_bounds(white, depth=1, max_nodes_per_attempt=1000)
    assert (proof.lower, proof.upper) == (1, 1)
    assert verify_bounds(white, bundle(proof)) == (1, 1)
    # Some sibling moves may remain unexamined: only one winning move is
    # necessary on the player's own turn.
    assert proof.proofs[0]["witness"]["type"] == "choice"

    initial = replay(chess.STARTING_FEN, [])
    bounded = certify_bounds(initial, depth=2, max_nodes_per_attempt=1000)
    assert (bounded.lower, bounded.upper) == (-1, 1)
    assert verify_bounds(initial, bundle(bounded)) == (-1, 1)


def test_real_chess_all_black_defenses_in_mate_2():
    root = ChessState(chess.Board("Q6k/8/8/6K1/8/8/8/1R6 b - - 1 1"))
    proof = prove_threshold(root, kind="lower", threshold=1,
                            depth=2, max_nodes=1000)
    assert proof.proven
    assert proof.witness["type"] == "all"
    assert set(c["action"] for c in proof.witness["children"]) == {
        x.uci() for x in root.board.legal_moves
    }
    assert verify_threshold(root, proof.witness, kind="lower",
                            threshold=1, depth=2)


def test_out_of_budget_never_claims_proof():
    root = Toy(False, children={
        "a": Toy(True, outcome=1), "b": Toy(True, outcome=1)
    })
    outcome = prove_threshold(root, kind="lower", threshold=1,
                              depth=4, max_nodes=1)
    assert not outcome.proven
    assert outcome.budget_exhausted


def test_illegal_thresholds_rejected():
    root = Toy(True, outcome=0)
    for kind, value in [("lower",-1),("upper",1),("lower",True),("nonsense",0)]:
        with pytest.raises(ValueError):
            prove_threshold(root, kind=kind, threshold=value, depth=0)


def test_oracle_only_valid_if_root_reproduces_it():
    class OracleToy(Toy):
        def oracle_value(self):
            return (1, "externally-trusted-oracle")

    root = OracleToy(True)
    witness = prove_threshold(root, kind="lower", threshold=1, depth=0)
    assert witness.proven
    assert verify_threshold(root, witness.witness,
                            kind="lower", threshold=1, depth=0)
    fake = copy.deepcopy(witness.witness)
    fake["source"] = "modified"
    with pytest.raises(ValueError, match="oracle"):
        verify_threshold(root, fake, kind="lower", threshold=1, depth=0)
