import json
import math
import os
import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import chess
import chess.engine
import chess.pgn

from database import ChessDatabase
from engine import analyze_position, evaluate_board
from game_session import GameLine, board_from_fen, parse_pgn_text


APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, ".chess_studio.json")
DEFAULT_STOCKFISH_PATH = (
    r"C:\Users\amitj\Downloads\stockfish-windows-x86-64-universal"
    r"\stockfish\stockfish-windows-x86-64-universal.exe"
)
BOARD_SIZE = 560
SQUARE_SIZE = BOARD_SIZE // 8

UNICODE_PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

THEMES = {
    "Classic": ("#EEEED2", "#769656", "#BACA2B"),
    "Ocean": ("#DCEAF2", "#527D9B", "#E7C766"),
    "Slate": ("#D5D8DC", "#69747E", "#D5A94C"),
}

OPENING_LINES = {
    ("e4", "e5", "Nf3", "Nc6", "Bb5"): "Ruy Lopez",
    ("e4", "e5", "Nf3", "Nc6", "Bc4"): "Italian Game",
    ("e4", "c5"): "Sicilian Defense",
    ("e4", "c6"): "Caro-Kann Defense",
    ("e4", "e6"): "French Defense",
    ("d4", "d5", "c4"): "Queen's Gambit",
    ("d4", "Nf6", "c4", "g6"): "King's Indian Defense",
    ("d4", "Nf6", "c4", "e6", "Nc3", "Bb4"): "Nimzo-Indian Defense",
    ("Nf3", "d5", "g3"): "King's Indian Attack",
}


