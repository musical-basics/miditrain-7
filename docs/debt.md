# Debt / open questions

- **Bar-LEVEL selection redesign** (2026-08-14, TOP ITEM): the sweep
  proved the accent-folding + prior + parsimony mechanism is at its
  ceiling (432 configs, none beats the adopted one; knobs trade meters
  against each other). Design direction: level should be voted by
  channels whose natural period IS the bar — harmonic rhythm (period of
  pitch-class-set change) and phrase parallelism (repetition lag) — with
  accent folding keeping phase duty. Also: groupings max G=4 cannot
  express 12/8 from an eighth-note tactus (op9/2); the tactus/level
  interaction needs to be joint, not sequential.
- **waldstein_s4 tactus** (2026-08-14): first tactus failure in the
  corpus (618 ms lock on a dotted-rhythm chorale texture, true 500).
  Diagnose the fold scores around 500 vs 618.
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
