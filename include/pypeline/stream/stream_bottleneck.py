"""Turns raw internal taps (stream_perf.py, fed by stream_perf_probe.py) into a
per-block throughput table and a named bottleneck, so "where is the time
going" is an output of a measurement rather than a reading exercise.

Plain Python (no pypeline import), so it also re-analyzes a saved results
JSON offline.

The design is described as a block graph: name -> spec, where

    consumes    the block's INPUT handshake tap (its own backpressure shows here)
    produces    its OUTPUT handshake tap (where it is in turn backpressured)
    downstream  tuple of block names consuming `produces` (a fork has several)
    state       optional FSM state tap naming *why* a block is slow
    what        one-line description for the reports

All tap names are relative; each phase is analyzed per label (the
`<label>/` prefix stream_perf_probe.MAIN_LABELS gives a MAIN's taps).

Derived per phase and label:

1. Per-block achieved throughput and in-situ ceiling. `service_period_cycles`
   (cycles per accepted beat while work was offered) is how fast the block
   could move data if never starved; `ceiling_bytes_per_cycle` is bytes/beat
   over that.
2. Relay-limited flag. A block whose own output is backpressured at least as
   hard as it backpressures its producer is (at least partly) relaying
   somebody else's stall, so its ceiling is only a LOWER bound.
3. A bottleneck verdict: the block that backpressures its producer hardest,
   walking downstream past blocks that merely relay, so the verdict names the
   origin rather than the nearest symptom.
"""

DEFAULT_TEXT = {
    # Column header / noun for the analysis label (a MAIN's label).
    "label_header": "label",
    "label_noun": "stream",
    "no_taps": "_No internal taps in this run._",
    "arbitration_intro": (
        "**Arbitration** — *resource not ready* means the selected request "
        "cannot launch (resource busy or its output backpressured); "
        "*contention* means another requester holds the slot and wants it; "
        "*wasted slot* means another requester holds an empty slot (zero for a "
        "request-aware arbiter):"
    ),
    "buffers_heading": (
        "**Buffers** (total storage capacity, including any output register):"
    ),
}

# Relay-limited: the block's own output stalled on more than this fraction of
# the window, and at least RELAY_RATIO times as often as its input stalled.
RELAY_MIN_OUT_STALL = 0.02
RELAY_RATIO = 0.9


def _text(text):
    merged = dict(DEFAULT_TEXT)
    merged.update(text or {})
    return merged


def block_spec(consumes, produces=None, downstream=(), state=None, what=""):
    """One block-graph entry (a plain dict, so a graph can also be written
    literally)."""
    return {
        "consumes": consumes,
        "produces": produces,
        "downstream": tuple(downstream),
        "state": state,
        "what": what,
    }


def get_tap(taps, label, name):
    return (taps or {}).get(f"{label}/{name}")


def _bytes_per_beat(tap, bus_bytes):
    if not tap:
        return None
    bpb = tap.get("bytes_per_beat")
    if bpb:
        return bpb
    return bus_bytes if tap.get("xfer_cycles") else None


