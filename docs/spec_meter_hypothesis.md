# Spec: MeterHypothesis Refactor + Metrical Reasoning Layer

Written 2026-08-15, from the external architect review of
`docs/deepthink_downbeat_challenge.md` (the "deepthink" response). This
is the implementation spec. Status: **PROPOSED — no stage started.**
Decisions the user must make before/while implementing are collected in
§Decisions at the bottom.

## Verdict being adopted

The evidence bus stays. Bass and harmony are measured load-bearing
(ablation: bass 49→39, harmony 49→44 acceptable), and the channel →
vote → joint-argmax pipeline got us to 51/54. What is at its limit is
the layer ABOVE the channels: forcing every kind of musical knowledge
into `{t, w}` votes folded per line. The three remaining failures are
three different missing abstractions, not three missing weights:

| segment | what's missing | mechanism |
|---|---|---|
| rage_s3 (2/4) | **hierarchy** — the true 500 ms tactus has NO fold peak; it exists only as 2× the 250 ms sub-pulse | metrical lattice (§S3) |
| grieg_s3 (3/4, beat-2 phase) | **syntax** — beat 1 is identified by the bass→chord→chord ORDER, not by any accent | event-role grammar (§S5) |
| op64_s5 (3/4, sostenuto) | **memory** — locally near-flat evidence; 3/4 was established two segments earlier | stateful beam tracker (§S6) |

