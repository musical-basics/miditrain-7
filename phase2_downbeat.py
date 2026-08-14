"""
Phase 2 — Downbeat inference.

Input: raw notes + Phase 1 hand labels. Output: the bar grid — tactus
period, beats per bar, bar phase, and the projected downbeat times.
NOTHING is read from metadata; every signal is computed relative to the
notes themselves (live-transcription constraint).

This is a compact rebuild of miditrain-6's meter evidence bus (its
measured-best engine: bus 863 vs thermo 1147 vs spike 1694 val errors),
reordered per docs/architecture.md so it consumes HAND STREAMS instead of
raw keyframes. Channels vote, one joint (period, phase) argmax decides.

Channels (all vote {time, weight}):
  onset      every onset cluster, weighted by summed velocity — the
             Temperley event rule; defines the tactus
  bass       LEFT-hand cluster onsets, weighted by depth below the
             piece's running pitch center × duration — classical
             accompaniment puts the bass at the bar start; this is why
             hand separation runs FIRST
  chord      clusters weighted by simultaneous note count (block chords
             mark structural positions)
  agogic     notes longer than their local context (accent by duration)
  velocity   notes louder than their local context — measured PER HAND
             STREAM: an accent only means something relative to the same
             hand's own recent level (a loud LH chord next to a soft RH
             run is not an accent; a LH chord louder than the LH's other
             chords is). This is what disambiguates the half-bar phase
             flip on the Arabesque, whose texture is otherwise symmetric
  harmony    change of the sounding pitch-class set between consecutive
             clusters (Jaccard distance) — harmony changes at bar starts;
             miditrain-6's measured conclusion was that denser harmonic
             votes are THE fix for bar-level hierarchy errors (its bus
             locked to half-bars without them, and so did this engine)
  entry      the segment's first onset and each hand's first entrance —
             a phrase begins where a stream enters from silence. SCOPE
             DEBT: valid while segments are phrase-aligned with no pickup
             (the current corpus rule); a pickup measure must be able to
             out-vote it later, which is why it is a soft channel and not
             a constraint

Decision:
  1. Tactus: folded-mass search over log-spaced periods 240–1200 ms with
     a log-Gaussian prior around 600 ms (sigma in octaves — miditrain-6's
     corpus-searched shape), then ±3% fine refinement.
  2. Bar: grouping G ∈ {2,3,4} × phase k·P. LEVEL (which G) is chosen
     on the PERIODIC structural channels only, per-line normalized, with
     a bar-length prior and a parsimony margin; PHASE within the chosen
     level additionally counts the one-shot entry votes. Point evidence
     must never pick the level: a single vote divided by n_lines
     mechanically inflates longer bars (measured: the entry channel
     alone flipped a 2/4 and a 6/8 piece to doubled bars). A
     contrast-vs-other-beats score was tried and measured OUT (it
     punishes 4/4 for having a legitimately strong beat 3).
  3. Downbeats projected from (bar_ms, phase), then (period, phase)
     refined by least squares against the onset votes the grid captured
     (kills the ~0.4% tactus quantization drift that walked late bars
     out of tolerance on long 2/4 segments).

Pure stdlib. Library: infer_downbeats(notes, hands) -> dict.
CLI: python3 phase2_downbeat.py <segment.json> [out.json]  (runs Phase 1
inline for the hands).
"""
import json
import math
import sys

PARAMS = {
    "cluster_ms": 30,
    "min_period_ms": 240.0,
    "max_period_ms": 1200.0,
    "n_periods": 120,           # log-spaced coarse candidates
    "fine_steps": 24,           # ±3% refinement steps
    "tactus_prior_center_ms": 600.0,
    "tactus_prior_sigma_oct": 0.9,     # miditrain-6 corpus-searched value
    "fold_tol_frac": 0.06,      # vote counts if within this fraction of P
    # Grid-searched 2026-08-14 on the committed train/val split
    # (benchmarks/split.json): train F1 95.8 (10/12 strict), val F1 100
    # (8/8 strict). Key lever vs the first tune: parsimony 1.12 -> 1.3.
    "groupings": (2, 3, 4),
    "parsimony_margin": 1.3,    # larger G must beat G=2 by this factor
    "bar_prior_center_ms": 1900.0,     # miditrain-6 corpus-searched values
    "bar_prior_sigma_oct": 1.4,
    "w_onset": 1.0,
    "w_bass": 3.0,
    "w_chord": 1.5,
    "w_agogic": 0.75,
    "w_velocity": 0.5,
    "w_harmony": 3.0,
    "harmony_min_dist": 0.35,   # Jaccard distance below this = no vote
    "w_entry": 2.0,
    "agogic_ratio": 1.8,        # duration > ratio × local median = accent
    "velocity_margin": 2,       # velocity above the SAME HAND's local mean
    "local_window_ms": 3000.0,
}