def block_rollup(taps, label, blocks, bus_bytes=None):
    """Per-block achieved throughput, in-situ ceiling and stall split for one
    label. Blocks whose input tap did not fire are left out. `bus_bytes` is
    the bytes-per-beat assumed for a handshake tap without byte accounting
    (None: no ceiling in bytes for those)."""
    out = {}
    for name, spec in blocks.items():
        tap_in = get_tap(taps, label, spec["consumes"])
        if not tap_in:
            continue
        tap_out = get_tap(taps, label, spec["produces"]) if spec.get("produces") else None
        state = get_tap(taps, label, spec["state"]) if spec.get("state") else None
        period = tap_in.get("service_period_cycles")
        per_beat = _bytes_per_beat(tap_in, bus_bytes)
        entry = {
            "what": spec.get("what"),
            "in_tap": spec["consumes"],
            "cycles": tap_in.get("cycles"),
            "beats": tap_in.get("xfer_cycles"),
            # What it actually moved, over the whole phase window.
            "bytes_per_cycle": tap_in.get("bytes_per_cycle"),
            # What it could move if never starved: bytes/beat over cycles/beat
            # measured only across the cycles work was being offered to it.
            "ceiling_bytes_per_cycle": (
                (per_beat / period) if (per_beat and period) else None
            ),
            "service_period_cycles": period,
            "accept_rate": tap_in.get("accept_rate"),
            # Stall = this block backpressuring its producer (its own slowness).
            # Starve = this block waiting on its producer (somebody else's).
            "in_stall_frac": tap_in.get("stall_frac"),
            "in_starve_frac": tap_in.get("starve_frac"),
            "out_stall_frac": tap_out.get("stall_frac") if tap_out else None,
        }
        # Relay-limited: the block's own consumer pushed back on it at least as
        # hard as the block pushed back on its producer. Its input stalls are
        # then (at least partly) somebody else's, so its service period only
        # bounds its true speed from above and the ceiling is a LOWER bound.
        out_stall = entry["out_stall_frac"] or 0.0
        in_stall = entry["in_stall_frac"] or 0.0
        entry["relay_limited"] = bool(
            tap_out and out_stall > RELAY_MIN_OUT_STALL and out_stall >= in_stall * RELAY_RATIO
        )
        if state:
            entry["dominant_state"] = state.get("dominant")
            entry["state_fracs"] = {
                k: v["frac"] for k, v in (state.get("states") or {}).items()
            }
        out[name] = entry
    return out


def find_bottleneck(rollup, blocks):
    """Name the block whose own slowness limits the label.

    Ranked by how much of the phase it spent backpressuring its producer. A
    block that is itself backpressured at least as hard on its output is only
    relaying, so the walk continues downstream (toward whichever consumer is
    stalling hardest) to the block actually causing it.
    """
    if not rollup:
        return None
    ranked = sorted(
        rollup.items(),
        key=lambda kv: (kv[1].get("in_stall_frac") or 0.0),
        reverse=True,
    )
    name, entry = ranked[0]
    seen = set()
    while True:
        seen.add(name)
        out_stall = entry.get("out_stall_frac") or 0.0
        in_stall = entry.get("in_stall_frac") or 0.0
        candidates = [
            n
            for n in blocks.get(name, {}).get("downstream", ())
            if n in rollup and n not in seen
        ]
        if candidates and out_stall >= in_stall * RELAY_RATIO:
            nxt = max(candidates, key=lambda n: rollup[n].get("in_stall_frac") or 0.0)
            name, entry = nxt, rollup[nxt]
            continue
        break
    runner_up = next(((n, e) for n, e in ranked if n != name), None)
    verdict = {
        "block": name,
        "what": entry.get("what"),
        "in_stall_frac": entry.get("in_stall_frac"),
        "in_starve_frac": entry.get("in_starve_frac"),
        "service_period_cycles": entry.get("service_period_cycles"),
        "ceiling_bytes_per_cycle": entry.get("ceiling_bytes_per_cycle"),
        "dominant_state": entry.get("dominant_state"),
    }
    if runner_up:
        verdict["runner_up"] = {
            "block": runner_up[0],
            "in_stall_frac": runner_up[1].get("in_stall_frac"),
            "in_starve_frac": runner_up[1].get("in_starve_frac"),
        }
    verdict["evidence"] = _evidence_line(name, entry, runner_up)
    return verdict


def pct(value):
    return "-" if value is None else f"{value * 100:.0f}%"


def num(value, spec=".2f"):
    return "-" if not isinstance(value, (int, float)) else format(value, spec)


