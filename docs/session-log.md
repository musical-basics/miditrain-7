# Session Log — miditrain-7

## 2026-08-14 — Repo born: Phase 0/1/2 built, measured, GUI verified

**Why this repo exists** (user's call): miditrain-6's parameters were
trained mostly on chorales/folk songs — garbage in, garbage out for a
piano product — and its phases were in the wrong hierarchical order.
miditrain-7 rebuilds bottom-up on clean piano data: hand separation
FIRST, downbeat detection SECOND, everything else in service of those.
Phase order + rationale: docs/architecture.md. Old logic is a reference,
not a dependency.

**Phase 0 — ingest & segmentation** (`tools/make_segments.py`): the 4
MIDI+MusicXML pairs (Clementi, Kuhlau, Burgmüller Arabesque + The Storm,
copied into `source/`) verified as 2-part, 4/4, pickup-free, MIDI aligned
to XML on the 120 BPM grid. Cut into **10 even 16-bar segments** (2238
notes, 99% hand-labeled from XML part index; the ~1% unmatched are
tie/ornament artifacts, kept in input, excluded from scoring). Pieces
with pickups are skipped loudly — deliberate scope, revisit later.

**Phase 1 — hand separation** (`phase1_hands.py`), single-voice-per-hand
model: onset clusters → deterministic beam search over low/high split
points, costs = movement (idle-decayed) + span + crossing + within-hand
sustain overlap + **articulation affinity** (velocity vs the hand's own
running profile — added after measuring that movement/span/crossing all
tie at zero on the Arabesque's repeated-A texture; duration affinity was
tried and measured OUT). Weights grid-searched
(`tools/tune_phase1.py`, 576 coarse + 864 fine configs):

| model | overall | crossover | switches |
|---|---|---|---|
| split@60 | 71.5% | 39.5% | 422 |
| oracle per-segment split | 95.6% | 76.5% | 160 |
| **phase1 beam** | **96.6%** | **94.7%** | **87** |

Beats the oracle on all three numbers — the spec's bar (a real algorithm
must beat the cheating threshold) is cleared, crossover by +18pp.

**Phase 2 — downbeat inference** (`phase2_downbeat.py`): compact rebuild
of miditrain-6's meter evidence bus (its measured-best engine), consuming
Phase 1 hand streams. Channels: onset, bass (LH depth×duration), chord
mass, agogic, velocity accent, harmonic change (sounding pitch-class-set
Jaccard), entry. One joint (tactus period, bar grouping, phase) argmax;
log-Gaussian tactus/bar priors with miditrain-6's corpus-searched sigmas.

**Result: 100% downbeat recall, 100% precision, 10/10 segments strict
(±50 ms)** — north star (≥98%) met on this corpus. The path there, each
step measured:
- First cut 80% recall: bar-level hierarchy errors (half-bar locks,
  G=6 overgrouping). Fixed by the bar-length prior + the harmonic-change
  channel — exactly the fix miditrain-6's own oracle test predicted.
- Then two phase-flip failures (Arabesque/Storm claim beat 3): their
  harmonic rhythm is genuinely half-bar and crescendo dynamics peak
  mid-bar, so neither harmony nor raw velocity decides. Two fixes:
  **accents are now measured per hand stream** (an accent only means
  something vs the same hand's own level) and a soft **entry channel**
  (segment start + each hand's first entrance).
- Kuhlau s4 missed only its final downbeat (a chord ON the last downbeat
  with nothing after); projection rule changed to "downbeat is real if
  any onset lands at/after it".
- Scorer fix: predictions at the segment edge (bar 17's downbeat) are
  unscoreable, not wrong — clipped at truth coverage end.

**GUI** (`gui/index.html`, `./run_gui.sh`, pure static): per-segment
piano roll; Phase 1 tab = notes colored by hand, wrong notes outlined
red, crossover band shaded, prediction-vs-baselines table; Phase 2 tab =
truth (green dashed) vs inferred (black) downbeat lines + grid stats.
Verified headless (Chromium): both tabs render, stats match the CLI, no
JS errors; server killed after.

**Decisions made this session**
- Phase order (user delegated): hands first; harmonic/thermo machinery
  demoted to vote channels inside the downbeat decision; voice threading
  deferred to after meter. Full rationale in docs/architecture.md.
- Oracle baseline is per-SEGMENT here (stricter than miditrain-6's
  per-piece oracle: 95.6/76.5 vs 94.5/87.2 on the same pieces).
- Objective for Phase 1 tuning: overall + crossover correct (crossover
  counts double).

**Known debts / caveats (also in docs/debt.md)**
1. **No held-out split.** All parameters are fit to the 4 source pieces /
   10 segments. Numbers are "the model can express this", not
   generalization. Growing `source/` and re-running is the fix.
2. **Entry channel leans on phrase-aligned segments** (no pickup, slice
   at bar 1). Soft vote by design so a pickup can out-vote it — must be
   re-examined the moment pickup segments enter the corpus.
3. Tactus drifts slightly (499.4 vs 500 ms → ~20 ms bar-phase bias,
   inside ±50 tol). A post-lock phase/period refinement pass would zero it.
4. Whole-segment analysis, not causal streaming yet. The vote/argmax
   design is causal-compatible (commit horizon = a few bars) but the
   streaming formulation is unbuilt.
5. Phase 1 residuals concentrate in 3 segments (arabesque_s0 93.5,
   storm_s1 92.8, clementi_s1 92.7) — figure-level reasoning (who owns
   the broken-chord pattern) is the next discriminator, same as
   miditrain-6's m9/m11 finding.

**Left incomplete**: Phase 3 (quantize) not started; more source pieces
wanted (~15 per the old spec); no benchmark gate yet (single-command
regression check à la miditrain-6's run_benchmark.py becomes worth it as
soon as there are two competing configs).
