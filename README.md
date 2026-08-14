# miditrain-7

Clean-slate rewrite of the MidiTrain pipeline: raw MIDI → sheet music, for
live classical-piano transcription. Bottom-up rebuild on clean 16-bar piano
segments, one phase at a time, each verified in a GUI before the next is
trusted. See `docs/architecture.md` for the phase order and rationale.

```
Phase 0  ingest & 16-bar segmentation      tools/make_segments.py
Phase 1  hand separation (L/R per note)    phase1_hands.py
Phase 2  downbeat inference                phase2_downbeat.py
Phase 3+ quantize / voices / notation      (deferred)
```

## Quickstart

```bash
# one-time: venv with mido + music21 (needed for segmentation truth only)
python3 -m venv venv && ./venv/bin/pip install mido music21

# Phase 0: cut source/ pairs into data/segments/
./venv/bin/python3 tools/make_segments.py

# run all implemented phases over all segments + score them
python3 run_all.py            # pure stdlib from here on

# inspect results per segment/phase
./run_gui.sh                  # http://localhost:8137/gui/
```

Truth (`truth` block in each segment file) is for scorers and the GUI
only — phase code never reads it.