def _evidence_line(name, entry, runner_up):
    parts = [
        f"{name} backpressured its producer {pct(entry.get('in_stall_frac'))} of the "
        f"phase (accept rate {num(entry.get('accept_rate'), '.3f')}, "
        f"{num(entry.get('service_period_cycles'))} cyc/beat while offered work, "
        f"ceiling {num(entry.get('ceiling_bytes_per_cycle'))} B/cyc)"
    ]
    fracs = entry.get("state_fracs") or {}
    if fracs:
        # Top two states, not just the dominant one: a block's second state is
        # often the part of its stall that is not its main compute wait.
        top = sorted(fracs.items(), key=lambda kv: kv[1], reverse=True)[:2]
        shown = [f"{n} {pct(f)}" for n, f in top if f >= 0.10] or [
            f"{top[0][0]} {pct(top[0][1])}"
        ]
        parts.append(f"its FSM sat in {', '.join(shown)} of cycles")
    if runner_up:
        parts.append(
            f"next-worst {runner_up[0]} stalled {pct(runner_up[1].get('in_stall_frac'))} "
            f"but was itself starved {pct(runner_up[1].get('in_starve_frac'))}"
        )
    return "; ".join(parts)


def check_taps(taps):
    """Every probe fires exactly once per simulated cycle, so within a phase all
    taps must report the SAME cycle count.

    This guards the epoch de-duplication in stream_perf._EpochTap: a body
    declaring Feedback[T] re-executes until it converges, and if that buffering
    ever broke, the taps inside such a body would inflate while the ones
    outside it would not -- which shows up here as a spread, and would silently
    overstate every per-cycle rate.
    """
    counts = sorted({(t or {}).get("cycles") for t in taps.values()} - {None})
    if not counts:
        return None
    check = {"cycles": counts[0], "consistent": len(counts) == 1}
    if not check["consistent"]:
        check["cycles_seen"] = counts
        check["disagreeing_taps"] = sorted(
            name
            for name, t in taps.items()
            if (t or {}).get("cycles") not in (None, counts[0])
        )
    return check


def analyze_phase(phase, blocks, labels, bus_bytes=None):
    """Add `taps_check`, `blocks`, `bottleneck` and `arbitration` to one phase
    dict (a stream_perf.PerfRecorder phase entry), in place.

    A label whose blocks moved no beats (e.g. a disabled direction whose
    probes still fired) is dropped rather than given a meaningless verdict.
    """
    taps = phase.get("taps")
    if not taps:
        return phase
    check = check_taps(taps)
    if check:
        phase["taps_check"] = check
    rollups, verdicts = {}, {}
    for label in labels:
        rollup = block_rollup(taps, label, blocks, bus_bytes)
        if not rollup or not any(entry.get("beats") for entry in rollup.values()):
            continue
        rollups[label] = rollup
        verdict = find_bottleneck(rollup, blocks)
        if verdict:
            verdicts[label] = verdict
    arb = {k: v for k, v in taps.items() if (v or {}).get("kind") == "arb"}
    if rollups:
        phase["blocks"] = rollups
    if verdicts:
        phase["bottleneck"] = verdicts
    if arb:
        phase["arbitration"] = arb
    return phase


def analyze(phases, blocks, labels, bus_bytes=None):
    for phase in phases:
        analyze_phase(phase, blocks, labels, bus_bytes)
    return phases


def best_ceiling(phases, label, block):
    """(ceiling B/cyc, phase, exact?) for one block across a whole sweep.

    Contamination only ever ADDS stall cycles to a block's input, so a service
    period is an upper bound on the block's true period. For a block that is not
    relay-limited the largest packet size is the cleanest reading; for a
    relay-limited one the best (highest) observation is the tightest lower bound.
    """
    rows = []
    for phase in phases:
        entry = ((phase.get("blocks") or {}).get(label) or {}).get(block)
        if entry and entry.get("ceiling_bytes_per_cycle"):
            rows.append((phase, entry))
    if not rows:
        return None
    phase, entry = max(rows, key=lambda r: r[0].get("packet_bytes") or 0)
    if not entry.get("relay_limited"):
        return entry["ceiling_bytes_per_cycle"], phase, True
    phase, entry = max(rows, key=lambda r: r[1]["ceiling_bytes_per_cycle"])
    return entry["ceiling_bytes_per_cycle"], phase, False


