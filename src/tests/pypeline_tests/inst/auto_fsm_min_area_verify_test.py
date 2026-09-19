#!/usr/bin/env python3
"""AUTO_FSM minimum-area verification against independently built alternatives.

auto_fsm_area_sweep_compare_test.py already asks the weaker question -- "did the
search make things worse than sharing everything?" -- and every in-repo design
answers it by taking no moves at all, which passes trivially. This test asks
the question that actually decides whether the search is worth running:

  DOES THE POINT THE SEARCH PICKS HAVE THE FEWEST REAL CELLS?

The search ranks candidates with an internal model and never reads utilization
back from a synthesis tool (only timing is reported uniformly across
Vivado/Quartus/PYRTL), so the only way to answer that is to BUILD the
alternatives it passed over and count them. That is what --auto_fsm_open and
--auto_fsm_unshare are for: each forces exactly one point of the search space.

Note what is deliberately NOT asserted: that the search MOVES. An earlier
version of this test demanded a move, on the assumption that a design with
three divides sharing one expensive divider must reward opening it. yosys says
otherwise -- opening that divider spreads it over 36 states and buys a 36-way
multiplexer on every operand port, costing 1271 cells of multiplexing to save
one divider (1680 cells against 979 for sharing it whole). Declining is the
right answer there, and a test that required a move would have been asserting a
hypothesis rather than measuring one. What is asserted is agreement with
synthesis, in both directions.

That inversion is also what set AREA_PER_BIT_MUX: the model priced a 2:1 mux
bit at ~1 cell where yosys charges ~2.1, which is exactly the term that decides
whether decomposition pays.

Every build runs under --syn_tool device_models (fast, and its STA report records the
mapped cell count) with --auto_fsm_abstract_area: under DEVICE_MODELS the search
would otherwise rank candidates by real cached sky130 area, and it is the
abstract per-bit model this test holds to account
(auto_fsm_real_area_compare_test.py covers the real-area mode).

Counts are real mapped cells. (The earlier PyRTL flow's yosys statistics
included $scopeinfo hierarchy bookkeeping, which had to be excluded -- counting
it inverted verdicts on designs that instantiate many small modules. The
flattened sky130 netlist has none.)
"""
import argparse
import os
import re
import subprocess
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DIV_DESIGN = os.path.join(THIS_DIR, "..", "auto_fsm_div_share_test.py")

# The search may not land more than this above the best point actually built.
# A tolerance, not a target: the model ranks in abstract units and can be a
# couple of percent off on one design without being wrong in the large.
MAX_ABOVE_BEST = 0.03

