#!/usr/bin/env python3
"""AUTOFSM control-path comparison: is the v3 constant-table control path
actually cheaper than the v2 comparator chains it replaced?

AUTOFSM shares operations across states, and something has to decode the state
into "which operand does this unit take", "which registers are written" and
"what is the next state". v2 spent an equality comparator per state per shared
unit plus a priority chain; v3 reads constant lookup tables indexed by the
state, which synthesis folds down to roughly a gate per table output bit. The
number of comparators per FSM went from O(states x units) to exactly one.

That is the claim, and it is entirely a claim about generated hardware, so it
is measured rather than argued: build the same design under --autofsm_ctl v2
and under the default v3 and compare yosys cell counts. The PYRTL timing flow
already runs yosys in both builds, so no extra tool invocation is needed. (Cell
counts are read here, inside the test suite, never inside the area search --
the search must work from its own model plus real timing measurements, since no
area number is available uniformly across synthesis tools.)

Two things are checked, because v3 bought two different wins:

  area    on autofsm_resources_test, where both control paths build, v3 must
          not be bigger than v2. Both modes schedule identically, so this
          isolates the control path.

  timing  on the vga donut update -- a design that sits right at its clock goal
          -- v3 must MEET that goal. This is not a soft property: with the v2
          control path in the critical path the same schedule misses 40 MHz,
          and the driver's response (tighten the state budget and reschedule)
          walks into a far larger and slower design. The comparator chains were
          the difference between meeting timing and not.

`$scopeinfo` is excluded from every count. It is yosys bookkeeping that records
where flattened logic came from, not hardware, and v3 deliberately instantiates
more small modules (one per lookup table) than v2 -- so leaving it in would
report a design that got smaller as if it had grown.
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
RESOURCES_DESIGN = os.path.join(THIS_DIR, "..", "autofsm_resources_test.py")
DONUT_DESIGN = os.path.join(
    THIS_DIR, "../../../../examples/pypeline/autofsm_donut_update.py"
)

# v3 must not be bigger than v2. A small tolerance so an unrelated synthesis
# nudge cannot fail the build, but far tighter than the win being claimed.
MAX_RATIO = 1.005


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(design, out_dir, extra, allow_fail=False):
    cmd = [sys.executable, PYPELINEC, design, "--out_dir", out_dir] + extra
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if result.returncode != 0 and not allow_fail:
        print(result.stdout)
        fail(f"build {extra} of {os.path.basename(design)} exited nonzero")
    return result.stdout, result.returncode


def _cells(log_path):
    """(total, total minus $scopeinfo) from a yosys statistics block."""
    text = open(log_path).read()
    blocks = list(
        re.finditer(r"Number of cells:\s+(\d+)\n((?:\s+\$\S+\s+\d+\n)+)", text)
    )
    if not blocks:
        fail(f"no yosys cell count in {log_path}")
    block = blocks[-1]
    scope = 0
    for line in block.group(2).strip().splitlines():
        kind, count = line.split()
        if kind == "$scopeinfo":
            scope = int(count)
    total = int(block.group(1))
    return total, total - scope


def top_cell_count(out_dir):
    top_dir = os.path.join(out_dir, "top")
    logs = [
        os.path.join(top_dir, f)
        for f in os.listdir(top_dir)
        if f.startswith("pyrtl_") and f.endswith(".log")
    ]
    if not logs:
        fail(f"no PYRTL/yosys log found under {top_dir}")
    logs.sort(key=os.path.getmtime)
    return _cells(logs[-1]) + (logs[-1],)


def schedule_banners(out):
    return sorted(set(re.findall(r"^AUTOFSM \S+: .*$", out, re.M)))


def check_area(base):
    v2_dir = os.path.join(base, "res_v2")
    v3_dir = os.path.join(base, "res_v3")
    v2_out, _ = run_build(RESOURCES_DESIGN, v2_dir, ["--autofsm_ctl", "v2"])
    v3_out, _ = run_build(RESOURCES_DESIGN, v3_dir, [])

    # Same schedule under both, so any cell difference is the control path and
    # nothing else. (The area model does price the two differently, but on this
    # design the difference is not enough to change what the search picks.)
    if schedule_banners(v2_out) != schedule_banners(v3_out):
        print("v2:", schedule_banners(v2_out))
        print("v3:", schedule_banners(v3_out))
        fail(
            "the two control paths did not schedule the same design the same "
            "way, so their cell counts are not a control-path comparison"
        )

    v2_raw, v2_cells, v2_log = top_cell_count(v2_dir)
    v3_raw, v3_cells, v3_log = top_cell_count(v3_dir)
    ratio = v3_cells / float(v2_cells) if v2_cells else 0.0

    print()
    print("=== AUTOFSM control path (yosys cells, whole design top) ===")
    print(f"  v2 comparator chains : {v2_cells:>8} ({v2_raw} incl. $scopeinfo)")
    print(f"  v3 constant tables   : {v3_cells:>8} ({v3_raw} incl. $scopeinfo)")
    print(f"  v3/v2                : {ratio:.4f}")
    print(f"  logs: {v2_log}")
    print(f"        {v3_log}")
    print()

    if ratio > MAX_RATIO:
        fail(
            f"the v3 control path is BIGGER than the v2 comparator chains it "
            f"replaced ({v2_cells} -> {v3_cells} cells, {ratio:.4f}x, allowed "
            f"up to {MAX_RATIO}x). Constant-table decode is the entire point "
            f"of ctl v3 -- if this regressed, v3 is paying latency and "
            f"complexity for nothing."
        )


def check_timing(base):
    out, rc = run_build(DONUT_DESIGN, os.path.join(base, "donut_v3"), [])
    m = re.search(
        r"synthesized as written \(standalone check\): "
        r"([\d.]+) MHz vs ([\d.]+) MHz goal - (PASS|FAIL)",
        out,
    )
    if not m:
        print(out[-4000:])
        fail("the donut build did not report an as-written timing check")
    got, goal, verdict = float(m.group(1)), float(m.group(2)), m.group(3)
    print()
    print("=== AUTOFSM control path (vga donut update, at its clock goal) ===")
    print(f"  v3: {got:.2f} MHz vs {goal:.2f} MHz goal - {verdict}")
    print()
    if verdict != "PASS":
        fail(
            f"the donut FSM misses its {goal:.2f} MHz goal at {got:.2f} MHz. "
            f"This design sits close enough to its goal that the control "
            f"path decides it: the v2 comparator chains miss here, and the "
            f"driver's response is to tighten the state budget and reschedule "
            f"into a much larger design. Whatever slowed the control path "
            f"back down needs finding."
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    base = args.out_dir or os.path.join(THIS_DIR, "autofsm_ctl_compare_test_out")
    check_area(base)
    check_timing(base)
    print("AUTOFSM control path comparison passed.")


if __name__ == "__main__":
    main()