def headline(phases, labels, compare, names=None):
    """One generated sentence per label comparing two blocks' ceilings: which
    is slower, by how much, and how close the whole datapath runs to the slower
    one's ceiling (from the boundary result `phase[label]`'s
    `sustained_bytes_per_cycle`). `compare` is a pair of block names, `names`
    optional display names for them."""
    names = names or {}
    a_block, b_block = compare
    a_name, b_name = names.get(a_block, a_block), names.get(b_block, b_block)
    out = []
    for label in labels:
        a = best_ceiling(phases, label, a_block)
        b = best_ceiling(phases, label, b_block)
        if not (a and b):
            continue
        (a_val, a_phase, a_exact), (b_val, b_phase, b_exact) = a, b
        slower = b_name if b_val < a_val else a_name
        s_val, s_phase = (b_val, b_phase) if slower == b_name else (a_val, a_phase)
        ratio = max(a_val, b_val) / min(a_val, b_val)
        at_least = "at least " if not (a_exact and b_exact) else ""
        text = (
            f"- **{label}**: {a_name} serves **{'' if a_exact else '≥'}"
            f"{num(a_val)} B/cyc** when fed (@{a_phase['packet_bytes']} B), "
            f"{b_name} **{'' if b_exact else '≥'}{num(b_val)} B/cyc** "
            f"(@{b_phase['packet_bytes']} B) — {slower} is the slower block by "
            f"{at_least}**{num(ratio, '.1f')}x**"
        )
        achieved = (s_phase.get(label) or {}).get("sustained_bytes_per_cycle")
        if achieved:
            text += (
                f"; at {s_phase['packet_bytes']} B the whole datapath delivers "
                f"{num(achieved)} B/cyc, **{pct(achieved / s_val)} of "
                f"{slower}'s ceiling**"
            )
        out.append(text + ".")
    if not out:
        return []
    return [
        "**Headline.** A block that is not relay-limited is quoted at the largest "
        "packet size (least per-packet overhead); a relay-limited one (its own "
        "output backpressured, so its in-situ ceiling is only a lower bound, "
        "marked ≥) is quoted at its best observation across the sweep:",
        "",
    ] + out


def bottleneck_tally(phases, labels):
    """({block: ["<label> @ <bytes> B", ...]}, total verdicts) across a sweep."""
    verdicts = {}
    total = 0
    for phase in phases:
        for label in labels:
            verdict = (phase.get("bottleneck") or {}).get(label)
            if verdict:
                verdicts.setdefault(verdict["block"], []).append(
                    f"{label} @ {phase['packet_bytes']} B"
                )
                total += 1
    return verdicts, total


def blocked_frac(per):
    """Share of a requester's wanted cycles spent on its own slot with the
    shared resource not ready. Derived from the partition identity when an
    older snapshot has no blocked_cycles field."""
    req = per.get("req_cycles") or 0
    if not req:
        return None
    blocked = per.get("blocked_cycles")
    if blocked is None:
        blocked = (
            req - per["xfer_cycles"] - per["contention_cycles"]
            - per["wasted_slot_cycles"]
        )
    return blocked / req


# --- CSV rows ---------------------------------------------------------------
BLOCK_CSV_COLUMNS = (
    "label", "phase", "packet_bytes", "main_label", "block",
    "cycles", "beats", "bytes_per_cycle", "ceiling_bytes_per_cycle",
    "service_period_cycles", "accept_rate", "in_stall_frac", "in_starve_frac",
    "out_stall_frac", "dominant_state",
)


def block_rows(run_label, phases):
    for phase in phases:
        for label, rollup in (phase.get("blocks") or {}).items():
            for name, e in rollup.items():
                yield [
                    run_label, phase["name"], phase["packet_bytes"], label, name,
                    e.get("cycles"), e.get("beats"), e.get("bytes_per_cycle"),
                    e.get("ceiling_bytes_per_cycle"), e.get("service_period_cycles"),
                    e.get("accept_rate"), e.get("in_stall_frac"),
                    e.get("in_starve_frac"), e.get("out_stall_frac"),
                    e.get("dominant_state"),
                ]


