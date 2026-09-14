#!/usr/bin/env python3
"""
Mine "critical, unclear-advantage" positions from master-game PGN files.

Refined heuristic (per user spec):
  1. Look for a genuine SWING: a short stretch of the game where Stockfish's
     eval moves from "roughly equal" (e.g. ~0.4) to a clear-but-not-crushing
     advantage (e.g. +1.3 / -1.6). The position we collect is the position
     right after that swing has happened and settled -- NOT a position that
     is already completely winning/losing.
  2. The advantage must be STABLE for a few more moves afterwards (so we
     caught a real re-evaluation of the position, not analysis noise).
  3. Material must stay essentially level, both at the candidate position and
     for several moves after it (in the actual game continuation). This
     filters out "obvious blunders / immediate tactics that win material" --
     we specifically want long-term strategic imbalances (bad piece, weak
     squares, better structure, king safety, space, etc.), not a hanging
     piece.
  4. The candidate position itself must be quiet: side to move is not in
     check and has a normal number of legal replies (not a forced sequence).

For every surviving candidate we later run a deep multi-PV analysis
(deep_analyze.py) to get the "solution" line and a second sanity check that
the best line does not simply cash in material either.
"""
import chess
import chess.pgn
import chess.engine
import json
import sys
import os

STOCKFISH_PATH = "/usr/games/stockfish"

MIN_PLY = 14                  # skip opening theory
MAX_PLY_FROM_END = 8          # skip the very end of decided games
LOOKBACK = 8                  # plies to look back for an "equal-ish" baseline
STAB_FORWARD = 6              # plies to require the swing to hold afterwards
GAP_AFTER_PICK = 14           # min ply gap between two picks in the same game

EQUAL_THRESH = 50             # cp: "relatively equal" baseline
TARGET_MIN = 90               # cp: candidate band lower bound (~0.9)
TARGET_MAX = 260              # cp: candidate band upper bound (~2.6)
STAB_MAX = 340                # cp: forward eval must not blow past this
MAX_MATERIAL_IMBALANCE = 1.0  # pawns, at the candidate position
MATERIAL_FLAT_TOL = 0.75      # pawns, allowed material drift over STAB_FORWARD

SCAN_DEPTH = 14

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3.25,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def material_diff(board):
    diff = 0.0
    for piece_type, val in PIECE_VALUES.items():
        diff += val * len(board.pieces(piece_type, chess.WHITE))
        diff -= val * len(board.pieces(piece_type, chess.BLACK))
    return diff


def cp_white_pov(score):
    s = score.white()
    if s.is_mate():
        return None
    return s.score()


def main():
    pgn_dir = sys.argv[1] if len(sys.argv) > 1 else "pgn"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/candidates.json"
    max_games = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    max_candidates = int(sys.argv[4]) if len(sys.argv) > 4 else 400

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    engine.configure({"Threads": 2, "Hash": 256})

    candidates = []
    games_seen = 0
    positions_scanned = 0

    pgn_files = [os.path.join(pgn_dir, f) for f in sorted(os.listdir(pgn_dir))
                 if f.endswith(".pgn")]

    for pgn_file in pgn_files:
        if games_seen >= max_games or len(candidates) >= max_candidates:
            break
        print(f"=== Scanning {pgn_file} ===", flush=True)
        with open(pgn_file, encoding="utf-8", errors="ignore") as fh:
            while games_seen < max_games and len(candidates) < max_candidates:
                game = chess.pgn.read_game(fh)
                if game is None:
                    break
                games_seen += 1
                headers = game.headers
                moves = list(game.mainline_moves())
                total_ply = len(moves)
                lo = MIN_PLY
                hi = total_ply - MAX_PLY_FROM_END
                if hi - lo < STAB_FORWARD + 4:
                    continue

                # Single pass: build board list, eval array, material array
                board = game.board()
                boards = []          # board AFTER move i (index = ply)
                evals = [None] * total_ply
                mats = [None] * total_ply
                eval_lo = max(0, lo - LOOKBACK)
                eval_hi = min(total_ply, hi + STAB_FORWARD)

                for ply, move in enumerate(moves):
                    board.push(move)
                    boards.append(board.copy(stack=False))
                    positions_scanned += 1
                    if eval_lo <= ply < eval_hi:
                        mats[ply] = material_diff(board)
                        if not board.is_check():
                            try:
                                info = engine.analyse(board, chess.engine.Limit(depth=SCAN_DEPTH))
                                evals[ply] = cp_white_pov(info["score"])
                            except Exception as e:
                                print("engine error:", e, flush=True)

                last_pick = -999
                for c in range(lo, hi):
                    if evals[c] is None:
                        continue
                    if c - last_pick < GAP_AFTER_PICK:
                        continue
                    bc = boards[c]
                    if bc.is_check() or bc.legal_moves.count() <= 2:
                        continue
                    mdiff = mats[c]
                    if mdiff is None or abs(mdiff) > MAX_MATERIAL_IMBALANCE:
                        continue
                    cp_now = evals[c]
                    if abs(cp_now) < TARGET_MIN or abs(cp_now) > TARGET_MAX:
                        continue
                    favored_white = cp_now > 0

                    # 1. was there a recent "roughly equal" baseline?
                    window = [evals[j] for j in range(max(0, c - LOOKBACK), c)
                              if evals[j] is not None]
                    if not window or min(abs(v) for v in window) > EQUAL_THRESH:
                        continue

                    # 2. stability forward: stays same-side, in a sane band
                    fwd = [evals[j] for j in range(c + 1, min(total_ply, c + 1 + STAB_FORWARD))
                           if evals[j] is not None]
                    if len(fwd) < max(2, STAB_FORWARD // 2):
                        continue
                    if not all(EQUAL_THRESH <= abs(v) <= STAB_MAX and (v > 0) == favored_white
                               for v in fwd):
                        continue

                    # 3. material stays flat afterwards (no cashed-in tactic)
                    fwd_mats = [mats[j] for j in range(c + 1, min(total_ply, c + 1 + STAB_FORWARD))
                                if mats[j] is not None]
                    if fwd_mats and max(abs(m - mdiff) for m in fwd_mats) > MATERIAL_FLAT_TOL:
                        continue

                    baseline_val = min(window, key=abs)
                    candidates.append({
                        "game_index": games_seen,
                        "pgn_file": os.path.basename(pgn_file),
                        "white": headers.get("White", "?"),
                        "black": headers.get("Black", "?"),
                        "event": headers.get("Event", "?"),
                        "date": headers.get("Date", "?"),
                        "result": headers.get("Result", "?"),
                        "ply": c,
                        "move_number": bc.fullmove_number,
                        "fen": bc.fen(),
                        "material_diff": round(mdiff, 2),
                        "scan_cp": cp_now,
                        "baseline_cp": baseline_val,
                        "jump_cp": abs(cp_now) - abs(baseline_val),
                        "favored_white": favored_white,
                    })
                    last_pick = c
                    if len(candidates) >= max_candidates:
                        break

                if games_seen % 25 == 0:
                    print(f"  ...{games_seen} games, {positions_scanned} positions, "
                          f"{len(candidates)} candidates", flush=True)

    engine.quit()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(candidates, f, indent=1)
    print(f"Scanned {games_seen} games, {positions_scanned} positions.")
    print(f"Found {len(candidates)} raw candidates -> {out_path}")


if __name__ == "__main__":
    main()
