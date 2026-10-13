"""Three-valued interval minimax with independently replayable proof trees.

Scores are from White's perspective: -1 Black wins, 0 draw, +1 White wins.
Unknown leaves are ALWAYS [-1, 1]. No evaluation heuristic proves a result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class GameState(Protocol):
    @property
    def turn_white(self) -> bool: ...
    def terminal_value(self) -> int | None: ...
    def legal_actions(self) -> list[str]: ...
    def play(self, action: str) -> "GameState": ...
    def oracle_value(self) -> tuple[int, str] | None: ...


Bounds = tuple[int, int]


@dataclass(frozen=True)
class SearchResult:
    bounds: Bounds
    certificate: dict
    visited: int
    unknown_leaves: int

    @property
    def solved(self) -> bool:
        return self.bounds[0] == self.bounds[1]


def propagate(turn_white: bool, intervals: list[Bounds]) -> Bounds:
    if not intervals:
        raise ValueError("Nonterminal state must have legal actions")
    if any(lo not in (-1, 0, 1) or hi not in (-1, 0, 1) or lo > hi
           for lo, hi in intervals):
        raise ValueError("Invalid child interval")
    op = max if turn_white else min
    return op(x[0] for x in intervals), op(x[1] for x in intervals)


def search(root: GameState, *, depth: int, max_nodes: int = 5000) -> SearchResult:
    if depth < 0 or max_nodes < 1:
        raise ValueError("Nonnegative depth and positive node budget required")
    visited = 0
    unknown = 0

    def walk(state: GameState, remaining: int) -> tuple[Bounds, dict]:
        nonlocal visited, unknown
        if visited >= max_nodes:
            unknown += 1
            return (-1, 1), {"type": "unknown"}
        visited += 1
        terminal = state.terminal_value()
        if terminal is not None:
            return (terminal, terminal), {"type": "terminal", "value": terminal}
        exact = state.oracle_value()
        if exact is not None:
            value, source = exact
            if value not in (-1, 0, 1) or not isinstance(source, str) or not source:
                raise ValueError("Invalid oracle result")
            return (value, value), {"type": "oracle", "value": value, "source": source}
        if remaining == 0:
            unknown += 1
            return (-1, 1), {"type": "unknown"}
        legal = state.legal_actions()
        if not legal or len(set(legal)) != len(legal):
            raise ValueError("Nonterminal state has invalid legal actions")
        entries = []
        child_bounds = []
        for action in sorted(legal):
            child_interval, certificate = walk(state.play(action), remaining - 1)
            entries.append({"action": action, "child": certificate})
            child_bounds.append(child_interval)
        return propagate(state.turn_white, child_bounds), {
            "type": "branch", "children": entries
        }

    bounds, certificate = walk(root, depth)
    return SearchResult(bounds, certificate, visited, unknown)


def verify(root: GameState, certificate: object, *, depth: int) -> Bounds:
    """Re-evaluate every leaf and demand ALL actions at every expanded node."""
    if depth < 0:
        raise ValueError("Negative depth")

    def walk(state: GameState, node: object, remaining: int) -> Bounds:
        if not isinstance(node, dict):
            raise ValueError("Malformed proof node")
        kind = node.get("type")
        if kind == "unknown":
            if set(node) != {"type"}:
                raise ValueError("Forged data in unknown leaf")
            return -1, 1
        terminal = state.terminal_value()
        if kind == "terminal":
            if (set(node) != {"type", "value"} or terminal is None
                    or type(node.get("value")) is not int
                    or node["value"] != terminal):
                raise ValueError("Forged terminal outcome")
            return terminal, terminal
        if terminal is not None:
            raise ValueError("Cannot expand after automatic termination")
        if kind == "oracle":
            known = state.oracle_value()
            if (set(node) != {"type", "value", "source"}
                    or known != (node.get("value"), node.get("source"))
                    or type(node.get("value")) is not int):
                raise ValueError("Unavailable or falsified oracle result")
            return node["value"], node["value"]
        if kind != "branch" or remaining <= 0 or set(node) != {"type", "children"}:
            raise ValueError("Invalid branch or horizon")
        children = node["children"]
        if not isinstance(children, list):
            raise ValueError("Children must be a list")
        legal = state.legal_actions()
        if not legal or len(set(legal)) != len(legal):
            raise ValueError("Invalid legal action list")
        if any(not isinstance(row, dict) or set(row) != {"action", "child"}
               or not isinstance(row["action"], str) for row in children):
            raise ValueError("Malformed proof edge")
        names = [row["action"] for row in children]
        if len(names) != len(set(names)) or set(names) != set(legal):
            raise ValueError("Missing, illegal or duplicated adversarial reply")
        intervals = [
            walk(state.play(row["action"]), row["child"], remaining - 1)
            for row in children
        ]
        return propagate(state.turn_white, intervals)

    return walk(root, certificate, depth)
