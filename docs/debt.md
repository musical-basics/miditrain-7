# Debt / open questions

- **NO 3/4 PIECE IN THE CORPUS** (2026-08-14): the user ranks 3/4 among
  the three canonical meters (3/4, 4/4, 6/8), and the new `triple_margin`
  (G=3 must beat the best duple by 1.10) has never been tested against a
  real triple-meter piece — it could suppress legitimate 3/4 readings.
  Add waltz/mazurka/minuet pairs before trusting the margin.
- **hungarian_s1: true pulse not among the top-5 tactus peaks**
  (2026-08-14): the friska's csárdás syncopation projects 749/563/375 ms
  periodicities; the true 500 ms pulse has no peak at all, and the
  true-bar candidate (250 ms x4) loses the joint score by 9%. This is
  the concrete case for a harmonic-rhythm level voter (chords change per
  1000 ms there). 1 of 34 segments.
- **Bar-LEVEL selection, remaining half** (2026-08-14): the joint
  (tactus x level) decision over top-K peaks + triple margin fixed
  waldstein_s4 and rage_s0. Still missing: harmonic rhythm and phrase
  parallelism as level voters (see hungarian_s1), and G is capped at 4
  (a 12/8 bar is unreachable from an eighth-note tactus).
- **Rage/Waldstein MIDI/XML desync past the exposition** (2026-08-14):
  both exports take repeats differently than music21 expands them; the
  segmenter keeps the better variant but late-piece windows still drop.
  Re-exporting MIDI+XML from the same MuseScore save would recover
  ~40 more windows. Rage v2 MIDI measured identical to v1 — unused.
- **Streaming hysteresis tracker** (2026-08-14): prefix replay shows
  first-correct at ~4.25 s but stability only at ~10 s because each
  prefix re-infers from scratch. Build the commit-horizon tracker (keep
  the current grid unless new evidence beats it by a margin);
  data/runs/lock.json + tools/measure_lock.py are the ready-made eval.
- **Pickup pieces waiting** (2026-08-14): Op.9/2 and Waldstein sit in
  source/ unused until pickup support lands.

- **No held-out split** (2026-08-14): every tuned parameter in Phase 1/2
  is fit to the 4 source pieces. Before trusting any number as general,
  grow `source/` (~15 pieces: Alberti, hand-crossing Scarlatti, dense
  chordal, sustained overlap) and split train/val.
- **Entry channel scope** (2026-08-14): phase2's `entry` votes assume
  segments start at a phrase/bar boundary — true for the current
  pickup-free corpus BY CONSTRUCTION. When pickup segments arrive, this
  channel must be re-weighed (it is a soft vote, so a pickup can out-vote
  it — verify that actually happens).
- **Tactus micro-drift**: inferred 499.4 ms vs true 500 ms leaves a ~20 ms
  constant bar-phase bias. Add a post-lock refinement (least-squares fit
  of the grid to matched strong onsets) if tolerance ever tightens.
- **Streaming/causal mode unbuilt**: both phases are whole-segment.
  Design is causal-compatible; needs an explicit commit-horizon variant.
- **Phase 1 figure-level residuals**: the ~3% remaining hand errors are
  broken-chord/alternation ownership cases (same class as miditrain-6's
  Clementi m9/m11). Candidate: repetition/figure affinity term.
- **No regression gate yet**: once a second competing config exists,
  port the run_benchmark.py pattern (committed baseline, PASS/REGRESSION).
