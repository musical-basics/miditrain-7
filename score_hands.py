"""
Phase 1 scorer — hand separation vs segment truth.

Metrics (same definitions as miditrain-6's score_hands.py, the numbers
are comparable):
  overall     % notes on the correct hand
  per-hand    L / R accuracy
  crossover   accuracy inside the pitch band where both true hands are
              active — the band where pitch alone cannot decide; THE
              primary number
  switches    predicted-hand flips between consecutive notes of the same
              TRUE hand — the line-continuity failure mode

Baselines per segment: split@60 (fixed middle C) and the oracle fixed
split (best single threshold for THAT segment, chosen knowing the answer
— the ceiling for any pitch-only rule; beating it is the bar).

Notes whose truth hand is "?" (no MusicXML match) are excluded from every
denominator but are still fed to the algorithm.

Usage:
  python3 score_hands.py                # all segments, prediction = phase1
  python3 score_hands.py --json out.json
  python3 score_hands.py --pred-dir data/runs   # score saved predictions
"""
import argparse
import glob
import json
import os

from phase1_hands import separate_hands

HERE = os.path.dirname(os.path.abspath(__file__))
SEG_DIR = os.path.join(HERE, "data", "segments")


def crossover_band(notes, truth):
    rh = [n["pitch"] for n, h in zip(notes, truth) if h == "R"]
    lh = [n["pitch"] for n, h in zip(notes, truth) if h == "L"]
    if not rh or not lh:
        return None
    lo, hi = min(rh), max(lh)
    return (lo, hi) if lo <= hi else None


def fixed_split(notes, threshold):
    return ["R" if n["pitch"] >= threshold else "L" for n in notes]


def oracle_split(notes, truth):
    best = (-1.0, 60)
    for t in range(21, 109):
        acc = sum(1 for n, h in zip(notes, truth)
                  if h != "?" and ("R" if n["pitch"] >= t else "L") == h)
        if acc > best[0]:
            best = (acc, t)
    return best[1]


def score(notes, truth, pred):
    idx = [i for i, h in enumerate(truth) if h != "?"]
    n = len(idx)
    correct = sum(1 for i in idx if pred[i] == truth[i])
    per = {}
    for hand in ("R", "L"):
        hidx = [i for i in idx if truth[i] == hand]
        if hidx:
            c = sum(1 for i in hidx if pred[i] == hand)
            per[hand] = {"notes": len(hidx), "correct": c,
                         "accuracy": round(c / len(hidx), 4)}
    band = crossover_band(notes, truth)
    cross = None
    if band:
        lo, hi = band
        cidx = [i for i in idx if lo <= notes[i]["pitch"] <= hi]
        if cidx:
            c = sum(1 for i in cidx if pred[i] == truth[i])
            cross = {"band": [lo, hi], "notes": len(cidx), "correct": c,
                     "accuracy": round(c / len(cidx), 4)}
    flips = 0
    last = {}
    for i in idx:
        h = truth[i]
        if h in last and pred[last[h]] != pred[i]:
            flips += 1
        last[h] = i
    return {"total": n, "correct": correct,
            "accuracy": round(correct / n, 4) if n else None,
            "per_hand": per, "crossover": cross, "switches": flips}


def agg(results):
    """Pool raw counts across segments (not a mean of percentages)."""
    total = sum(r["total"] for r in results)
    correct = sum(r["correct"] for r in results)
    cn = sum(r["crossover"]["notes"] for r in results if r["crossover"])
    cc = sum(r["crossover"]["correct"] for r in results if r["crossover"])
    out = {"total": total, "correct": correct,
           "accuracy": round(correct / total, 4) if total else None,
           "crossover_notes": cn, "crossover_correct": cc,
           "crossover_accuracy": round(cc / cn, 4) if cn else None,
           "switches": sum(r["switches"] for r in results)}
    for hand in ("R", "L"):
        hn = sum(r["per_hand"][hand]["notes"] for r in results if hand in r["per_hand"])
        hc = sum(r["per_hand"][hand]["correct"] for r in results if hand in r["per_hand"])
        out[hand] = round(hc / hn, 4) if hn else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default=None, help="one segment id")
    ap.add_argument("--pred-dir", default=None,
                    help="score <id>.phase1.json files instead of running phase1")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(SEG_DIR, "*.json")))
    paths = [p for p in paths if not p.endswith("manifest.json")]
    if args.seg:
        paths = [p for p in paths if os.path.basename(p) == args.seg + ".json"]
    if not paths:
        raise SystemExit("no segments found — run tools/make_segments.py first")

    rows, by = {}, {"prediction": [], "split@60": [], "oracle*": []}
    for path in paths:
        with open(path) as f:
            seg = json.load(f)
        notes, truth = seg["notes"], seg["truth"]["hand"]
        if args.pred_dir:
            with open(os.path.join(args.pred_dir, seg["id"] + ".phase1.json")) as f:
                pred = json.load(f)["hand"]
        else:
            pred = separate_hands(notes)
        preds = {
            "prediction": pred,
            "split@60": fixed_split(notes, 60),
            "oracle*": fixed_split(notes, oracle_split(notes, truth)),
        }
        rows[seg["id"]] = {}
        for label, p in preds.items():
            r = score(notes, truth, p)
            rows[seg["id"]][label] = r
            by[label].append(r)

    def fmt(r):
        c = r["crossover"]
        cx = f"{c['accuracy']*100:5.1f}" if c else "  n/a"
        return (f"{r['accuracy']*100:5.1f}  cross {cx}  sw {r['switches']:3d}")

    print(f"{'segment':<28} {'prediction':<28} {'split@60':<28} {'oracle*':<28}")
    for sid, r in rows.items():
        print(f"{sid:<28} {fmt(r['prediction']):<28} {fmt(r['split@60']):<28} "
              f"{fmt(r['oracle*']):<28}")
    print()
    aggs = {label: agg(res) for label, res in by.items()}
    for label, a in aggs.items():
        print(f"{label:<12} overall {a['accuracy']*100:5.1f}%  "
              f"crossover {a['crossover_accuracy']*100:5.1f}%  "
              f"R {a['R']*100:5.1f}%  L {a['L']*100:5.1f}%  "
              f"switches {a['switches']}")
    print("\n* oracle = best fixed split per SEGMENT, chosen knowing the answer.")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"segments": rows, "aggregate": aggs}, f, indent=1)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
