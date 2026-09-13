#!/usr/bin/env python3
# AUTOMCP end to end under the real Vivado throughput sweep (Xilinx part;
# MULTI_CYCLE-style constraints are Vivado-only). Design:
# automcp_sweep_design.py, a mixing chain far slower than its 100 MHz clock
# behind make_stream_interface_automcp.
#  (a) default start (1 cycle): the sweep raises the count (action=automcp(...))
#      until the multi-cycle path meets timing, the pin-and-confirm pass
#      re-elaborates the handshake with the final count, the final XDC carries
#      that count, and the pipelined native --sim's sim_assert proves the
#      handshake waits count + 1 cycles
#  (b) start_latency = (a)'s count: the sweep starts and settles there -- no
#      AUTOMCP change, pass 2 skipped
#  (c) max_latency=1: the cap blocks the goal, the sweep says so, build fails
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "automcp_sweep_design.py")


def run(out_dir, start=None, max_latency=None, extra=()):
    cmd = [sys.executable, PYPELINEC, DESIGN]
    if out_dir:
        cmd += ["--out_dir", out_dir]
    cmd += list(extra)
    env = dict(os.environ)
    env.pop("AUTOMCP_SWEEP_START", None)
    env.pop("AUTOMCP_SWEEP_MAX", None)
    if start is not None:
        env["AUTOMCP_SWEEP_START"] = str(start)
    if max_latency is not None:
        env["AUTOMCP_SWEEP_MAX"] = str(max_latency)
    print(
        "Running:",
        f"AUTOMCP_SWEEP_START={start} AUTOMCP_SWEEP_MAX={max_latency}",
        " ".join(cmd),
        flush=True,
    )
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    print(result.stdout)
    return result.returncode, result.stdout


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def harvested(out):
    """Last AUTOMCP harvest lines printed (key -> cycles)."""
    counts = {}
    for key, n in re.findall(r"^AUTOMCP (\S+): (\d+) cycles$", out, re.M):
        counts[key] = int(n)
    return counts


def final_xdc_counts(out_dir):
    """Multi-cycle counts in the build's final top-level constraints (per-module
    syn runs, e.g. the planless as-written check, write their own clock.xdc
    under the module's directory -- not the result)."""
    with open(os.path.join(out_dir, "clocks.xdc")) as f:
        return {int(n) for n in re.findall(r"set_multicycle_path (\d+) ", f.read())}


def check_raises_count(out_dir):
    rc, out = run(out_dir, extra=["--sim", "--run", "60"])
    if rc != 0:
        fail(f"default-start AUTOMCP build/sim exited {rc}")
    if "action=automcp(" not in out:
        fail("the sweep never raised the AUTOMCP count")
    counts = harvested(out)
    if len(counts) != 1:
        fail(f"expected one AUTOMCP harvest line, got {counts}")
    (count,) = counts.values()
    if count <= 1:
        fail(f"AUTOMCP settled on {count} cycles; the design needs more than 1")
    if "AUTOPIPELINE Pass 2" not in out:
        fail("the raised count was not re-elaborated (no pin-and-confirm pass 2)")
    xdc = final_xdc_counts(out_dir) if out_dir else {count}
    if xdc != {count}:
        fail(f"final XDC multi-cycle counts {xdc}, expected {{{count}}}")
    if "TIMING NOT MET" in out:
        fail("timing not met")
    return count


def check_starts_and_settles(out_dir, count):
    rc, out = run(out_dir, start=count)
    if rc != 0:
        fail(f"start_latency={count} build exited {rc}")
    if "action=automcp(" in out:
        fail(f"start_latency={count} (a known-good count) was raised again")
    counts = harvested(out)
    if list(counts.values()) != [count]:
        fail(f"start_latency={count} harvested {counts}")
    if "AUTOMCP: every .latency read matched the built multi-cycle count" not in out:
        fail("pass 2 skip not reported although the start count was built")
    if "AUTOPIPELINE Pass 2" in out:
        fail("pin-and-confirm pass 2 ran although the start count was kept")


def check_max_latency_cap(out_dir):
    rc, out = run(out_dir, max_latency=1)
    if rc == 0:
        fail("an AUTOMCP capped at max_latency=1 below its need did not fail the build")
    if "limited by AUTOMCP" not in out:
        fail("the sweep did not name the AUTOMCP max_latency cap as the limit")
    if "TIMING NOT MET" not in out:
        fail("no TIMING NOT MET report for the capped AUTOMCP")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    sub = (lambda name: os.path.join(args.out_dir, name)) if args.out_dir else (lambda name: None)
    shared = sub("sweep")
    count = check_raises_count(shared)
    check_starts_and_settles(shared, count)
    check_max_latency_cap(sub("max_latency"))
    print(f"All AUTOMCP sweep end-to-end tests passed (settled on {count} cycles).")


if __name__ == "__main__":
    main()
