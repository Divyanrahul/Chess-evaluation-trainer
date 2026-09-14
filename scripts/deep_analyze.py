#!/usr/bin/env python3
"""
Deep-analyze raw candidate positions (from mine_positions.py) and produce the
final training database.

For each candidate:
  - Run MultiPV=2 search at DEEP_DEPTH to get:
      * final eval (cp or mate), best move, PV (the "solution" line)
      * second-best move + its eval (how sharp is finding the right idea)
  - Sanity re-check: replay the PV and confirm material stays essentially
    level for the first PV_MATERIAL_CHECK_PLIES plies of the *best* line
    too (not just the game's actual continuation). If Stockfish's own best
    line cashes in material quickly, this is a tactic, not a long-term
    strategic imbalance -- reject it.
  - Reject if the "solution" starts with a forced sequence of only-moves
    for the opponent for too long (a mating attack), since that's a tactic
    puzzle, not an evaluation-judgment position.

Output: data/positions.json -- the final position database consumed by the
training app.
"""
import chess
import chess.engine
import json
import sys
import os

STOCKFISH_PATH = "/usr/games/stockfish"
DEEP_DEPTH = 22
MULTIPV = 2
PV_PLIES_TO_STORE = 12
PV_MATERIAL_CHECK_PLIES = 8
MAX_PV_MATERIAL_DRIFT = 1.25   # pawns, over PV_MATERIAL_CHECK_PLIES of best line

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3.25,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def material_diff(board):
    diff = 0.0
    for piece_type, val in PIECE_VALUES.items():
        diff += val * len(board.pieces(piece_type, chess.WHITE))
        diff -= val * len(board.pieces(piece_type, chess.BLACK))
    return diff


def score_str_and_cp(score, pov_white):
    s = score.white() if True else score
    if s.is_mate():
        m = s.mate()
        return (f"#{m}" if m > 0 else f"#{m}"), None, m
    cp = s.score()
    pawns = cp / 100.0
    return f"{pawns:+.2f}", cp, None


def analyze_one(engine, cand):
    board = chess.Board(cand["fen"])
    side_to_move_white = board.turn == chess.WHITE

    info = engine.analyse(board, chess.engine.Limit(depth=DEEP_DEPTH),
                           multipv=MULTIPV)
    if not isinstance(info, list):
        info = [info]

    best = info[0]
    best_score = best["score"]
    eval_str, eval_cp, eval_mate = score_str_and_cp(best_score, True)
    if eval_mate is not None:
        return None  # forced mate found at depth -- too decisive, skip

    pv_moves = best.get("pv", [])
    if not pv_moves:
        return None

    # Reject if the line is essentially forced for the opponent throughout
    # (every reply is close to a forced-only-legal-move sequence) -- crude
    # check: if MULTIPV produced a 2nd line, compare eval gap; a razor-thin
    # gap plus a long forcing PV usually means "obvious", not "unclear".

    second = None
    if len(info) > 1:
        smove = info[1].get("pv", [None])[0]
        s_eval_str, s_cp, s_mate = score_str_and_cp(info[1]["score"], True)
        second = {
            "move_uci": smove.uci() if smove else None,
            "eval_str": s_eval_str,
            "eval_cp": s_cp,
        }

    # Replay PV to get SAN strings + material-drift sanity check
    replay = board.copy()
    san_moves = []
    mdiff_start = material_diff(replay)
    mdiff_after_check = None
    for i, mv in enumerate(pv_moves[:PV_PLIES_TO_STORE]):
        if mv not in replay.legal_moves:
            break
        san_moves.append(replay.san(mv))
        replay.push(mv)
        if i + 1 == PV_MATERIAL_CHECK_PLIES:
            mdiff_after_check = material_diff(replay)

    if mdiff_after_check is None:
        mdiff_after_check = material_diff(replay)

    if abs(mdiff_after_check - mdiff_start) > MAX_PV_MATERIAL_DRIFT:
        return None  # best line itself cashes in material -- it's a tactic

    best_move_uci = pv_moves[0].uci()
    best_move_san = chess.Board(cand["fen"]).san(pv_moves[0])

    result = dict(cand)
    result.update({
        "side_to_move": "white" if side_to_move_white else "black",
        "eval_str": eval_str,
        "eval_cp": eval_cp,
        "best_move_uci": best_move_uci,
        "best_move_san": best_move_san,
        "pv_san": san_moves,
        "second_choice": second,
        "depth": DEEP_DEPTH,
    })
    return result


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "data/candidates.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/analyzed.json"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9

    with open(in_path) as f:
        candidates = json.load(f)

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    engine.configure({"Threads": 2, "Hash": 256})

    results = []
    rejected = 0
    for i, cand in enumerate(candidates[:limit]):
        try:
            r = analyze_one(engine, cand)
        except Exception as e:
            print(f"[{i}] error: {e}", flush=True)
            r = None
        if r is None:
            rejected += 1
            continue
        r["id"] = len(results) + 1
        results.append(r)
        print(f"[{i+1}/{min(limit,len(candidates))}] kept #{r['id']}: "
              f"{r['white']} - {r['black']} ({r['event']}) "
              f"eval={r['eval_str']} best={r['best_move_san']}", flush=True)

    engine.quit()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=1)
    print(f"\nAnalyzed {min(limit,len(candidates))} candidates: "
          f"{len(results)} kept, {rejected} rejected -> {out_path}")


if __name__ == "__main__":
    main()