class AdvancedChessStudio:
    def __init__(self, root):
        self.root = root
        self.root.title("Chess Studio")
        self.root.geometry("1220x860")
        self.root.minsize(1160, 790)
        self.root.configure(bg="#151A21")

        self.settings = self.load_settings()
        self.db = ChessDatabase()
        self.engine_lock = threading.Lock()
        self.analysis_lock = threading.Lock()
        self.stockfish_engine = None
        self.analysis_generation = 0
        self.game_saved = False
        self.closing = False

        self.game_line = GameLine.from_moves(chess.Board())
        self.starting_board = self.game_line.starting_board
        self.positions = self.game_line.positions
        self.moves = self.game_line.moves
        self.move_san = self.game_line.move_san
        self.evaluations = self.game_line.evaluations
        self.mates = self.game_line.mates
        self.current_ply = 0
        self.board = self.positions[0].copy(stack=True)
        self.selected_square = None
        self.legal_moves_for_selected = []
        self.best_suggested_move = None
        self.best_move_text = "Best move: —"
        self.feedback_text = ""
        self.last_move = None
        self.white_captures = self.game_line.white_captures
        self.black_captures = self.game_line.black_captures
        self.animation_id = 0
        self.animation_phase = 0
        self.clock_enabled = False
        self.clock_minutes = 5
        self.clock_remaining = {chess.WHITE: 300.0, chess.BLACK: 300.0}
        self.clock_last_tick = time.monotonic()
        self.clock_job = None

        self.setup_ui()
        self.init_stockfish()
        self.draw_board()
        self.update_eval_display(0.0)
        self.update_game_labels()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.request_position_work()
        self.schedule_clock_tick()

    def load_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
        except FileNotFoundError:
            settings = {}
            self._settings_error = ""
        except (OSError, json.JSONDecodeError) as exc:
            settings = {}
            self._settings_error = str(exc)
        else:
            self._settings_error = ""
        if not isinstance(settings, dict):
            self._settings_error = "Settings must be a JSON object."
            settings = {}
        try:
            analysis_time = float(settings.get("analysis_time", 1.0))
            depth = int(settings.get("depth", 3))
            skill = int(settings.get("skill", 10))
            if not math.isfinite(analysis_time) or not 0.1 <= analysis_time <= 30:
                raise ValueError
            if not 1 <= depth <= 5 or not 0 <= skill <= 20:
                raise ValueError
        except (TypeError, ValueError):
            self._settings_error = "Invalid saved engine settings; using defaults."
            analysis_time, depth, skill = 1.0, 3, 10
        engine = settings.get("engine", "stockfish")
        if engine not in ("custom", "stockfish"):
            self._settings_error = "Invalid saved engine choice; using Custom AI."
            engine = "custom"
        stockfish_path = settings.get(
            "stockfish_path") or DEFAULT_STOCKFISH_PATH
        if not isinstance(stockfish_path, str):
            self._settings_error = "Invalid Stockfish path setting."
            stockfish_path = DEFAULT_STOCKFISH_PATH
        return {
            "stockfish_path": stockfish_path,
            "engine": engine,
            "analysis_time": analysis_time,
            "depth": depth,
            "skill": skill,
        }

    def setup_ui(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#151A21")
        style.configure("Panel.TFrame", background="#202832")
        style.configure("TLabel", background="#151A21", foreground="#E6EDF3")
        style.configure(
            "Title.TLabel", font=("Helvetica", 20, "bold"),
            background="#151A21", foreground="#F0F6FC")
        style.configure(
            "Subtitle.TLabel", font=("Helvetica", 9),
            background="#151A21", foreground="#9AA7B5")
        style.configure(
            "Section.TLabel", font=("Helvetica", 9, "bold"),
            background="#151A21", foreground="#9AA7B5")
        style.configure(
            "PanelSection.TLabel", font=("Helvetica", 9, "bold"),
            background="#202832", foreground="#9AA7B5")
        style.configure(
            "Eval.TLabel", font=("Consolas", 21, "bold"),
            background="#202832", foreground="#F0F6FC")
        style.configure(
            "Status.TLabel", font=("Helvetica", 10, "bold"),
            background="#202832", foreground="#9FE3B0")
        style.configure(
            "Clock.TLabel", font=("Consolas", 15, "bold"),
            background="#11161C", foreground="#F0F6FC", padding=5)
        style.configure(
            "TButton", font=("Helvetica", 9, "bold"), padding=(8, 5),
            background="#2D3946", foreground="#E6EDF3")
        style.map("TButton", background=[("active", "#3B4A59")])
        style.configure(
            "TEntry", fieldbackground="#11161C", foreground="#E6EDF3",
            insertcolor="#E6EDF3", padding=5)
        style.configure(
            "TCombobox", fieldbackground="#11161C", foreground="#E6EDF3")
        style.configure(
            "TRadiobutton", background="#202832", foreground="#E6EDF3",
            font=("Helvetica", 9))
        style.map("TRadiobutton", background=[("active", "#202832")])
        style.configure(
            "Card.TLabelframe", background="#202832", bordercolor="#35414D",
            relief="solid", borderwidth=1)
        style.configure(
            "Card.TLabelframe.Label", background="#202832",
            foreground="#9AA7B5", font=("Helvetica", 9, "bold"))

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)

        header = ttk.Frame(main_frame)
        header.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header, text="CHESS STUDIO", style="Title.TLabel").pack(
            anchor=tk.W)
        ttk.Label(
            header, text="Play, analyze, and review your games",
            style="Subtitle.TLabel").pack(anchor=tk.W, pady=(2, 0))

        fen_frame = ttk.Frame(main_frame)
        fen_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(fen_frame, text="POSITION FEN", style="Section.TLabel").pack(
            side=tk.LEFT, padx=(0, 8))
        self.fen_display = ttk.Entry(fen_frame, font=("Consolas", 10))
        self.fen_display.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(fen_frame, text="Load FEN", command=self.load_fen).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(fen_frame, text="Import PGN", command=self.import_pgn).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(fen_frame, text="Export PGN", command=self.export_pgn).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(fen_frame, text="Copy FEN", command=self.copy_fen).pack(
            side=tk.LEFT, padx=2)

        content = ttk.Frame(main_frame)
        content.pack(fill=tk.BOTH, expand=True)
        self.eval_canvas = tk.Canvas(
            content, width=42, height=BOARD_SIZE, bg="#151A21",
            highlightthickness=0)
        self.eval_canvas.pack(side=tk.LEFT, padx=(0, 8))
        self.board_canvas = tk.Canvas(
            content, width=BOARD_SIZE, height=BOARD_SIZE, bg="#202832",
            highlightthickness=2, highlightbackground="#35414D")
        self.board_canvas.pack(side=tk.LEFT, padx=(0, 12))
        self.board_canvas.bind("<Button-1>", self.on_square_click)

        panel = ttk.Frame(content, width=390, style="Panel.TFrame", padding=12)
        panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        panel.pack_propagate(False)

        self.tabs = ttk.Notebook(panel)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        self.play_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=8)
        self.settings_tab = ttk.Frame(
            self.tabs, style="Panel.TFrame", padding=8)
        self.tabs.add(self.play_tab, text="Play")
        self.tabs.add(self.settings_tab, text="Settings")

        self.build_game_controls(self.play_tab)
        self.build_engine_controls(self.settings_tab)

        info_frame = ttk.Frame(self.play_tab, style="Panel.TFrame")
        info_frame.pack(fill=tk.X, pady=(6, 0))
        self.eval_label = ttk.Label(
            info_frame, text="+0.00", style="Eval.TLabel")
        self.eval_label.pack(side=tk.LEFT, anchor=tk.W)
        self.status_label = ttk.Label(
            info_frame, text="White to move", style="Status.TLabel")
        self.status_label.pack(side=tk.RIGHT, anchor=tk.E)
        self.best_move_label = ttk.Label(
            self.play_tab, text=self.best_move_text, background="#202832",
            foreground="#C4D8FF", font=("Helvetica", 9, "bold"))
        self.best_move_label.pack(anchor=tk.W, pady=(3, 0))
        self.feedback_label = ttk.Label(
            self.play_tab, text="", background="#202832", foreground="#F0B44D",
            font=("Helvetica", 9, "bold"))
        self.feedback_label.pack(anchor=tk.W, pady=(2, 0))

        ttk.Label(self.play_tab, text="EVALUATION BY MOVE",
                  style="PanelSection.TLabel").pack(anchor=tk.W, pady=(6, 1))
        self.graph_canvas = tk.Canvas(
            self.play_tab, height=92, bg="#11161C", highlightthickness=1,
            highlightbackground="#35414D")
        self.graph_canvas.pack(fill=tk.X)

        self.opening_label = ttk.Label(
            self.play_tab, text="Opening: Starting position",
            background="#202832", foreground="#9AA7B5")
        self.opening_label.pack(anchor=tk.W, pady=(5, 1))
        self.captured_label = ttk.Label(
            self.play_tab, text="Captured by White: —   |   by Black: —",
            background="#202832", foreground="#D8DEE4")
        self.captured_label.pack(anchor=tk.W, pady=(1, 4))

        ttk.Label(self.play_tab, text="MOVE HISTORY (click a move to review)",
                  style="PanelSection.TLabel").pack(anchor=tk.W, pady=(3, 2))
        self.log_box = tk.Text(
            self.play_tab, height=7, font=("Consolas", 10), state=tk.DISABLED,
            bg="#11161C", fg="#D8DEE4", insertbackground="#D8DEE4",
            selectbackground="#35506B", relief=tk.FLAT, padx=7, pady=5,
            highlightthickness=1, highlightbackground="#35414D")
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.bind("<Button-1>", self.on_log_click)

        nav_frame = ttk.Frame(self.play_tab, style="Panel.TFrame")
        nav_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(nav_frame, text="|<", command=lambda: self.navigate(0)).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(nav_frame, text="Previous", command=lambda: self.navigate(
            self.current_ply - 1)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(nav_frame, text="Next", command=lambda: self.navigate(
            self.current_ply + 1)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        ttk.Button(nav_frame, text=">|", command=lambda: self.navigate(
            len(self.moves))).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        action_frame = ttk.Frame(self.play_tab, style="Panel.TFrame")
        action_frame.pack(fill=tk.X, pady=(5, 0))
        for column, (text, command) in enumerate((
            ("Undo", self.undo_move),
            ("Reset", self.reset_game),
            ("Saved Games", self.show_db_logs),
        )):
            ttk.Button(action_frame, text=text, command=command).grid(
                row=0, column=column, sticky="ew", padx=2, pady=2)
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        action_frame.columnconfigure(2, weight=1)

        if self._settings_error:
            self.engine_status_label.config(
                text=self._settings_error, foreground="#F0B44D")

    def build_game_controls(self, panel):
        frame = ttk.LabelFrame(
            panel, text="  GAME  ", style="Card.TLabelframe", padding=7)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="Mode", background="#202832",
                  foreground="#9AA7B5").grid(row=0, column=0, sticky=tk.W)
        self.play_mode = tk.StringVar(value="Play as White")
        self.mode_box = ttk.Combobox(
            frame, textvariable=self.play_mode, state="readonly",
            values=("Play as White", "Play as Black", "Two-player"), width=16)
        self.mode_box.grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.mode_box.bind("<<ComboboxSelected>>", self.on_mode_change)

        self.flip_board_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Flip board", variable=self.flip_board_var,
            command=self.draw_board).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(frame, text="Theme", background="#202832",
                  foreground="#9AA7B5").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.theme_var = tk.StringVar(value="Classic")
        theme_box = ttk.Combobox(
            frame, textvariable=self.theme_var, state="readonly",
            values=tuple(THEMES), width=12)
        theme_box.grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)
        theme_box.bind("<<ComboboxSelected>>",
                       lambda _event: self.draw_board())

        self.piece_style = tk.StringVar(value="Unicode")
        ttk.Combobox(
            frame, textvariable=self.piece_style, state="readonly",
            values=("Unicode", "Letters"), width=10).grid(
                row=1, column=2, sticky=tk.W)
        self.piece_style.trace_add("write", lambda *_args: self.draw_board())

        clock_row = ttk.Frame(frame, style="Panel.TFrame")
        clock_row.grid(row=2, column=0, columnspan=3,
                       sticky=tk.EW, pady=(3, 0))
        self.clock_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            clock_row, text="Clock", variable=self.clock_var,
            command=self.configure_clock).pack(side=tk.LEFT)
        self.clock_minutes_var = tk.StringVar(value="5")
        ttk.Spinbox(
            clock_row, from_=1, to=180, width=4,
            textvariable=self.clock_minutes_var,
            command=self.configure_clock).pack(side=tk.LEFT, padx=(4, 8))
        self.white_clock_label = ttk.Label(
            clock_row, text="White  05:00", style="Clock.TLabel")
        self.white_clock_label.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.black_clock_label = ttk.Label(
            clock_row, text="Black  05:00", style="Clock.TLabel")
        self.black_clock_label.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.clock_minutes_var.trace_add(
            "write", lambda *_args: self.configure_clock())

        self.sound_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Move sounds", variable=self.sound_var).grid(
                row=3, column=0, sticky=tk.W)
        self.blunder_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text="Move feedback", variable=self.blunder_var).grid(
                row=3, column=1, columnspan=2, sticky=tk.W)
        ttk.Label(frame, text="Player names", background="#202832",
                  foreground="#9AA7B5").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.white_name_var = tk.StringVar(value="White")
        self.black_name_var = tk.StringVar(value="Black")
        ttk.Entry(frame, textvariable=self.white_name_var, width=11).grid(
            row=4, column=1, sticky=tk.EW, padx=4)
        ttk.Entry(frame, textvariable=self.black_name_var, width=11).grid(
            row=4, column=2, sticky=tk.EW, padx=4)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

    def build_engine_controls(self, panel):
        frame = ttk.LabelFrame(
            panel, text="  ENGINE SETTINGS  ", style="Card.TLabelframe",
            padding=10)
        frame.pack(fill=tk.X, pady=(6, 0))

        self.engine_mode = tk.StringVar(
            value=self.settings.get("engine", "custom"))
        ttk.Radiobutton(
            frame, text="Stockfish", value="stockfish",
            variable=self.engine_mode).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(
            frame, text="Custom AI", value="custom",
            variable=self.engine_mode).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(frame, text="Executable", background="#202832",
                  foreground="#9AA7B5").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.stockfish_path_var = tk.StringVar(
            value=self.settings.get("stockfish_path", DEFAULT_STOCKFISH_PATH))
        ttk.Entry(frame, textvariable=self.stockfish_path_var).grid(
            row=1, column=1, sticky=tk.EW, padx=4)
        ttk.Button(frame, text="Browse", command=self.browse_stockfish).grid(
            row=1, column=2, padx=2)

        ttk.Label(frame, text="Search (sec)", background="#202832",
                  foreground="#9AA7B5").grid(row=2, column=0, sticky=tk.W)
        self.analysis_time_var = tk.StringVar(
            value=str(self.settings.get("analysis_time", 1.0)))
        ttk.Spinbox(
            frame, from_=0.1, to=30.0, increment=0.1, width=7,
            textvariable=self.analysis_time_var).grid(
                row=2, column=1, sticky=tk.W, padx=4, pady=2)
        ttk.Label(frame, text="Custom depth", background="#202832",
                  foreground="#9AA7B5").grid(row=3, column=0, sticky=tk.W)
        self.depth_var = tk.StringVar(value=str(self.settings.get("depth", 3)))
        ttk.Spinbox(
            frame, from_=1, to=5, width=7, textvariable=self.depth_var).grid(
                row=3, column=1, sticky=tk.W, padx=4)
        ttk.Label(frame, text="Stockfish skill (0-20)", background="#202832",
                  foreground="#9AA7B5").grid(row=4, column=0, sticky=tk.W)
        self.skill_var = tk.StringVar(
            value=str(self.settings.get("skill", 10)))
        ttk.Spinbox(
            frame, from_=0, to=20, width=7, textvariable=self.skill_var).grid(
                row=4, column=1, sticky=tk.W, padx=4)
        ttk.Button(
            frame, text="Apply settings", command=self.apply_engine_settings
        ).grid(row=4, column=2, padx=2)
        frame.columnconfigure(1, weight=1)

        self.engine_status_label = ttk.Label(
            panel, text="Checking Stockfish…", background="#202832",
            foreground="#9AA7B5", font=("Helvetica", 9), wraplength=320)
        self.engine_status_label.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))
        ttk.Label(
            panel,
            text="Choose a Stockfish executable above or use the built-in "
                 "Custom AI. Apply settings to test and save the selection.",
            background="#202832", foreground="#9AA7B5", wraplength=320,
            justify=tk.LEFT).pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

    def browse_stockfish(self):
        path = filedialog.askopenfilename(
            title="Select Stockfish executable",
            filetypes=(("Executable", "*.exe"), ("All files", "*.*")))
        if path:
            self.stockfish_path_var.set(path)

    def init_stockfish(self):
        path = self.settings.get("stockfish_path", "").strip()
        if not path:
            self.stockfish_engine = None
            self.engine_status_label.config(
                text="Stockfish path not set; Custom AI is available")
            if self.engine_mode.get() == "stockfish":
                self.engine_mode.set("custom")
            return
        if not os.path.isfile(path):
            self.stockfish_engine = None
            self.engine_status_label.config(
                text="Stockfish executable not found; check the configured path",
                foreground="#F0B44D")
            if self.engine_mode.get() == "stockfish":
                self.engine_mode.set("custom")
            return
        try:
            with self.engine_lock:
                self.stockfish_engine = chess.engine.SimpleEngine.popen_uci(
                    path)
            self.engine_status_label.config(
                text="Stockfish connected", foreground="#9FE3B0")
        except (OSError, chess.engine.EngineError) as exc:
            self.stockfish_engine = None
            self.engine_status_label.config(
                text=f"Stockfish could not start: {exc}", foreground="#F08080")
            if self.engine_mode.get() == "stockfish":
                self.engine_mode.set("custom")

    def apply_engine_settings(self):
        try:
            analysis_time = float(self.analysis_time_var.get())
            depth = int(self.depth_var.get())
            skill = int(self.skill_var.get())
            if not 0.1 <= analysis_time <= 30:
                raise ValueError("Search time must be from 0.1 to 30 seconds.")
            if not 1 <= depth <= 5:
                raise ValueError("Custom depth must be from 1 to 5.")
            if not 0 <= skill <= 20:
                raise ValueError("Stockfish skill must be from 0 to 20.")
        except ValueError as exc:
            messagebox.showerror("Invalid engine settings", str(exc))
            return

        path = self.stockfish_path_var.get().strip()
        if self.engine_mode.get() == "stockfish" and (
                not path or not os.path.isfile(path)):
            messagebox.showerror(
                "Stockfish unavailable",
                "Select a valid Stockfish executable or choose Custom AI.")
            return

        if path != self.settings.get("stockfish_path", ""):
            self.stop_stockfish()
            self.settings["stockfish_path"] = path
            self.init_stockfish()
        if self.engine_mode.get() == "stockfish" and self.stockfish_engine is None:
            return

        self.settings.update({
            "engine": self.engine_mode.get(),
            "analysis_time": analysis_time,
            "depth": depth,
            "skill": skill,
            "stockfish_path": path,
        })
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as settings_file:
                json.dump(self.settings, settings_file, indent=2)
        except OSError as exc:
            self.engine_status_label.config(
                text=f"Could not save settings: {exc}", foreground="#F08080")
        else:
            self.engine_status_label.config(
                text="Settings applied", foreground="#9FE3B0")
            self.request_position_work()

    def stop_stockfish(self):
        with self.engine_lock:
            if self.stockfish_engine:
                self.stockfish_engine.quit()
                self.stockfish_engine = None

    def board_square_at(self, col, row):
        if self.flip_board_var.get():
            col, row = 7 - col, 7 - row
        return chess.square(col, 7 - row)

    def screen_square(self, square):
        file_index = chess.square_file(square)
        rank_index = chess.square_rank(square)
        if self.flip_board_var.get():
            file_index, rank_index = 7 - file_index, 7 - rank_index
        return file_index, 7 - rank_index

    def draw_board(self):
        self.board_canvas.delete("all")
        light, dark, selected = THEMES.get(
            self.theme_var.get(), THEMES["Classic"])
        pulse = ("#F8C766", "#E7B64B", "#F6D27E", "#E7B64B")[
            self.animation_phase % 4]
        for square in chess.SQUARES:
            file_index, row = self.screen_square(square)
            x1, y1 = file_index * SQUARE_SIZE, row * SQUARE_SIZE
            x2, y2 = x1 + SQUARE_SIZE, y1 + SQUARE_SIZE
            color = light if (file_index + row) % 2 == 0 else dark
            if self.last_move and square in (
                    self.last_move.from_square, self.last_move.to_square):
                color = pulse if self.animation_phase else "#F6F669"
            if square == self.selected_square:
                color = selected
            self.board_canvas.create_rectangle(
                x1, y1, x2, y2, fill=color, outline="")

            if file_index == 0:
                self.board_canvas.create_text(
                    x1 + 7, y1 + 10,
                    text=str(row + 1 if self.flip_board_var.get() else 8 - row),
                    font=("Arial", 8, "bold"), fill="#333")
            if row == 7:
                self.board_canvas.create_text(
                    x2 - 10, y2 - 8, text=chess.FILE_NAMES[
                        7 - file_index if self.flip_board_var.get() else file_index],
                    font=("Arial", 8, "bold"), fill="#333")

            piece = self.board.piece_at(square)
            if piece:
                symbol = UNICODE_PIECES[piece.symbol()]
                if self.piece_style.get() == "Letters":
                    symbol = piece.symbol().upper()
                piece_color = "#F8F8F2" if piece.color == chess.WHITE else "#202020"
                self.board_canvas.create_text(
                    x1 + 35, y1 + 35, text=symbol,
                    font=("Arial", 37, "bold" if self.piece_style.get()
                          == "Letters" else "normal"),
                    fill=piece_color, activefill="#FFCA62")

            if square in self.legal_moves_for_selected:
                dot_color = "#E53935" if self.board.is_capture(
                    chess.Move(self.selected_square, square)) else "#59616A"
                radius = 10 if self.board.piece_at(square) is None else 19
                self.board_canvas.create_oval(
                    x1 + 35 - radius, y1 + 35 - radius,
                    x1 + 35 + radius, y1 + 35 + radius,
                    fill=dot_color, outline="", stipple="gray50")

            if self.board.is_check() and self.board.king(self.board.turn) == square:
                self.board_canvas.create_rectangle(
                    x1 + 3, y1 + 3, x2 - 3, y2 - 3,
                    outline="#E34D59", width=4)

        if self.best_suggested_move and self.current_ply == len(self.moves):
            fx, fy = self.screen_square(self.best_suggested_move.from_square)
            tx, ty = self.screen_square(self.best_suggested_move.to_square)
            self.board_canvas.create_line(
                fx * SQUARE_SIZE + 35, fy * SQUARE_SIZE + 35,
                tx * SQUARE_SIZE + 35, ty * SQUARE_SIZE + 35,
                fill="#FF5722", width=4, arrow=tk.LAST)

        self.fen_display.delete(0, tk.END)
        self.fen_display.insert(0, self.board.fen())
        self.draw_eval_graph()

    def start_move_animation(self):
        self.animation_id += 1
        animation_id = self.animation_id

        def pulse(phase):
            if animation_id != self.animation_id or self.closing:
                return
            self.animation_phase = phase
            self.draw_board()
            if phase < 3:
                self.root.after(140, lambda: pulse(phase + 1))
            else:
                self.animation_phase = 0

        pulse(1)

    def update_eval_display(self, eval_value, mate=None):
        if mate is not None:
            if mate == 0:
                label = "Checkmate"
            else:
                label = f"Mate in {abs(mate)}" if mate > 0 else f"Mated in {abs(mate)}"
            bar_value = 10.0 if mate > 0 else -10.0
        else:
            label = f"{eval_value:+.2f}"
            bar_value = eval_value
        self.eval_label.config(text=label)
        self.update_eval_bar(bar_value)

    def update_eval_bar(self, eval_value):
        self.eval_canvas.delete("all")
        height, left, right = BOARD_SIZE, 10, 32
        clamped = max(-10.0, min(10.0, eval_value))
        split_y = int(height * (10.0 - clamped) / 20.0)
        self.eval_canvas.create_rectangle(
            left, 0, right, height, fill="#252D36", outline="#46515D")
        self.eval_canvas.create_rectangle(
            left + 1, split_y, right - 1, height - 1,
            fill="#F0F2F4", outline="")
        for fraction in (0.25, 0.5, 0.75):
            tick_y = int(height * fraction)
            self.eval_canvas.create_line(
                left, tick_y, right, tick_y, fill="#87929E",
                width=1 if fraction != 0.5 else 2)
        self.eval_canvas.create_line(
            4, split_y, 38, split_y, fill="#F0B44D", width=3)

    def draw_eval_graph(self):
        self.graph_canvas.delete("all")
        width = max(self.graph_canvas.winfo_width(), 250)
        height = 92
        midpoint = height // 2
        self.graph_canvas.create_line(
            4, midpoint, width - 4, midpoint, fill="#46515D")
        values = self.evaluations[:self.current_ply + 1]
        if len(values) < 2:
            self.graph_canvas.create_text(
                width // 2, midpoint, text="Evaluation trend appears as you play",
                fill="#718091", font=("Helvetica", 8))
            return
        points = []
        for index, score in enumerate(values):
            if score is None:
                continue
            x = 5 + index * (width - 10) / max(len(values) - 1, 1)
            y = midpoint - max(-10.0, min(10.0, score)) * (height - 12) / 20.0
            points.extend((x, y))
        if len(points) >= 4:
            self.graph_canvas.create_line(
                *points, fill="#73C9A5", width=2, smooth=True)
        for index, score in enumerate(values):
            if score is not None:
                x = 5 + index * (width - 10) / max(len(values) - 1, 1)
                y = midpoint - max(-10.0, min(10.0, score)
                                   ) * (height - 12) / 20.0
                self.graph_canvas.create_oval(
                    x - 2, y - 2, x + 2, y + 2, fill="#F0B44D", outline="")

    def engine_color(self):
        return {
            "Play as White": chess.BLACK,
            "Play as Black": chess.WHITE,
            "Two-player": None,
        }.get(self.play_mode.get())

    def on_mode_change(self, _event=None):
        self.update_game_labels()
        self.request_position_work()

    def on_square_click(self, event):
        if self.board.is_game_over():
            return
        engine_color = self.engine_color()
        if engine_color == self.board.turn:
            return
        col = event.x // SQUARE_SIZE
        row = event.y // SQUARE_SIZE
        if not 0 <= col < 8 or not 0 <= row < 8:
            return
        clicked_square = self.board_square_at(col, row)

        if self.selected_square is None:
            piece = self.board.piece_at(clicked_square)
            if piece and piece.color == self.board.turn:
                self.selected_square = clicked_square
                self.legal_moves_for_selected = [
                    move.to_square for move in self.board.legal_moves
                    if move.from_square == clicked_square]
        else:
            move = chess.Move(self.selected_square, clicked_square)
            moving_piece = self.board.piece_at(self.selected_square)
            if moving_piece and moving_piece.piece_type == chess.PAWN \
                    and chess.square_rank(clicked_square) in (0, 7):
                promotion = self.choose_promotion()
                if promotion is not None:
                    move.promotion = promotion
            if move in self.board.legal_moves:
                self.execute_move(move, human_move=True)
            self.selected_square = None
            self.legal_moves_for_selected = []
        self.draw_board()

    def choose_promotion(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Promote pawn")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        result = {"piece": None}
        ttk.Label(dialog, text="Choose a promotion piece").pack(
            padx=12, pady=8)
        buttons = ttk.Frame(dialog)
        buttons.pack(padx=8, pady=(0, 8))
        for piece_type, label in (
                (chess.QUEEN, "Queen"), (chess.ROOK, "Rook"),
                (chess.BISHOP, "Bishop"), (chess.KNIGHT, "Knight")):
            ttk.Button(
                buttons, text=label,
                command=lambda piece=piece_type: (
                    result.update(piece=piece), dialog.destroy())
            ).pack(side=tk.LEFT, padx=2)
        self.root.wait_window(dialog)
        return result["piece"]

    def execute_move(self, move, human_move=False, trigger_engine=True):
        if self.current_ply < len(self.moves):
            self.truncate_game(self.current_ply)
        before_eval = self.evaluations[-1] if self.evaluations else 0.0
        if before_eval is None:
            before_eval = evaluate_board(self.board) / 100.0
        self.board, san_text, _captured, _mover = self.game_line.append_move(
            move)
        self.current_ply += 1
        self.last_move = move
        self.best_suggested_move = None
        self.game_saved = False
        self.selected_square = None
        self.legal_moves_for_selected = []
        self.feedback_text = ""
        self.update_log_box()
        self.update_game_labels()
        self.play_sound()
        self.start_move_animation()
        if self.board.is_game_over():
            self.finish_game()
        elif trigger_engine:
            self.request_position_work(
                human_move=human_move, before_eval=before_eval)

    def schedule_analysis(self, human_move=False, before_eval=None):
        if self.closing:
            return
        self.analysis_generation += 1
        generation = self.analysis_generation
        board_snapshot = self.board.copy(stack=True)
        position_ply = self.current_ply
        mode = self.engine_mode.get()
        analysis_time = self.settings.get("analysis_time", 1.0)
        depth = self.settings.get("depth", 3)
        skill = self.settings.get("skill", 10)
        self.status_label.config(text="Analyzing position")
        self.engine_status_label.config(text="Analysis running…")
        self.best_suggested_move = None
        self.best_move_label.config(text="Finding best move…")
        self.draw_board()

        def analyze():
            try:
                with self.analysis_lock:
                    if generation != self.analysis_generation or self.closing:
                        return
                    if mode == "stockfish":
                        if self.stockfish_engine is None:
                            raise chess.engine.EngineError(
                                "Stockfish is not connected. Check the executable path.")
                        with self.engine_lock:
                            if "Skill Level" in self.stockfish_engine.options:
                                self.stockfish_engine.configure(
                                    {"Skill Level": skill})
                            info = self.stockfish_engine.analyse(
                                board_snapshot,
                                chess.engine.Limit(time=analysis_time))
                        score = info["score"].white()
                        mate = score.mate()
                        score_pawns = score.score(mate_score=1000) / 100.0
                        principal_variation = info.get("pv", [])
                        best_move = (
                            principal_variation[0]
                            if principal_variation else None)
                    else:
                        score_pawns, best_move = analyze_position(
                            board_snapshot, depth=depth)
                        mate = (
                            -1 if board_snapshot.turn == chess.WHITE else 1
                        ) if board_snapshot.is_checkmate() else None
                self.root.after(
                    0, lambda: self.on_analysis_result(
                        generation, position_ply, board_snapshot.fen(),
                        score_pawns, mate, best_move, human_move, before_eval))
            except Exception as exc:
                self.root.after(
                    0, lambda error=str(exc): self.on_analysis_error(
                        generation, error))

        threading.Thread(target=analyze, daemon=True).start()

    def request_position_work(self, human_move=False, before_eval=None):
        if self.engine_color() == self.board.turn:
            self.analysis_generation += 1
            self.maybe_play_engine(human_move, before_eval)
        else:
            self.schedule_analysis(human_move, before_eval)

    def on_analysis_error(self, generation, error):
        if generation != self.analysis_generation or self.closing:
            return
        self.status_label.config(text="Analysis failed", foreground="#F08080")
        self.engine_status_label.config(
            text=f"Engine error: {error}", foreground="#F08080")

    def on_analysis_result(
            self, generation, position_ply, snapshot_fen, score, mate,
            best_move, human_move, before_eval):
        if generation != self.analysis_generation or self.closing:
            return
        if position_ply != self.current_ply or snapshot_fen != self.board.fen():
            return
        self.evaluations[position_ply] = score
        self.mates[position_ply] = mate
        self.best_suggested_move = best_move
        if best_move and best_move in self.board.legal_moves:
            best_text = self.board.san(best_move)
            self.best_move_text = f"Best move: {best_text}"
        else:
            self.best_move_text = "Best move: —"
        self.best_move_label.config(text=self.best_move_text)
        self.update_eval_display(score, mate)
        self.draw_eval_graph()
        self.draw_board()
        self.engine_status_label.config(
            text=f"{self.engine_mode.get().title()} analysis complete",
            foreground="#9FE3B0")
        if human_move and before_eval is not None and self.blunder_var.get():
            move_loss = (before_eval - score if self.board.turn == chess.BLACK
                         else score - before_eval)
            if move_loss >= 2:
                self.feedback_text = f"Blunder? Evaluation shifted {move_loss:.1f} pawns."
            elif move_loss >= 1:
                self.feedback_text = f"Inaccuracy: evaluation shifted {move_loss:.1f} pawns."
            else:
                self.feedback_text = ""
            self.feedback_label.config(text=self.feedback_text)
        self.update_game_labels()

    def maybe_play_engine(self, human_move=False, before_eval=None):
        engine_color = self.engine_color()
        if (engine_color is None or self.board.turn != engine_color
                or self.board.is_game_over() or self.current_ply < len(self.moves)):
            return
        generation = self.analysis_generation
        self.root.after(100, lambda: self.play_engine_turn(
            human_move, before_eval, generation))

    def play_engine_turn(self, human_move=False, before_eval=None, generation=None):
        if (self.closing or self.board.is_game_over()
                or self.board.turn != self.engine_color()
                or self.current_ply < len(self.moves)):
            return
        generation = self.analysis_generation if generation is None else generation
        if generation != self.analysis_generation:
            return
        snapshot = self.board.copy(stack=True)
        mode = self.engine_mode.get()
        analysis_time = self.settings.get("analysis_time", 1.0)
        depth = self.settings.get("depth", 3)
        skill = self.settings.get("skill", 10)

        def calculate():
            try:
                with self.analysis_lock:
                    if generation != self.analysis_generation or self.closing:
                        return
                    if mode == "stockfish":
                        if self.stockfish_engine is None:
                            raise chess.engine.EngineError(
                                "Stockfish is not connected. Check the executable path.")
                        with self.engine_lock:
                            if "Skill Level" in self.stockfish_engine.options:
                                self.stockfish_engine.configure(
                                    {"Skill Level": skill})
                            info = self.stockfish_engine.analyse(
                                snapshot,
                                chess.engine.Limit(time=analysis_time))
                        score_obj = info["score"].white()
                        score = score_obj.score(mate_score=1000) / 100.0
                        mate = score_obj.mate()
                        pv = info.get("pv", [])
                        move = pv[0] if pv else None
                    else:
                        score, move = analyze_position(snapshot, depth=depth)
                        mate = (
                            -1 if snapshot.turn == chess.WHITE else 1
                        ) if snapshot.is_checkmate() else None
                self.root.after(
                    0, lambda: self.complete_engine_turn(
                        generation, snapshot.fen(), score, mate, move,
                        human_move, before_eval))
            except Exception as exc:
                self.root.after(
                    0, lambda error=str(exc): self.on_engine_error(
                        generation, error))

        self.status_label.config(text="Engine thinking…")
        self.best_move_label.config(text="Engine is choosing a move…")
        threading.Thread(target=calculate, daemon=True).start()

    def complete_engine_turn(
            self, generation, snapshot_fen, score, mate, move,
            human_move=False, before_eval=None):
        if self.closing or generation != self.analysis_generation:
            return
        if snapshot_fen != self.board.fen() or self.board.turn != self.engine_color():
            return
        self.evaluations[self.current_ply] = score
        self.mates[self.current_ply] = mate
        self.update_eval_display(score, mate)
        self.draw_eval_graph()
        if human_move and before_eval is not None and self.blunder_var.get():
            move_loss = (before_eval - score if self.board.turn == chess.BLACK
                         else score - before_eval)
            if move_loss >= 2:
                self.feedback_text = (
                    f"Blunder? Evaluation shifted {move_loss:.1f} pawns.")
            elif move_loss >= 1:
                self.feedback_text = (
                    f"Inaccuracy: evaluation shifted {move_loss:.1f} pawns.")
            else:
                self.feedback_text = ""
            self.feedback_label.config(text=self.feedback_text)
        if move and move in self.board.legal_moves:
            san = self.board.san(move)
            self.execute_move(move, human_move=False)
            self.best_move_label.config(text=f"Engine played: {san}")
        else:
            self.best_suggested_move = None
            self.best_move_label.config(text="Best move: —")
            self.status_label.config(text="No legal engine move")

    def on_engine_error(self, generation, error):
        if generation != self.analysis_generation or self.closing:
            return
        self.status_label.config(
            text="Engine unavailable", foreground="#F08080")
        self.engine_status_label.config(
            text=f"Could not make engine move: {error}", foreground="#F08080")

    def update_log_box(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        for full_move in range((len(self.moves) + 1) // 2):
            white_index = full_move * 2
            black_index = white_index + 1
            self.log_box.insert(tk.END, f"{full_move + 1:>2}. ")
            white_start = self.log_box.index(tk.END)
            self.log_box.insert(tk.END, self.move_san[white_index])
            white_end = self.log_box.index(tk.END)
            self.add_move_tag(white_index + 1, white_start, white_end)
            self.log_box.insert(tk.END, "   ")
            if black_index < len(self.moves):
                black_start = self.log_box.index(tk.END)
                self.log_box.insert(tk.END, self.move_san[black_index])
                black_end = self.log_box.index(tk.END)
                self.add_move_tag(black_index + 1, black_start, black_end)
            self.log_box.insert(tk.END, "\n")
        self.log_box.config(state=tk.DISABLED)
        self.log_box.see(tk.END)

    def add_move_tag(self, ply, start, end):
        tag = f"move_{ply}"
        self.log_box.tag_add(tag, start, end)
        if ply == self.current_ply:
            self.log_box.tag_config(tag, background="#35506B")

    def on_log_click(self, event):
        index = self.log_box.index(f"@{event.x},{event.y}")
        tags = self.log_box.tag_names(index)
        for tag in tags:
            if tag.startswith("move_"):
                self.navigate(int(tag[5:]))
                return "break"
        return None

    def navigate(self, ply):
        ply = max(0, min(len(self.moves), ply))
        self.current_ply = ply
        self.analysis_generation += 1
        self.board = self.positions[ply].copy(stack=True)
        self.last_move = self.moves[ply - 1] if ply else None
        self.best_suggested_move = None
        self.selected_square = None
        self.legal_moves_for_selected = []
        self.update_log_box()
        self.update_game_labels()
        self.clock_last_tick = time.monotonic()
        self.draw_board()
        value = self.evaluations[ply]
        if value is not None:
            self.update_eval_display(value, self.mates[ply])
        else:
            self.schedule_analysis()

    def truncate_game(self, ply):
        self.current_ply = ply
        self.board = self.game_line.truncate(ply)

    def update_game_labels(self):
        self.status_label.config(
            text=("Checkmate" if self.board.is_checkmate()
                  else "Check" if self.board.is_check()
                  else f"{'White' if self.board.turn else 'Black'} to move"),
            foreground="#F08080" if self.board.is_check() else "#9FE3B0")
        san_prefix = tuple(self.move_san[:self.current_ply])
        opening = "Unclassified" if san_prefix else "Starting position"
        matching = [
            (len(line), name) for line, name in OPENING_LINES.items()
            if san_prefix[:len(line)] == line]
        if matching:
            opening = max(matching)[1]
        self.opening_label.config(text=f"Opening: {opening}")
        white_symbols = " ".join(
            UNICODE_PIECES[p.symbol()] for p in self.white_captures)
        black_symbols = " ".join(
            UNICODE_PIECES[p.symbol()] for p in self.black_captures)
        self.captured_label.config(
            text=f"Captured by White: {white_symbols or '—'}   |   "
            f"by Black: {black_symbols or '—'}")
        self.draw_eval_graph()
        self.update_clock_labels()

    def play_sound(self):
        if self.sound_var.get():
            self.root.bell()

    def configure_clock(self):
        try:
            minutes = int(self.clock_minutes_var.get())
            if not 1 <= minutes <= 180:
                return
        except ValueError:
            return
        self.clock_enabled = self.clock_var.get()
        self.clock_minutes = minutes
        self.clock_remaining = {
            chess.WHITE: float(minutes * 60),
            chess.BLACK: float(minutes * 60),
        }
        self.clock_last_tick = time.monotonic()
        self.update_clock_labels()

    @staticmethod
    def format_clock(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02}:{seconds % 60:02}"

    def update_clock_labels(self):
        for color, label in (
                (chess.WHITE, self.white_clock_label),
                (chess.BLACK, self.black_clock_label)):
            label.config(
                text=f"{'White' if color else 'Black'}  "
                f"{self.format_clock(self.clock_remaining[color])}")

    def schedule_clock_tick(self):
        if self.closing:
            return
        now = time.monotonic()
        if (self.clock_enabled and self.current_ply == len(self.moves)
                and not self.board.is_game_over()):
            active = self.board.turn
            self.clock_remaining[active] -= now - self.clock_last_tick
            if self.clock_remaining[active] <= 0:
                self.clock_remaining[active] = 0
                self.update_clock_labels()
                self.finish_game(timeout=True)
                return
            self.update_clock_labels()
        self.clock_last_tick = now
        self.clock_job = self.root.after(200, self.schedule_clock_tick)

    def finish_game(self, timeout=False):
        if timeout:
            result = "0-1" if self.board.turn == chess.WHITE else "1-0"
        else:
            result = self.board.result()
        self.analysis_generation += 1
        self.best_suggested_move = None
        self.status_label.config(text=f"Game over: {result}")
        if not self.game_saved:
            time_control = (
                f"{self.clock_minutes}+0" if self.clock_enabled else "-")
            headers = dict(getattr(self, "game_headers", {}))
            headers.update({
                "Event": "Chess Studio",
                "Date": datetime.now().strftime("%Y.%m.%d"),
                "White": self.white_name_var.get().strip() or "White",
                "Black": self.black_name_var.get().strip() or "Black",
                "TimeControl": time_control,
            })
            try:
                self.db.save_game(
                    self.board, result,
                    white_player=self.white_name_var.get().strip() or "White",
                    black_player=self.black_name_var.get().strip() or "Black",
                    time_control=time_control,
                    pgn_headers=headers)
            except sqlite3.Error as exc:
                messagebox.showerror("Could not save game", str(exc))
            else:
                self.game_saved = True
        messagebox.showinfo("Game over", f"Result: {result}")

    def reset_game(self):
        self.analysis_generation += 1
        self.game_line = GameLine.from_moves(chess.Board())
        self.starting_board = self.game_line.starting_board
        self.positions = self.game_line.positions
        self.moves = self.game_line.moves
        self.move_san = self.game_line.move_san
        self.evaluations = self.game_line.evaluations
        self.mates = self.game_line.mates
        self.white_captures = self.game_line.white_captures
        self.black_captures = self.game_line.black_captures
        self.current_ply = 0
        self.board = self.positions[0].copy(stack=True)
        self.last_move = None
        self.best_suggested_move = None
        self.game_saved = False
        self.game_headers = {}
        self.white_name_var.set("White")
        self.black_name_var.set("Black")
        self.feedback_label.config(text="")
        self.update_log_box()
        self.update_eval_display(0.0)
        self.draw_board()
        self.update_game_labels()
        self.configure_clock()
        self.request_position_work()

    def load_fen(self):
        fen = self.fen_display.get().strip()
        try:
            new_board = board_from_fen(fen)
        except ValueError as exc:
            messagebox.showerror("Invalid FEN", str(exc))
            return
        self.load_position(new_board)

    def load_position(self, board, moves=None, headers=None):
        moves = list(moves or [])
        game_line = GameLine.from_moves(board, moves)
        self.analysis_generation += 1
        self.game_line = game_line
        self.starting_board = game_line.starting_board
        self.moves = game_line.moves
        self.move_san = game_line.move_san
        self.positions = game_line.positions
        self.evaluations = game_line.evaluations
        self.mates = game_line.mates
        self.board = game_line.positions[-1].copy(stack=True)
        self.current_ply = len(self.moves)
        self.last_move = self.moves[-1] if self.moves else None
        self.best_suggested_move = None
        self.white_captures = game_line.white_captures
        self.black_captures = game_line.black_captures
        self.game_headers = headers or {}
        if self.game_headers.get("White"):
            self.white_name_var.set(self.game_headers["White"])
        if self.game_headers.get("Black"):
            self.black_name_var.set(self.game_headers["Black"])
        self.game_saved = False
        self.clock_enabled = False
        self.clock_var.set(False)
        self.clock_last_tick = time.monotonic()
        self.update_log_box()
        self.draw_board()
        self.update_game_labels()
        self.schedule_analysis()

    def import_pgn(self):
        path = filedialog.askopenfilename(
            title="Import PGN", filetypes=(("PGN files", "*.pgn"), ("All files", "*.*")))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as pgn_file:
                start_board, moves, headers = parse_pgn_text(pgn_file.read())
            self.load_position(start_board, moves, headers)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not import PGN", str(exc))

    def export_pgn(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".pgn", filetypes=(("PGN files", "*.pgn"),))
        if not path:
            return
        game = chess.pgn.Game.from_board(self.positions[-1])
        headers = getattr(self, "game_headers", {})
        for key in ("Event", "Site", "Date", "Round", "White", "Black", "TimeControl"):
            if headers.get(key):
                game.headers[key] = headers[key]
        game.headers["Result"] = (
            self.board.result() if self.board.is_game_over()
            else headers.get("Result", "*"))
        game.headers["Event"] = headers.get("Event", "Chess Studio")
        game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
        game.headers["White"] = (
            self.white_name_var.get().strip() or headers.get("White", "White"))
        game.headers["Black"] = (
            self.black_name_var.get().strip() or headers.get("Black", "Black"))
        game.headers["TimeControl"] = (
            f"{self.clock_minutes}+0" if self.clock_enabled else "-")
        try:
            with open(path, "w", encoding="utf-8") as pgn_file:
                print(game, file=pgn_file, end="\n\n")
        except OSError as exc:
            messagebox.showerror("Could not export PGN", str(exc))
        else:
            messagebox.showinfo("PGN exported", f"Saved game to {path}")

    def copy_fen(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.board.fen())
        self.status_label.config(text="FEN copied")

    def undo_move(self):
        if self.current_ply == 0:
            return
        remove_count = 1 if self.engine_color() is None else min(2, self.current_ply)
        target = max(0, self.current_ply - remove_count)
        self.truncate_game(target)
        self.analysis_generation += 1
        self.last_move = self.moves[-1] if self.moves else None
        self.game_saved = False
        self.update_log_box()
        self.draw_board()
        self.update_game_labels()
        self.request_position_work()

    def show_db_logs(self):
        records = self.db.fetch_recent_games()
        if not records:
            messagebox.showinfo("Saved games", "No saved games.")
            return
        selection = tk.Toplevel(self.root)
        selection.title("Saved games")
        selection.geometry("540x300")
        listbox = tk.Listbox(selection, bg="#11161C", fg="#E6EDF3")
        listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for game_id, result, _pgn, timestamp in records:
            listbox.insert(
                tk.END, f"Game #{game_id}  |  {result}  |  {timestamp}")

        def load_selected(_event=None):
            if not listbox.curselection():
                return
            record = records[listbox.curselection()[0]]
            pgn_text = self.db.fetch_game_pgn(record[0])
            if not pgn_text:
                messagebox.showerror(
                    "Saved game unavailable", "No PGN was saved.")
                return
            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if game is None:
                messagebox.showerror(
                    "Saved game unavailable", "The stored PGN is invalid.")
                return
            try:
                self.load_position(
                    game.board(), list(game.mainline_moves()), dict(game.headers))
            except ValueError as exc:
                messagebox.showerror("Saved game unavailable", str(exc))
                return
            selection.destroy()

        listbox.bind("<Double-Button-1>", load_selected)
        ttk.Button(selection, text="Load selected", command=load_selected).pack(
            pady=(0, 8))

    def close(self):
        self.closing = True
        self.analysis_generation += 1
        if self.clock_job:
            self.root.after_cancel(self.clock_job)
        try:
            self.stop_stockfish()
        finally:
            self.db.conn.close()
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AdvancedChessStudio(root)
    root.mainloop()
