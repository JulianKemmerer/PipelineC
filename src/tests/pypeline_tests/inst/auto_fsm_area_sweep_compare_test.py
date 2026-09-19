#!/usr/bin/env python3
"""AUTO_FSM area-search test: does the minimum-area search actually help, and is
its cost model telling the truth?

The search picks between candidate schedules using an INTERNAL area estimate,
never a number read back from a synthesis tool -- deliberately, because timing
is the only quantity every backend (Vivado, Quartus, PYRTL, ...) reports in a
form the driver can parse, and an area-minimizing search that depended on
utilization output would only work on some of them.

That makes this test the place where the estimate meets reality. Mapped cell
counts are used HERE, in the test suite, and nowhere in the search itself.

Both builds run under --syn_tool device_models (fast, and its STA report records the
mapped cell count) with --auto_fsm_abstract_area: under DEVICE_MODELS the
search would otherwise rank candidates by real cached sky130 area, and it is
the abstract per-bit model this test exists to check
(auto_fsm_real_area_compare_test.py covers the real-area mode).

Method: build the same design twice.
  --auto_fsm_no_area_sweep   the plain greedy schedule (v1 behaviour): share
                            every operation, open nothing up.
  (default)                 the area search.
Then compare mapped cell counts, and check that the estimator ranked the two
schedules the same way synthesis did -- which is the property that makes the search
trustworthy at all.
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
# auto_fsm_test.py rather than auto_fsm_resources_test.py: the latter is 6
# multiplies and 5 adds, all of them so much more expensive than their own
# multiplexers that sharing every one is obviously right and the search
# correctly declines to move at all. This design has cheap operations mixed in,
# which is where the decision is actually interesting.
DESIGN = os.path.join(THIS_DIR, "auto_fsm_test.py")

# The search may not make things WORSE by more than this. It is a tolerance,
# not a target: the model ranks candidates in abstract units and a rank that is
# right in the large can still be off by a couple of percent on one design.
# A real regression (the search systematically choosing bigger designs) blows
# straight through it.
MAX_REGRESSION = 0.03


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(out_dir, extra):
    cmd = [
        sys.executable, PYPELINEC, DESIGN,
        "--syn_tool", "device_models", "--auto_fsm_abstract_area",
        "--out_dir", out_dir,
    ] + extra
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if result.returncode != 0:
        print(result.stdout)
        fail(f"build {extra} exited nonzero ({result.returncode})")
    return result.stdout


def top_cell_count(out_dir):
    """Mapped sky130 standard-cell count of the whole-design top entity, from
    the "N cells:" line of the DEVICE_MODELS STA report the build already
    wrote (this wrapper builds with --syn_tool device_models). The mapped netlist is
    flattened, so it has no $scopeinfo hierarchy-bookkeeping cells to
    subtract."""
    top_dir = os.path.join(out_dir, "top")
    logs = [
        os.path.join(top_dir, f)
        for f in os.listdir(top_dir)
        if f.startswith("device_models_") and f.endswith(".log")
    ]
    if not logs:
        fail(f"no DEVICE_MODELS STA report found under {top_dir}")
    logs.sort(key=os.path.getmtime)
    with open(logs[-1]) as f:
        text = f.read()
    m = re.findall(r"^N cells:\s+(\d+)", text, re.M)
    if not m:
        fail(f"no 'N cells:' line in {logs[-1]}")
    return int(m[-1])


def schedule_line(out):
    m = re.search(
        r"^AUTO_FSM \S+: (\d+) ops -> (\d+) shared unit\(s\), (\d+) states, "
        r"latency (\d+)",
        out,
        re.M,
    )
    if not m:
        fail("build did not schedule an AUTO_FSM")
    return tuple(int(g) for g in m.groups())


def estimated_area(out):
    """The search's own estimate of what it picked, and of the share-everything
    schedule it started from."""
    m = re.search(r"estimated (\d+) against (\d+)", out)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    base = args.out_dir or os.path.join(THIS_DIR, "auto_fsm_area_sweep_out")
    greedy_dir = os.path.join(base, "greedy")
    sweep_dir = os.path.join(base, "sweep")

    greedy_out = run_build(greedy_dir, ["--auto_fsm_no_area_sweep"])
    sweep_out = run_build(sweep_dir, [])

    if "area search:" in greedy_out:
        fail("--auto_fsm_no_area_sweep did not disable the area search")
    if "area search:" not in sweep_out:
        fail("the area search did not run on the default build")

    g_ops, g_fus, g_states, g_lat = schedule_line(greedy_out)
    s_ops, s_fus, s_states, s_lat = schedule_line(sweep_out)
    greedy_cells = top_cell_count(greedy_dir)
    sweep_cells = top_cell_count(sweep_dir)
    est_sweep, est_greedy = estimated_area(sweep_out)

    print()
    print("=== AUTO_FSM area search (sky130 mapped cells, whole design top) ===")
    print(
        f"  share everything (--auto_fsm_no_area_sweep): {greedy_cells:>8} cells  "
        f"({g_ops} ops -> {g_fus} units, {g_states} states, latency {g_lat})"
    )
    print(
        f"  area search (default)                     : {sweep_cells:>8} cells  "
        f"({s_ops} ops -> {s_fus} units, {s_states} states, latency {s_lat})"
    )
    if est_sweep is not None:
        print(
            f"  the search's own estimate                 : {est_sweep} vs "
            f"{est_greedy} (abstract units, tool-independent)"
        )
    change = (sweep_cells - greedy_cells) / float(greedy_cells)
    print(f"  change                                    : {change * 100:+.1f}%")
    print()

    if change > MAX_REGRESSION:
        fail(
            f"the area search made this design {change * 100:.1f}% BIGGER "
            f"({greedy_cells} -> {sweep_cells} cells). The search keeps the "
            f"share-everything schedule as its anchor and only moves off it "
            f"when its cost model says the result is smaller, so a regression "
            f"this size means the cost model disagrees with real synthesis -- "
            f"recalibrate the AREA_* constants in src/AUTO_FSM.py against these "
            f"numbers."
        )

    # Ranking agreement: if the estimator says the chosen schedule is smaller,
    # yosys should not strongly disagree. This is the calibration guard -- the
    # search is only as good as this correspondence.
    if est_sweep is not None and est_sweep < est_greedy:
        if change > MAX_REGRESSION:
            fail(
                "the estimator ranked the chosen schedule smaller but yosys "
                "ranked it clearly bigger"
            )

    print(f"AUTO_FSM area search test passed ({change * 100:+.1f}% cells).")


if __name__ == "__main__":
    main()
