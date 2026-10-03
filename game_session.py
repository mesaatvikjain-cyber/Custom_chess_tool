import io
from dataclasses import dataclass, field

import chess
import chess.pgn

from engine import evaluate_board


def board_from_fen(fen):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("The FEN describes an invalid chess position.")
    return board


def parse_pgn_text(pgn_text):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("The selected file does not contain a PGN game.")
    if game.errors:
        raise ValueError(f"PGN contains errors: {game.errors[0]}")
    start_board = chess.Board()
    if "FEN" in game.headers:
        start_board = board_from_fen(game.headers["FEN"])
    moves = list(game.mainline_moves())
    position = start_board.copy(stack=True)
    for move in moves:
        if move not in position.legal_moves:
            raise ValueError(f"Illegal move in PGN: {move.uci()}")
        position.push(move)
    return start_board, moves, dict(game.headers)


@dataclass
class GameLine:
    """Validated game history and the board snapshots used by the UI."""

    starting_board: chess.Board
    moves: list = field(default_factory=list)
    move_san: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    evaluations: list = field(default_factory=list)
    mates: list = field(default_factory=list)
    white_captures: list = field(default_factory=list)
    black_captures: list = field(default_factory=list)

    @classmethod
    def from_moves(cls, board, moves=None):
        starting_board = board.copy(stack=False)
        position = starting_board.copy(stack=True)
        line = cls(
            starting_board=starting_board,
            positions=[position.copy(stack=True)],
            evaluations=[round(evaluate_board(position) / 100, 2)],
            mates=[None],
        )
        for move in moves or []:
            line.append_move(move)
        return line

    @staticmethod
    def captured_piece(board, move):
        if board.is_en_passant(move):
            captured_square = (
                move.to_square - 8 if board.turn == chess.WHITE
                else move.to_square + 8)
            return board.piece_at(captured_square)
        return board.piece_at(move.to_square)

    def append_move(self, move):
        board = self.positions[-1].copy(stack=True)
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move in game: {move.uci()}")
        san = board.san(move)
        captured = self.captured_piece(board, move)
        mover = board.turn
        board.push(move)
        self.moves.append(move)
        self.move_san.append(san)
        self.positions.append(board.copy(stack=True))
        self.evaluations.append(round(evaluate_board(board) / 100, 2))
        self.mates.append(None)
        if captured:
            (self.white_captures if mover == chess.WHITE
             else self.black_captures).append(captured)
        return board, san, captured, mover

    def truncate(self, ply):
        if not 0 <= ply <= len(self.moves):
            raise ValueError("Ply is outside the game history.")
        del self.moves[ply:]
        del self.move_san[ply:]
        del self.positions[ply + 1:]
        del self.evaluations[ply + 1:]
        del self.mates[ply + 1:]
        self.white_captures.clear()
        self.black_captures.clear()
        board = self.starting_board.copy(stack=True)
        for move in self.moves:
            captured = self.captured_piece(board, move)
            mover = board.turn
            board.push(move)
            if captured:
                (self.white_captures if mover == chess.WHITE
                 else self.black_captures).append(captured)
        return self.positions[ply].copy(stack=True)
