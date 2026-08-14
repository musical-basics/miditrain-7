"""
Phase 1 — Hand separation (single-voice-per-hand model).

Raw notes in (onset_ms, duration_ms, pitch, velocity — NOTHING else),
hand in {"L", "R"} per note out. Deterministic beam search.

Model
-----
Notes are grouped into onset clusters (simultaneous strikes). Within a
cluster the hands do not interleave (no-crossing repertoire, see
docs/architecture.md), so every legal assignment of a cluster is a split
point: the lowest k notes to one hand, the rest to the other. A beam of
hypotheses is carried across clusters; each hypothesis tracks, per hand,
where it is (an exponentially smoothed pitch center), when it last
played, and which of its notes are still sounding.

Costs (per cluster, per hypothesis):
  movement   distance of the hand's new notes from its center, decayed by
             how long the hand has been idle (a resting hand repositions
             freely) — the line-continuity term, the discriminator the
             miditrain-6 measurements said pitch thresholds cannot express
  span       a hand's simultaneous reach beyond a 10th, including notes it
             is still holding
  crossing   left hand sounding above the right, scaled by how fresh the
             other hand's position is
  overlap    a new note while the hand's previous note still sounds —
             the single-voice-per-hand constraint (chords struck together
             are one cluster and exempt)
  articulation  mismatch between the group's velocity / duration and the
             hand's running profile. Each hand's stream has consistent
             articulation (soft staccato 16ths vs loud sustained chords),
             and it is a purely RELATIVE signal — measured on the
             Arabesque, where movement/span/crossing all tie at zero and
             articulation is the only thing separating the repeated A4s
             (R) from the chord under them (L)

The final labeling swaps L/R if needed so that L is the lower hand on
average (the beam itself is label-symmetric).

Pure stdlib. Library use: separate_hands(notes) -> ["L"|"R", ...].
CLI: python3 phase1_hands.py data/segments/<id>.json
"""
import json
import math
import sys

# Grid-searched over the 10 segments 2026-08-14 (tools/tune_phase1.py):
# 96.6% overall / 94.7% crossover / 87 switches. NOTE: fit to the 4 source
# pieces — no held-out split exists yet (docs/architecture.md).
PARAMS = {
    "cluster_ms": 30,        # strikes within this window = one cluster
    "beam_width": 48,
    "comfort_semitones": 5,  # movement inside this is free
    "span_semitones": 15,    # simultaneous reach (a 10th) before penalty
    "w_move": 0.015,         # per semitone^2 beyond comfort
    "w_span": 0.20,          # per semitone^2 beyond span
    "w_cross": 0.25,         # per semitone^2 of L-above-R overlap
    "w_overlap": 3.0,        # per second of within-hand sustain overlap
    "w_vel": 0.0015,         # per (velocity delta)^2 vs the hand's profile
    "w_dur": 0.0,            # per (log2 duration ratio)^2 — measured OUT (hurts)
    "ema_alpha": 0.5,        # center update weight toward the new notes
    "tau_gap_ms": 900.0,     # movement-cost decay time constant
}


def cluster_notes(notes, cluster_ms):
    """Group note indices into onset clusters, each sorted by pitch."""
    order = sorted(range(len(notes)), key=lambda i: (notes[i]["onset_ms"], notes[i]["pitch"]))
    clusters = []
    for i in order:
        if clusters and notes[i]["onset_ms"] - notes[clusters[-1][0]]["onset_ms"] <= cluster_ms:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    for c in clusters:
        c.sort(key=lambda i: notes[i]["pitch"])
    return clusters


class Hand:
    __slots__ = ("center", "last_time", "held", "vel", "ldur")

    def __init__(self, center=None, last_time=None, held=(), vel=None, ldur=None):
        self.center = center
        self.last_time = last_time
        self.held = held           # tuple of (pitch, end_ms) still sounding
        self.vel = vel             # EMA velocity of the hand's stream
        self.ldur = ldur           # EMA log2(duration) of the hand's stream

    def key(self, now):
        alive = tuple(p for p, e in self.held if e > now)
        c = None if self.center is None else round(self.center)
        v = None if self.vel is None else round(self.vel)
        d = None if self.ldur is None else round(self.ldur, 1)
        return (c, alive, v, d)


def _group_cost(hand, group, notes, now, p):
    """Cost of giving `group` (nonempty, pitch-sorted note indices) to `hand`."""
    pitches = [notes[i]["pitch"] for i in group]
    mean_pitch = sum(pitches) / len(pitches)
    cost = 0.0

    # movement + articulation mismatch, decayed by idle time
    if hand.center is not None:
        gap = max(0.0, now - hand.last_time)
        decay = p["tau_gap_ms"] / (p["tau_gap_ms"] + gap)
        d = abs(mean_pitch - hand.center)
        over = max(0.0, d - p["comfort_semitones"])
        cost += p["w_move"] * over * over * decay
        mean_vel = sum(notes[i]["velocity"] for i in group) / len(group)
        mean_ldur = sum(math.log2(max(1, notes[i]["duration_ms"]))
                        for i in group) / len(group)
        dv = mean_vel - hand.vel
        dd = mean_ldur - hand.ldur
        cost += (p["w_vel"] * dv * dv + p["w_dur"] * dd * dd) * decay

    # simultaneous reach: this cluster's notes plus anything still held
    alive = [q for q, e in hand.held if e > now]
    lo = min(pitches + alive)
    hi = max(pitches + alive)
    over = max(0.0, (hi - lo) - p["span_semitones"])
    cost += p["w_span"] * over * over

    # single-voice constraint: previous note still sounding under a new one
    if alive:
        end = max(e for q, e in hand.held if e > now)
        cost += p["w_overlap"] * (end - now) / 1000.0

    return cost, mean_pitch


