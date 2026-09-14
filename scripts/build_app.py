#!/usr/bin/env python3
"""
Build app/index.html by embedding data/positions.json into app/template.html.
Run this any time positions.json changes (e.g. after adding a new batch).

Hand-written annotations from data/annotations.json are merged in here rather
than being stored in positions.json, so re-running the mining pipeline (which
rewrites positions.json wholesale) can never destroy them.
"""
import json
import datetime
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fen_key(fen):
    """Board/side/castling/en-passant only -- drops the halfmove and fullmove
    counters so a FEN pasted from anywhere still matches the mined one."""
    return " ".join(fen.split()[:4])


def load_annotations(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # Hand-edited file: skip malformed entries rather than failing the build.
    # scripts/annotate.py --validate is what reports them.
    return {fen_key(k): v for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict)}


def main():
    positions_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "positions.json")
    annotations_path = os.path.join(ROOT, "data", "annotations.json")
    template_path = os.path.join(ROOT, "app", "template.html")
    out_path = os.path.join(ROOT, "app", "index.html")

    with open(positions_path, encoding="utf-8") as f:
        positions = json.load(f)
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    annotations = load_annotations(annotations_path)
    annotated = 0
    for pos in positions:
        entry = annotations.get(fen_key(pos["fen"]))
        if not entry or not entry.get("text"):
            continue
        pos["annotation"] = entry["text"]
        if entry.get("source"):
            pos["annotation_source"] = entry["source"]
        annotated += 1

    depth = positions[0]["depth"] if positions else "?"
    html = template.replace("__POSITIONS_JSON__", json.dumps(positions))
    html = html.replace("__DEPTH__", str(depth))
    html = html.replace("__GENDATE__", datetime.date.today().isoformat())

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out_path} with {len(positions)} positions.")
    print(f"Annotations: {annotated}/{len(positions)} positions annotated.")

    unused = set(annotations) - {fen_key(p["fen"]) for p in positions}
    if unused:
        print(f"Note: {len(unused)} annotation(s) match no current position "
              f"(run scripts/annotate.py --validate).")


if __name__ == "__main__":
    main()
