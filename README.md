# Chess Studio

Chess Studio is a desktop chess app built with Tkinter and `python-chess`.

## Run

1. Install Python 3.10 or newer.
2. Install the dependency with `python -m pip install -r requirements.txt`.
3. Start the application with `python main.py` or double-click `run.bat` on
   Windows.

Stockfish is optional. Open the **Settings** tab to enter or browse to a
Stockfish executable, choose Stockfish, and apply the settings. The app uses
`C:\Users\amitj\Downloads\stockfish-windows-x86-64-universal\stockfish\stockfish-windows-x86-64-universal.exe`
as its initial path on this machine. If that executable is unavailable, the app
reports the issue and keeps the built-in Python engine available. Engine
preferences are stored in `.chess_studio.json` beside the application.

## Features

- Play as White, play as Black, or play a two-player game.
- Review moves with the clickable notation and position navigation buttons.
- Import and export PGN, or load a previously saved database game.
- Configure engine search time, custom-engine depth, and Stockfish skill.
- Track evaluations by move, view the evaluation graph and best-move hint, and
  enable approximate blunder/inaccuracy feedback.
- Flip the board, choose a board theme or letter pieces, and select a promotion
  piece.
- Optional clocks and move sounds, plus check highlighting, captured-piece
  summaries, and common opening-name recognition.
- Completed games are stored in `chess_games.db` with player names, time control,
  PGN headers, and timestamps. Existing database tables are migrated in place.

## Project structure

- `main.py` builds the Tkinter interface and coordinates play.
- `game_session.py` validates FEN/PGN input and owns replayable game-line data.
- `engine.py` contains position evaluation and the custom search engine.
- `database.py` handles SQLite storage and legacy-schema migration.

## Tests

Run the focused unit tests with:

```powershell
python -m unittest discover -s tests -v
```

The evaluation feedback is a practical comparison of engine scores before and
after a move, not a tournament-grade blunder classifier. Opening names are
recognized from a small set of common move sequences.