TAP_CSV_COLUMNS = (
    "label", "phase", "packet_bytes", "tap", "kind", "cycles", "xfer_cycles",
    "stall_cycles", "starved_cycles", "idle_cycles", "accept_rate",
    "service_period_cycles", "beats_per_cycle", "bytes_per_cycle",
    "stall_frac", "starve_frac", "dominant_state",
    "capacity_beats", "high_water_beats", "start_occupancy", "end_occupancy",
    "accepted_beats", "retired_beats", "simultaneous_cycles",
)


def tap_rows(run_label, phases):
    for phase in phases:
        for name, tap in sorted((phase.get("taps") or {}).items()):
            if not tap:
                continue
            yield [
                run_label, phase["name"], phase["packet_bytes"], name, tap.get("kind"),
                tap.get("cycles"), tap.get("xfer_cycles"), tap.get("stall_cycles"),
                tap.get("starved_cycles"), tap.get("idle_cycles"),
                tap.get("accept_rate"), tap.get("service_period_cycles"),
                tap.get("beats_per_cycle"), tap.get("bytes_per_cycle"),
                tap.get("stall_frac"), tap.get("starve_frac"), tap.get("dominant"),
                tap.get("capacity_beats"), tap.get("high_water_beats"),
                tap.get("start_occupancy"), tap.get("end_occupancy"),
                tap.get("accepted_beats"), tap.get("retired_beats"),
                tap.get("simultaneous_cycles"),
            ]


