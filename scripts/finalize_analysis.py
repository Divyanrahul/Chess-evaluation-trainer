#!/usr/bin/env python3
"""
Final high-quality analysis pass for the positions that will actually ship in
the app. This is deliberately much stronger than the mining/filtering passes:

  - Stockfish 19 (current NNUE net) instead of the older Stockfish 16 used
    for mining -- meaningfully more accurate, matching what you'd see on
    lichess/chess.com analysis boards.
  - A real time budget per position (not just a depth cap) so the search
    actually settles down.
  - MultiPV=3, so we store the top three candidate moves with their own
    evaluation and follow-up line, not just one "the" answer.

It also re-applies the "no cashed-in material" sanity check using this
stronger engine's own top line -- a position that looked clean at shallower
depth can turn out to have a real tactic once you look deeper (this is
exactly what happened when the user cross-checked one of our positions on
lichess and the eval kept climbing). Positions that fail this re-check are
reported as REJECTED so they can be swapped out during curation.
"""
import chess
import chess.engine
import json
import sys
import os
import time

STOCKFISH_PATH = os.environ.get("STOCKFISH19_PATH",
                                 "/tmp/sf19/stockfish/stockfish-linux-x86-64-universal")
THREADS = 2
HASH_MB = 1024
TIME_PER_POSITION = 12.0     # seconds, real wall-clock search time
MULTIPV = 3
PV_PLIES_TO_STORE = 12
PV_MATERIAL_CHECK_PLIES = 8
MAX_PV_MATERIAL_DRIFT = 1.25  # pawns

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3.25,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def material_diff(board):
    diff = 0.0
    for piece_type, val in PIECE_VALUES.items():
        diff += val * len(board.pieces(piece_type, chess.WHITE))
        diff -= val * len(board.pieces(piece_type, chess.BLACK))
    return diff


def score_str_cp_mate(score):
    s = score.white()
    if s.is_mate():
        m = s.mate()
        return f"#{m}", None, m
    cp = s.score()
    return f"{cp/100.0:+.2f}", cp, None


def finalize_one(engine, rec):
    board = chess.Board(rec["fen"])
    info = engine.analyse(board, chess.engine.Limit(time=TIME_PER_POSITION),
                           multipv=MULTIPV)
    if not isinstance(info, list):
        info = [info]

    lines = []
    for entry in info:
        pv_moves = entry.get("pv", [])
        if not pv_moves:
            continue
        eval_str, eval_cp, eval_mate = score_str_cp_mate(entry["score"])
        replay = board.copy()
        san_moves = []
        for mv in pv_moves[:PV_PLIES_TO_STORE]:
            if mv not in replay.legal_moves:
                break
            san_moves.append(replay.san(mv))
            replay.push(mv)
        lines.append({
            "eval_str": eval_str,
            "eval_cp": eval_cp,
            "eval_mate": eval_mate,
            "move_san": san_moves[0] if san_moves else None,
            "pv_san": san_moves,
            "depth": entry.get("depth"),
        })

    if not lines:
        return None, "no_lines"

    best = lines[0]
    if best["eval_mate"] is not None:
        return None, "forced_mate_at_higher_depth"

    # material-drift re-check on the (stronger) best line
    replay = board.copy()
    mdiff_start = material_diff(replay)
    mdiff_after_check = mdiff_start
    for i, san in enumerate(best["pv_san"]):
        mv = replay.parse_san(san)
        replay.push(mv)
        if i + 1 == PV_MATERIAL_CHECK_PLIES:
            mdiff_after_check = material_diff(replay)
    if len(best["pv_san"]) < PV_MATERIAL_CHECK_PLIES:
        mdiff_after_check = material_diff(replay)

    if abs(mdiff_after_check - mdiff_start) > MAX_PV_MATERIAL_DRIFT:
        return None, "material_drift_at_higher_depth"

    result = dict(rec)
    result["eval_str"] = best["eval_str"]
    result["eval_cp"] = best["eval_cp"]
    result["best_move_san"] = best["move_san"]
    result["pv_san"] = best["pv_san"]
    result["lines"] = lines
    result["engine"] = "Stockfish 19"
    result["analysis_time_s"] = TIME_PER_POSITION
    result["depth"] = best.get("depth")
    result.pop("second_choice", None)
    return result, "ok"


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "data/positions.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/positions_final.json"

    with open(in_path) as f:
        records = json.load(f)

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    engine.configure({"Threads": THREADS, "Hash": HASH_MB})

    kept = []
    rejected = []
    t0 = time.time()
    for i, rec in enumerate(records):
        result, status = finalize_one(engine, rec)
        elapsed = time.time() - t0
        if result is None:
            rejected.append({"id": rec.get("id"), "white": rec["white"],
                              "black": rec["black"], "reason": status})
            print(f"[{i+1}/{len(records)}] REJECT #{rec.get('id')} "
                  f"{rec['white']}-{rec['black']}: {status}  ({elapsed:.0f}s elapsed)",
                  flush=True)
        else:
            kept.append(result)
            print(f"[{i+1}/{len(records)}] OK #{rec.get('id')} "
                  f"{rec['white']}-{rec['black']} eval={result['eval_str']} "
                  f"best={result['best_move_san']}  ({elapsed:.0f}s elapsed)",
                  flush=True)

    engine.quit()
    for i, r in enumerate(kept, start=1):
        r["id"] = i
    with open(out_path, "w") as f:
        json.dump(kept, f, indent=1)

    print(f"\nFinalized {len(records)}: {len(kept)} kept, {len(rejected)} rejected -> {out_path}")
    if rejected:
        print("Rejected:")
        for r in rejected:
            print(" ", r)


if __name__ == "__main__":
    main()
