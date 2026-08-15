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
from score_downbeat import level_verdict, match           # noqa: E402

TOL = 50.0

# Objective (2026-08-14, matches the user's metric): acceptable segments
# under meter equivalence first, exact-level second, pooled F1 third.
COARSE = {
    "w_par": [0.0, 1.0, 2.0],
    "cadence_boost": [1.0, 3.0, 6.0],
    "w_resolution": [1.5, 3.0],
    "w_hr": [1.0, 2.0],
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
    tp = fp = fn = acc = ex = n = 0
    for seg, hands in SEGS:
        in_val = seg["id"] in VAL_IDS
        if (which == "train") == in_val:
            continue
        res = infer_downbeats(seg["notes"], hands, overrides)
        a, b, c = match(res["downbeats_ms"], seg["truth"]["downbeats_ms"], TOL,
                        seg["n_bars"] * seg["bar_ms"])
        v = level_verdict(res["bar_ms"], seg["bar_ms"], a, b, c)
        tp += a
        fp += b
        fn += c
        acc += (v != "wrong")
        ex += (v == "exact")
        n += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return overrides, acc, ex, round(f1, 4), n


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

    results.sort(key=lambda r: (-r[1], -r[2], -r[3]))
    _init()
    print(f"\n{'train acc/ex':>13}  {'val acc/ex':>11}  {'trF1':>6}  config")
    for ov, acc, ex, f1, n in results[:12]:
        _, vacc, vex, vf1, vn = evaluate(ov, "val")
        print(f"{acc:6d},{ex:3d}/{n}  {vacc:4d},{vex:3d}/{vn}  {f1*100:5.1f}%  "
              f"{json.dumps(ov)}")
    _, acc, ex, f1, n = evaluate({})
    _, vacc, vex, vf1, vn = evaluate({}, "val")
    print(f"\ncurrent PARAMS: train {acc},{ex}/{n} acceptable,exact; "
          f"val {vacc},{vex}/{vn}")


if __name__ == "__main__":
    main()
