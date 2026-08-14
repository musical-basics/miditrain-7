# Debt / open questions

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
