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


def parse_xml(path, expand=True):
    """Truth: per-note hands + measure structure, offsets at 120 BPM ms.

    expand: whether to run expandRepeats. Some exports render repeats
    differently than music21 expands them, so main() tries both variants
    and keeps whichever aligns with the MIDI better.
    """
    score = converter.parse(path)
    has_repeats = bool(score.recurse().getElementsByClass("Repeat"))
    if expand and has_repeats:
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
    for i, m in enumerate(measures[1:], start=1):
        if m.timeSignature and m.timeSignature.ratioString != ts.ratioString:
            # keep the clean prefix instead of losing the piece — segments
            # are windows anyway, and a mid-piece cadenza/TS change just
            # ends the usable run
            print(f"  time signature changes at measure {m.number} "
                  f"({ts.ratioString} -> {m.timeSignature.ratioString}); "
                  f"keeping measures before it")
            measures = measures[:i]
            break

    # Pickup detection by OFFSET DELTA between the first measures — a
    # measure's own .duration is the span of its contained notes, which
    # is unreliable (the Waldstein's first FULL bar reports 0.5 ql).
    # A leading pickup is simply trimmed: segmentation starts at the
    # first full measure (downstream windows anchor on it), and the
    # pickup's notes fall outside every window.
    trimmed = 0
    while len(measures) > 1 and (float(measures[1].offset) - float(measures[0].offset)
                                 < bar_ql - 1e-6):
        measures.pop(0)
        trimmed += 1
    if trimmed:
        print(f"  pickup: trimmed {trimmed} leading partial measure(s), "
              f"starting at measure {measures[0].number}")

    downbeats_ms = [round(float(m.offset) * MS_PER_QUARTER) for m in measures]
    # Even-grid check is PER SEGMENT WINDOW (in main), not whole-piece: one
    # irregular bar (volta quirk, engraving error) should only invalidate
    # the windows containing it, not the piece.
    return truth_notes, downbeats_ms, bar_ms, ts.ratioString, has_repeats


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


def build_segments(stem, pslug, midi_notes, truth_notes, downbeats_ms,
                   bar_ms, ts):
    """All valid 16-bar segments for one (MIDI, truth-variant) pairing.
    Returns (segments, log_lines)."""
    hands, unmatched = label_hands(midi_notes, truth_notes)
    n_segments = len(downbeats_ms) // BARS_PER_SEGMENT
    segments, log = [], []
    log.append(f"{stem}: {len(midi_notes)} MIDI notes, {len(downbeats_ms)} bars, "
               f"{ts}, bar={bar_ms}ms -> {n_segments} windows "
               f"({unmatched} unmatched notes)")
    for k in range(n_segments):
            window = downbeats_ms[k * BARS_PER_SEGMENT:(k + 1) * BARS_PER_SEGMENT]
            # window anchors on its own first downbeat (an irregular bar
            # earlier in the piece shifts everything globally; the window
            # only needs to be internally even)
            start = window[0]
            end = start + BARS_PER_SEGMENT * bar_ms
            if [d - start for d in window] != [b * bar_ms for b in range(BARS_PER_SEGMENT)]:
                log.append(f"  SKIP segment {k}: uneven measure grid inside bars "
                           f"{k * BARS_PER_SEGMENT + 1}–{(k + 1) * BARS_PER_SEGMENT}")
                continue
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
            labeled = sum(1 for h in seg["truth"]["hand"] if h != "?")
            if not seg_notes or labeled / len(seg_notes) < 0.7:
                log.append(f"  SKIP segment {k}: only {labeled}/{len(seg_notes)} "
                           "notes truth-labeled (MIDI/XML desync?)")
                continue
            seg["_labeled"] = labeled
            segments.append(seg)
            log.append(f"  {seg['id']}: {len(seg_notes)} notes ({labeled} labeled)")
    return segments, log


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    stems = sorted(
        (os.path.splitext(f)[0], os.path.splitext(f)[1])
        for f in os.listdir(SRC_DIR) if f.endswith((".musicxml", ".mxl")))
    manifest = []
    for stem, ext in stems:
        xml = os.path.join(SRC_DIR, stem + ext)
        mid = os.path.join(SRC_DIR, stem + ".mid")
        if not os.path.exists(mid):
            print(f"SKIP {stem}: no matching .mid")
            continue
        midi_notes = parse_midi(mid)
        pslug = slug(stem)

        # Try repeat expansion both ways; keep whichever the MIDI agrees
        # with (more surviving segments, then more labeled notes). Some
        # exports take repeats differently than music21 expands them.
        variants = []
        for expand in (True, False):
            try:
                truth_notes, downbeats_ms, bar_ms, ts, has_repeats = \
                    parse_xml(xml, expand)
            except ValueError as e:
                if expand:
                    print(f"SKIP {stem}: {e}")
                break
            segs, log = build_segments(stem, pslug, midi_notes, truth_notes,
                                       downbeats_ms, bar_ms, ts)
            variants.append((len(segs), sum(s["_labeled"] for s in segs),
                             expand, segs, log))
            if not has_repeats:
                break
        if not variants:
            continue
        variants.sort(key=lambda v: (-v[0], -v[1]))
        n_segs, n_labeled, expand, segs, log = variants[0]
        for line in log:
            print(line)
        if len(variants) > 1:
            print(f"  repeats: kept {'expanded' if expand else 'UNEXPANDED'} "
                  f"variant ({n_segs} vs {variants[1][0]} segments)")
        for seg in segs:
            labeled = seg.pop("_labeled")
            out = os.path.join(OUT_DIR, seg["id"] + ".json")
            with open(out, "w") as f:
                json.dump(seg, f)
            manifest.append({
                "id": seg["id"], "piece": stem, "measures": seg["measures"],
                "n_notes": len(seg["notes"]), "n_labeled": labeled,
                "bar_ms": seg["bar_ms"],
                "time_signature": seg["truth"]["time_signature"],
            })

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"ms_per_quarter": MS_PER_QUARTER,
                   "bars_per_segment": BARS_PER_SEGMENT,
                   "segments": manifest}, f, indent=1)
    print(f"\n{len(manifest)} segments -> {OUT_DIR}")


if __name__ == "__main__":
    main()
