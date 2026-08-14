# miditrain-7 Architecture — Phase Order and Why

Written 2026-08-14. This is the decision document for the rewrite. The
predecessor (miditrain-6) has strong per-phase logic but the phases are in
the wrong hierarchical order; this repo reorders them and rebuilds bottom-up
on clean piano data, verifying each phase's output in a GUI before the next
phase is trusted.

## The premise

- **Garbage in, garbage out.** miditrain-6's parameters were trained on 76
  chorales/folk songs out of 89 corpus pieces — not the target domain.
  miditrain-7 trains ONLY on clean classical piano data: the MIDI+MusicXML
  pairs in `source/`, cut into **even 16-bar segments with no pickup
  measures** (`data/segments/`).
- **Everything is inferred from notes alone.** MIDIs are the input; the
  MusicXMLs are only for checking. No time-signature, tempo, or barline
  metadata is consumed by any phase. All values are computed RELATIVE to
  what came before — the endgame is live transcription, where the first
  1–3 seconds of a segment are genuinely ambiguous.
- **Downbeat is the point.** Harmonic color, voice separation, and the
  thermodynamic machinery exist *in service of* finding the downbeat.
  If downbeat detection is not ≥98%, nothing downstream matters.

## The phase order (the decision)

```
Phase 0  Ingest & Segmentation    MIDI → note events (onset, duration, pitch, velocity)
                                  16-bar clean segments + truth from MusicXML (eval only)
Phase 1  Hand Separation          notes → hand ∈ {L, R} per note      ← FIRST algorithm
                                  (single-voice-per-hand model for now)
Phase 2  Downbeat Inference       hand streams → (bar period, phase) → downbeat times
                                  evidence channels: bass/LH onsets, harmonic change,
                                  agogic/accent, parallelism, chord mass   ← NORTH STAR
Phase 3  Beat Grid & Quantize     downbeats + tactus → tick coordinates per note
Phase 4  Within-Hand Voices       only where a hand truly holds 2+ voices (DEFERRED)
Phase 5  Notation                 spelling, beaming, MusicXML export (DEFERRED,
                                  port from miditrain-6 when 1–3 are trusted)
```

### What changed vs miditrain-6 (P1 harmonic → P2 voices → P3/4 meter → P5)

1. **Hand separation is promoted to the first real phase.** miditrain-6
   measured why: its 18 wrong-staff notes on the Clementi were all Phase 2
   voice-threading failures in the D4–F4 crossover; hands are a coarser,
   physically constrained partition (span ≈ octave, rarely cross) and the
   discriminator — line continuity — lives at the hand level. Hands give
   Phase 2 a real bass stream instead of a lowest-note proxy, and turn
   4-way voice assignment into two constrained 2-way problems later.
2. **Harmonic regimes and the thermodynamic meter are demoted from
   standalone phases to evidence channels inside the downbeat decision.**
   This matches miditrain-6's own measured endpoint: the meter evidence
   bus (one joint period+phase argmax over many channels) beat both
   standalone engines decisively (bus 863 vs thermo 1147 vs spike 1694
   val errors). What was "Phase 1 makes colors, Phase 3 makes freezes,
   Phase 4 combines them" becomes simply: channels vote, one decision.
3. **Voice threading moves AFTER meter and is deferred.** Under the
   single-voice-per-hand model the hand IS the voice. Multi-voice hands
   are a later refinement, and when they come they benefit from the
   metrical grid rather than preceding it.
4. **Per-phase GUI verification is a standing requirement.** Every phase's
   output is inspectable per segment (`gui/`), against truth, before the
   next phase builds on it.

### Hierarchy rules

- A phase may consume only raw notes and the output of LOWER-numbered
  phases. Phase 1 sees pitch/onset/duration/velocity ONLY.
- Phases never read the `truth` block of a segment. Truth is for scorers
  and the GUI.
- Deterministic, causal-compatible where cheap: bounded lookahead is
  acceptable now, whole-piece passes are a debt to record.

## Data discipline

- `source/`: the 4 MIDI+MusicXML pairs (Clementi, Kuhlau, Burgmüller ×2).
  All verified: 2 parts, 4/4, **no pickup measures**, MIDI aligns to the
  XML on the 120 BPM grid (quarter = 500 ms, bar = 2000 ms).
- `tools/make_segments.py` cuts consecutive, non-overlapping 16-bar
  windows (32 s each): 10 segments, remainder bars dropped. Pieces WITH a
  pickup measure are skipped loudly (none currently; the parser must
  eventually handle capturing the downbeat despite a pickup — deferred by
  design, see session log).
- Truth per segment: per-note hand (from MusicXML part index, matched
  onset+pitch), downbeat times, time signature. Notes with no XML match
  (ornament/tie artifacts, ~1–3%) carry hand `"?"` and are excluded from
  scoring denominators but stay in the input — the algorithm still has to
  process them.
- **Known limitation, accepted for now**: with 4 pieces there is no
  train/held-out split; parameters tuned here are fit to these pieces.
  Growing `source/` is drag-and-drop + re-running the segmenter; before
  trusting any number as general, grow to ~15 pieces (miditrain-6's
  phase0 spec, §7).

## Bars to beat (measured in miditrain-6, same 4 pieces)

| baseline | overall | crossover |
|---|---|---|
| fixed split @ middle C | 72.8% | 43.5% |
| oracle per-piece split | 94.5% | 87.2% |

The oracle cheats (picks the best threshold knowing the answer), so
**beating it is the bar** — matching it means the algorithm learned
nothing a per-piece constant couldn't. Crossover accuracy is the primary
number; ~43% of all notes sit where both hands are active and pitch alone
provably cannot decide (Clementi has pitch-identical hand-opposite
textures). Hand switches inside a true hand is the line-continuity tell:
split@60 makes 130+ on the worst pieces, the oracle makes 6.

Downbeat: scored as F1 at ±50 ms against truth downbeats, plus the
headline rate "% of truth downbeats returned" — the 98% target — and
segment-strict rate (all 16 downbeats correct).
