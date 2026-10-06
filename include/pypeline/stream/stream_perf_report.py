"""Boundary throughput/latency reporting for stream_perf.PerfRecorder output.

Plain Python (no pypeline import). The testbench records cycles, beats and
bytes only; `derive_throughput` multiplies by a clock afterwards, so the same
measured run can be re-expressed at a different fmax without re-simulating.
Each phase entry holds one result per runner name (`labels`), e.g.
`phase["encrypt"]`; internal-tap analysis lives in stream_bottleneck.py.
"""

import csv


def derive_throughput(perf_raw, fmax_mhz, target_mhz, bus_bytes, labels):
    """Phase list with MHz-dependent columns added to each runner's
    cycle-domain result:

      throughput_bytes_per_cycle  the sustained (inter-packet period) rate,
                                  falling back to the whole-window rate for a
                                  single-packet phase (`throughput_basis` says
                                  which)
      line_rate_frac              that over the bus width
      gbps_at_fmax / gbps_at_target, window_gbps_at_fmax,
      steady_in_gbps_at_fmax      the same rates in Gb/s

    Only the INPUT-side steady rate is converted: the output-side one is a
    drain rate (see stream_perf.StreamMeter._steady_bytes_per_cycle).
    """
    phases = []
    for phase in perf_raw.get("phases", []):
        entry = {k: phase[k] for k in ("name", "packet_bytes", "num_packets") if k in phase}
        if "taps" in phase:
            entry["taps"] = phase["taps"]
        if phase.get("timed_out"):
            entry["timed_out"] = True
        for label in labels:
            res = phase.get(label)
            if not res:
                continue
            res = dict(res)
            bpc = res.get("bytes_per_cycle")
            steady_in = res.get("steady_in_bytes_per_cycle")
            rate = res.get("sustained_bytes_per_cycle") or bpc
            res["throughput_bytes_per_cycle"] = rate
            res["throughput_basis"] = (
                "sustained (inter-packet period)"
                if res.get("sustained_bytes_per_cycle")
                else "whole window (single packet)"
            )
            res["line_rate_frac"] = (rate / bus_bytes) if rate else None
            if rate and fmax_mhz:
                res["gbps_at_fmax"] = rate * 8 * fmax_mhz / 1000.0
            if rate and target_mhz:
                res["gbps_at_target"] = rate * 8 * target_mhz / 1000.0
            if bpc and fmax_mhz:
                res["window_gbps_at_fmax"] = bpc * 8 * fmax_mhz / 1000.0
            if steady_in and fmax_mhz:
                res["steady_in_gbps_at_fmax"] = steady_in * 8 * fmax_mhz / 1000.0
            entry[label] = res
        phases.append(entry)
    return phases


def summarize(phases, labels):
    """Flat per-phase/per-runner headline numbers plus each runner's peak
    whole-window and peak sustained rate across the sweep."""
    summary = {}
    for phase in phases:
        for label in labels:
            res = phase.get(label)
            if not res:
                continue
            summary[f"{phase['name']}_{label}"] = {
                "bytes_per_cycle": res.get("bytes_per_cycle"),
                "sustained_bytes_per_cycle": res.get("sustained_bytes_per_cycle"),
                "line_rate_frac": res.get("line_rate_frac"),
                "gbps_at_fmax": res.get("gbps_at_fmax"),
                "steady_in_bytes_per_cycle": res.get("steady_in_bytes_per_cycle"),
                "total_latency_med": res.get("latency_cycles", {}).get("total_med"),
            }
    for label in labels:
        rates = [p[label].get("bytes_per_cycle") or 0 for p in phases if p.get(label)]
        sustained = [
            p[label].get("throughput_bytes_per_cycle") or 0 for p in phases if p.get(label)
        ]
        summary[f"peak_bytes_per_cycle_{label}"] = max(rates) if rates else None
        summary[f"peak_sustained_bytes_per_cycle_{label}"] = (
            max(sustained) if sustained else None
        )
    return summary


