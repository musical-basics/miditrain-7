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
    "bar_prior_center_ms": [1000.0, 1400.0, 1900.0],
    "bar_prior_sigma_oct": [1.4, 2.2, 3.5],
    "parsimony_margin": [1.05, 1.15, 1.3],
    "w_harmony": [3.0, 5.0],
    "w_bass": [1.5, 3.0],
    "w_agogic": [0.75, 1.5],
    "velocity_margin": [2, 4],
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
VAL_IDS = None


def _init():
    global SEGS, VAL_IDS
    with open(os.path.join(ROOT, "benchmarks", "split.json")) as f:
        VAL_IDS = set(json.load(f)["val"])
    SEGS = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "segments", "*.json"))):
        if p.endswith("manifest.json"):
            continue
        with open(p) as f:
            seg = json.load(f)
        hands = separate_hands(seg["notes"])
        SEGS.append((seg, hands))


def evaluate(overrides, which="train"):
    tp = fp = fn = strict = n = 0
    for seg, hands in SEGS:
        in_val = seg["id"] in VAL_IDS
        if (which == "train") == in_val:
            continue
        res = infer_downbeats(seg["notes"], hands, overrides)
        a, b, c = match(res["downbeats_ms"], seg["truth"]["downbeats_ms"], TOL,
                        seg["n_bars"] * seg["bar_ms"])
        tp += a
        fp += b
        fn += c
        strict += (b == 0 and c == 0)
        n += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return overrides, round(f1, 4), strict, round(rec, 4), n


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
    _init()
    print(f"\n{'trainF1':>8} {'str':>5}  {'valF1':>7} {'str':>5}  config")
    for ov, f1, strict, rec, n in results[:12]:
        _, vf1, vstrict, vrec, vn = evaluate(ov, "val")
        print(f"{f1*100:7.1f}% {strict:3d}/{n}  {vf1*100:6.1f}% {vstrict:3d}/{vn}  "
              f"{json.dumps(ov)}")
    _, f1, strict, rec, n = evaluate({})
    _, vf1, vstrict, _, vn = evaluate({}, "val")
    print(f"\ncurrent PARAMS: train F1 {f1*100:.1f}% ({strict}/{n} strict), "
          f"val F1 {vf1*100:.1f}% ({vstrict}/{vn} strict)")


if __name__ == "__main__":
    main()