# Nothing extra on the command line: the design's own 1 MHz goal is what makes
# opening a DECISION rather than a forced move, and it is documented there.
# Deliberately NOT done with --auto_fsm_budget_scale: scaling the budget past the
# real clock period lets the scheduler build states it cannot meet, and the
# driver then spends several full synthesis passes tightening back down.
LOOSE_BUDGET = []


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(out_dir, extra):
    cmd = [
        sys.executable, PYPELINEC, DIV_DESIGN,
        "--syn_tool", "device_models", "--auto_fsm_abstract_area",
        "--out_dir", out_dir,
    ] + extra
    print("Running:", " ".join(cmd), flush=True)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "build.log")
    started = time.monotonic()
    print("Live build log:", log_path, flush=True)
    with open(log_path, "w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    with open(log_path) as log:
        output = log.read()
    print(f"Build finished: status={result.returncode}, elapsed={time.monotonic() - started:.1f}s, log={log_path}", flush=True)
    if result.returncode != 0:
        print(output[-4000:])
        fail(f"build {extra} exited nonzero ({result.returncode}); full log: {log_path}")
    return output


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


def moves_taken(out):
    """(kinds opened, kinds given extra units) as the search reported them."""
    m = re.search(
        r"(\d+) kind\(s\) opened up, (\d+) kind\(s\) given extra unit\(s\)", out
    )
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def estimated_area(out):
    m = re.search(r"estimated (\d+) against (\d+)", out)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    base = args.out_dir or os.path.join(THIS_DIR, "auto_fsm_min_area_verify_out")

    # The search's own answer, and the two references it is judged against:
    # sharing everything (its anchor) and the alternative points of the space.
    variants = [
        ("area search (default)", "sweep", LOOSE_BUDGET),
        (
            "share everything",
            "greedy",
            LOOSE_BUDGET + ["--auto_fsm_no_area_sweep"],
        ),
        (
            "forced: 2 dividers",
            "unshare_div",
            LOOSE_BUDGET + ["--auto_fsm_unshare", "soft_div_radix=2"],
        ),
        (
            "forced: 3 dividers",
            "unshare_div3",
            LOOSE_BUDGET + ["--auto_fsm_unshare", "soft_div_radix=3"],
        ),
    ]

    results = []
    sweep_out = None
    for label, sub, extra in variants:
        out_dir = os.path.join(base, sub)
        out = run_build(out_dir, extra)
        if sub == "sweep":
            sweep_out = out
        results.append((label, sub, out, top_cell_count(out_dir)))

    print()
    print("=== AUTO_FSM minimum-area verification (sky130 mapped cells, whole design) ===")
    for label, _sub, out, cells in results:
        ops, fus, states, lat = schedule_line(out)
        est, anchor_est = estimated_area(out)
        est_txt = f", est {est}" if est is not None else ""
        print(
            f"  {label:<24} {cells:>8} cells  ({ops} ops -> {fus} units, "
            f"{states} states, latency {lat}{est_txt})"
        )
    print()

    by_sub = {sub: (label, out, cells) for label, sub, out, cells in results}
    sweep_cells = by_sub["sweep"][2]
    greedy_cells = by_sub["greedy"][2]

    moves = moves_taken(sweep_out)
    if moves is None:
        fail("the area search did not run on the default build")
    n_opened, n_unshared = moves
    change = (sweep_cells - greedy_cells) / float(greedy_cells)
    print(
        f"  search took {n_opened} open + {n_unshared} unshare move(s); "
        f"{change * 100:+.1f}% cells vs sharing everything"
    )

    # THE ONE THING THAT MATTERS: the point the search picked is the smallest
    # one we could build. Not "it moved" and not "it beat the anchor" -- either
    # of those can be true of a schedule that real synthesis says is worse, and
    # both were, before AREA_PER_BIT_MUX was measured.
    best_label, best_cells = min(
        ((label, cells) for label, _sub, _out, cells in results),
        key=lambda lc: lc[1],
    )
    if sweep_cells > best_cells * (1.0 + MAX_ABOVE_BEST):
        over = (sweep_cells - best_cells) / float(best_cells)
        fail(
            f"the search chose a schedule {over * 100:.1f}% bigger than the "
            f"best point built here ({best_label}: {best_cells} cells vs "
            f"{sweep_cells}). Its cost model ranked them the other way round. "
            f"Rerun the default build with --auto_fsm_sweep_debug to see which "
            f"move it took and what it thought that move was worth, then "
            f"recalibrate the AREA_* constants in src/AUTO_FSM.py against this "
            f"table -- AREA_PER_BIT_MUX is the term that decides whether "
            f"decomposition pays, and SWEEP_MIN_IMPROVEMENT is how large a "
            f"modelled win has to be before the search is allowed to act on it."
        )

    # And the anchor guarantee, which is what makes the search safe to leave on
    # by default: whatever it picks, it is never meaningfully worse than not
    # having searched at all.
    if change > MAX_ABOVE_BEST:
        fail(
            f"the search made this design {change * 100:.1f}% BIGGER than "
            f"sharing everything ({greedy_cells} -> {sweep_cells} cells), "
            f"which the anchor guarantee is supposed to make impossible."
        )

    print(
        f"AUTO_FSM minimum-area verification passed: the search's choice is "
        f"within {MAX_ABOVE_BEST * 100:.0f}% of the smallest of "
        f"{len(results)} built points ({best_label}, {best_cells} cells)."
    )


if __name__ == "__main__":
    main()
