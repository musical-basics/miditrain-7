"""
Phase 0 — Ingest & segmentation.

Cuts every MIDI+MusicXML pair in source/ into consecutive, non-overlapping
16-bar segments (the even training slots). The MIDI is the INPUT; the
MusicXML supplies TRUTH only (per-note hand, downbeat times, time
signature). Pieces with a pickup measure are skipped loudly — for now the
corpus is required to be pickup-free (docs/architecture.md).

Output, per segment: data/segments/<piece_slug>__s<k>.json

    {
      "id": "...", "piece": "...", "segment_index": k,
      "measures": [first, last],          # 1-based positional, within the piece
      "bar_ms": 2000, "n_bars": 16,
      "notes": [ {onset_ms, duration_ms, pitch, velocity}, ... ],   # INPUT
      "truth": {                                                    # EVAL ONLY
        "time_signature": "4/4",
        "downbeats_ms": [0, 2000, ...],   # 16 entries, segment-relative
        "hand": ["L"|"R"|"?", ...]        # parallel to notes; "?" = no XML match
      }
    }

plus data/segments/manifest.json.

Times follow the repo-wide 120 BPM convention: quarter = 500 ms
(tick_to_ms = 500/tpq regardless of MIDI tempo metadata), same as the
MusicXML offsets — that is what makes MIDI<->XML matching exact.

Run with ./venv/bin/python3 (needs mido + music21).
"""
import json
import os
import re

import mido
from music21 import converter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC_DIR = os.path.join(ROOT, "source")
OUT_DIR = os.path.join(ROOT, "data", "segments")

MS_PER_QUARTER = 500.0      # 120 BPM convention
BARS_PER_SEGMENT = 16
MATCH_TOL_MS = 10           # MIDI<->XML onset tolerance


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return re.sub(r"_(all_markings|full_lesson|lesson)_version(_v\d+)?$", "", s)


def parse_midi(path):
    mid = mido.MidiFile(path)
    tpq = mid.ticks_per_beat
    notes = []
    for track in mid.tracks:
        t = 0
        active = {}
        for msg in track:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                active.setdefault(msg.note, []).append((t, msg.velocity))
            elif msg.type in ("note_off", "note_on"):
                if active.get(msg.note):
                    start, vel = active[msg.note].pop(0)
                    notes.append({
                        "onset_ms": round(start * MS_PER_QUARTER / tpq),
                        "duration_ms": round((t - start) * MS_PER_QUARTER / tpq),
                        "pitch": msg.note,
                        "velocity": vel,
                    })
    notes.sort(key=lambda n: (n["onset_ms"], n["pitch"]))
    return notes


def parse_xml(path):
    """Truth: per-note hands + measure structure, offsets at 120 BPM ms."""
    score = converter.parse(path)
    if score.recurse().getElementsByClass("Repeat"):
        score = score.expandRepeats()
    parts = list(score.parts)
    if len(parts) != 2:
        raise ValueError(f"{len(parts)} parts (need 2: part 0 = RH, part 1 = LH)")

    truth_notes = []
    for pi, part in enumerate(parts):
        for n in part.flatten().notes:
            for p in n.pitches:
                truth_notes.append({
                    "onset_ms": round(float(n.offset) * MS_PER_QUARTER),
                    "pitch": int(p.midi),
                    "hand": "R" if pi == 0 else "L",
                })

    measures = list(parts[0].getElementsByClass("Measure"))
    ts = measures[0].timeSignature
    if ts is None:
        sigs = parts[0].recurse().getElementsByClass("TimeSignature")
        ts = sigs[0] if sigs else None
    if ts is None:
        raise ValueError("no time signature in the reference")
    bar_ql = float(ts.barDuration.quarterLength)
    bar_ms = round(bar_ql * MS_PER_QUARTER)
    if float(measures[0].duration.quarterLength) < bar_ql:
        raise ValueError(
            f"pickup measure ({measures[0].duration.quarterLength} < {bar_ql} ql) "
            "— pickup-free corpus required for now")
    for m in measures[1:]:
        if m.timeSignature and m.timeSignature.ratioString != ts.ratioString:
            raise ValueError(f"mid-piece time signature change at measure {m.number}")

    downbeats_ms = [round(float(m.offset) * MS_PER_QUARTER) for m in measures]
    # sanity: even grid
    for i, d in enumerate(downbeats_ms):
        if d != i * bar_ms:
            raise ValueError(f"uneven measure grid at index {i}: {d} != {i * bar_ms}")

    return truth_notes, downbeats_ms, bar_ms, ts.ratioString


