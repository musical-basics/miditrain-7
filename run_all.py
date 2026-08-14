"""
Run every implemented phase over every segment and write the results +
scorecards that the GUI reads.

  data/runs/<id>.phase1.json   {"hand": [...]}
  data/runs/<id>.phase2.json   {"downbeats_ms": [...], "bar_ms": ..., ...}
  data/runs/report.json        per-segment + aggregate scores, both phases

Pure stdlib. Usage: python3 run_all.py
"""
import glob
import json
import os

from phase1_hands import separate_hands
from phase2_downbeat import infer_downbeats
from score_downbeat import match
from score_hands import agg, fixed_split, oracle_split, score

HERE = os.path.dirname(os.path.abspath(__file__))
SEG_DIR = os.path.join(HERE, "data", "segments")
RUN_DIR = os.path.join(HERE, "data", "runs")
TOL = 50.0


def main():
    os.makedirs(RUN_DIR, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(SEG_DIR, "*.json")))
    paths = [p for p in paths if not p.endswith("manifest.json")]

    report = {"tol_ms": TOL, "segments": {}}
    p1_results = {"prediction": [], "split@60": [], "oracle*": []}
    p2_tot = {"tp": 0, "fp": 0, "fn": 0, "strict": 0, "n": 0}

    for path in paths:
        with open(path) as f:
            seg = json.load(f)
        notes, truth = seg["notes"], seg["truth"]["hand"]

        hands = separate_hands(notes)
        with open(os.path.join(RUN_DIR, seg["id"] + ".phase1.json"), "w") as f:
            json.dump({"id": seg["id"], "hand": hands}, f)

        p2 = infer_downbeats(notes, hands)
        p2["id"] = seg["id"]
        with open(os.path.join(RUN_DIR, seg["id"] + ".phase2.json"), "w") as f:
            json.dump(p2, f)

        p1_scores = {}
        for label, pred in (
                ("prediction", hands),
                ("split@60", fixed_split(notes, 60)),
                ("oracle*", fixed_split(notes, oracle_split(notes, truth)))):
            r = score(notes, truth, pred)
            p1_scores[label] = r
            p1_results[label].append(r)

        coverage_end = seg["n_bars"] * seg["bar_ms"]
        tp, fp, fn = match(p2["downbeats_ms"], seg["truth"]["downbeats_ms"],
                           TOL, coverage_end)
        recall = tp / (tp + fn) if tp + fn else 0.0
        prec = tp / (tp + fp) if tp + fp else 0.0
        strict = fp == 0 and fn == 0
        p2_tot["tp"] += tp
        p2_tot["fp"] += fp
        p2_tot["fn"] += fn
        p2_tot["strict"] += strict
        p2_tot["n"] += 1

        report["segments"][seg["id"]] = {
            "phase1": p1_scores,
            "phase2": {"tp": tp, "fp": fp, "fn": fn,
                       "recall": round(recall, 4), "precision": round(prec, 4),
                       "strict": strict, "bar_ms": p2["bar_ms"],
                       "beats_per_bar": p2["beats_per_bar"],
                       "bar_phase_ms": p2["bar_phase_ms"],
                       "tactus_ms": p2["tactus_ms"]},
        }
        print(f"{seg['id']:<30} hands {p1_scores['prediction']['accuracy']*100:5.1f}%  "
              f"downbeats {recall*100:5.1f}%{' strict' if strict else ''}")

    recall = p2_tot["tp"] / (p2_tot["tp"] + p2_tot["fn"]) if p2_tot["tp"] + p2_tot["fn"] else 0.0
    prec = p2_tot["tp"] / (p2_tot["tp"] + p2_tot["fp"]) if p2_tot["tp"] + p2_tot["fp"] else 0.0
    report["aggregate"] = {
        "phase1": {label: agg(res) for label, res in p1_results.items()},
        "phase2": {"recall": round(recall, 4), "precision": round(prec, 4),
                   "strict": p2_tot["strict"], "n": p2_tot["n"]},
    }
    with open(os.path.join(RUN_DIR, "report.json"), "w") as f:
        json.dump(report, f, indent=1)

    a1 = report["aggregate"]["phase1"]["prediction"]
    print(f"\nPhase 1: {a1['accuracy']*100:.1f}% overall, "
          f"{a1['crossover_accuracy']*100:.1f}% crossover, {a1['switches']} switches")
    print(f"Phase 2: {recall*100:.1f}% recall, {prec*100:.1f}% precision, "
          f"strict {p2_tot['strict']}/{p2_tot['n']}")
    print(f"wrote {RUN_DIR}")


if __name__ == "__main__":
    main()
