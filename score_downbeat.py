"""
Phase 2 scorer — inferred downbeats vs segment truth.

Matching: two-pointer one-to-one within ±tol (same discipline as
miditrain-6's corpus scorer, so numbers are comparable).

Reported per segment and pooled:
  recall      % of true downbeats returned — THE north-star number
              (target >= 98%, docs/architecture.md)
  precision   % of claimed downbeats that are real
  F1
  strict      segment counted only if every true downbeat matched and no
              false positives
  bar/beats   inferred bar length and grouping vs truth (truth bar is
              bar_ms; grouping truth is the time signature numerator)

Usage:
  python3 score_downbeat.py [--tol 50] [--json out.json]
"""
import argparse
import glob
import json
import os

from phase1_hands import separate_hands
from phase2_downbeat import infer_downbeats

HERE = os.path.dirname(os.path.abspath(__file__))
SEG_DIR = os.path.join(HERE, "data", "segments")


def level_verdict(pred_bar, truth_bar, tp, fp, fn):
    """Meter-equivalence classes (user decision 2026-08-14): notating a
    2/4 piece as 4/4, or a 12/8 piece as 6/8, is acceptable — the
    canonical target meters are 3/4, 4/4, 6/8.

      exact    right bar, every downbeat, no extras
      double   bar = 2x truth AND every claimed downbeat is a true one
               (2/4 read as 4/4 — every claim lands on a real downbeat)
      half     bar = truth/2 AND every true downbeat is claimed
               (12/8 read as 6/8 — extras are the true half-bars)
      wrong    anything else (e.g. 1.5x bars, misphased grids)
    """
    if not pred_bar or not truth_bar:
        return "wrong"
    r = pred_bar / truth_bar
    rec = tp / (tp + fn) if tp + fn else 0.0
    prec = tp / (tp + fp) if tp + fp else 0.0
    # "exact" is a LEVEL verdict: right bar, right phase, >=90% of
    # downbeats — a single sparse-bar miss is not a level failure (the
    # separate `strict` count still demands zero errors)
    if 0.98 < r < 1.02 and rec >= 0.9 and prec >= 0.9:
        return "exact"
    if 1.96 < r < 2.04 and fp == 0 and tp > 0:
        return "double"
    if 0.49 < r < 0.51 and fn == 0 and tp > 0:
        return "half"
    return "wrong"


def match(pred, truth, tol, coverage_end=None):
    """One-to-one two-pointer matching. Returns (tp, fp, fn).

    Predictions at/past `coverage_end` (the end of the truth's window,
    e.g. bar 17's downbeat at the edge of a 16-bar segment) are dropped:
    the truth cannot score them, so they are neither right nor wrong.
    """
    pred = sorted(pred)
    truth = sorted(truth)
    if coverage_end is not None:
        pred = [t for t in pred if t < coverage_end - tol]
    i = j = tp = 0
    while i < len(pred) and j < len(truth):
        d = pred[i] - truth[j]
        if abs(d) <= tol:
            tp += 1
            i += 1
            j += 1
        elif d < 0:
            i += 1
        else:
            j += 1
    return tp, len(pred) - tp, len(truth) - tp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=50.0)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(SEG_DIR, "*.json")))
    paths = [p for p in paths if not p.endswith("manifest.json")]
    rows = {}
    T = {"tp": 0, "fp": 0, "fn": 0, "strict": 0, "acceptable": 0, "n": 0}
    print(f"{'segment':<29} {'bar_ms':>7} {'beats':>5} {'phase':>6} "
          f"{'recall':>7} {'prec':>6} {'level':>7}")
    for path in paths:
        with open(path) as f:
            seg = json.load(f)
        hands = separate_hands(seg["notes"])
        res = infer_downbeats(seg["notes"], hands)
        coverage_end = seg["n_bars"] * seg["bar_ms"]
        tp, fp, fn = match(res["downbeats_ms"], seg["truth"]["downbeats_ms"],
                           args.tol, coverage_end)
        recall = tp / (tp + fn) if tp + fn else 0.0
        prec = tp / (tp + fp) if tp + fp else 0.0
        strict = fp == 0 and fn == 0
        level = level_verdict(res["bar_ms"], seg["bar_ms"], tp, fp, fn)
        T["tp"] += tp
        T["fp"] += fp
        T["fn"] += fn
        T["strict"] += strict
        T["acceptable"] += (level != "wrong")
        T["n"] += 1
        true_beats = int(seg["truth"]["time_signature"].split("/")[0])
        rows[seg["id"]] = {
            "bar_ms": res["bar_ms"], "beats_per_bar": res["beats_per_bar"],
            "bar_phase_ms": res["bar_phase_ms"], "tactus_ms": res["tactus_ms"],
            "tp": tp, "fp": fp, "fn": fn,
            "recall": round(recall, 4), "precision": round(prec, 4),
            "strict": strict, "level": level,
            "truth": {"bar_ms": seg["bar_ms"], "beats_per_bar": true_beats},
        }
        mark = {"exact": "  OK", "double": "  OK (as 2x)", "half": "  OK (as 1/2)",
                "wrong": "  XX"}[level]
        print(f"{seg['id']:<29} {res['bar_ms']:7.0f} {res['beats_per_bar']:>5} "
              f"{res['bar_phase_ms']:6.0f} {recall*100:6.1f}% {prec*100:5.1f}% "
              f"{level:>7}{mark}")

    recall = T["tp"] / (T["tp"] + T["fn"]) if T["tp"] + T["fn"] else 0.0
    prec = T["tp"] / (T["tp"] + T["fp"]) if T["tp"] + T["fp"] else 0.0
    f1 = 2 * prec * recall / (prec + recall) if prec + recall else 0.0
    print(f"\nacceptable segments {T['acceptable']}/{T['n']}  "
          f"(north star: level within the 2/4=4/4, 12/8=6/8 equivalence)   "
          f"exact {T['strict']}/{T['n']}")
    print(f"raw downbeat recall {recall*100:.1f}%   precision {prec*100:.1f}%   "
          f"F1 {f1*100:.1f}%")
    if args.json:
        agg = {"recall": round(recall, 4), "precision": round(prec, 4),
               "f1": round(f1, 4), "strict": T["strict"],
               "acceptable": T["acceptable"], "n": T["n"],
               "tol_ms": args.tol}
        with open(args.json, "w") as f:
            json.dump({"segments": rows, "aggregate": agg}, f, indent=1)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
