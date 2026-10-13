"""Selective proof-carrying minimax (no guessed or heuristic chess results).

To certify WHITE >= threshold or WHITE <= threshold, the favorable player
chooses ONE action; their opponent's ALL legal actions must be covered.
This asymmetric witness often replaces the very large complete search tree
with a compact, replayable strategy tree.

An unsuccessful bounded search is NOT evidence for the negation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .minimax import GameState

VALID = {("lower", 0), ("lower", 1), ("upper", -1), ("upper", 0)}


def _ensure_request(kind: str, threshold: int) -> None:
    if (kind, threshold) not in VALID or type(threshold) is not int:
        raise ValueError("Valid thresholds: lower>=0, lower>=1, upper<=-1, upper<=0")


def _satisfies(value: int, kind: str, threshold: int) -> bool:
    if type(value) is not int or value not in (-1, 0, 1):
        raise ValueError("Invalid game-theoretic leaf")
    return value >= threshold if kind == "lower" else value <= threshold


def _existential(turn_white: bool, kind: str) -> bool:
    return turn_white if kind == "lower" else not turn_white


@dataclass(frozen=True)
class ThresholdAttempt:
    kind: str
    threshold: int
    proven: bool
    witness: dict[str, Any] | None
    visited: int
    budget_exhausted: bool


def prove_threshold(root: GameState, *, kind: str, threshold: int,
                    depth: int, max_nodes: int = 10000) -> ThresholdAttempt:
    """Find an exhaustive adversarial witness inside a finite search horizon."""
    _ensure_request(kind, threshold)
    if depth < 0 or max_nodes < 1:
        raise ValueError("Invalid search limits")
    visited = 0
    exhausted = False

    def go(pos: GameState, remaining: int) -> dict[str, Any] | None:
        nonlocal visited, exhausted
        if visited >= max_nodes:
            exhausted = True
            return None
        visited += 1
        terminal = pos.terminal_value()
        if terminal is not None:
            if _satisfies(terminal, kind, threshold):
                return {"type": "terminal", "value": terminal}
            return None
        oracle = pos.oracle_value()
        if oracle is not None:
            value, source = oracle
            if _satisfies(value, kind, threshold):
                if not isinstance(source, str) or not source:
                    raise ValueError("Invalid oracle source")
                return {"type": "oracle", "value": value, "source": source}
            return None
        if remaining == 0:
            return None
        legal = sorted(pos.legal_actions())
        if not legal or len(set(legal)) != len(legal):
            raise ValueError("Invalid legal actions at nonterminal node")

        if _existential(pos.turn_white, kind):
            for action in legal:
                proof = go(pos.play(action), remaining - 1)
                if proof is not None:
                    return {"type": "choice", "action": action, "child": proof}
            return None

        # Universal: EVERY action is required; inability to prove even one
        # child invalidates the parent. Never silently drop a defense.
        children = []
        for action in legal:
            proof = go(pos.play(action), remaining - 1)
            if proof is None:
                return None
            children.append({"action": action, "child": proof})
        return {"type": "all", "children": children}

    witness = go(root, depth)
    return ThresholdAttempt(kind, threshold, witness is not None,
                            witness, visited, exhausted)


def verify_threshold(root: GameState, witness: object, *, kind: str,
                     threshold: int, depth: int) -> bool:
    """Independent interpretation: audit exact leaves and required ALL actions."""
    _ensure_request(kind, threshold)
    if depth < 0:
        raise ValueError("Invalid depth")

    def walk(pos: GameState, node: object, remaining: int) -> None:
        if not isinstance(node, dict):
            raise ValueError("Missing/malformed proof node")
        tag = node.get("type")
        terminal = pos.terminal_value()
        if tag == "terminal":
            if (set(node) != {"type", "value"} or terminal is None or
                    type(node.get("value")) is not int or
                    node["value"] != terminal or
                    not _satisfies(terminal, kind, threshold)):
                raise ValueError("False terminal witness")
            return
        if terminal is not None:
            raise ValueError("Certificate continues after game ended")
        if tag == "oracle":
            known = pos.oracle_value()
            if (set(node) != {"type", "value", "source"} or known is None or
                    known != (node.get("value"), node.get("source")) or
                    not _satisfies(known[0], kind, threshold)):
                raise ValueError("False or unavailable oracle")
            return
        if remaining <= 0:
            raise ValueError("Unproven frontier cannot certify game outcome")
        legal = pos.legal_actions()
        if not legal or len(set(legal)) != len(legal):
            raise ValueError("Bad legal-action generator")
        if _existential(pos.turn_white, kind):
            if set(node) != {"type", "action", "child"} or tag != "choice":
                raise ValueError("Only verified choice allowed at existential node")
            action = node["action"]
            if action not in legal:
                raise ValueError("Illegal chosen move")
            walk(pos.play(action), node["child"], remaining - 1)
            return
        if set(node) != {"type", "children"} or tag != "all":
            raise ValueError("Complete defender coverage required")
        rows = node["children"]
        if (not isinstance(rows, list)
                or any(not isinstance(r, dict) or set(r) != {"action", "child"}
                       or type(r["action"]) is not str for r in rows)):
            raise ValueError("Malformed universal move list")
        actions = [r["action"] for r in rows]
        if len(actions) != len(set(actions)) or set(actions) != set(legal):
            raise ValueError("Missing, repeated or fabricated adversarial response")
        for row in rows:
            walk(pos.play(row["action"]), row["child"], remaining - 1)

    walk(root, witness, depth)
    return True


@dataclass(frozen=True)
class SelectiveResult:
    lower: int
    upper: int
    proofs: tuple[dict[str, Any], ...]
    attempts: tuple[dict[str, Any], ...]

    @property
    def exact(self) -> bool:
        return self.lower == self.upper


def certify_bounds(root: GameState, *, depth: int,
                   max_nodes_per_attempt: int = 5000) -> SelectiveResult:
    """Try proving separate lower/upper bounds; every proof is self-contained.

    Four independent threshold queries are attempted in strength-first order.
    Failed searches are not treated as proofs of the opposite assertion.
    """
    lower, upper = -1, 1
    witnesses: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for kind, t in (("lower", 1), ("upper", -1),
                    ("lower", 0), ("upper", 0)):
        if lower == upper:
            break
        if kind == "lower" and lower >= t:
            continue
        if kind == "upper" and upper <= t:
            continue
        outcome = prove_threshold(
            root, kind=kind, threshold=t, depth=depth,
            max_nodes=max_nodes_per_attempt
        )
        attempts.append({"kind": kind, "threshold": t,
                         "proven": outcome.proven, "visited": outcome.visited,
                         "budget_exhausted": outcome.budget_exhausted})
        if not outcome.proven:
            continue
        assert outcome.witness is not None
        verify_threshold(root, outcome.witness, kind=kind, threshold=t, depth=depth)
        witnesses.append({"kind": kind, "threshold": t, "depth": depth,
                          "witness": outcome.witness})
        if kind == "lower":
            lower = max(lower, t)
        else:
            upper = min(upper, t)
        if lower > upper:
            raise ValueError("Contradictory chess proof certificates")
    return SelectiveResult(lower, upper, tuple(witnesses), tuple(attempts))


def verify_bounds(root: GameState, saved: dict[str, Any]) -> tuple[int, int]:
    """Never trust reported intervals or attempt-failure claims."""
    if not isinstance(saved, dict) or set(saved) != {"bounds", "proofs"}:
        raise ValueError("Invalid saved report")
    proofs = saved["proofs"]
    if not isinstance(proofs, list):
        raise ValueError("Proof list required")
    lower, upper = -1, 1
    used = set()
    for record in proofs:
        if not isinstance(record, dict) or set(record) != {"kind", "threshold", "depth", "witness"}:
            raise ValueError("Malformed threshold record")
        kind, threshold, depth = record["kind"], record["threshold"], record["depth"]
        _ensure_request(kind, threshold)
        if type(depth) is not int or depth < 0 or (kind, threshold) in used:
            raise ValueError("Invalid or repeated threshold proof")
        used.add((kind, threshold))
        verify_threshold(root, record["witness"], kind=kind,
                         threshold=threshold, depth=depth)
        if kind == "lower":
            lower = max(lower, threshold)
        else:
            upper = min(upper, threshold)
        if lower > upper:
            raise ValueError("Inconsistent exact evidence")
    if saved["bounds"] != [lower, upper]:
        raise ValueError("Claimed interval is not supported by included certificates")
    return lower, upper
