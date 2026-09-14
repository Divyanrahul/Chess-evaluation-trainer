# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A self-contained browser tool for practicing chess *position evaluation*
(judging who's better and why, then checking against Stockfish). The app
itself (`app/index.html`) is a single static HTML file with embedded JSON
data and no build step, no server, and no external libraries — it's meant to
be opened directly in a browser. The Python scripts in `scripts/` are an
offline pipeline (not run by the app) that mines positions from master-game
PGNs, filters/analyzes them with Stockfish, and bakes the result into that
HTML file.

## Data pipeline (run in order)

There is no single "build" command — regenerating the app means running the
6-stage pipeline, each stage consuming the previous stage's output:

```
python3 scripts/mine_positions.py pgn data/candidates.json <max_games> <max_candidates>
python3 scripts/deep_analyze.py data/candidates.json data/analyzed.json
python3 scripts/finalize_analysis.py data/analyzed.json data/finalized_pool.json
python3 scripts/extract_annotations.py data/finalized_pool.json data/annotations.json
python3 scripts/curate.py data/finalized_pool.json data/positions.json <target_n>
python3 scripts/build_app.py data/positions.json
```

`extract_annotations.py` must run **before** `curate.py`, because curate now
drops any position without commentary (`REQUIRE_ANNOTATION`). Running curate
first yields an empty set.

- `mine_positions.py` and `deep_analyze.py` use whatever `stockfish` binary
  is on `PATH` (`STOCKFISH_PATH` constant at the top of each script) — an
  older/faster build is fine here since it's just a filter.
- `finalize_analysis.py` is the quality gate for what actually ships, so it
  should be pointed at a current Stockfish build via the `STOCKFISH19_PATH`
  env var (or by editing the constant at the top of the script) — download
  the platform binary from the official Stockfish releases page. This stage
  does a real ~12s-per-position, MultiPV=3 search, so it's slow.
- `curate.py` and `build_app.py` are cheap/instant (no engine calls).
- After editing `app/template.html`, you still need to rerun
  `build_app.py` to regenerate `app/index.html` — always edit the template,
  never `index.html` directly (it's a generated artifact).
- Requires `pip install chess` (the `python-chess` library); no other
  dependencies.

### Tuning the mining heuristic

Every stage's filtering thresholds (the "roughly equal" cp band, swing
target band, stability-forward window, material-drift tolerance, engine
depth/time, final eval-band, balance targets) live as module-level constants
at the top of each script — adjust there rather than passing new CLI flags.

## Architecture: why the pipeline has 4 filtering stages

The core design goal (see README.md for full rationale) is finding
positions with a genuine, stable, *positional* advantage — not a hanging
piece or a forced tactical sequence — so each stage exists to rule out a
specific false positive:

1. **`mine_positions.py`** — scans every game move-by-move at shallow depth
   looking for an eval *swing* (equal-ish -> moderate advantage) that then
   holds stable for several plies, with material staying flat both then and
   afterward, landing on a quiet (non-check, non-forced) position. Output:
   `data/candidates.json`.
2. **`deep_analyze.py`** — cheap deep recheck (depth 22, MultiPV=2) per
   candidate; re-verifies the best line itself doesn't just cash in
   material (rejects if so). Output: `data/analyzed.json`.
3. **`finalize_analysis.py`** — the real quality gate: Stockfish 19 (current
   NNUE net), ~12s wall-clock per position, MultiPV=3, re-running the same
   material-drift sanity check against the *stronger* engine's own top
   line (deeper search sometimes reveals a tactic that looked clean at
   shallow depth). Rejections are reported explicitly. Output:
   `data/finalized_pool.json`.
4. **`extract_annotations.py`** — pulls published commentary out of the
   source PGNs for each pooled position (see Annotations below). Output:
   `data/annotations.json`.
5. **`curate.py`** — eval-band filter, **annotation requirement**,
   one-position-per-source-game dedup, then a balanced selection.
   Output: `data/positions.json` (the file the app actually consumes).

   Balancing is on **favored side only** (exactly 50/50), with side-to-move
   interleaved as a secondary best-effort pass. It is not a full 4-way
   cross-product balance: requiring annotations skews the supply badly
   (buckets differ by ~6x), and balancing the cross-product would discard
   most of the pool. Favored side is the directly guessable thing, so that
   is what gets the hard guarantee. Curate prints a guessability report at
   the end — if "Favored White" drifts far from 50%, the trainer is
   rewarding a heuristic instead of real evaluation.

`build_app.py` replaces the `__POSITIONS_JSON__`, `__DEPTH__`, and
`__GENDATE__` placeholders in `app/template.html` to produce
`app/index.html`, and merges in annotations (below).

## Annotations

Commentary lives in `data/annotations.json`, keyed by FEN, and is merged into
each record at **build** time — deliberately *not* stored in `positions.json`,
because `curate.py` rewrites that file wholesale on every run and would
destroy it. FEN is the key because record `id` is reassigned each run and
`(pgn_file, game_index)` shifts as soon as PGN files are added.

Lookup uses only the first four FEN fields (board/side/castling/en-passant),
so the trailing move counters don't have to match — see `fen_key()`, defined
identically in `build_app.py`, `annotate.py`, `curate.py` and
`extract_annotations.py`.

### Where the text comes from

The source PGNs ship with ~6,700 published move comments, and
`extract_annotations.py` harvests them. Annotators rarely write at the exact
ply the miner picks, so it searches outward (`PLY_WINDOW = 4`), nearest
first, **preferring the earlier ply** — a note written before the position
leads into it, whereas a later note may describe what happened next. The
offset is recorded in the `source` string so the reader can see it. Comments
that are bare variation dumps are rejected by `is_prose()`; the aim is text
that explains something, not a move list.

**Attribution is deliberately blunt.** The three collections differ wildly:
`gm_games.pgn` is credited to Irina Krush, `great_masters.pgn` names its
club-level annotators, and `famous_games.pgn` — which supplies the large
majority — credits nobody, so those entries say "annotator not credited".
Do not relabel these as grandmaster commentary; some of it is (Kasparov
annotating his own games in the first person), much of it is anonymous
instructional prose, and the file cannot tell them apart. A game score isn't
copyrightable; a commentator's prose about it generally is, which is the
other reason every entry carries a `source`.

### Hand-written entries win

Extracted entries are tagged `"extracted": true`. `extract_annotations.py`
never overwrites an entry lacking that tag, so removing the tag (or adding a
new entry by hand) permanently protects it. `--overwrite` refreshes only the
tagged ones.

`scripts/annotate.py` is a read-only authoring helper, not a pipeline stage:
`--coverage`, `--list-missing`, `--validate` (stale keys, missing sources,
length bounds).

## App internals (`app/template.html`)

Single-page vanilla JS/HTML/CSS, no dependencies. Key pieces:
- `POSITIONS` — the embedded array from `data/positions.json`.
- `fenToGrid` / `renderBoard` — FEN parsing and board rendering using
  Unicode chess glyphs (no images/sprites).
- `loadProgress` / `saveProgress` — session state (shuffle order, index,
  session stats) persisted to `localStorage` under `LS_KEY`; falls back
  gracefully if unavailable.
- `loadPrefs` / `savePrefs` — display preferences under a *separate*
  `PREFS_KEY`. This split matters: "Reset progress" does
  `removeItem(LS_KEY)`, which would otherwise wipe preferences that have
  nothing to do with training progress.
- `renderAnnotation` — the single source of truth for annotation
  visibility. Both the reveal handler and the hide-toggle call it rather
  than touching `.show` themselves; that is what lets annotations be
  toggled *after* revealing. Don't reintroduce a direct
  `classList.add('show')` in either handler.
- Board orientation always defaults to White's perspective regardless of
  who's actually to move or favored (manual flip button only) — this is
  intentional, to avoid leaking the answer via orientation.

## Data files

- `data/candidates.json`, `data/analyzed.json`, `data/finalized_pool.json`
  are intermediate pipeline artifacts (regenerated by their respective
  scripts).
- `data/positions.json` is the curated set actually embedded in the app —
  this is the one to inspect when debugging what the app shows.
- `data/annotations.json` is regenerated by `extract_annotations.py`, but
  any entry *without* `"extracted": true` is hand-written and must survive —
  the extractor skips those, and nothing else should rewrite this file.
- `pgn/*.pgn` are the source master-game databases (see README.md for
  provenance/licensing of each collection).

## Planned direction (v2.0)

Current state: **62 positions, all annotated**. The annotation layer (item 1)
is built; the database expansion (items 2-3) is not started.

1. **Annotations** — **DONE**, see the Annotations section above. Text comes
   from the source PGNs' own published comments, attributed honestly rather
   than being labelled grandmaster commentary wholesale. The count is now
   annotation-bound: 62 is what survives requiring commentary *and* a 50/50
   favored-side balance, from a 136-position pool. Growing past this needs
   more games, which is item 2.
2. **500 positions instead of 30**, via a deeper/looser mining pass:
   scan more games, relax `mine_positions.py`'s `TARGET_MIN`/`TARGET_MAX`
   eval band, and also deliberately keep some near-equal positions and
   positions with a slight material imbalance but unclear evaluation
   (currently rejected outright by the `MAX_MATERIAL_IMBALANCE` check and
   the eval-band filters in `curate.py`). This is a real widening of the
   project's scope beyond "clear positional swing" — expect to touch
   thresholds in `mine_positions.py`, `finalize_analysis.py`, and
   `curate.py` together, not just crank up `target_n`.
   - `data/positions.json`'s record shape otherwise stays the same
     (this is additive: the pipeline output format is unchanged aside
     from the new `annotation` field).
   - `curate.py`'s balance buckets are currently binary
     (`favored_white` x `side_to_move`); once "equal" positions are
     included, `favored_white` needs a third state (or a separate
     `is_equal` flag) so balancing logic doesn't silently misclassify
     them.
3. **UI**: an annotation panel in `app/template.html` shown as part of
   the reveal flow (see `revealBtn` handler and `revealPanel` in the
   template), plus a toggle to hide annotations while still evaluating a
   position — this toggle should be independent of `revealBtn` so a user
   can keep annotations hidden even after revealing the engine's eval,
   if they want to reason it out from the position/eval alone first.
