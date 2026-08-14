# Debt / open questions

- **rage_s0 bar level** (2026-08-14): the opening of Rage Op.129 (2/4)
  scores G=3/1500 ms above G=2/1000 even after the retune — the rondo
  theme's agogic pattern apparently supports a triple fold. 1 of 20
  segments; needs a channel-level diagnosis like the doubled-bar one.
- **Rage MIDI/XML desync** (2026-08-14): the pair diverges progressively
  (repeat structure in the MuseScore export); 26 of 29 windows dropped by
  the ≥70%-labeled guard. Re-export the MIDI from the same score, or
  accept 3 segments.
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
