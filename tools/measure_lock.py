"""
Streaming emulation: how long is the ambiguous opening?

Prefix replay — at each evaluation time t the engine sees ONLY what a
live listener would have: notes whose onset is < t, with durations capped
at t (a note still sounding has unknown length). Phase 1 hands and the
Phase 2 grid are re-inferred from scratch per prefix (no caching, no
peeking), exactly the whole-segment algorithms on a growing window.

Reported per segment:
  first correct   earliest t where the inferred grid (bar Δ<2%, every
                  projected downbeat within ±50 ms of truth over the
                  full segment span) is right
  locked at       earliest t after which the grid is right at EVERY
                  later evaluation — the end of the ambiguity; the
                  number the user asked for
  flips           hypothesis changes (bar or phase) after first-correct
  hands causal    note-level hand accuracy when each note is judged by
                  the first prefix that contains it (vs offline accuracy
                  with the whole segment)

Eval grid: every 250 ms to 12 s, then every 1 s to the segment end.
Writes data/runs/lock.json for the GUI / later analysis.

Usage: python3 tools/measure_lock.py
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
from score_downbeat import match                          # noqa: E402

TOL = 50.0


def eval_times(end_ms):
    ts = list(range(1000, min(12000, end_ms) + 1, 250))
    ts += list(range(13000, end_ms + 1, 1000))
    return ts


def prefix(notes, t):
    out = []
    for n in notes:
        if n["onset_ms"] < t:
            m = dict(n)
            m["duration_ms"] = min(n["duration_ms"], t - n["onset_ms"])
            out.append(m)
    return out


def grid_correct(res, seg):
    """Does this hypothesis, projected over the WHOLE segment, match truth?"""
    if not res["downbeats_ms"] or res["bar_ms"] is None:
        return False
    if abs(res["bar_ms"] - seg["bar_ms"]) / seg["bar_ms"] > 0.02:
        return False
    # project the hypothesis grid across the full segment span
    bar, phase = res["bar_ms"], res["bar_phase_ms"]
    end = seg["n_bars"] * seg["bar_ms"]
    t = phase % bar
    while t - bar >= -TOL:
        t -= bar
    pred = []
    while t < end - TOL:
        if t > -TOL:
            pred.append(t)
        t += bar
    tp, fp, fn = match(pred, seg["truth"]["downbeats_ms"], TOL, end)
    return fp == 0 and fn == 0


def run_segment(path):
    with open(path) as f:
        seg = json.load(f)
    notes = seg["notes"]
    end = seg["n_bars"] * seg["bar_ms"]

    # offline reference for the hands comparison
    offline_hands = separate_hands(notes)

    history = []          # (t, correct, bar_ms, phase)
    causal_hands = [None] * len(notes)
    for t in eval_times(end):
        pre = prefix(notes, t)
        if len(pre) < 4:
            history.append((t, False, None, None))
            continue
        hands = separate_hands(pre)
        for i in range(len(pre)):
            if causal_hands[i] is None:
                causal_hands[i] = hands[i]
        res = infer_downbeats(pre, hands)
        history.append((t, grid_correct(res, seg),
                        res["bar_ms"], res["bar_phase_ms"]))

    first = next((t for t, ok, *_ in history if ok), None)
    locked = None
    for idx in range(len(history)):
        if all(ok for _, ok, *_ in history[idx:]):
            locked = history[idx][0]
            break
    flips = 0
    if first is not None:
        started = False
        prev = None
        for t, ok, bar, ph in history:
            if t < first:
                continue
            state = (None if bar is None
                     else (round(bar / 50), None if ph is None else round(ph / 50)))
            if started and state != prev:
                flips += 1
            prev, started = state, True

    truth = seg["truth"]["hand"]
    idx = [i for i, h in enumerate(truth) if h != "?"]
    causal_acc = (sum(1 for i in idx if causal_hands[i] == truth[i]) / len(idx)
                  if idx else None)
    offline_acc = (sum(1 for i in idx if offline_hands[i] == truth[i]) / len(idx)
                   if idx else None)

    return {
        "id": seg["id"], "bar_ms": seg["bar_ms"],
        "first_correct_ms": first, "locked_ms": locked, "flips": flips,
        "hands_causal": round(causal_acc, 4) if causal_acc is not None else None,
        "hands_offline": round(offline_acc, 4) if offline_acc is not None else None,
        "history": [{"t": t, "ok": ok, "bar_ms": bar, "phase_ms": ph}
                    for t, ok, bar, ph in history],
    }


def main():
    paths = sorted(glob.glob(os.path.join(ROOT, "data", "segments", "*.json")))
    paths = [p for p in paths if not p.endswith("manifest.json")]
    with mp.Pool() as pool:
        rows = pool.map(run_segment, paths)

    print(f"{'segment':<46} {'first':>7} {'locked':>7} {'flips':>5} "
          f"{'causal':>7} {'offline':>8}")
    locked_vals = []
    for r in rows:
        f = "never" if r["first_correct_ms"] is None else f"{r['first_correct_ms']/1000:.2f}s"
        lk = "never" if r["locked_ms"] is None else f"{r['locked_ms']/1000:.2f}s"
        if r["locked_ms"] is not None:
            locked_vals.append(r["locked_ms"])
        print(f"{r['id']:<46} {f:>7} {lk:>7} {r['flips']:>5} "
              f"{r['hands_causal']*100:6.1f}% {r['hands_offline']*100:7.1f}%")
    if locked_vals:
        locked_vals.sort()
        med = locked_vals[len(locked_vals) // 2]
        print(f"\nlocked segments: {len(locked_vals)}/{len(rows)}   "
              f"median lock {med/1000:.2f}s   worst {max(locked_vals)/1000:.2f}s")
    out = os.path.join(ROOT, "data", "runs", "lock.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fjson:
        json.dump({"tol_ms": TOL, "segments": rows}, fjson, indent=1)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
