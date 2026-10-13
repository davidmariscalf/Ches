"""Exact finite-horizon FORCE-MATE/NO-FORCE-MATE proof trees.

This DOES NOT prove the game-theoretic outcome of a nonterminal position.
A NO_FORCE_MATE(H) witness only refutes the named player's ability to force
checkmate within H *plies*, never their long-term ability to win.

Proofs use adversarial AND/OR quantifiers. A truncated search returns UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import chess

from .chess_state import ChessState, TerminalDraw

MATE, NO_MATE, UNKNOWN = "FORCED_MATE", "NO_FORCED_MATE", "UNKNOWN"


def _leaf(state: ChessState | TerminalDraw, attacker_white: bool,
          depth: int) -> tuple[bool | None, str | None]:
    automatic = state.terminal_value()
    if automatic is not None:
        if isinstance(state, ChessState):
            is_mate = state.board.is_checkmate()
        else:
            is_mate = False
        return bool(is_mate and automatic == (1 if attacker_white else -1)), "ended"
    if depth == 0:
        return False, "horizon"
    return None, None


@dataclass(frozen=True)
class HorizonResult:
    status: str
    attacker: str
    plies: int
    visited: int
    budget_exhausted: bool
    certificate: dict[str, Any] | None


def search(root: ChessState, *, attacker: str, plies: int,
           max_nodes: int = 100_000) -> HorizonResult:
    if attacker not in ("white", "black") or plies < 0 or max_nodes < 1:
        raise ValueError("Invalid attacker, horizon or budget")
    attacking_white = attacker == "white"
    seen = 0
    cut = False

    def visit(state: ChessState | TerminalDraw, remaining: int):
        nonlocal seen, cut
        if seen >= max_nodes:
            cut = True
            return None, None
        seen += 1
        leaf, reason = _leaf(state, attacking_white, remaining)
        if leaf is not None:
            return leaf, {"kind": "leaf", "reason": reason, "mate": leaf}
        attacking_turn = state.turn_white == attacking_white
        choices = state.legal_actions()
        if not choices or len(choices) != len(set(choices)):
            raise ValueError("Bad nonterminal legal action list")
        all_results = []
        unknown = False
        # Each legal action is considered at both universal outcomes; at
        # existential outcomes stop after the first complete witness.
        for action in sorted(choices):
            result, proof = visit(state.play(action), remaining - 1)
            if result is None:
                unknown = True
                continue
            if attacking_turn and result:
                return True, {"kind": "choice", "action": action, "child": proof}
            if not attacking_turn and not result:
                return False, {"kind": "choice", "action": action, "child": proof}
            all_results.append({"action": action, "child": proof})
        if unknown:
            return None, None
        # If no existential witness exists, universal closure is required.
        if len(all_results) != len(choices):
            raise AssertionError("Dropped legal continuation")
        return (False if attacking_turn else True), {
            "kind": "all", "children": all_results
        }

    verdict, certificate = visit(root, plies)
    status = (UNKNOWN if verdict is None else
              MATE if verdict else NO_MATE)
    return HorizonResult(status, attacker, plies, seen, cut, certificate)


def verify(root: ChessState, certificate: object, *,
           attacker: str, plies: int) -> str:
    if attacker not in ("white", "black") or plies < 0:
        raise ValueError("Invalid horizon/attacker")
    attacking_white = attacker == "white"

    def visit(state: ChessState | TerminalDraw, node: object, remaining: int) -> bool:
        if not isinstance(node, dict):
            raise ValueError("Malformed certificate node")
        leaf, reason = _leaf(state, attacking_white, remaining)
        if leaf is not None:
            if (set(node) != {"kind", "reason", "mate"} or
                    node["kind"] != "leaf" or node["reason"] != reason or
                    type(node["mate"]) is not bool or node["mate"] != leaf):
                raise ValueError("Invalid mate/horizon leaf")
            return leaf
        attacking_turn = state.turn_white == attacking_white
        legal = state.legal_actions()
        if len(legal) != len(set(legal)) or not legal:
            raise ValueError("Invalid nonterminal actions")
        kind = node.get("kind")
        if kind == "choice":
            if set(node) != {"kind", "action", "child"}:
                raise ValueError("Malformed choice")
            move = node["action"]
            if move not in legal:
                raise ValueError("Selected action is not legal")
            result = visit(state.play(move), node["child"], remaining - 1)
            if result != attacking_turn:
                # Attacker needs TRUE; defender needs FALSE.
                raise ValueError("Selected continuation is not a witness")
            return result
        if kind != "all" or set(node) != {"kind", "children"}:
            raise ValueError("Unrecognised proof node")
        rows = node["children"]
        if (not isinstance(rows, list) or
                any(not isinstance(x, dict) or set(x) != {"action", "child"}
                    or type(x["action"]) is not str for x in rows)):
            raise ValueError("Malformed universal list")
        actions = [x["action"] for x in rows]
        if len(actions) != len(set(actions)) or set(actions) != set(legal):
            raise ValueError("Missing or duplicated opponent continuations")
        expected = not attacking_turn
        for entry in rows:
            if visit(state.play(entry["action"]), entry["child"], remaining-1) != expected:
                raise ValueError("Universal node contains a contrary child")
        return expected

    mate = visit(root, certificate, plies)
    return MATE if mate else NO_MATE


def summarize(result: HorizonResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "attacker": result.attacker,
        "horizon_plies": result.plies,
        "visited": result.visited,
        "budget_exhausted": result.budget_exhausted,
        "certificate": result.certificate,
        "interpretation": (
            "Forced checkmate inside given horizon (all defenses included)"
            if result.status == MATE else
            "No forced checkmate within horizon; NOT a full-game drawing proof"
            if result.status == NO_MATE else
            "Unresolved; budget or search frontier cannot be interpreted"
        ),
    }