def label_hands(midi_notes, truth_notes):
    """Per-MIDI-note hand from the XML: match on (onset±tol, exact pitch)."""
    pool = {}
    for tn in truth_notes:
        pool.setdefault((tn["onset_ms"], tn["pitch"]), []).append(tn["hand"])
    hands, unmatched = [], 0
    for n in midi_notes:
        found = None
        for tol in (0, -5, 5, -MATCH_TOL_MS, MATCH_TOL_MS):
            k = (n["onset_ms"] + tol, n["pitch"])
            if pool.get(k):
                found = pool[k].pop(0)
                break
        if found is None:
            unmatched += 1
            found = "?"
        hands.append(found)
    return hands, unmatched


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    stems = sorted(os.path.splitext(f)[0] for f in os.listdir(SRC_DIR)
                   if f.endswith(".musicxml"))
    manifest = []
    for stem in stems:
        xml = os.path.join(SRC_DIR, stem + ".musicxml")
        mid = os.path.join(SRC_DIR, stem + ".mid")
        if not os.path.exists(mid):
            print(f"SKIP {stem}: no matching .mid")
            continue
        try:
            truth_notes, downbeats_ms, bar_ms, ts = parse_xml(xml)
        except ValueError as e:
            print(f"SKIP {stem}: {e}")
            continue
        midi_notes = parse_midi(mid)
        hands, unmatched = label_hands(midi_notes, truth_notes)

        n_bars_total = len(downbeats_ms)
        n_segments = n_bars_total // BARS_PER_SEGMENT
        pslug = slug(stem)
        print(f"{stem}: {len(midi_notes)} MIDI notes, {n_bars_total} bars, "
              f"{ts}, bar={bar_ms}ms -> {n_segments} segments "
              f"({unmatched} unmatched notes)")

        for k in range(n_segments):
            start = k * BARS_PER_SEGMENT * bar_ms
            end = start + BARS_PER_SEGMENT * bar_ms
            idx = [i for i, n in enumerate(midi_notes)
                   if start <= n["onset_ms"] < end]
            seg_notes = []
            for i in idx:
                n = dict(midi_notes[i])
                n["onset_ms"] -= start
                seg_notes.append(n)
            seg = {
                "id": f"{pslug}__s{k}",
                "piece": stem,
                "segment_index": k,
                "measures": [k * BARS_PER_SEGMENT + 1, (k + 1) * BARS_PER_SEGMENT],
                "bar_ms": bar_ms,
                "n_bars": BARS_PER_SEGMENT,
                "notes": seg_notes,
                "truth": {
                    "time_signature": ts,
                    "downbeats_ms": [b * bar_ms for b in range(BARS_PER_SEGMENT)],
                    "hand": [hands[i] for i in idx],
                },
            }
            out = os.path.join(OUT_DIR, seg["id"] + ".json")
            with open(out, "w") as f:
                json.dump(seg, f)
            labeled = sum(1 for h in seg["truth"]["hand"] if h != "?")
            manifest.append({
                "id": seg["id"], "piece": stem, "measures": seg["measures"],
                "n_notes": len(seg_notes), "n_labeled": labeled,
                "bar_ms": bar_ms, "time_signature": ts,
            })
            print(f"  {seg['id']}: {len(seg_notes)} notes ({labeled} labeled)")

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"ms_per_quarter": MS_PER_QUARTER,
                   "bars_per_segment": BARS_PER_SEGMENT,
                   "segments": manifest}, f, indent=1)
    print(f"\n{len(manifest)} segments -> {OUT_DIR}")


if __name__ == "__main__":
    main()
