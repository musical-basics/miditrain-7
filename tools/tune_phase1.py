"""
Grid search for Phase 1 hand-separation weights.

Objective: overall correct + crossover correct (crossover notes count
double — they are the primary metric per docs/architecture.md), summed
over all segments. Deterministic; ties break toward the earlier config.

CAVEAT (recorded in the session log too): with 4 pieces there is no
held-out split — the winner is fit to these pieces. Re-run when source/
grows.

Usage: python3 tools/tune_phase1.py [--fine]
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

from phase1_hands import PARAMS, separate_hands          # noqa: E402
from score_hands import agg, score                        # noqa: E402

COARSE = {
    "w_move": [0.02, 0.03, 0.05],
    "w_vel": [0.0, 0.001, 0.002, 0.004],
    "w_dur": [0.0, 0.25, 0.5, 1.0],
    "w_overlap": [0.5, 1.0, 2.0],
    "comfort_semitones": [3, 5],
    "tau_gap_ms": [500.0, 700.0],
}

FINE = {   # refined around the coarse winner (2026-08-14 run)
    "w_move": [0.015, 0.02, 0.03],
    "w_vel": [0.0015, 0.002, 0.003],
    "w_dur": [0.0, 0.1],
    "w_overlap": [2.0, 3.0],
    "comfort_semitones": [4, 5],
    "tau_gap_ms": [700.0, 900.0],
    "w_cross": [0.1, 0.15, 0.25],
    "ema_alpha": [0.5, 0.6],
}


def load_segments():
    segs = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "segments", "*.json"))):
        if p.endswith("manifest.json"):
            continue
        with open(p) as f:
            segs.append(json.load(f))
    return segs


SEGS = None


def _init():
    global SEGS
    SEGS = load_segments()


def evaluate(overrides):
    results = []
    for seg in SEGS:
        pred = separate_hands(seg["notes"], overrides)
        results.append(score(seg["notes"], seg["truth"]["hand"], pred))
    a = agg(results)
    objective = a["correct"] + a["crossover_correct"]
    return overrides, objective, a


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

    results.sort(key=lambda r: -r[1])
    print(f"\n{'objective':>9}  {'overall':>7}  {'cross':>6}  {'switches':>8}  config")
    for ov, obj, a in results[:15]:
        print(f"{obj:9d}  {a['accuracy']*100:6.1f}%  {a['crossover_accuracy']*100:5.1f}%  "
              f"{a['switches']:8d}  {json.dumps(ov)}")
    _init()
    _, base_obj, base = evaluate({})
    print(f"\ncurrent PARAMS: objective {base_obj}, overall {base['accuracy']*100:.1f}%, "
          f"cross {base['crossover_accuracy']*100:.1f}%, switches {base['switches']}")
    print(json.dumps({k: PARAMS[k] for k in keys}))


if __name__ == "__main__":
    main()
