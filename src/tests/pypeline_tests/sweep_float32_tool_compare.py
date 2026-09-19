#!/usr/bin/env python3
"""Opt-in cross-SYN_TOOL comparison for the float32 adder sweep.

Builds inst/sweep_float32_test.py -- one part-neutral float32 adder @MAIN --
once per synthesis backend, then overlays every backend's sweep iterations on
one plot: **total pipeline latency on X, achieved fmax on Y**.

Each point is one sweep iteration, i.e. one real synthesis run: the planner
added cuts, the tool reported an fmax, and the pair (stages, fmax) says what
that trade bought. Total latency is the wall-clock time a value spends in the
pipeline, stages / fmax, which is the number that actually matters to a
caller -- more stages only helps if fmax rises faster than the stage count.

Deliberately outside run_all.py: this rebuilds on every backend, and the
full-PnR tools (Quartus, open tools, Efinity, CologneChip) place-and-route
every uncached leaf. run_all's synth_<tool> categories already prove each
backend builds; this is for looking at how they compare.

  python3 sweep_float32_tool_compare.py --out_root /media/1TB/tmp/f32cmp
  python3 sweep_float32_tool_compare.py --out_root DIR --tool quartus --tool vivado
  python3 sweep_float32_tool_compare.py --out_root DIR --no_build   # replot only
"""

import argparse
import json
import re
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPELINEC = REPO_ROOT / "src" / "pypelinec"
DESIGN = Path(__file__).resolve().parent / "inst" / "sweep_float32_test.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SYN_TOOLS  # noqa: E402
from synth_tests import SWEEP_FLOAT32_MHZ  # noqa: E402


