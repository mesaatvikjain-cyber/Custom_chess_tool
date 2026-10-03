import chess
import chess.polyglot

PIECE_VALUES = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000
}

PAWN_TABLE = [
    0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
    5,  5, 10, 25, 25, 10,  5,  5,
    0,  0,  0, 20, 20,  0,  0,  0,
    5, -5, -10,  0,  0, -10, -5,  5,
    5, 10, 10, -20, -20, 10, 10,  5,
    0,  0,  0,  0,  0,  0,  0,  0
]

KNIGHT_TABLE = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,  0,  0,  0,  0, -20, -40,
    -30,  0, 10, 15, 15, 10,  0, -30,
    -30,  5, 15, 20, 20, 15,  5, -30,
    -30,  0, 15, 20, 20, 15,  0, -30,
    -30,  5, 10, 15, 15, 10,  5, -30,
    -40, -20,  0,  5,  5,  0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50
]

TRANSPOSITION_TABLE = {}


def evaluate_board(board: chess.Board) -> int:
    if board.is_checkmate():
        return -99999 if board.turn == chess.WHITE else 99999
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if not piece:
            continue
        val = PIECE_VALUES[piece.piece_type]
        sq_idx = square if piece.color == chess.WHITE else chess.square_mirror(
            square)

        pst_bonus = 0
        if piece.piece_type == chess.PAWN:
            pst_bonus = PAWN_TABLE[sq_idx]
        elif piece.piece_type == chess.KNIGHT:
            pst_bonus = KNIGHT_TABLE[sq_idx]

        total = val + pst_bonus
        score += total if piece.color == chess.WHITE else -total

    return score


def order_moves(board: chess.Board):
    def move_score(move):
        if board.is_capture(move):
            attacker = board.piece_at(move.from_square)
            victim = board.piece_at(move.to_square)
            attacker_val = PIECE_VALUES[attacker.piece_type] if attacker else 100
            victim_val = PIECE_VALUES[victim.piece_type] if victim else 100
            return 10 * victim_val - attacker_val
        return 0

    return sorted(board.legal_moves, key=move_score, reverse=True)


def minimax(board: chess.Board, depth: int, alpha: float, beta: float, is_maximizing: bool):
    board_hash = chess.polyglot.zobrist_hash(board)
    if board_hash in TRANSPOSITION_TABLE:
        cached_depth, cached_eval, cached_move = TRANSPOSITION_TABLE[board_hash]
        if cached_depth >= depth:
            return cached_eval, cached_move

    if depth == 0 or board.is_game_over():
        return evaluate_board(board), None

    best_move = None
    ordered_moves = order_moves(board)

    if is_maximizing:
        max_eval = float('-inf')
        for move in ordered_moves:
            board.push(move)
            eval_score, _ = minimax(board, depth - 1, alpha, beta, False)
            board.pop()
            if eval_score > max_eval:
                max_eval = eval_score
                best_move = move
            alpha = max(alpha, eval_score)
            if beta <= alpha:
                break
        TRANSPOSITION_TABLE[board_hash] = (depth, max_eval, best_move)
        return max_eval, best_move
    else:
        min_eval = float('inf')
        for move in ordered_moves:
            board.push(move)
            eval_score, _ = minimax(board, depth - 1, alpha, beta, True)
            board.pop()
            if eval_score < min_eval:
                min_eval = eval_score
                best_move = move
            beta = min(beta, eval_score)
            if beta <= alpha:
                break
        TRANSPOSITION_TABLE[board_hash] = (depth, min_eval, best_move)
        return min_eval, best_move


def analyze_position(board: chess.Board, depth: int = 3):
    """Returns evaluation score in pawns (+1.5) and best move."""
    is_max = (board.turn == chess.WHITE)
    score, move = minimax(board, depth, float('-inf'), float('inf'), is_max)
    eval_pawns = round(score / 100.0, 2)
    return eval_pawns, move
