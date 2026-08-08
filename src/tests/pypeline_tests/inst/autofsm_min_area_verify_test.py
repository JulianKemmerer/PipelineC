#!/usr/bin/env python3
"""AUTOFSM minimum-area verification: does the area search MOVE, and is where it
lands actually the smallest design?

autofsm_area_sweep_compare_test.py already asks the weaker question -- "did the
search make things worse than sharing everything?" -- and every in-repo design
answers it by taking no moves at all, which passes trivially. This test asks
the question that actually decides whether the search is worth running:

  DOES THE POINT THE SEARCH PICKS HAVE THE FEWEST REAL CELLS?

The search ranks candidates with an internal model and never reads utilization
back from a synthesis tool (only timing is reported uniformly across
Vivado/Quartus/PYRTL), so the only way to answer that is to BUILD the
alternatives it passed over and count them. That is what --autofsm_open and
--autofsm_unshare are for: each forces exactly one point of the search space.

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

Cell counts exclude $scopeinfo, which is yosys hierarchy bookkeeping rather than
hardware -- counting it inverts verdicts on designs that instantiate many small
modules (an AUTOFSM under ctl=v3 instantiates one per lookup table).
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DIV_DESIGN = os.path.join(THIS_DIR, "autofsm_div_share_test.py")

# The search may not land more than this above the best point actually built.
# A tolerance, not a target: the model ranks in abstract units and can be a
# couple of percent off on one design without being wrong in the large.
MAX_ABOVE_BEST = 0.03

# Nothing extra on the command line: the design's own 1 MHz goal is what makes
# opening a DECISION rather than a forced move, and it is documented there.
# Deliberately NOT done with --autofsm_budget_scale: scaling the budget past the
# real clock period lets the scheduler build states it cannot meet, and the
# driver then spends several full synthesis passes tightening back down.
LOOSE_BUDGET = []


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(out_dir, extra):
    cmd = [sys.executable, PIPELINEC, DIV_DESIGN, "--out_dir", out_dir] + extra
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        fail(f"build {extra} exited nonzero ({result.returncode})")
    return result.stdout


def top_cell_count(out_dir):
    """Real cells in the last yosys report under out_dir/top, minus $scopeinfo.

    $scopeinfo is hierarchy bookkeeping, not hardware. Leaving it in makes a
    design that instantiates more small modules look bigger when it is not --
    it inverted the v2-vs-v3 control-path verdict on the donut example.
    """
    top_dir = os.path.join(out_dir, "top")
    logs = [
        os.path.join(top_dir, f)
        for f in os.listdir(top_dir)
        if f.startswith("pyrtl_") and f.endswith(".log")
    ]
    if not logs:
        fail(f"no PYRTL/yosys log found under {top_dir}")
    logs.sort(key=os.path.getmtime)
    with open(logs[-1]) as f:
        text = f.read()
    blocks = list(
        re.finditer(r"Number of cells:\s+(\d+)\n((?:\s+\$\S+\s+\d+\n)+)", text)
    )
    if not blocks:
        m = re.findall(r"^\s*Number of cells:\s+(\d+)", text, re.M)
        if not m:
            fail(f"no yosys cell count in {logs[-1]}")
        return int(m[-1])
    block = blocks[-1]
    scopeinfo = 0
    for line in block.group(2).strip().splitlines():
        kind, count = line.split()
        if kind == "$scopeinfo":
            scopeinfo = int(count)
    return int(block.group(1)) - scopeinfo


def schedule_line(out):
    m = re.search(
        r"^AUTOFSM \S+: (\d+) ops -> (\d+) shared unit\(s\), (\d+) states, "
        r"latency (\d+)",
        out,
        re.M,
    )
    if not m:
        fail("build did not schedule an AUTOFSM")
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
    base = args.out_dir or os.path.join(THIS_DIR, "autofsm_min_area_verify_out")

    # The search's own answer, and the two references it is judged against:
    # sharing everything (its anchor) and the alternative points of the space.
    variants = [
        ("area search (default)", "sweep", LOOSE_BUDGET),
        (
            "share everything",
            "greedy",
            LOOSE_BUDGET + ["--autofsm_no_area_sweep"],
        ),
        (
            "forced: 2 dividers",
            "unshare_div",
            LOOSE_BUDGET + ["--autofsm_unshare", "soft_div_radix=2"],
        ),
        (
            "forced: 3 dividers",
            "unshare_div3",
            LOOSE_BUDGET + ["--autofsm_unshare", "soft_div_radix=3"],
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
    print("=== AUTOFSM minimum-area verification (yosys cells, whole design) ===")
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
            f"Rerun the default build with --autofsm_sweep_debug to see which "
            f"move it took and what it thought that move was worth, then "
            f"recalibrate the AREA_* constants in src/AUTOFSM.py against this "
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
        f"AUTOFSM minimum-area verification passed: the search's choice is "
        f"within {MAX_ABOVE_BEST * 100:.0f}% of the smallest of "
        f"{len(results)} built points ({best_label}, {best_cells} cells)."
    )


if __name__ == "__main__":
    main()
