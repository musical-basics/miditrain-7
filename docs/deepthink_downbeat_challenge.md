# Deepthink Brief: The Remaining Downbeat-Detection Challenge

Written 2026-08-15 for an architect-level model. Everything below is
MEASURED on the current corpus, not assumed. Your job: propose a
mechanism (not a weight tweak — those are exhausted, see §6) that closes
the remaining failures without breaking what works.

## 1. The task and the constraints

Live piano transcription. Input: raw MIDI notes only — (onset_ms,
duration_ms, pitch 0–127, velocity 1–127). NO time signature, tempo, or
barline metadata; every signal must be computed RELATIVE to what came
before (the endgame is a live performer, so whole-piece statistics are a
debt and bounded lookahead is the ideal). Deterministic. Output: the bar
grid — tactus period, beats per bar, bar phase → projected downbeat
times.

Upstream (working, not the subject of this brief): hand separation
assigns every note L/R at ~93% (beam search over onset-cluster splits;
`phase1_hands.py`). The downbeat engine consumes the hand streams.

**Scoring** (user-defined equivalence): reading 2/4 as 4/4 is CORRECT
(every claimed downbeat is a true one); reading 12/8 as 6/8 is CORRECT
(every true downbeat claimed). Canonical target meters: 3/4, 4/4, 6/8.
A 1.5x bar, or a right-length bar with the wrong phase, is WRONG.
Verdicts: exact / double / half / wrong; headline = segments not-wrong.

## 2. Current architecture (`phase2_downbeat.py`)

