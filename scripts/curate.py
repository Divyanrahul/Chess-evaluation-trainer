#!/usr/bin/env python3
"""
Pick a diverse final subset from the finalized (SF19, MultiPV3) candidate
pool -> data/positions.json.

Diversity rules:
  - At most one position per source game (avoid near-duplicates).
  - Balanced across the 4 combinations of (who's favored) x (who's actually
    on move): favored-side-to-move AND disadvantaged-side-to-move, for both
    colors. Left unchecked, "who's favored" correlates with "who's to move"
    in the raw data (it's usually the just-improved side's turn to sit and
    consolidate) -- if the app always oriented the board towards the mover,
    that correlation would leak the answer. Balancing this dimension means
    there's no tell in "whose move it is" either.
  - Final eval must still land in the "moderate, not yet winning" band after
    the strong SF19 re-analysis (deeper search sometimes pushes an eval
    further than the original quick scan found).
"""
import json
import os
import sys
import random

MIN_ABS_CP = 55
MAX_ABS_CP = 300

# Only ship positions that have commentary. Run extract_annotations.py first.
REQUIRE_ANNOTATION = True
ANNOTATIONS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "annotations.json")


def fen_key(fen):
    return " ".join(fen.split()[:4])


def annotated_keys():
    if not os.path.exists(ANNOTATIONS_PATH):
        return set()
    with open(ANNOTATIONS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return {fen_key(k) for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict)
            and (v.get("text") or "").strip()}


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "data/finalized_pool.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/positions.json"
    # ceiling, not a quota: the annotation requirement and the 50/50 favored-side
    # balance bind well below this, so the default just means "take what's there"
    target_n = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 7

    with open(in_path) as f:
        pool_raw = json.load(f)

    before = len(pool_raw)
    pool_raw = [r for r in pool_raw if r.get("eval_cp") is not None
                and MIN_ABS_CP <= abs(r["eval_cp"]) <= MAX_ABS_CP]

    if REQUIRE_ANNOTATION:
        keys = annotated_keys()
        pool_raw = [r for r in pool_raw if fen_key(r["fen"]) in keys]
        print(f"Annotation filter: {len(pool_raw)} of {before} pool positions "
              f"have commentary ({len(keys)} annotations on file).")
        if not pool_raw:
            print("Nothing left to curate -- run scripts/extract_annotations.py first.")
            return

    # one per game (prefer the one with the larger jump_cp, a proxy for "clean swing")
    by_game = {}
    for r in pool_raw:
        key = (r["pgn_file"], r["game_index"])
        by_game.setdefault(key, []).append(r)
    pool = []
    for key, items in by_game.items():
        items.sort(key=lambda r: -abs(r.get("jump_cp", 0)))
        pool.append(items[0])

    rnd = random.Random(seed)
    rnd.shuffle(pool)

    def bucket_key(r):
        return (r["favored_white"], r["side_to_move"])

    print("Available per (favored_white, side_to_move) bucket:")
    avail = {}
    for r in pool:
        avail[bucket_key(r)] = avail.get(bucket_key(r), 0) + 1
    for k in sorted(avail):
        print(" ", k, avail[k])

    # Balance on favored side exactly: it is the directly guessable thing, and
    # requiring annotations skews the supply badly (the four-way buckets differ
    # by ~6x, so a full cross-product balance would throw away most of the
    # pool). side_to_move is balanced as a secondary, best-effort pass within
    # each favored side.
    def side_interleaved(records):
        subs = {}
        for r in records:
            subs.setdefault(r["side_to_move"], []).append(r)
        for v in subs.values():
            rnd.shuffle(v)
        keys = sorted(subs)
        out, i = [], 0
        while any(subs[k] for k in keys):
            k = keys[i % len(keys)]
            if subs[k]:
                out.append(subs[k].pop())
            i += 1
        return out

    by_favored = {True: [], False: []}
    for r in pool:
        by_favored[bool(r["favored_white"])].append(r)
    ordered = {k: side_interleaved(v) for k, v in by_favored.items()}

    per_side = min(len(ordered[True]), len(ordered[False]), target_n // 2)
    selected = ordered[True][:per_side] + ordered[False][:per_side]
    if per_side < target_n // 2:
        short = "White" if len(ordered[True]) < len(ordered[False]) else "Black"
        print(f"\nNote: capped at {per_side} per side -- only {per_side} "
              f"{short}-favored positions available. Mine more games to grow this.")

    rnd.shuffle(selected)
    for i, r in enumerate(selected, start=1):
        r["id"] = i

    with open(out_path, "w") as f:
        json.dump(selected, f, indent=1)

    print(f"\nPool after eval-band filter + 1-per-game dedup: {len(pool)}")
    print(f"Selected {len(selected)} -> {out_path}")
    final_counts = {}
    for r in selected:
        final_counts[bucket_key(r)] = final_counts.get(bucket_key(r), 0) + 1
    print("Final selection per (favored_white, side_to_move) bucket:")
    for k in sorted(final_counts):
        print(" ", k, final_counts[k])

    # the guessability check -- if either of these drifts far from 50%, the
    # trainer is rewarding a heuristic instead of real evaluation
    n = len(selected) or 1
    fav_w = sum(1 for r in selected if r["favored_white"])
    print(f"Favored White: {fav_w}/{n} ({100*fav_w/n:.0f}%)")
    for side in ("white", "black"):
        grp = [r for r in selected if r["side_to_move"] == side]
        if grp:
            fw = sum(1 for r in grp if r["favored_white"])
            print(f"  when {side} to move: {fw}/{len(grp)} favor White "
                  f"({100*fw/len(grp):.0f}%)")


if __name__ == "__main__":
    main()