def build(tool, out_dir, goal_mhz, timeout, comb=False):
    """Run one backend's build. Returns (ok, log_path).

    comb=True is the unpipelined reference point: one synthesis run reporting
    the design's combinational fmax, which is where every sweep starts from.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / ("comb.log" if comb else "build.log")
    cmd = [
        sys.executable, str(PYPELINEC), str(DESIGN),
        "--syn_tool", tool,
        "--out_dir", str(out_dir / ("comb_o" if comb else "o")),
    ]
    if comb:
        cmd.append("--comb")
    env = dict(
        os.environ,
        SWEEP_FLOAT32_MHZ=str(goal_mhz),
        PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG="1",
    )
    what = "comb" if comb else f"sweep goal {goal_mhz} MHz"
    print(f"[{tool}] {what} -> {log_path}", flush=True)
    with open(log_path, "w") as f:
        try:
            rc = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, env=env,
                                 timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"[{tool}] TIMEOUT after {timeout}s", flush=True)
            return False, log_path
    print(f"[{tool}] exit {rc}", flush=True)
    return rc == 0, log_path


# SYN prints this once the part and tool are settled (SYN.RESOLVE_PART_AND_TOOL).
PART_RE = re.compile(r"^Using \S+ synthesizing for part: (\S+)\s*$", re.M)


def collect_part(build_dir_log):
    """The part a build actually used, straight from its log."""
    try:
        text = build_dir_log.read_text(errors="replace")
    except OSError:
        return None
    found = PART_RE.findall(text)
    if not found:
        return None
    # Last one wins: an early part-less line can precede the resolved one.
    part = found[-1]
    # PyRTL models a tech node, not a part, and prints the literal "None".
    return None if part == "None" else part


def _point(stages, mhz, met):
    """(total_latency_ns, fmax_mhz, stages, met).

    Total latency is what a value actually costs end to end: stages / fmax.
    stages counts pipeline stages, so unpipelined (0 added clocks) is 1 stage
    and its latency is one clock period -- the combinational delay itself.
    """
    return ((stages * 1000.0 / mhz), mhz, stages, met)


def collect(build_dir):
    """Iteration points from one build's sweep_history.json.

    Written under <out_dir>/<top>/, and by every build that synthesizes the
    top level -- including --comb, which records the unpipelined point the
    sweep starts from. Iterations with no measured fmax (nothing in the timing
    report named this main) carry no data point and are skipped.
    """
    matches = sorted(build_dir.glob("*/sweep_history.json"))
    if not matches:
        return []
    with open(matches[0]) as f:
        hist = json.load(f)
    points = []
    for entry in hist.get("mains", {}).values():
        if not isinstance(entry, dict):
            continue
        goal = entry.get("goal_mhz")
        for rec in entry.get("iterations", []):
            mhz = rec.get("achieved_mhz")
            latency = rec.get("main_latency")
            if not mhz or latency is None:
                continue
            met = rec.get("met")
            if met is None and goal is not None:
                met = mhz >= goal
            # main_latency is added clocks; +1 makes it a stage count, so the
            # comb point (0 added clocks) and sweep points share one scale.
            points.append(_point(latency + 1, mhz, bool(met)))
    return points


def plot(per_tool, png_path, per_tool_part=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = plt.get_cmap("tab10")
    for i, (tool, points) in enumerate(sorted(per_tool.items())):
        if not points:
            continue
        color = cmap(i % 10)
        # Connect in STAGE order, not x order: stages is the variable the sweep
        # actually moves, so the line reads as "what the next cut bought".
        by_stage = sorted(points, key=lambda p: p[2])
        ax.plot([p[0] for p in by_stage], [p[1] for p in by_stage],
                "-", color=color, alpha=0.45, linewidth=1.2, zorder=1)
        # Filled = met its goal, hollow = did not; the shape of the trade is
        # the point, but whether a run was acceptable matters too.
        met = [p for p in points if p[3]]
        unmet = [p for p in points if not p[3]]
        if unmet:
            ax.scatter([p[0] for p in unmet], [p[1] for p in unmet],
                       facecolors="none", edgecolors=[color], s=42, zorder=2)
        if met:
            ax.scatter([p[0] for p in met], [p[1] for p in met],
                       color=color, s=42, zorder=3)
        # Stage count is the variable being traded for fmax, so name it on
        # each point rather than making the reader infer it from the x value.
        for latency_ns, mhz, stages, _met in points:
            ax.annotate(str(stages), (latency_ns, mhz),
                        textcoords="offset points", xytext=(0, 7),
                        ha="center", fontsize=7, color=color)
        part = (per_tool_part or {}).get(tool)
        label = f"{tool}" + (f"  [{part}]" if part else "  [no part]")
        ax.plot([], [], "o-", color=color, label=label)

    ax.set_xlabel("Total pipeline latency (ns)  =  stages / fmax")
    ax.set_ylabel("Achieved fmax (MHz)")
    ax.set_title("float32 adder: fmax vs total pipeline latency, per SYN_TOOL\n"
                 "one point per synthesis run; number = pipeline stages; "
                 "filled = met its clock goal", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(png_path, dpi=130)
    print(f"\nWrote {png_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out_root", required=True,
                    help="Directory for per-tool build dirs and the plot.")
    ap.add_argument("--tool", action="append", choices=sorted(SYN_TOOLS),
                    help="Limit to these tools (default: all).")
    ap.add_argument("--no_build", action="store_true",
                    help="Skip building; just re-read sweep_history.json and replot.")
    ap.add_argument("--timeout", type=float, default=7200,
                    help="Per-tool build timeout in seconds (default 7200).")
    args = ap.parse_args()

    out_root = Path(args.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    tools = args.tool or list(SYN_TOOLS)

    per_tool = {}
    per_tool_part = {}
    failed = []
    for tool in tools:
        out_dir = out_root / tool
        goal = SWEEP_FLOAT32_MHZ[tool]
        if not args.no_build:
            # Comb first: it is the cheap unpipelined reference AND it warms
            # the leaf delay cache the sweep is about to need.
            build(tool, out_dir, goal, args.timeout, comb=True)
            ok, _ = build(tool, out_dir, goal, args.timeout)
            if not ok:
                failed.append(tool)
        points = collect(out_dir / "comb_o") + collect(out_dir / "o")
        part = collect_part(out_dir / "build.log") or collect_part(out_dir / "comb.log")
        if part:
            per_tool_part[tool] = part
        # One point per distinct stage count; keep the best fmax measured there.
        best_at = {}
        for pt in points:
            if pt[2] not in best_at or pt[1] > best_at[pt[2]][1]:
                best_at[pt[2]] = pt
        points = sorted(best_at.values())
        if points:
            per_tool[tool] = points

    print("\n" + "=" * 86)
    print(f"{'tool':15s} {'part':22s} {'stages':>7s} {'fmax MHz':>10s} {'latency ns':>12s}  met")
    print("=" * 86)
    for tool, points in sorted(per_tool.items()):
        # PyRTL genuinely has no part -- say so rather than "unknown".
        part = per_tool_part.get(tool) or "(no part)"
        for latency_ns, mhz, stages, met in points:
            print(f"{tool:15s} {part:22s} {stages:7d} {mhz:10.2f} {latency_ns:12.1f}"
                  f"  {'yes' if met else 'no'}")
        if len(points) < 3:
            print(f"{'':16s} ^^ only {len(points)} point(s) -- expected the comb "
                  "point plus at least 2 sweep iterations")
        print("-" * 72)
    if failed:
        print("\nBuild failed (no data): " + ", ".join(failed))
    # Only complain about tools that actually produced a build directory;
    # --no_build over a partial out_root legitimately has nothing for the rest.
    no_data = [
        t for t in tools
        if t not in per_tool and t not in failed and (out_root / t).is_dir()
    ]
    if no_data:
        print("Built but no sweep iterations recorded: " + ", ".join(no_data))

    if per_tool:
        plot(per_tool, out_root / "sweep_float32_tool_compare.png", per_tool_part)
    else:
        print("\nNo data to plot.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