def _advance(hand, group, notes, now, p):
    """Hand state after taking `group` at time `now` (EMA updates + held)."""
    a = p["ema_alpha"]
    mean = sum(notes[i]["pitch"] for i in group) / len(group)
    mean_vel = sum(notes[i]["velocity"] for i in group) / len(group)
    mean_ldur = sum(math.log2(max(1, notes[i]["duration_ms"]))
                    for i in group) / len(group)
    center = mean if hand.center is None else a * mean + (1 - a) * hand.center
    vel = mean_vel if hand.vel is None else a * mean_vel + (1 - a) * hand.vel
    ldur = mean_ldur if hand.ldur is None else a * mean_ldur + (1 - a) * hand.ldur
    held = tuple((q, e) for q, e in hand.held if e > now) + tuple(
        (notes[i]["pitch"], notes[i]["onset_ms"] + notes[i]["duration_ms"])
        for i in group)
    return Hand(center, now, held, vel, ldur)


def _cross_cost(lo_top, hi_bottom, p, freshness=1.0):
    """Penalty when the low hand sounds above the high hand."""
    over = lo_top - hi_bottom
    return p["w_cross"] * over * over * freshness if over > 0 else 0.0


def separate_hands(notes, params=None):
    p = dict(PARAMS)
    if params:
        p.update(params)
    if not notes:
        return []
    clusters = cluster_notes(notes, p["cluster_ms"])

    # A hypothesis: (cost, hand_lo, hand_hi, assignment tuple-chain)
    # hand_lo is the "low" hand (provisionally L); labels resolved at the end.
    beam = [(0.0, Hand(), Hand(), None)]

    for cluster in clusters:
        now = notes[cluster[0]]["onset_ms"]
        pitches = [notes[i]["pitch"] for i in cluster]
        ends = [notes[i]["onset_ms"] + notes[i]["duration_ms"] for i in cluster]
        candidates = []
        for cost0, lo, hi, chain in beam:
            for k in range(len(cluster) + 1):
                g_lo, g_hi = cluster[:k], cluster[k:]
                cost = cost0
                new_lo, new_hi = lo, hi

                if g_lo:
                    c, mean_lo = _group_cost(lo, g_lo, notes, now, p)
                    cost += c
                if g_hi:
                    c, mean_hi = _group_cost(hi, g_hi, notes, now, p)
                    cost += c

                # crossing: within the cluster, or against the other hand's center
                if g_lo and g_hi:
                    cost += _cross_cost(pitches[k - 1], pitches[k], p)
                elif g_lo and hi.center is not None:
                    gap = max(0.0, now - hi.last_time)
                    fresh = p["tau_gap_ms"] / (p["tau_gap_ms"] + gap)
                    cost += _cross_cost(pitches[-1], hi.center, p, fresh)
                elif g_hi and lo.center is not None:
                    gap = max(0.0, now - lo.last_time)
                    fresh = p["tau_gap_ms"] / (p["tau_gap_ms"] + gap)
                    cost += _cross_cost(lo.center, pitches[0], p, fresh)

                # state updates
                if g_lo:
                    new_lo = _advance(lo, g_lo, notes, now, p)
                if g_hi:
                    new_hi = _advance(hi, g_hi, notes, now, p)

                candidates.append((cost, new_lo, new_hi, (chain, k)))

        # dedup identical states, keep best cost, then prune to beam width
        best = {}
        for cand in candidates:
            sig = (cand[1].key(now), cand[2].key(now))
            if sig not in best or cand[0] < best[sig][0]:
                best[sig] = cand
        beam = sorted(best.values(), key=lambda c: c[0])[:p["beam_width"]]

    # unwind the winning chain
    _, _, _, chain = beam[0]
    splits = []
    while chain is not None:
        chain, k = chain
        splits.append(k)
    splits.reverse()

    hands = [None] * len(notes)
    for cluster, k in zip(clusters, splits):
        for j, i in enumerate(cluster):
            hands[i] = "L" if j < k else "R"

    # resolve labels: L is the lower hand on average
    lo_p = [notes[i]["pitch"] for i in range(len(notes)) if hands[i] == "L"]
    hi_p = [notes[i]["pitch"] for i in range(len(notes)) if hands[i] == "R"]
    if lo_p and hi_p and sum(lo_p) / len(lo_p) > sum(hi_p) / len(hi_p):
        hands = ["L" if h == "R" else "R" for h in hands]
    return hands


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: phase1_hands.py <segment.json> [out.json]")
    with open(sys.argv[1]) as f:
        seg = json.load(f)
    hands = separate_hands(seg["notes"])
    out = {"id": seg.get("id"), "hand": hands}
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w") as f:
            json.dump(out, f)
    else:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