Target architecture (the review's boundary, adopted):

```
EVIDENCE EXTRACTION   build_votes() — survives nearly unchanged
        ↓
METRICAL REASONING    hypothesis lattice + role grammar + HR ratios
        ↓             (one score_hypothesis() for ALL consumers)
TEMPORAL INFERENCE    beam tracker: state + confidence + continuity
```

Standing rule while this lands: **no new channels into the current
`_bar()`**. New musical knowledge goes into hypothesis scoring terms.

## Verified defects (checked against code 2026-08-15, not assumed)

1. **Tracker scores with a different model than the selector.**
   `infer_downbeats` picks by `tactus_score × level_score` where level
   includes the hr multiplier and parsimony selection; the streaming
   tracker compares grids with `grid_level_score()` = per-line periodic
   mass × bar prior only.
2. **Tolerance mismatch**: `_bar()` folds at `fold_tol_frac ×
   tactus_ms`; `grid_level_score()` at `fold_tol_frac × bar_ms / 2` —
   identical at G=2 but 1.5× wider at G=3 and 2× at G=4. The tracker
   systematically favors larger-G incumbents. Likely a contributor to
   tracked 45/54 vs raw 51/54.
3. **No uncertainty output**: `infer_downbeats` returns the winner only.
   "3/4 lost 0.98 vs 1.00" and "3/4 lost 0.22 vs 1.00" are
   indistinguishable downstream — exactly the op64_s5 information.

## The data structure

A meter reading is a hypothesis over the whole hierarchy, not a
`(tactus, G)` pair. Plain dict (house style), constructed by candidate
generation, consumed by scoring, tracking, and eventually Phase 3
(simple vs compound subdivision is a first-class variable that
`beats_per_bar` alone cannot carry — 6/8 is 2 tactus × 3 subdivisions):

```python
hyp = {
    "sub_ms":       250.0,   # strongest supporting sub-pulse (or None)
    "sub_arity":    2,       # subdivisions per tactus: 2 | 3 | None
    "tactus_ms":    500.0,
    "tactus_phase": 12.0,
    "group":        2,       # tactus beats per bar (bar = group * tactus)
    "bar_phase":    12.0,
}
```

One scoring function, used by offline inference, the tracker, ablation,
and the GUI — **no second simplified scorer anywhere**:

```python
score_hypothesis(votes, hyp, span_ms, p) -> {
    "total":   ...,   # what selection maximizes / the tracker compares
    "tactus":  ...,   # folded mass at tactus × tactus prior
    "level":   ...,   # per-line periodic mass × bar prior
    "phase":   ...,   # phase mass incl. entry (never in level)
    "hr":      ...,   # harmonic-rhythm term (mode per §S4)
    "subdiv":  ...,   # subdivision-support term (§S3)
    "role":    ...,   # event-role grammar term (§S5)
}
```

Selection rules (parsimony margin, triple margin, entry-never-picks-
level) stay OUTSIDE the score as explicit selection logic — they are
comparisons between hypotheses, not properties of one.

## Stages

Ordered so that each stage is independently measurable and the
no-regression gate (51/54 acceptable, 38/54 exact, `python3
score_downbeat.py` + `tools/ablate_phase2.py`) holds at every merge.
Per repo rule 9, every new mechanism ships as a **selectable option**
(param default = current behavior) until measured in; per rule 8, back
up `phase2_downbeat.py` and `tools/measure_lock.py` into
`_backup_files/` before S1.

### S1 — Unify scoring (refactor, behavior-neutral)

Introduce the `hyp` dict + `score_hypothesis()`. `_tactus()` and
candidate enumeration feed hypotheses; `infer_downbeats` selects by
`score_hypothesis(...)["total"]` + the existing margins;
`grid_level_score()` is DELETED and `measure_lock.py`'s tracker
compares incumbents/challengers with the same `score_hypothesis`
total (hysteresis factor re-checked after — 1.25 was tuned against the
old, inconsistent scorer). This fixes verified defects 1 and 2.

- **Acceptance**: offline per-segment outputs byte-identical to today
  (assert against a captured `score_downbeat.py --json` baseline);
  then re-run `tools/measure_lock.py` and record the tracked number —
  expected to move from 45/54 toward raw's 51/54 on the tol fix alone.
  Any offline diff = bug in the refactor, fix before proceeding.
- **Failure mode**: silent behavior drift hidden inside the refactor.
  Mitigation: baseline-diff gate above, no parameter changes in S1.

### S2 — Evaluation triad (no engine change)

Three simultaneous targets, per the review; a change is only
"architecturally proven" if it survives all three:

1. **Cold-start 54-segment suite** — permanent regression gate,
   unchanged.
2. **Continuous-piece streaming** — segments of a piece are contiguous
   16-bar windows by construction; run the (S1-unified) tracker across
   each piece's concatenated segments and score per segment. New tool
   `tools/measure_piece.py` (or a mode of `measure_lock.py`). This is
   the eval on which op64_s5 is allowed to succeed (§S6).
3. **Leave-one-piece-out** — `tools/tune_phase2.py` learns a
   `--holdout <piece>` grouping; report the 13-fold LOPO acceptable
   count alongside train numbers. The current split is segment-level
   with piece leakage (disclosed in session-log); the role grammar
   (§S5) is exactly the kind of mechanism that overfits a piece's
   recurring texture, so this lands BEFORE any S3–S5 tuning.

- **Acceptance**: baseline numbers recorded in session-log for all
  three targets before any mechanism work.

### S3 — Metrical lattice: hierarchical candidate closure (Rage)

Problem (measured): the csárdás syncopation projects 749/563/375 ms;
the true 500 ms pulse has no fold peak at all, so it dies before the
level stage can reason. Weights cannot fix an absent candidate.

Mechanism: candidate generation stops requiring a tactus to manifest
as an accent periodicity. From each of the top-K fold peaks, CLOSE the
set under small integer relations: for peak P, add derived tactus
candidates {P×2, P×3, P/2, P/3} (clamped to a widened plausible-tactus
range), deduplicated by the existing `tactus_peak_sep`. Each derived
hypothesis records its generator as `sub_ms`/`sub_arity`.

Scoring: a derived tactus has little folded mass of its own — that is
the point — so `score_hypothesis` gains a **subdivision-support term**
(`w_subdiv`, default 0 = off): the tactus inherits credit from the
folded mass at its sub-pulse, contingent on consistency (the sub-pulse
phase must align with the tactus phase within tol). A beat can be
perceptually real without containing an onset; its subdivision is the
witness. Rage then reads as 250 ×2 → 500 tactus ×2 → 1000 bar with no
csárdás-specific template.

- **Code**: `_tactus()` → returns peaks + closure; new term in
  `score_hypothesis`; `groupings` untouched (the bar is reached from
  the corrected tactus, not by letting G grow to 8).
- **Acceptance**: rage_s3 (and sibling rage_s1 texture) acceptable;
  54-suite no regression; LOPO not worse.
- **Failure modes**: candidate explosion (K×5 candidates — cap and
  keep top-N by score after closure); double-counting (a real peak
  also generated as another's multiple — dedup by period); the
  911-vs-真-pulse 9% joint deficit persisting because the subdivision
  term is too weak → it is a weight, tune it on the split under LOPO.

### S4 — Harmonic rhythm as a RATIO on level, not an anchor on phase

Problem (measured): harmonic rhythm is half-bar in one 4/4 piece and
2 bars in the waltzes; in grieg_s3 the 2-bar HR anchored on odd bars
actively supports the WRONG phase through today's concentration
multiplier, which sits inside the loop over both level and phase.

Mechanism: estimate the harmonic-change period H directly — weighted
autocorrelation / pairwise-lag consistency of the harmony votes — with
an explicit **reliability**: if changes are irregular, the estimator
says "don't know" and the term contributes ~0 (this is what the
irregular-HR pieces need). Then score the LEVEL only:

```
hr_ratio_score(bar) = reliability × max over r ∈ {1/2, 1, 2} of
                      closeness(H, r × bar)
```

No phase input at all — harmony still votes on phase as a normal
periodic channel, but the HR multiplier stops rotating downbeats.

- **Code**: new estimator in `build_votes` or a sibling; in
  `score_hypothesis`, `hr` term gets a mode switch `hr_mode ∈
  {"concentration" (today, default), "ratio"}` — selectable per rule
  9, because the concentration form is credited with fixing
  hungarian_s1 and the swap must be measured, not assumed.
- **Acceptance**: with `hr_mode=ratio`: grieg_s3's phase no longer
  supported by HR (may not flip alone — §S5 is the positive
  evidence); hungarian segments hold; 54-suite no regression. Decide
  the default by measurement across cold-start + LOPO.
- **Failure mode**: H estimator locking onto texture change instead of
  harmony (the old Jaccard trap) — it consumes the regime-chroma votes
  precisely to avoid this; reliability gate is the backstop.

### S5 — Event-role grammar (Grieg)

Problem (measured): every accent channel points at beat 2 (Grieg's
agogic mannerism + weak "um"); only ORDER knows beat 1. The um-pah-pah
schema is bass-role THEN chord-role THEN chord-role; the anchor's
identity comes from what FOLLOWS it, not its strength.

Mechanism: per onset cluster, a deterministic **role vector** — no
learned classifier in the first cut: {low-register strength, LH/RH
participation, vertical density, chordality, duration, register
distance from previous bass, sustain state}. Define `anchorhood(c)`
(register + hand dominated) and `continuation(c, prev)` (chordal,
higher, harmonically static vs prev). Then a level+phase term:

```
role_score(hyp) = consistency, across the segment's bars, of the
                  pattern (anchor at beat 0) → (continuation at 1..G-1)
```

scored per candidate `(group, bar_phase)` so the bass position that
INITIATES a repeating figure claims beat 1. This is the general form
of "waltz recognition" — the same term should later reward Alberti
and other figuration anchors, which is why it is a grammar over roles
and not a um-pah-pah template.

- **Code**: role extraction beside `build_votes` (needs clusters +
  hands, both available); `w_role` term (default 0) in
  `score_hypothesis`, participating in level AND phase (it is ordered
  evidence, so the one-shot-inflation rule that bans entry from level
  does not apply — but verify the per-line normalization anyway).
- **Acceptance**: grieg_s3 exact; the other 19 waltz segments and all
  4/4 (Alberti-adjacent textures) no regression; **LOPO mandatory** —
  this is the mechanism most able to memorize a piece's texture.
- **Failure modes**: role vectors degenerate where hands interleave
  (Waldstein s0's pulsing close-position chords) — reliability-gate on
  anchor sparsity; punishing legitimate beat-3 bass in 4/4 — the score
  rewards CONSISTENT repetition of the figure, not single instances.

### S6 — Beam tracker, confidence, abstention (op64_s5)

Reframe (user decision required, §Decisions): op64_s5's sostenuto
passage may be locally under-determined BY CONSTRUCTION — a human
entering cold needs context too. The live product HAS context. So:
cold-start stays the stress test, but op64_s5's success criterion
moves to the continuous-piece eval (S2 target 2), where s4 has already
established 500 ms / 1500 ms / phase φ and s5 contains nothing strong
enough to overthrow it.

Mechanism: replace the binary incumbent/challenger hysteresis with a
**beam of 4–8 hypotheses** (deterministic Viterbi-style, no training):
each step, every beam member is rescored `score_hypothesis(current
votes) + transition score from previous state`; staying (small period
drift, same phase trajectory) is cheap, jumping (level change, phase
discontinuity) costs a penalty only strong new evidence can pay. Weak
evidence then correctly FAILS TO OVERTURN 3/4 instead of magically
supporting 4/4. The S1 unification is the prerequisite — beam and
selector already speak the same score.

Confidence as an actual output of `infer_downbeats`: runner-up and
margin per component —

```
"confidence": {"tactus": ..., "level": ..., "phase": ...,
               "runner_up": {...}, "margin": ...}
```

allowing partial commitment (TACTUS locked / LEVEL uncertain — for
transcription, far better than confidently wrong). Feeding it: the
**channel-reliability multiplier** (review §10): after normalization,
scale each channel by a reliability that rises with effective sample
count and periodic consistency — one ambiguous resolution event stops
carrying the same authority as twenty consistent cadences.
Normalization itself stays (it is the measured single largest win).

- **Code**: `tools/measure_lock.py` tracker → beam (or a new
  `phase2_stream.py` if it outgrows the tool); reliability in
  `build_votes` post-normalization (`rel_*` params, default 1.0 =
  today); confidence block in `infer_downbeats` output + GUI display.
- **Acceptance**: continuous-piece eval — op64_s5 correct via
  continuity; tracked locks ≥ raw's 51/54 with median lock ≤ the
  current 4.75 s; the 6 tracker-stuck segments from 2026-08-15
  resolved or diagnosed; cold-start suite untouched (beam is
  streaming-only).
- **Failure modes**: beam collapse (all members one meter family —
  seed the beam with the top-K DISTINCT hypotheses, not the top-K
  scores); transition penalty too high = never recovers from a wrong
  early lock (measure switch latency on storm_s0/hungarian_s3, the
  known stickers).

## What is explicitly NOT being done

- No csárdás/waltz templates — the lattice and the role grammar are
  the general forms.
- No trained models — every term deterministic, stdlib, causal-
  compatible (bounded lookahead only).
- No new channels into `_bar()` while the refactor is in flight.
- No removal of channel normalization (reliability multiplies it).
- Parallelism stays measured-out (`w_par=0`) — the role grammar may
  later subsume its intent (figuration STRUCTURE, not accents).

## Decisions for the user (Prime Directive — none of these are made)

1. **The op64_s5 reframe**: accept that cold-start 51/54 + op64_s5-
   via-continuity counts as SOLVED (three-target evaluation, §S2/S6)?
   This redefines the headline gate; it is the review's position and
   matches live use, but it is a scoring-philosophy change and the
   user owns the metric.
2. **hr_mode default**: after S4 measurement, which mode ships as
   default? (Concentration is credited with hungarian_s1; ratio is
   architecturally right for Grieg/waltzes. Measurement may say
   "ratio for level + nothing for phase" wins outright — but if it is
   a swap, the user picks.)
3. **Beam replaces hysteresis** (S6) or stays selectable alongside it?
   Rule 9 says selectable; the review says fold streaming into Phase 2
   proper as THE engine. Proposal: selectable during S6 measurement,
   then a user call on making beam the default.
4. **Stage order**: S1→S2 are safe and unblocking; proceed
   immediately? S3–S6 in review order, or reprioritized (e.g. S6
   early because streaming is the product surface)?

## Traceability

| review § | this spec | brief § |
|---|---|---|
| 3 (lattice) | S3 | §7 Q1 (rage) |
| 4 (role grammar) | S5 | §7 Q2 (grieg) |
| 5 (HR ratio) | S4 | §7 Q4 |
| 6+8 (tracker/beam) | S6 | §7 Q3 (op64) |
| 7 (unify scorer) | S1 | — (verified defect) |
| 9 (confidence) | S6 | §7 Q3c (abstain) |
| 10 (reliability) | S6 | — |
| 11 (evaluation) | S2 | §8 gate |
