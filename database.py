import sqlite3
import chess
import chess.pgn
import io
import json


class ChessDatabase:
    def __init__(self, db_name="chess_games.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_table()

    def create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    moves TEXT NOT NULL,
                    result TEXT NOT NULL,
                    pgn TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    white_player TEXT,
                    black_player TEXT,
                    time_control TEXT,
                    pgn_headers TEXT NOT NULL DEFAULT '{}'
                )
            """)

        columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(games)")
        }
        migrations = {
            "pgn": "TEXT NOT NULL DEFAULT ''",
            "white_player": "TEXT",
            "black_player": "TEXT",
            "time_control": "TEXT",
            "pgn_headers": "TEXT NOT NULL DEFAULT '{}'",
        }
        with self.conn:
            for column, definition in migrations.items():
                if column not in columns:
                    self.conn.execute(
                        f"ALTER TABLE games ADD COLUMN {column} {definition}"
                    )

    def save_game(
        self,
        board: chess.Board,
        result: str,
        white_player: str = "White",
        black_player: str = "Black",
        time_control: str = "-",
        pgn_headers: dict = None,
    ):
        game = chess.pgn.Game.from_board(board)
        headers = dict(pgn_headers or {})
        game.headers["Event"] = "Custom Engine Match"
        game.headers.update({key: str(value)
                            for key, value in headers.items()})
        game.headers["Result"] = result
        if white_player is not None:
            game.headers["White"] = white_player
        if black_player is not None:
            game.headers["Black"] = black_player
        if time_control is not None:
            game.headers["TimeControl"] = time_control

        exporter = io.StringIO()
        print(game, file=exporter, end="\n\n")
        pgn_string = exporter.getvalue()

        moves_str = " ".join([m.uci() for m in board.move_stack])
        stored_headers = dict(game.headers)

        with self.conn:
            self.conn.execute(
                """INSERT INTO games
                   (moves, result, pgn, white_player, black_player,
                    time_control, pgn_headers)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    moves_str,
                    result,
                    pgn_string,
                    stored_headers.get("White")
                    if stored_headers.get("White") not in (None, "")
                    else None,
                    stored_headers.get("Black")
                    if stored_headers.get("Black") not in (None, "")
                    else None,
                    stored_headers.get("TimeControl")
                    if stored_headers.get("TimeControl") not in (None, "")
                    else None,
                    json.dumps(stored_headers),
                )
            )

    def fetch_game_pgn(self, game_id: int):
        cursor = self.conn.execute(
            "SELECT pgn FROM games WHERE id = ?", (game_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def load_game_pgn(self, game_id: int):
        return self.fetch_game_pgn(game_id)

    def fetch_recent_games(self, limit=5):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, result, pgn, timestamp FROM games ORDER BY id DESC LIMIT ?", (limit,))
        return cursor.fetchall()
