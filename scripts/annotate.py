#!/usr/bin/env python3
"""
Authoring helper for data/annotations.json. Read-only -- it never writes.

  python3 scripts/annotate.py --coverage
  python3 scripts/annotate.py --list-missing
  python3 scripts/annotate.py --validate

Annotations are keyed by FEN and merged into the app by build_app.py. The
lookup ignores the halfmove/fullmove counters, so a FEN pasted from anywhere
still matches.
"""
import json
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSITIONS_PATH = os.path.join(ROOT, "data", "positions.json")
ANNOTATIONS_PATH = os.path.join(ROOT, "data", "annotations.json")

MIN_TEXT_CHARS = 40
MAX_TEXT_CHARS = 1200


def fen_key(fen):
    return " ".join(fen.split()[:4])


def load():
    with open(POSITIONS_PATH, encoding="utf-8") as f:
        positions = json.load(f)
    annotations = {}
    if os.path.exists(ANNOTATIONS_PATH):
        with open(ANNOTATIONS_PATH, encoding="utf-8") as f:
            annotations = {k: v for k, v in json.load(f).items()
                           if not k.startswith("_")}
    return positions, annotations


def annotated_keys(annotations):
    """FEN keys that carry usable text. Tolerates malformed hand-written
    entries -- --validate is what reports them."""
    return {fen_key(k) for k, v in annotations.items()
            if isinstance(v, dict) and (v.get("text") or "").strip()}


def describe(pos):
    return (f"#{pos.get('id')}: {pos.get('white')} - {pos.get('black')} "
            f"({pos.get('event')}, {pos.get('date')}) "
            f"move {pos.get('move_number')}, {pos.get('side_to_move')} to move, "
            f"eval {pos.get('eval_str')}")


def cmd_coverage(positions, annotations):
    keyed = annotated_keys(annotations)
    have = sum(1 for p in positions if fen_key(p["fen"]) in keyed)
    total = len(positions)
    pct = (100.0 * have / total) if total else 0.0
    print(f"{have}/{total} positions annotated ({pct:.0f}%).")
    missing = total - have
    if missing:
        print(f"{missing} to go -- run --list-missing to see them.")


def cmd_list_missing(positions, annotations):
    keyed = annotated_keys(annotations)
    missing = [p for p in positions if fen_key(p["fen"]) not in keyed]
    if not missing:
        print("Nothing missing -- every position has an annotation.")
        return
    print(f"{len(missing)} position(s) without an annotation:\n")
    for pos in missing:
        print(describe(pos))
        print(f'  "{pos["fen"]}"')
        print(f"  best: {pos.get('best_move_san')}   "
              f"line: {' '.join(pos.get('pv_san', [])[:6])}")
        print()


def cmd_validate(positions, annotations):
    by_key = {}
    for p in positions:
        by_key.setdefault(fen_key(p["fen"]), []).append(p)

    problems = 0
    for raw_fen, entry in annotations.items():
        key = fen_key(raw_fen)
        label = f'"{raw_fen[:50]}..."' if len(raw_fen) > 50 else f'"{raw_fen}"'

        if key not in by_key:
            print(f"STALE   {label}\n        matches no position in positions.json")
            problems += 1
            continue
        if not isinstance(entry, dict):
            print(f"BAD     {label}\n        expected an object with 'text'/'source'")
            problems += 1
            continue

        text = (entry.get("text") or "").strip()
        if not text:
            print(f"EMPTY   {label}\n        no 'text'")
            problems += 1
        elif len(text) < MIN_TEXT_CHARS:
            print(f"SHORT   {label}\n        {len(text)} chars, expected >= {MIN_TEXT_CHARS}")
            problems += 1
        elif len(text) > MAX_TEXT_CHARS:
            print(f"LONG    {label}\n        {len(text)} chars, expected <= {MAX_TEXT_CHARS}")
            problems += 1

        if not (entry.get("source") or "").strip():
            print(f"NOSRC   {label}\n        missing 'source' -- record where the text came from")
            problems += 1

    for group in [v for v in by_key.values() if len(v) > 1]:
        print("DUPE    two positions share a FEN, so they cannot be annotated separately:")
        for p in group:
            print(f"        {describe(p)}")
        problems += 1

    if problems:
        print(f"\n{problems} problem(s) found.")
        return 1
    print(f"OK -- {len(annotations)} annotation(s), no problems found.")
    return 0


def main():
    args = set(sys.argv[1:])
    positions, annotations = load()

    if "--list-missing" in args:
        cmd_list_missing(positions, annotations)
    elif "--validate" in args:
        sys.exit(cmd_validate(positions, annotations))
    elif "--coverage" in args or not args:
        cmd_coverage(positions, annotations)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
