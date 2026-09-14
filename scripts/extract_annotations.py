#!/usr/bin/env python3
"""
Pull the published move annotations out of the source PGN files and write them
into data/annotations.json, keyed by FEN.

  python3 scripts/extract_annotations.py [pool.json] [annotations.json]

Runs between finalize_analysis.py and curate.py, so curate.py can then keep
only positions that actually have commentary.

Matching is by FEN, not by game index: every game is replayed and each node's
board position is looked up against the wanted set. That survives PGN files
being added or reordered.

Hand-written entries are never overwritten. Anything this script produces is
tagged "extracted": true; entries without that tag are treated as hand-written
and left alone. Pass --overwrite to refresh previously extracted entries.

Attribution is taken from the PGN's [Annotator] header when there is one, and
explicitly records when there is not -- these collections vary from credited
grandmaster commentary to anonymous instructional notes, and the difference
matters when you are reading the annotation as authority.
"""
import chess
import chess.pgn
import json
import sys
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PGN_DIR = os.path.join(ROOT, "pgn")

# How far from the mined ply a comment may sit. Annotators rarely write at the
# exact ply the miner picks, so search outwards from it: nearest first, and at
# equal distance prefer the earlier ply (a note written before the position is
# commentary leading into it; one written after may describe what happened
# next). The distance used is recorded in the source string either way.
PLY_WINDOW = 4

MIN_PROSE_WORDS = 8      # reject bare variation dumps like "12.Nd5 Nxd5 13.Qxd5"
MAX_MOVE_TOKEN_RATIO = 0.6
MIN_CHARS = 40
MAX_CHARS = 1200

MOVE_TOKEN = re.compile(
    r"^(?:\d+\.+|O-O(?:-O)?[+#!?]*|"
    r"[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#!?]*|"
    r"[01]-[01]|1/2-1/2|\*|[!?]+|\$\d+)$"
)


def fen_key(fen):
    return " ".join(fen.split()[:4])


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def is_prose(text):
    """A comment is useful only if it actually explains something. Many PGN
    comments are pure variation dumps, which read as noise in the app."""
    tokens = text.split()
    if not tokens:
        return False
    moves = sum(1 for t in tokens if MOVE_TOKEN.match(t.strip("(),.;")))
    prose = len(tokens) - moves
    return (prose >= MIN_PROSE_WORDS
            and moves / len(tokens) <= MAX_MOVE_TOKEN_RATIO)


def source_label(headers, pgn_file, offset):
    annotator = (headers.get("Annotator") or "").strip()
    who = annotator if annotator else "annotator not credited"
    cite = (f'{headers.get("White", "?")} - {headers.get("Black", "?")}, '
            f'{headers.get("Event", "?")} {headers.get("Date", "?")}')
    label = f"{cite} - annotation by {who} ({pgn_file})"
    if offset:
        n = abs(offset)
        where = "after" if offset > 0 else "before"
        label += f" [note written {n} {'ply' if n == 1 else 'plies'} {where} this position]"
    return label


def main():
    pool_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "finalized_pool.json")
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "annotations.json")
    overwrite = "--overwrite" in sys.argv

    with open(pool_path, encoding="utf-8") as f:
        pool = json.load(f)
    wanted = {fen_key(p["fen"]) for p in pool}

    existing = {}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)

    # hand-written entries (and preserved metadata keys) are untouchable
    protected = {k for k, v in existing.items()
                 if k.startswith("_") or not (isinstance(v, dict) and v.get("extracted"))}

    found = {}
    rejected_noise = 0
    pgn_files = sorted(f for f in os.listdir(PGN_DIR) if f.endswith(".pgn"))

    for pgn_file in pgn_files:
        path = os.path.join(PGN_DIR, pgn_file)
        with open(path, encoding="utf-8", errors="ignore") as fh:
            while True:
                game = chess.pgn.read_game(fh)
                if game is None:
                    break

                # one pass over the mainline: remember each ply's FEN + comment
                plies = []
                node = game
                while node.variations:
                    node = node.variations[0]
                    plies.append((fen_key(node.board().fen()), clean(node.comment)))

                for i, (key, _) in enumerate(plies):
                    if key not in wanted or key in found or key in protected:
                        continue
                    for offset in range(0, PLY_WINDOW + 1):
                        # explicit order, earlier ply first -- a set here would
                        # make which comment gets picked non-deterministic
                        for signed in ((0,) if offset == 0 else (-offset, offset)):
                            j = i + signed
                            if not (0 <= j < len(plies)):
                                continue
                            text = plies[j][1]
                            if not text or not (MIN_CHARS <= len(text) <= MAX_CHARS):
                                continue
                            if not is_prose(text):
                                rejected_noise += 1
                                continue
                            found[key] = {
                                "text": text,
                                "source": source_label(game.headers, pgn_file, signed),
                                "extracted": True,
                            }
                            break
                        if key in found:
                            break

    merged = dict(existing)
    added = replaced = 0
    for key, entry in found.items():
        if key in merged:
            if not overwrite:
                continue
            replaced += 1
        else:
            added += 1
        merged[key] = entry

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1, ensure_ascii=False)

    real = sum(1 for k in merged if not k.startswith("_"))
    print(f"Pool: {len(pool)} positions. Matched commentary for {len(found)}.")
    print(f"Added {added}, refreshed {replaced}, "
          f"left {len(protected - {k for k in protected if k.startswith('_')})} hand-written entry(s) alone.")
    print(f"Skipped {rejected_noise} comment(s) that were variation dumps rather than prose.")
    print(f"{out_path}: {real} annotation(s) total.")
    print(f"Coverage against this pool: {len(wanted & set(merged))}/{len(wanted)}")


if __name__ == "__main__":
    main()
