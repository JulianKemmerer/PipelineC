#!/usr/bin/env python3
# AUTO_MULTI_CYCLE end to end under the real Vivado throughput sweep (Xilinx part;
# MULTI_CYCLE-style constraints are Vivado-only). Design:
# auto_multi_cycle_sweep_design.py, a mixing chain far slower than its 100 MHz clock
# behind make_stream_auto_multi_cycle.
#  (a) default start (1 cycle): the sweep raises the count (action=auto_multi_cycle(...))
#      until the multi-cycle path meets timing, the pin-and-confirm pass
#      re-elaborates the handshake with the final count, the final XDC carries
#      that count, and the pipelined native --sim's sim_assert proves the
#      handshake waits count + 1 cycles
#  (b) start_latency = (a)'s count: the sweep starts and settles there -- no
#      AUTO_MULTI_CYCLE change, pass 2 skipped
#  (c) max_latency=1: the cap blocks the goal, the sweep says so, build fails
#  (d) latency memory: (a) runs with the memory on, so a rebuild of its output
#      directory starts from the remembered count and skips pass 2; a
#      same-goal memory count three cycles too high stays provisional, so
#      confirm-down brings it back to (a)'s count; and at a raised goal the
#      same piece from the lower goal is a floor the count never goes below
import argparse
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "auto_multi_cycle_sweep_design.py")


def run(out_dir, start=None, max_latency=None, extra=(), memory=False):
    cmd = [sys.executable, PYPELINEC, DESIGN, "-j", "1"]
    if out_dir:
        cmd += ["--out_dir", out_dir]
    cmd += list(extra)
    if start is not None:
        cmd += ["-D", f"AUTO_MULTI_CYCLE_SWEEP_START={start}"]
    if max_latency is not None:
        cmd += ["-D", f"AUTO_MULTI_CYCLE_SWEEP_MAX={max_latency}"]
    print("Running:", " ".join(cmd), flush=True)
    # The harness turns the latency memory off for every test; (d) wants it
    env = dict(os.environ)
    if memory:
        env["PIPELINEC_INTERNAL_NO_LATENCY_MEMORY"] = "0"
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    print(result.stdout)
    return result.returncode, result.stdout


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def harvested(out):
    """Last AUTO_MULTI_CYCLE harvest lines printed (key -> cycles)."""
    counts = {}
    for key, n in re.findall(r"^AUTO_MULTI_CYCLE (\S+): (\d+) cycles$", out, re.M):
        counts[key] = int(n)
    return counts


def final_xdc_counts(out_dir):
    """Multi-cycle counts in the build's final top-level constraints (per-module
    syn runs, e.g. isolated MCP endpoint checks, write their own clock.xdc
    under the module's directory -- not the result)."""
    with open(os.path.join(out_dir, "clocks.xdc")) as f:
        return {int(n) for n in re.findall(r"set_multicycle_path (\d+) -setup ", f.read())}


def check_raises_count(out_dir):
    rc, out = run(out_dir, extra=["--sim", "--run", "60"], memory=True)
    if rc != 0:
        fail(f"default-start AUTO_MULTI_CYCLE build/sim exited {rc}")
    # Endpoint characterization now seeds all groups before the first top run.
    if "provisional seed 1->6" not in out:
        fail("the measured mixing-chain MCP was not directly seeded from 1 to 6")
    counts = harvested(out)
    if len(counts) != 1:
        fail(f"expected one AUTO_MULTI_CYCLE harvest line, got {counts}")
    (count,) = counts.values()
    if count <= 1:
        fail(f"AUTO_MULTI_CYCLE settled on {count} cycles; the design needs more than 1")
    if "AUTO_PIPELINE Pass 2" not in out:
        fail("the raised count was not re-elaborated (no pin-and-confirm pass 2)")
    xdc = final_xdc_counts(out_dir) if out_dir else {count}
    if xdc != {count}:
        fail(f"final XDC multi-cycle counts {xdc}, expected {{{count}}}")
    if "TIMING NOT MET" in out:
        fail("timing not met")
    if out_dir and "Latency memory: recorded 2 pieces (out_dir)" not in out:
        fail("the verified count was not remembered")
    return count


