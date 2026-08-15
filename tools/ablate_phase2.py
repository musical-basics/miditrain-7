"""
Channel ablation for Phase 2 downbeat inference.

Answers "which evidence channels actually earn their seat?" two ways:
  drop-one   full engine minus one channel (its weight -> 0)
  build-up   onset only (tactus can still form; no structural evidence),
             then onset + one structural channel at a time

Scored over ALL segments: acceptable / exact-level counts (meter
equivalence) and pooled raw downbeat F1. Deterministic.

Usage: python3 tools/ablate_phase2.py
"""
import glob
import json
import multiprocessing as mp
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from phase1_hands import separate_hands                   # noqa: E402
from phase2_downbeat import infer_downbeats               # noqa: E402
from score_downbeat import level_verdict, match           # noqa: E402

TOL = 50.0
STRUCTURAL = ("harmony", "resolution", "bass", "chord", "agogic", "velocity", "entry")

CONFIGS = [("full", {}), ("- hr voter", {"w_hr": 0.0})]
for ch in STRUCTURAL:
    CONFIGS.append((f"- {ch}", {f"w_{ch}": 0.0}))
CONFIGS.append(("onset only", {f"w_{c}": 0.0 for c in STRUCTURAL}))
for ch in STRUCTURAL:
    ov = {f"w_{c}": 0.0 for c in STRUCTURAL if c != ch}
    CONFIGS.append((f"onset + {ch}", ov))

SEGS = None


def _init():
    global SEGS
    SEGS = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "segments", "*.json"))):
        if p.endswith("manifest.json"):
            continue
        with open(p) as f:
            seg = json.load(f)
        SEGS.append((seg, separate_hands(seg["notes"])))


def evaluate(item):
    label, overrides = item
    acc = ex = tp = fp = fn = 0
    wrongs = []
    for seg, hands in SEGS:
        res = infer_downbeats(seg["notes"], hands, overrides)
        a, b, c = match(res["downbeats_ms"], seg["truth"]["downbeats_ms"], TOL,
                        seg["n_bars"] * seg["bar_ms"])
        v = level_verdict(res["bar_ms"], seg["bar_ms"], a, b, c)
        acc += (v != "wrong")
        ex += (v == "exact")
        tp += a
        fp += b
        fn += c
        if v == "wrong":
            wrongs.append(seg["id"].replace("_1st_movement", "").replace(
                "_e_flat_major", "")[:34])
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return label, acc, ex, round(f1 * 100, 1), wrongs


def main():
    with mp.Pool(initializer=_init) as pool:
        results = pool.map(evaluate, CONFIGS)
    n = len(json.load(open(os.path.join(
        ROOT, "data", "segments", "manifest.json")))["segments"])
    print(f"{'config':<18} {'accept':>8} {'exact':>7} {'rawF1':>7}  wrong segments")
    for label, acc, ex, f1, wrongs in results:
        w = ", ".join(wrongs[:4]) + (" …" if len(wrongs) > 4 else "")
        print(f"{label:<18} {acc:>5}/{n} {ex:>4}/{n} {f1:>6.1f}%  {w}")


if __name__ == "__main__":
    main()