def _clusters(notes, hands, cluster_ms):
    order = sorted(range(len(notes)), key=lambda i: notes[i]["onset_ms"])
    out = []
    for i in order:
        if out and notes[i]["onset_ms"] - out[-1]["t"] <= cluster_ms:
            out[-1]["idx"].append(i)
        else:
            out.append({"t": notes[i]["onset_ms"], "idx": [i]})
    for c in out:
        c["L"] = [i for i in c["idx"] if hands[i] == "L"]
    return out


def build_votes(notes, hands, p):
    """Per-channel vote lists [{t, w}]. Everything is relative/causal-ish:
    local context = a trailing window, no whole-piece statistics."""
    clusters = _clusters(notes, hands, p["cluster_ms"])
    votes = {"onset": [], "bass": [], "chord": [], "agogic": [],
             "velocity": [], "harmony": [], "entry": []}

    if clusters:
        votes["entry"].append({"t": clusters[0]["t"], "w": 1.0})
        for hand_name in ("L", "R"):
            for c in clusters:
                members = (c["L"] if hand_name == "L"
                           else [i for i in c["idx"] if hands[i] != "L"])
                if members:
                    if c["t"] != clusters[0]["t"]:
                        votes["entry"].append({"t": c["t"], "w": 1.0})
                    break

    # running pitch center for bass depth (EMA over cluster means)
    center = None
    win = []          # trailing (t, duration, velocity) for local context
    prev_pcs = None   # sounding pitch-class set at the previous cluster
    for c in clusters:
        t = c["t"]
        pitches = [notes[i]["pitch"] for i in c["idx"]]
        vels = [notes[i]["velocity"] for i in c["idx"]]
        durs = [notes[i]["duration_ms"] for i in c["idx"]]
        mean_pitch = sum(pitches) / len(pitches)
        center = mean_pitch if center is None else 0.15 * mean_pitch + 0.85 * center

        votes["onset"].append({"t": t, "w": sum(vels) / 127.0})

        if len(c["idx"]) >= 3:
            votes["chord"].append({"t": t, "w": float(len(c["idx"]))})

        if c["L"]:
            low = min(notes[i]["pitch"] for i in c["L"])
            depth = max(0.0, center - low) / 12.0          # octaves below center
            dur = max(notes[i]["duration_ms"] for i in c["L"])
            w = depth * (0.5 + min(dur, 2000) / 1000.0)
            if w > 0:
                votes["bass"].append({"t": t, "w": w})

        # harmonic change: sounding pitch-class set (this cluster's notes
        # plus everything still ringing) vs the previous cluster's
        pcs = set()
        for n in notes:
            if n["onset_ms"] <= t < n["onset_ms"] + n["duration_ms"] \
                    or n["onset_ms"] == t:
                pcs.add(n["pitch"] % 12)
        if prev_pcs:
            inter = len(pcs & prev_pcs)
            union = len(pcs | prev_pcs)
            dist = 1.0 - (inter / union if union else 1.0)
            if dist > p["harmony_min_dist"]:
                votes["harmony"].append({"t": t, "w": dist})
        prev_pcs = pcs

        # local context: trailing window, kept PER HAND — an accent is
        # only an accent relative to the same hand's own recent level
        hand_split = {"L": c["L"], "R": [i for i in c["idx"] if hands[i] != "L"]}
        for hand_name, idx in hand_split.items():
            if not idx:
                continue
            h_vel = max(notes[i]["velocity"] for i in idx)
            h_dur = max(notes[i]["duration_ms"] for i in idx)
            recent = [x for x in win
                      if t - x[0] <= p["local_window_ms"] and x[3] == hand_name]
            if recent:
                meds = sorted(x[1] for x in recent)
                med_dur = meds[len(meds) // 2]
                mean_vel = sum(x[2] for x in recent) / len(recent)
                if h_dur > p["agogic_ratio"] * med_dur:
                    votes["agogic"].append({"t": t, "w": h_dur / max(1.0, med_dur)})
                if h_vel > mean_vel + p["velocity_margin"]:
                    votes["velocity"].append({"t": t, "w": (h_vel - mean_vel) / 16.0})
            win.append((t, h_dur, h_vel, hand_name))
        win = [x for x in win if t - x[0] <= p["local_window_ms"]]

    # normalize each channel's total mass to 1 (miditrain-6's single
    # largest win: channel_norm), then apply channel weights
    for name, vs in votes.items():
        total = sum(v["w"] for v in vs)
        if total > 0:
            scale = p["w_" + name] / total
            for v in vs:
                v["w"] *= scale
    return votes


def _folded_best_phase(vote_list, period, tol):
    """Best phase and its folded mass for one period. Deterministic."""
    if not vote_list:
        return 0.0, 0.0
    events = sorted(((v["t"] % period, v["w"]) for v in vote_list))
    # circular sweep: window of width 2*tol
    n = len(events)
    ext = events + [(t + period, w) for t, w in events]
    best_mass, best_phase = 0.0, 0.0
    j = 0
    for i in range(n):
        t0 = ext[i][0]
        if j < i:
            j = i
        while j < i + n and ext[j][0] <= t0 + 2 * tol:
            j += 1
        mass = sum(w for _, w in ext[i:j])
        if mass > best_mass:
            best_mass = mass
            # mass-weighted mean phase, not the window edge (an edge-based
            # phase carries a constant +tol bias into every downbeat)
            best_phase = (sum(t * w for t, w in ext[i:j]) / mass) % period
    return best_phase, best_mass


def _tactus(votes, p):
    lo, hi = p["min_period_ms"], p["max_period_ms"]
    cands = [lo * (hi / lo) ** (k / (p["n_periods"] - 1))
             for k in range(p["n_periods"])]
    all_votes = [v for vs in votes.values() for v in vs]

    def prior(period):
        octs = math.log2(period / p["tactus_prior_center_ms"])
        return math.exp(-0.5 * (octs / p["tactus_prior_sigma_oct"]) ** 2)

    def score(period):
        tol = p["fold_tol_frac"] * period
        phase, mass = _folded_best_phase(all_votes, period, tol)
        # mass per grid line, so short periods don't win by having more lines
        return prior(period) * mass, phase

    best = max(((score(c), c) for c in cands), key=lambda x: x[0][0])
    (s, phase), period = best
    # fine refinement ±3%
    for k in range(p["fine_steps"] + 1):
        c = period * (0.97 + 0.06 * k / p["fine_steps"])
        (s2, ph2) = score(c)
        if s2 > s:
            s, phase, period = s2, ph2, c
    return period, phase


def _bar(votes, tactus_ms, tactus_phase, span_ms, p):
    periodic = (votes["bass"] + votes["chord"] + votes["agogic"]
                + votes["velocity"] + votes["harmony"])
    tol = p["fold_tol_frac"] * tactus_ms

    def bar_prior(bar):
        octs = math.log2(bar / p["bar_prior_center_ms"])
        return math.exp(-0.5 * (octs / p["bar_prior_sigma_oct"]) ** 2)

    def folded(vote_list, phase, bar):
        mass = 0.0
        for v in vote_list:
            d = (v["t"] - phase) % bar
            if d <= tol or bar - d <= tol:
                mass += v["w"]
        return mass

    # level: periodic evidence only, per-line normalized
    results = {}
    for g in p["groupings"]:
        bar = g * tactus_ms
        n_lines = max(1.0, span_ms / bar)
        best = (0.0, tactus_phase)
        for k in range(g):
            phase = (tactus_phase + k * tactus_ms) % bar
            per_line = folded(periodic, phase, bar) / n_lines * bar_prior(bar)
            if per_line > best[0]:
                best = (per_line, phase)
        results[g] = best
    base = results[2][0] or 1e-9
    g_win, (s_win, _) = 2, results[2]
    for g in p["groupings"]:
        if g == 2:
            continue
        if results[g][0] > p["parsimony_margin"] * base and results[g][0] > s_win:
            g_win, (s_win, _) = g, results[g]

    # phase within the level: periodic + one-shot entry votes, raw mass
    bar = g_win * tactus_ms
    phase_win, best_mass = tactus_phase, -1.0
    for k in range(g_win):
        phase = (tactus_phase + k * tactus_ms) % bar
        mass = folded(periodic + votes["entry"], phase, bar)
        if mass > best_mass:
            best_mass, phase_win = mass, phase
    return g_win, phase_win


def _refine_grid(bar_ms, phase, votes, span_ms, p):
    """Weighted least-squares fit of the downbeat grid to the votes it
    captures. The discrete period search quantizes at ~0.25%, which
    accumulates to real drift over 16 bars; the votes themselves hold the
    exact timing. Two iterations; correction bounded to ±1% per pass."""
    all_votes = sorted(((v["t"], v["w"]) for vs in votes.values() for v in vs))
    for _ in range(2):
        tol = p["fold_tol_frac"] * bar_ms / 2.0
        k_first = int((-(phase % bar_ms)) // bar_ms) - 1
        pts = []           # (k, mass-weighted mean time, weight)
        k = k_first
        while phase + k * bar_ms < span_ms + tol:
            center = phase + k * bar_ms
            wsum = tsum = 0.0
            for t, w in all_votes:
                if abs(t - center) <= tol:
                    wsum += w
                    tsum += t * w
            if wsum > 0:
                pts.append((k, tsum / wsum, wsum))
            k += 1
        if len(pts) < 3:
            return bar_ms, phase
        sw = sum(w for _, _, w in pts)
        mk = sum(k * w for k, _, w in pts) / sw
        mt = sum(t * w for _, t, w in pts) / sw
        num = sum(w * (k - mk) * (t - mt) for k, t, w in pts)
        den = sum(w * (k - mk) ** 2 for k, _, w in pts)
        if den <= 0:
            return bar_ms, phase
        b = num / den
        b = max(bar_ms * 0.99, min(bar_ms * 1.01, b))
        phase = mt - b * mk
        bar_ms = b
    return bar_ms, phase


def infer_downbeats(notes, hands, params=None):
    p = dict(PARAMS)
    if params:
        p.update(params)
    if not notes:
        return {"downbeats_ms": [], "bar_ms": None}
    votes = build_votes(notes, hands, p)
    tactus_ms, tactus_phase = _tactus(votes, p)
    span = max(n["onset_ms"] + n["duration_ms"] for n in notes)
    g, bar_phase = _bar(votes, tactus_ms, tactus_phase, span, p)
    bar_ms = g * tactus_ms
    bar_ms, bar_phase = _refine_grid(bar_ms, bar_phase, votes, span, p)

    first = bar_phase % bar_ms
    # walk back so the grid covers the segment from the top
    while first - bar_ms >= -1.0:
        first -= bar_ms
    # a downbeat is real if any onset lands at or after it (a chord ON the
    # final downbeat counts; empty bars beyond the music do not)
    last_onset = max(n["onset_ms"] for n in notes)
    downbeats = []
    t = first
    while t <= last_onset + 0.1 * bar_ms:
        if t > -0.5 * bar_ms:
            downbeats.append(round(t))
        t += bar_ms
    return {
        "tactus_ms": round(tactus_ms, 2),
        "beats_per_bar": g,
        "bar_ms": round(bar_ms, 2),
        "bar_phase_ms": round(bar_phase % bar_ms, 2),
        "downbeats_ms": downbeats,
        "votes": {k: len(v) for k, v in votes.items()},
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: phase2_downbeat.py <segment.json> [out.json]")
    from phase1_hands import separate_hands
    with open(sys.argv[1]) as f:
        seg = json.load(f)
    hands = separate_hands(seg["notes"])
    out = infer_downbeats(seg["notes"], hands)
    out["id"] = seg.get("id")
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w") as f:
            json.dump(out, f)
    else:
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
