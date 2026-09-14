# Chess Eval Trainer

A self-contained tool for practicing chess *position evaluation*: judging who's
better and why, then checking yourself against Stockfish.

## How positions are chosen

Not just "any position with an advantage" -- these are mined from real master
games and filtered to be genuinely instructive:

1. **A real swing, not a static advantage.** We scan every game move-by-move
   with Stockfish and look for points where the evaluation moves from
   *roughly equal* (~0.0-0.5 pawns) to a *moderate, not-yet-winning*
   advantage within a short stretch of the game.
2. **Stability.** That new evaluation has to hold for several more moves
   afterwards -- so we're not grabbing a one-move analysis blip.
3. **No hanging material.** Material stays essentially level, both in the
   game's actual continuation *and* in Stockfish's own best line for several
   moves after the snapshot. This rules out "someone just blundered a piece"
   or "there's a forced tactic that wins material" -- what's left is a
   *positional / strategic* imbalance: better structure, a dominant piece,
   king safety, space, weak squares, etc.
4. **Quiet position.** The side to move isn't in check and has a normal
   number of legal replies -- this is a "sit and evaluate" position, not a
   forced sequence.
5. **A cheap first deep re-check**, then **a much stronger final pass**. Every
   surviving candidate first gets a depth-22 MultiPV-2 recheck (fast, weeds
   out the obvious mistakes). The positions that actually ship in the app
   then get a *second*, far stronger pass with **Stockfish 19** (current
   NNUE net, the same generation of engine lichess/chess.com analysis boards
   use) searching for a real ~12 seconds per position with MultiPV=3 -- long
   enough for the evaluation to settle rather than catching it mid-search.
   This step also re-applies the material/tactic check against the *stronger*
   engine's own best line, since a position that looks clean at low depth can
   turn out to have a real tactic once you look deeper.
6. **Balanced, not tell-y.** The final selection is balanced across all four
   combinations of (who's actually favored) x (who's on move) -- in the raw
   mined data these correlate (it's usually the just-improved side's turn to
   consolidate), which would otherwise let you guess "whoever's to move is
   better" as a shortcut. The board's default orientation is also always
   White's perspective regardless of who's to move or who's favored, with a
   manual flip button -- so orientation itself never hints at the answer.

The source games are `pgn/famous_games.pgn` (500 well-known annotated games,
from Marco Costalba's `chess_db` collection -- Costalba is the original
author of the Stockfish engine), plus two smaller annotated collections,
`pgn/gm_games.pgn` and `pgn/great_masters.pgn` (from ValdemarOrn/Chess on
GitHub). Game scores themselves are historical facts, not copyrighted works;
the source repositories are GPL-3.0 / MIT respectively for their own code.

## Folder structure

```
data/
  candidates.json       raw swing-detected candidates (mine_positions.py)
  analyzed.json         depth-22 MultiPV-2 recheck (deep_analyze.py)
  finalized_pool.json   Stockfish-19 strong re-analysis of the whole pool (finalize_analysis.py)
  annotations.json      published commentary, keyed by FEN (extract_annotations.py)
  positions.json        final curated + balanced set used by the app (curate.py)
pgn/                    source master-game PGN files
scripts/
  mine_positions.py       stage 1: scan PGNs, detect eval swings -> candidates.json
  deep_analyze.py         stage 2: cheap deep recheck + PV -> analyzed.json
  finalize_analysis.py    stage 3: strong Stockfish-19 pass, top-3 lines -> finalized_pool.json
  extract_annotations.py  stage 4: pull the PGNs' own notes -> annotations.json
  curate.py               stage 5: eval-band + annotation filter, balanced selection -> positions.json
  build_app.py            stage 6: embed positions + annotations into app/index.html
  annotate.py             helper (not a stage): annotation coverage / validation
app/
  template.html     the app's HTML/CSS/JS shell (edit this, not index.html)
  index.html        generated file -- open this in your browser
```

## Using the app

Open `app/index.html` in any browser (no server, no internet connection
needed -- it's fully self-contained, board drawn with Unicode glyphs, no
external libraries). For each position:

1. Look at the board (files a-h and ranks 1-8 are labeled on the edges; use
   **Flip board** to view from the other side any time). Decide who you
   think is better and roughly by how much (the slider), and jot down *why*
   in the text box (for your own reference -- it isn't graded).
2. Click **Reveal Stockfish's verdict**. You'll see the engine's evaluation,
   the actual game citation, the **annotation** (see below), and the **top 3
   lines** Stockfish considers, each with its own evaluation. Those lines are
   the "solution": play through them and it should make the evaluation's
   reasoning clear. Use **Annotations: shown/hidden** to suppress the
   commentary — it works independently of the reveal, so you can look at the
   engine's number while keeping the prose hidden.
3. Use **&larr; Prev / Next &rarr;** at the top to move between positions in
   either direction, **Shuffle** to re-randomize the order, or **Reset
   progress** to start over.

Progress (how far you are, session stats) is saved in your browser's local
storage, so closing and reopening the file picks up where you left off.

## About the annotations

Every shipped position carries commentary, because the curation step now
drops positions that don't have any. The text isn't written for this app —
it's the **published notes already present in the source PGN files**, which
between them carry about 6,700 move comments.

Two honest caveats:

- **Attribution varies a lot.** `gm_games.pgn` is credited to Irina Krush and
  `great_masters.pgn` names its annotators, but `famous_games.pgn` — which
  supplies most of the commentary — credits nobody. Those entries say
  "annotator not credited" rather than implying a titled author. Some of it
  is clearly strong (Kasparov annotating his own games in the first person);
  some is anonymous instructional prose. The source line under each
  annotation tells you which you're reading.
- **The note isn't always about the exact position.** Annotators write where
  they have something to say, not where the miner picked. Commentary is
  taken from up to 4 plies away, preferring notes written *before* the
  position, and the source line states the offset when there is one.

So treat annotations as context, not as a verdict — Stockfish's evaluation is
the actual answer you're being graded against.

## Growing the database

To mine a fresh batch and rebuild the app:

```
source venv/bin/activate   # or your own venv with `pip install chess`
python3 scripts/mine_positions.py pgn data/candidates.json <max_games> <max_candidates>
python3 scripts/deep_analyze.py data/candidates.json data/analyzed.json
python3 scripts/finalize_analysis.py data/analyzed.json data/finalized_pool.json
python3 scripts/extract_annotations.py data/finalized_pool.json data/annotations.json
python3 scripts/curate.py data/finalized_pool.json data/positions.json <target_n>
python3 scripts/build_app.py data/positions.json
```

`extract_annotations.py` has to run before `curate.py`, which now keeps only
positions that actually have commentary.

`mine_positions.py` and `deep_analyze.py` use whatever `stockfish` binary is
on your PATH (fine to use an older/faster build there -- it's just a
filter). `finalize_analysis.py` is the quality gate for what actually ships,
so it's worth pointing it at a current Stockfish build: download the
"Linux x86-64 universal" (or your platform's) binary from
https://github.com/official-stockfish/Stockfish/releases/latest/download/
and set `STOCKFISH19_PATH=/path/to/it` (or edit the constant at the top of
the script) -- it's a ~80-100MB download with the NNUE net bundled in, so
it isn't included in this folder.

The thresholds that define "critical, unclear-advantage position" live at
the top of each script if you want to tune them (the eval band, how much
material drift is tolerated, how many plies must stay stable, how long
Stockfish 19 gets per position, how the final balance across
favored-side/side-to-move is targeted).
