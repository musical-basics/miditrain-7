"""
Grid search for Phase 2 downbeat weights.

Objective: pooled downbeat F1 (±50 ms) with strict-segment count as the
tiebreak. Phase 1 hands are computed once (they do not depend on Phase 2
parameters). Same caveat as tune_phase1: fit to the 4 source pieces, no
held-out split yet.

Usage: python3 tools/tune_phase2.py [--fine]
"""
import argparse
import glob
import itertools
import json
import multiprocessing as mp
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from phase1_hands import separate_hands                   # noqa: E402
from phase2_downbeat import infer_downbeats               # noqa: E402
from score_downbeat import match                          # noqa: E402

TOL = 50.0

COARSE = {
    "velocity_margin": [2, 4, 8],
    "w_velocity": [0.5, 1.0, 2.0],
    "w_harmony": [1.5, 3.0, 5.0],
    "harmony_min_dist": [0.2, 0.35, 0.5],
    "w_bass": [1.5, 3.0, 5.0],
    "w_agogic": [0.75, 1.5],
    "parsimony_margin": [1.05, 1.15],
}

FINE = {   # refined around the coarse winner — edit after the coarse run
    "velocity_margin": [1, 2, 3],
    "w_velocity": [1.0, 2.0, 3.0],
    "w_harmony": [4.0, 5.0, 7.0],
    "harmony_min_dist": [0.15, 0.2, 0.3],
    "w_bass": [1.0, 1.5, 2.0],
    "w_agogic": [0.5, 0.75, 1.0],
    "fold_tol_frac": [0.04, 0.06, 0.08],
}

SEGS = None


def _init():
    global SEGS
    SEGS = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "segments", "*.json"))):
        if p.endswith("manifest.json"):
            continue
        with open(p) as f:
            seg = json.load(f)
        hands = separate_hands(seg["notes"])
        SEGS.append((seg, hands))


def evaluate(overrides):
    tp = fp = fn = strict = 0
    for seg, hands in SEGS:
        res = infer_downbeats(seg["notes"], hands, overrides)
        a, b, c = match(res["downbeats_ms"], seg["truth"]["downbeats_ms"], TOL,
                        seg["n_bars"] * seg["bar_ms"])
        tp += a
        fp += b
        fn += c
        strict += (b == 0 and c == 0)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return overrides, round(f1, 4), strict, round(rec, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fine", action="store_true")
    args = ap.parse_args()
    grid = FINE if args.fine else COARSE

    keys = sorted(grid)
    configs = [dict(zip(keys, vals))
               for vals in itertools.product(*(grid[k] for k in keys))]
    print(f"{len(configs)} configs over {keys}")

    with mp.Pool(initializer=_init) as pool:
        results = pool.map(evaluate, configs)

    results.sort(key=lambda r: (-r[1], -r[2]))
    print(f"\n{'F1':>7}  {'strict':>6}  {'recall':>7}  config")
    for ov, f1, strict, rec in results[:15]:
        print(f"{f1*100:6.1f}%  {strict:4d}/10  {rec*100:6.1f}%  {json.dumps(ov)}")
    _init()
    _, f1, strict, rec = evaluate({})
    print(f"\ncurrent PARAMS: F1 {f1*100:.1f}%, strict {strict}/10, recall {rec*100:.1f}%")


if __name__ == "__main__":
    main()