Vote-based, one joint argmax (a compact rebuild of a "meter evidence
bus" that beat two standalone engines in the predecessor repo):

1. **Channels** emit time votes {t, w}, each channel's total mass
   normalized to 1, then weighted: onset (velocity-weighted clusters),
   bass (LH depth x duration), chord (>=3 simultaneous notes), agogic
   (duration vs same-hand trailing median), velocity (loudness vs
   same-hand trailing mean), harmony (harmonic-REGIME change: cosine
   distance between trailing and forward 600 ms duration-weighted
   chroma), resolution (dissonance of forward chroma DROPS -> cadential
   arrival; x3 when the bass falls a fifth into it), entry (segment
   start + each hand's first entrance — one-shot phase evidence).
2. **Tactus**: fold all votes at log-spaced periods 240–1200 ms,
   log-Gaussian prior around 600 ms; keep the TOP-5 distinct peaks.
3. **Bar level**: for each tactus candidate, grouping G ∈ {2,3,4} x
   beat-phase k: per-line folded mass of the periodic channels x
   bar-length prior (log-Gaussian around 1900 ms, sigma 1.4 oct) x
   harmonic-rhythm multiplier (concentration of harmony votes on the
   candidate's downbeat lines vs its other beat lines). G>2 must beat
   G=2 by parsimony 1.15. Joint winner maximizes tactus_score x
   level_score. Phase within the level additionally counts entry votes.
4. **Refinement**: least-squares fit of (period, phase) to captured
   votes (kills 0.2–0.4% quantization drift).
5. **Streaming**: prefix replay + hysteresis tracker (incumbent grid
   earns inertia after 2 confirming re-inferences, challenger needs
   1.25x its score). Median permanent lock ~4.75 s (~2 bars).

## 3. Current results (54 segments, 13 pieces, meters 4/4 2/4 3/4 6/8 12/8)

**51/54 acceptable, 38/54 exact, precision 92%.** Tactus correct in
~52/54. Segments are contiguous 16-bar windows (32 for 2/4), no pickup,
quantized-tempo renders with real dynamics, ~120–620 notes each.

Channel ablation (drop-one, acceptable count): bass 49→39 (the king),
harmony 49→44, entry 49→46, chord/agogic/velocity ≈ neutral
individually, resolution net-zero at the margin BUT its cadence-gated
form fixed two 2/4 segments the plain form missed. Parallelism as a
LEVEL voter (matched 4-note contour+rhythm n-grams; anchors whose lag is
a bar multiple support their phase) was measured OUT — repetition
anchors land on beats 1 and 3 alike in this repertoire.

## 4. The three remaining failures (be specific about these)

1. **beethoven_rage_over_a_lost_penny__s3** (2/4, presto, true bar
   1000 ms): locks bar 2981 ms, G=3 — i.e. a ~745 ms tactus family.
   The csardas-like syncopation projects 749/563/375 ms periodicities;
   in the sibling segment s1 (same texture) the TRUE 500 ms pulse has NO
   peak in the fold at all (checked: not in the top-5), and the
   true-bar candidate via 250 ms x4 loses the joint score by 9%.
2. **grieg_waltz_op_12_no_2__s3** (3/4, true bar 1500): bar length
   RIGHT, phase on beat 2 (500 ms). Texture: the accompaniment is
   um-pah-pah with a weak "um"; the melody's agogic accents sit on
   beat 2 in this section (a Grieg mannerism). Every accent channel
   votes beat 2; only harmony/bass know better, and here the harmonic
   rhythm is 2 bars long, landing on ODD bars — its votes support beat
   2's phase at the 2-bar fold.
3. **waltz_opus_64_no_2_in_c_minor__s5** (3/4, true 1500): reads 2000
   G=4 — a duple lock in the sostenuto section where the LH plays
   long-held notes (no oom-pah), the harmonic rhythm is slow, and the
   melody is legato eighths. Very thin structural evidence; the 500 ms
   tactus is right and the level evidence is nearly flat.

## 5. What we know does and does not work (do not re-derive)

- Plain per-line accent folding CANNOT pick the level between
  self-similar readings (2/4 vs 4/4, 6/8 vs 12/8): at ambiguous levels
  the accents are self-similar by construction. Priors/margins only
  trade meters against each other (multiple exhausted grid searches).
- Accent CONTRAST (best beat minus other beats) punishes 4/4's
  legitimately strong beat 3 — measured out.
- Harmonic-regime change (windowed chroma) is the #2 channel and the
  right kind of level evidence, but harmonic rhythm is not always 1
  bar: it is half-bar in one 4/4 piece, 2 bars in parts of the waltzes.
  A fixed "harmony changes at bar starts" assumption is wrong; the
  RELATIONSHIP (bar = harmonic rhythm x {1/2, 1, 2}) is what's true.
- One-shot evidence (entry) must never touch level selection (divides
  by fewer lines for longer bars -> mechanical inflation). It carries
  phase strongly but is a phrase-alignment crutch (segments start at
  bar 1 by construction; live windows won't).
- The joint (tactus x level) decision over top-K tactus peaks rescued
  two segments whose best fold peak carried a hopeless bar. But it
  cannot rescue a pulse that produces NO fold peak (rage).
- Hysteresis with earned inertia beats from-scratch re-inference in
  streaming (31/34 -> measured pre-waltz; re-measure pending).

## 6. Exhausted directions

Four independent grid searches (100s of configs each) over every channel
weight, both priors, parsimony/triple margins, fold tolerances. The
current config is the optimum of this design; every remaining gain in
those sweeps was a swap (fix one segment, break another). The failures
above need a NEW MECHANISM or a structural change, not tuning.

## 7. Questions for you

1. **The rage problem**: how do you find a pulse that the onset fold
   literally does not contain? The eighth-note layer (250 ms) exists;
   the notated beat (500 ms) is a silent level between 250 and the
   syncopation's 750. Ideas we have NOT tried: subdivision-consistency
   constraints (tactus must be an integer multiple of the strongest
   sub-pulse AND divide the bar), asymmetric-pattern matching (the
   csardas figure as a rhythmic template), letting G reach 8 from the
   sub-pulse.
2. **The Grieg phase problem**: when every surface accent points at
   beat 2 and the harmonic rhythm is 2 bars anchored on odd bars, what
   evidence identifies beat 1? (Human listeners use the um-pah-PAH
   schema itself — bass-then-chords ORDER, not bass strength.) Is a
   figure-template channel (bass note followed by two chord strikes =>
   the bass position is beat 1) principled or a hack? Is there a
   general formulation ("within-bar event-role grammar")?
3. **The thin-evidence problem** (op64_s5): with almost no structural
   votes, should the engine (a) inherit the neighboring segments' grid
   (temporal continuity across windows — currently each segment is
   independent), (b) widen its windows, or (c) abstain? For live use,
   continuity is free — is per-segment independence simply the wrong
   evaluation and the tracker the real answer?
4. **Level from harmonic rhythm as a RATIO, not an anchor**: propose a
   robust estimator of the harmonic-change period itself (autocorrelate
   the harmony votes?) and a scoring term for bar = HR x {1/2, 1, 2}
   that does not break the pieces where HR is irregular.
5. Anything structurally missing? The channels are all LOCAL (window or
   pairwise). The only global structure we tried (melodic parallelism
   at the level stage) measured out. What global evidence would a
   musician say we are ignoring? (Form? Register cycles? Texture-change
   boundaries? LH figuration periodicity — note the pah-pah insight
   suggests figuration STRUCTURE, not just accents, is informative.)

## 8. Ground rules for proposals

- Causal-compatible (bounded lookahead), deterministic, pure function
  of the notes. No trained models unless the training data story is
  explicit and small.
- Must be expressible as either (a) a new vote channel, (b) a new term
  in the level/phase score, or (c) a structural change to the decision
  — say which, and what its failure mode would be.
- The gate: 51/54 acceptable / 38 exact must not regress; proposals are
  judged on the 3 named segments plus no-regression, via
  `python3 score_downbeat.py` and `tools/ablate_phase2.py`.

## 9. File map

| what | where |
|---|---|
| engine | `phase2_downbeat.py` (channels, joint decision, refinement) |
| hands (upstream) | `phase1_hands.py` |
| scorer + equivalence | `score_downbeat.py` |
| ablation harness | `tools/ablate_phase2.py` |
| weight sweeps | `tools/tune_phase2.py` (+ benchmarks/split.json) |
| streaming/tracker eval | `tools/measure_lock.py` |
| segments + truth | `data/segments/*.json` (notes + truth block) |
| measured history | `docs/session-log.md` (read it — every rejected idea is recorded) |