CSV_COLUMNS = (
    "label", "phase", "packet_bytes", "num_packets", "stream",
    "window_cycles", "goodput_bytes", "in_beats", "out_beats",
    "bytes_per_cycle", "sustained_bytes_per_cycle", "packet_period_cycles",
    "steady_in_bytes_per_cycle", "steady_out_bytes_per_cycle", "line_rate_frac",
    "gbps_at_fmax", "gbps_at_target", "in_duty", "out_duty", "in_stall_frac",
    "cold_head_latency", "head_med", "total_med", "total_max", "timed_out",
)


def csv_rows(run_label, phases, labels):
    """One row per phase x runner, in CSV_COLUMNS order (the `stream`
    column holds the runner name)."""
    for phase in phases:
        for label in labels:
            res = phase.get(label)
            if not res:
                continue
            lat = res.get("latency_cycles", {})
            yield [
                run_label, phase["name"], phase["packet_bytes"], phase["num_packets"],
                label, res.get("window_cycles"), res.get("goodput_bytes"),
                res.get("in_beats"), res.get("out_beats"),
                res.get("bytes_per_cycle"),
                res.get("sustained_bytes_per_cycle"),
                res.get("packet_period_cycles"),
                res.get("steady_in_bytes_per_cycle"),
                res.get("steady_out_bytes_per_cycle"),
                res.get("line_rate_frac"), res.get("gbps_at_fmax"),
                res.get("gbps_at_target"), res.get("in_duty"), res.get("out_duty"),
                res.get("in_stall_frac"), lat.get("cold_head"), lat.get("head_med"),
                lat.get("total_med"), lat.get("total_max"),
                res.get("timed_out"),
            ]


def write_csv(path, columns, rows):
    """Write `columns` then `rows`; True if any row was written."""
    rows = list(rows)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    return bool(rows)


def fmt(value, spec=".3f"):
    return format(value, spec) if isinstance(value, (int, float)) else "-"


def markdown_boundary_table(phases, labels, fmax_mhz, target_mhz, label_header="stream"):
    """Throughput/latency table, one row per phase x runner. When fmax IS the
    target (e.g. a goal quoted as a lower bound), one Gb/s column instead of
    two identical ones."""
    same_mhz = bool(fmax_mhz and target_mhz and abs(fmax_mhz - target_mhz) < 1e-9)
    mhz_cols = f"Gb/s @{fmt(fmax_mhz, '.0f')} MHz |" if same_mhz else "Gb/s @fmax | Gb/s @target |"
    lines = [
        f"| phase | bytes | pkts | {label_header} | sustained B/cyc | pkt period (clk) | "
        "% line rate | " + mhz_cols + " in stall | cold head (clk) | total lat med (clk) |",
        "|---|---|---|---|---|---|---|---|---|---|---|" + ("" if same_mhz else "---|"),
    ]
    for phase in phases:
        for label in labels:
            res = phase.get(label)
            if not res:
                continue
            lat = res.get("latency_cycles", {})
            frac = res.get("line_rate_frac")
            gbps = f"| {fmt(res.get('gbps_at_fmax'))} "
            if not same_mhz:
                gbps += f"| {fmt(res.get('gbps_at_target'))} "
            lines.append(
                f"| {phase['name']} | {phase['packet_bytes']} | {phase['num_packets']} "
                f"| {label} | {fmt(res.get('throughput_bytes_per_cycle'))} "
                f"| {fmt(res.get('packet_period_cycles'), '.1f')} "
                f"| {fmt(frac * 100 if frac else None, '.1f')}% "
                + gbps
                + f"| {fmt(res.get('in_stall_frac'))} | {lat.get('cold_head')} "
                f"| {lat.get('total_med')} |"
            )
    return lines


def splice_markers(text, begin, end, body):
    """Replace whatever sits between two marker lines (e.g. HTML comments in a
    README) with `body`. None if either marker is missing."""
    if begin not in text or end not in text:
        return None
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    return head + f"{begin}\n\n{body}\n\n{end}" + tail
