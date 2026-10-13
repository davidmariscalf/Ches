"""Orthodox chess rules adapter and optional trusted Syzygy WDL leaves.

Syzygy is an external computational assumption, not a self-contained formal
proof. Probe only fresh-history 50-move-clock-zero states, <=7 pieces and no
castling or en-passant rights. Cursed/blessed +/-1 become FIDE draws.
"""
from __future__ import annotations

from dataclasses import dataclass
import chess
import chess.syzygy


@dataclass(frozen=True)
class TerminalDraw:
    @property
    def turn_white(self) -> bool:
        return True

    def terminal_value(self) -> int:
        return 0

    def oracle_value(self):
        return None

    def legal_actions(self) -> list[str]:
        return []

    def play(self, action: str):
        raise ValueError("Cannot play after draw claim")


class ChessState:
    def __init__(self, board: chess.Board, tablebase=None, threepiece_tables=None):
        if not board.is_valid():
            raise ValueError("Invalid orthodox chess position")
        self.board = board
        self.tablebase = tablebase
        self.threepiece_tables = threepiece_tables or {}

    @property
    def turn_white(self) -> bool:
        return bool(self.board.turn)

    def terminal_value(self) -> int | None:
        outcome = self.board.outcome(claim_draw=False)
        if outcome is None:
            return None
        if outcome.winner is None:
            return 0
        return 1 if outcome.winner == chess.WHITE else -1

    def legal_actions(self) -> list[str]:
        if self.terminal_value() is not None:
            return []
        moves = sorted(move.uci() for move in self.board.legal_moves)
        if (self.board.can_claim_threefold_repetition()
                or self.board.can_claim_fifty_moves()):
            moves.append("claim_draw")
        return moves

    def play(self, action: str):
        if action not in self.legal_actions():
            raise ValueError("Illegal chess action: " + str(action))
        if action == "claim_draw":
            return TerminalDraw()
        child = self.board.copy(stack=True)
        child.push_uci(action)
        return ChessState(child, self.tablebase, self.threepiece_tables)

    def oracle_value(self) -> tuple[int, str] | None:
        board = self.board
        # Prefer endgames whose complete legal-transition graphs were locally
        # regenerated and checked, rather than an externally trusted WDL file.
        for audited in self.threepiece_tables.values():
            leaf = audited.lookup(board)
            if leaf is not None:
                return leaf
        if (self.tablebase is None
                or len(board.piece_map()) > 7
                or board.halfmove_clock != 0
                or board.castling_rights != 0
                or board.ep_square is not None
                or board.is_repetition(2)):
            return None
        try:
            wdl = self.tablebase.probe_wdl(board)
        except (chess.syzygy.MissingTableError, KeyError, ValueError, OSError):
            return None
        if wdl not in (-2, -1, 0, 1, 2):
            raise ValueError("Unexpected Syzygy WDL")
        if abs(wdl) < 2:
            value = 0
        else:
            white_wins = (wdl > 0) if board.turn == chess.WHITE else (wdl < 0)
            value = 1 if white_wins else -1
        return value, "syzygy-wdl-trusted-50move"


def replay(root_fen: str, uci_moves: list[str], tablebase=None, threepiece_tables=None) -> ChessState:
    board = chess.Board(root_fen, chess960=False)
    if not board.is_valid():
        raise ValueError("Bad root FEN")
    if not isinstance(uci_moves, list) or len(uci_moves) > 12000:
        raise ValueError("Bad UCI move list")
    for uci in uci_moves:
        if board.outcome(claim_draw=False) is not None:
            raise ValueError("Move after automatic chess end")
        if not isinstance(uci, str):
            raise ValueError("Move must be a UCI string")
        board.push_uci(uci)  # Raises if illegal.
        if not board.is_valid():
            raise ValueError("Move generated invalid board")
    return ChessState(board, tablebase, threepiece_tables)