# --- markdown ---------------------------------------------------------------
def markdown_block_table(phases, labels, blocks, text=None):
    """Per-phase, per-label, per-block table (block-graph order), plus the
    note explaining ≥ ceilings."""
    t = _text(text)
    lines = [
        f"| phase | bytes | {t['label_header']} | block | B/cyc | ceiling B/cyc "
        "| svc period (clk) | in stall | in starved | dominant FSM state |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for phase in phases:
        for label in labels:
            rollup = (phase.get("blocks") or {}).get(label)
            if not rollup:
                continue
            for name in [b for b in blocks if b in rollup]:
                e = rollup[name]
                state = e.get("dominant_state") or "-"
                frac = (e.get("state_fracs") or {}).get(e.get("dominant_state"))
                if frac is not None:
                    state = f"{state} ({pct(frac)})"
                lines.append(
                    f"| {phase['name']} | {phase['packet_bytes']} | {label} "
                    f"| {name} | {num(e.get('bytes_per_cycle'), '.3f')} "
                    f"| {'≥' if e.get('relay_limited') else ''}"
                    f"{num(e.get('ceiling_bytes_per_cycle'), '.3f')} "
                    f"| {num(e.get('service_period_cycles'))} "
                    f"| {pct(e.get('in_stall_frac'))} "
                    f"| {pct(e.get('in_starve_frac'))} | {state} |"
                )
    lines.append("")
    lines.append(
        "`ceiling B/cyc` marked **≥** is a lower bound: that block's own output was "
        "backpressured at least as hard as its input, so part of its input stall "
        "is relayed from downstream rather than its own."
    )
    return lines


def markdown_bottleneck_table(phases, labels, text=None):
    t = _text(text)
    lines = [
        "**Bottleneck per phase** (the block whose own service rate limits "
        f"the {t['label_noun']}, after walking past blocks that only relay "
        "backpressure):",
        "",
        f"| phase | bytes | {t['label_header']} | bottleneck | why |",
        "|---|---|---|---|---|",
    ]
    for phase in phases:
        for label in labels:
            verdict = (phase.get("bottleneck") or {}).get(label)
            if not verdict:
                continue
            lines.append(
                f"| {phase['name']} | {phase['packet_bytes']} | {label} "
                f"| **{verdict['block']}** | {verdict['evidence']} |"
            )
    return lines


def markdown_arbitration(phases, text=None):
    """Per-resource, per-requester arbitration split; [] without arb taps."""
    t = _text(text)
    rows = []
    for phase in phases:
        for name, tap in sorted((phase.get("arbitration") or {}).items()):
            for label, per in (tap.get("per_requester") or {}).items():
                req = per.get("req_cycles")
                if not req:
                    continue
                rows.append(
                    f"| {phase['name']} | {phase['packet_bytes']} | {name} | {label} "
                    f"| {req} | {per['xfer_cycles']} "
                    f"| {pct(blocked_frac(per))} "
                    f"| {pct(per['contention_frac'])} "
                    f"| {pct(per['wasted_slot_frac'])} |"
                )
    if not rows:
        return []
    return [
        t["arbitration_intro"],
        "",
        f"| phase | bytes | resource | {t['label_header']} | wanted (clk) | launched (clk) "
        "| resource not ready | contention | wasted slot |",
        "|---|---|---|---|---|---|---|---|---|",
    ] + rows


def markdown_buffers(phases, text=None):
    """Occupancy table for every buffer tap; [] without any."""
    t = _text(text)
    buffers = [(phase, name, tap) for phase in phases
               for name, tap in (phase.get("taps") or {}).items()
               if (tap or {}).get("kind") == "buffer"]
    if not buffers:
        return []
    lines = [t["buffers_heading"], "",
             "| phase | buffer | capacity | high water | accepted | retired | simultaneous | end fill |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for phase, name, tap in buffers:
        lines.append(f"| {phase['name']} | {name} | {tap['capacity_beats']} | "
                     f"{tap['high_water_beats']} | {tap['accepted_beats']} | "
                     f"{tap['retired_beats']} | {tap['simultaneous_cycles']} | {tap['end_occupancy']} |")
    return lines


def markdown_blocks(phases, labels, blocks, compare=None, names=None,
                    extra_sections=(), text=None):
    """The full block report: optional headline (`compare` = two block names),
    the block table, bottleneck verdicts, arbitration, any design-specific
    `extra_sections` (lists of lines), then buffers."""
    t = _text(text)
    if not any(p.get("blocks") for p in phases):
        return t["no_taps"]
    lines = []
    if compare:
        head = headline(phases, labels, compare, names)
        if head:
            lines.extend(head)
            lines.append("")
    lines.extend(markdown_block_table(phases, labels, blocks, text))
    lines.append("")
    lines.extend(markdown_bottleneck_table(phases, labels, text))
    for section in [markdown_arbitration(phases, text)] + list(extra_sections):
        if section:
            lines.append("")
            lines.extend(section)
    buffers = markdown_buffers(phases, text)
    if buffers:
        lines.append("")
        lines.extend(buffers)
    return "\n".join(lines)


# --- buffer acceptance ------------------------------------------------------
def buffer_tap_errors(phase, buffers, taps_required=False, settled=True):
    """Consistency checks for a phase's buffer taps.

    `buffers` maps a buffer's full tap prefix (`<label>/<tap_name>`, whose taps
    are `.occupancy`, `.in`, `.out`) to its configured capacity in beats.
    Checks the measured capacity, no overflow, transfer conservation
    (start + accepted - retired == end), that occupancy agrees with the in/out
    handshake taps, and -- when the phase ended `settled` (fully drained) --
    that nothing was left buffered. A missing occupancy tap is an error only
    when `taps_required`.
    """
    errors = []
    taps = phase.get("taps") or {}
    for name, capacity in buffers.items():
        label = f"Phase {phase.get('name')}/{name}"
        counts = taps.get(name + ".occupancy")
        if counts is None:
            if taps_required:
                errors.append(label + ": enabled buffer occupancy tap missing")
            continue
        if counts.get("capacity_beats") != capacity:
            errors.append(label + ": measured and configured buffer capacities differ")
        if counts.get("high_water_beats", 0) > capacity:
            errors.append(label + ": buffer overflow")
        if counts.get("start_occupancy", 0) + counts.get("accepted_beats", 0) - counts.get(
                "retired_beats", 0) != counts.get("end_occupancy"):
            errors.append(label + ": buffer transfer conservation failed")
        if settled and counts.get("end_occupancy") != 0:
            errors.append(label + ": settled phase left buffered data")
        for suffix, field in (("in", "accepted_beats"), ("out", "retired_beats")):
            hs = taps.get(name + "." + suffix)
            if hs and hs.get("xfer_cycles") != counts.get(field):
                errors.append(label + ": occupancy disagrees with " + suffix + " transfers")
    return errors
