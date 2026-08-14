# Claude Code Operating Instructions — miditrain-7

> **Core mandate**: Make focused, verifiable improvements and surface decisions to me — not autonomously solve every problem you see. When in doubt, document and ask rather than implement.

## What this repo is

Clean-slate rewrite of the MidiTrain pipeline (miditrain-6 is the predecessor and reference implementation). The end goal is **live music transcription**: infer notation from raw notes only — no sheet-music metadata, everything computed RELATIVE to what came before.

**North-star metrics** (in priority order):
1. **Downbeat detection ≥ 98%** — if the engine cannot return the downbeat, everything downstream is pointless.
2. **Hand-separation crossover accuracy** — the prerequisite for everything; bar to beat is the oracle fixed split (94.5% overall / 87.2% crossover, measured in miditrain-6).

**Scope for now**: classical-style piano, single voice per hand, even 16-bar segments, no pickup measures, no hand crossing, no impressionism. Get that right before generalizing.

Read `docs/architecture.md` for the phase order and why. Read `docs/session-log.md` at session start; update it at session end.

## Rules (carried over from miditrain-6)

1. Use **pnpm** over npm where relevant. Python: use `./venv/bin/python3` (has mido + music21).
2. After every code change, verify before pushing (run the scorers; `tsc --noEmit` if TS exists). **Never push red.**
3. Kill your own localhost processes after verification runs.
4. Push after every completed change. Major changes that deviated from the user's expectation: ask first.
5. Debugging: >2 failed fix attempts → add verbose logging, keep it until user confirms fixed, document the bug in `/docs`.
6. **Never modify files outside the current task's scope** without flagging. Broken things found along the way go to `docs/debt.md`.
7. Edge-case fixes: prefer architectural fixes over if/else patches.
8. Refactorings: back up files into `_backup_files/` first.
9. Feature upgrades become **selectable options** (A/B), never overwrites.
10. Phases must not read ground truth. Truth lives in each segment's `truth` block; phase code consumes `notes` only. A phase that peeks at truth invalidates every number.
11. Every measured claim goes in `docs/session-log.md` with the number, not an adjective.

## The Prime Directive

**Your role is executor, not autonomous agent.** Surface decisions, don't make them unilaterally. When something is ambiguous, document it in `docs/debt.md` and ask.