def check_remembered_count(out_dir, count, hints_dir):
    rc, out = run(out_dir, memory=True)
    if rc != 0:
        fail(f"remembered-count rebuild exited {rc}")
    if not re.search(rf"^\[latency memory\] AUTO_MULTI_CYCLE \S+: starts at {count} \(latency memory", out, re.M):
        fail(f"the rebuild did not start from the remembered {count} cycles")
    if list(harvested(out).values()) != [count] or "AUTO_PIPELINE Pass 2" in out:
        fail("a rebuild starting from the remembered count must keep it and skip pass 2")
    # A matching current-goal piece remains provisional and confirms down.
    memory_path = os.path.join(out_dir, "latency_memory.json")
    with open(memory_path) as f:
        memory = json.load(f)
    for piece in memory["pieces"]:
        if piece["kind"] == "AUTO_MULTI_CYCLE":
            piece["latency"] = count + 3
    with open(memory_path, "w") as f:
        json.dump(memory, f)
    rc, out = run(out_dir, memory=True)
    if rc != 0 or "MCP confirm-down passed" not in out or list(harvested(out).values()) != [count]:
        fail("a current-goal MCP piece was not confirmed down")
    # The same verified datapath piece at a lower goal is a floor at a raised
    # goal, even if its known-good starting implementation was conservative.
    for piece in memory["pieces"]:
        if piece["kind"] == "AUTO_MULTI_CYCLE":
            piece["latency"] = count + 3
    os.makedirs(hints_dir, exist_ok=True)
    with open(os.path.join(hints_dir, "latency_memory.json"), "w") as f:
        json.dump(memory, f)
    rc, out = run(hints_dir, extra=["-D", "AUTO_MULTI_CYCLE_SWEEP_GOAL=110"], memory=True)
    if rc != 0 or list(harvested(out).values())[0] < count + 3:
        fail("the lower-goal MCP piece did not act as a floor")


def check_starts_and_settles(out_dir, count):
    rc, out = run(out_dir, start=count)
    if rc != 0:
        fail(f"start_latency={count} build exited {rc}")
    if "action=auto_multi_cycle(" in out:
        fail(f"start_latency={count} (a known-good count) was raised again")
    counts = harvested(out)
    if list(counts.values()) != [count]:
        fail(f"start_latency={count} harvested {counts}")
    if "AUTO_MULTI_CYCLE: every .latency read matched the built multi-cycle count" not in out:
        fail("pass 2 skip not reported although the start count was built")
    if "AUTO_PIPELINE Pass 2" in out:
        fail("pin-and-confirm pass 2 ran although the start count was kept")


def check_max_latency_cap(out_dir):
    rc, out = run(out_dir, max_latency=1)
    if rc == 0:
        fail("an AUTO_MULTI_CYCLE capped at max_latency=1 below its need did not fail the build")
    if "limited by AUTO_MULTI_CYCLE" not in out:
        fail("the sweep did not name the AUTO_MULTI_CYCLE max_latency cap as the limit")
    if "TIMING NOT MET" not in out:
        fail("no TIMING NOT MET report for the capped AUTO_MULTI_CYCLE")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    sub = (lambda name: os.path.join(args.out_dir, name)) if args.out_dir else (lambda name: None)
    shared = sub("sweep")
    count = check_raises_count(shared)
    if shared:
        check_remembered_count(shared, count, sub("stale_hint"))
    check_starts_and_settles(shared, count)
    check_max_latency_cap(sub("max_latency"))
    print(f"All AUTO_MULTI_CYCLE sweep end-to-end tests passed (settled on {count} cycles).")


if __name__ == "__main__":
    main()
