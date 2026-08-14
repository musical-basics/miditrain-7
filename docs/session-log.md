# Session Log — miditrain-7

## 2026-08-14 (evening) — All 9 pieces in (28 segments); the level-selection frontier is now mapped

**Data fixes, all user-driven:**
- **Waldstein has NO pickup — user was right.** The old detector read the
  first measure's contained-note span (this file reports 0.5 ql for a
  full bar); pickup detection now uses the OFFSET DELTA between measures.
  Waldstein contributes 5 segments (8.5k-note movement).
- **Op.9/2**: leading pickup is now TRIMMED (segmentation starts at the
  first full measure — "start on measure 2"), and the mid-piece TS change
  at m.33 (cadenza) truncates the piece instead of losing it → 2 segments
  of 12/8, the corpus's first 3000 ms bars.
- **Rage v2 MIDI measured: NOT better** (same desync curve as v1 —
  unused). The desync is the XML side: music21's expandRepeats disagrees
  with how both MIDIs take the repeats. The segmenter now tries BOTH
  expansion variants per piece and keeps the one the MIDI agrees with
  (more surviving segments): rage unexpanded → 4 clean segments,
  waldstein unexpanded → 5.

**Corpus: 9/9 pieces usable, 28 segments, 4 meters (4/4, 2/4, 6/8, 12/8).**

**Scores** (Phase 2 re-tuned on the widened split — the sweep's winner IS
the already-adopted config; no weight setting beats it):
- Phase 1: 93.6% overall / 82.1% crossover pooled. New hardest segment:
  Waldstein s0 (79.5%) — both hands pulsing chords in close position.
- Phase 2: 92.4% recall / 86.4% precision, **21/28 strict**.

**The 4 failing segments decompose cleanly — all are METRICAL-LEVEL
errors on a correctly-found pulse** (tactus correct in 27/28):
| segment | tactus | error |
|---|---|---|
| rage_s0 (2/4) | 502 ✓ | groups ×3 → 1500 bars |
| rage_s2 (2/4) | 502 ✓ | groups ×4 → 2000 bars (doubling) |
| op9no2 both (12/8) | 375 = eighth, not 750 | max G=4 can't reach 3000; halving |
| waldstein_s4 (4/4) | **618 ✗** | first tactus failure in the corpus (dotted-rhythm chorale texture) |

**Design conclusion (answers "is phase 2 well designed?"):** the grid
search proves the CURRENT level-selection mechanism (accent-mass folding
+ bar-length prior + parsimony margin) is at its ceiling — 432 configs,
none beats the adopted one, and the knobs trade meters against each
other (loosen parsimony → 12/8 heals, 2/4 re-breaks). The accent
channels reliably find the HIERARCHY but cannot pick the notated LEVEL,
because at ambiguous levels the accents are self-similar by construction.
The channels whose natural granularity IS the bar — harmonic RHYTHM
(period of harmonic change: rage changes per 1000 ms, op9/2 per 3000 ms)
and phrase PARALLELISM (repetition lag) — are not yet level voters.
That redesign is the top open item, recorded in debt.

**Streaming across 28 segments**: first-correct median still ~4.25 s;
22/28 reach stable lock (median 10.25 s). The 6 never-locks are the 4
level-error segments plus waldstein_s0/s2 wobble. Hysteresis tracker
remains the standing next step.


## 2026-08-14 (later) — 5 new pieces; held-out truth-telling; streaming lock times

**Corpus grew 4 → 7 usable pieces, 10 → 20 segments** (~5.6k scored
notes). New: Chopin Nocturne Op.27/2 (6/8 — first compound meter, 4
segs), Chopin Op.72/1 (4/4, 3 segs), Beethoven Rage Op.129 (2/4, 3 segs).
Skipped loudly per current scope: Op.9/2 + Waldstein (pickup measures).
The new MIDIs are voice-separated (hands on separate tracks) — the
ingest already merges all tracks into one stream and discards track
identity, so the engine never sees the separation; truth comes from the
XML part index as before. Segmenter now reads .mxl, anchors each 16-bar
window on its own first downbeat (one irregular bar no longer kills the
rest of the piece), and drops windows with <70% truth-labeled notes.
KNOWN DATA ISSUE: the Rage MIDI/XML pair desyncs progressively (repeat
structure); only 3 of its 29 windows survive the guards.

**Held-out test (params untouched from the 4-piece tune):**
- Phase 1 GENERALIZES: Rage 100%×3, nocturnes 87.7–99.0%. Pooled
  96.0% / 87.8% crossover.
- Phase 2 failed systematically on non-4/4: every 4/4 segment stayed
  strict, but 2/4 and 6/8 locked to DOUBLED bars (Rage 43.8%, Op.27/2
  50% recall). Root causes found by channel-level diagnosis:
  1. BUG: one-shot entry votes divided by n_lines mechanically inflate
     longer bars. Fix: point evidence picks the PHASE, never the LEVEL.
  2. The 1900 ms bar prior penalizes real 1000/1500 ms bars.
  3. A contrast-vs-other-beats score was tried and REJECTED (it punishes
     4/4's legitimately strong beat 3 — broke The Storm).
  Plus: least-squares grid refinement added (fixes the ~0.4% tactus
  quantization drift AND the old ~18 ms phase bias — phases now lock at
  0–2 ms); refinement window = fold tolerance, not ±10% of bar (a wide
  window drags phase onto ornament mass).

**Retune on a committed train/val split** (benchmarks/split.json,
segment-stratified, piece leakage disclosed): winner is parsimony
1.12→1.3 + agogic 1.5→0.75 + velocity_margin 2 — train F1 95.8 (10/12
strict), **val F1 100 (8/8 strict)**. Full corpus after adoption:
**recall 96.6%, precision 98.4%, 18/20 strict**. Remaining failures:
rage_s0 picks G=3/1500 in 2/4 (open — see debt), op72_s2 misses 1 of 16.

**Streaming ("how long is the ambiguous opening?")** —
tools/measure_lock.py, prefix replay with durations capped at now:
- **First correct grid: median 4.25 s (~2 bars), range 3.25–6 s**;
  19/20 segments lock (rage_s0's grid is wrong even offline).
- Stable lock without inertia: median 10.25 s, worst 31 s — from-scratch
  re-inference wobbles after first-correct. NEXT: a hysteresis tracker
  (keep the grid unless beaten by a margin); lock.json is its eval.
- Hands need almost no hindsight: causal within ~2 pp of offline
  everywhere except the Arabesque's symmetric texture (86.4 vs 93.5).


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
