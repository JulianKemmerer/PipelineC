#!/usr/bin/env python3
"""AUTOFSM `max_latency=` end-to-end test.

`max_latency=N` is a HARD constraint, not a preference, and this checks both
halves of that:

  1. A cap the tool CAN meet is met -- by unsharing, because building a second
     copy of a unit is the only thing that can shorten a schedule. Without the
     cap the same design shares everything onto one adder and runs longer, so
     the test also confirms the cap actually changed the answer.
  2. A cap the tool CANNOT meet fails the build, loudly, naming the FSM and the
     latency it really needs. Quietly returning a slower FSM would defeat the
     entire point of asking for a cap -- the surrounding design has a deadline.
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DESIGN = os.path.join(THIS_DIR, "autofsm_max_latency_design.py")

CAP = 4


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(out_dir, impossible=False):
    env = dict(os.environ)
    if impossible:
        env["PYPELINE_AUTOFSM_IMPOSSIBLE_LATENCY"] = "1"
    else:
        env.pop("PYPELINE_AUTOFSM_IMPOSSIBLE_LATENCY", None)
    cmd = [sys.executable, PIPELINEC, DESIGN, "--out_dir", out_dir]
    print("Running:", " ".join(cmd), f"(impossible={impossible})", flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    return result.returncode, result.stdout


def schedule_summary(out):
    m = re.search(
        r"^AUTOFSM (\S+): (\d+) ops -> (\d+) shared unit\(s\), (\d+) states, "
        r"latency (\d+)(?:/(\d+) max)? clks",
        out,
        re.M,
    )
    if not m:
        fail("no AUTOFSM schedule summary printed")
    return {
        "key": m.group(1),
        "ops": int(m.group(2)),
        "fus": int(m.group(3)),
        "states": int(m.group(4)),
        "latency": int(m.group(5)),
        "cap": int(m.group(6)) if m.group(6) else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    base = args.out_dir or os.path.join(THIS_DIR, "autofsm_max_latency_test_out")

    # ── 1. a cap the tool can meet ──────────────────────────────────────────
    rc, out = run_build(os.path.join(base, "capped"))
    print(out)
    if rc != 0:
        fail(f"the capped build exited nonzero ({rc}); the cap should be met")
    s = schedule_summary(out)
    if s["cap"] != CAP:
        fail(f"the schedule summary does not report the cap (got {s['cap']!r})")
    if s["latency"] > CAP:
        fail(
            f"max_latency={CAP} was not honoured: the FSM has latency "
            f"{s['latency']} ({s['states']} states)"
        )
    # 5 adds sharing one adder would take 5 states / latency 6. Meeting a cap of
    # 4 therefore REQUIRES more than one adder -- if this reads 1, the cap was
    # satisfied by accident and the test is not testing anything.
    if s["fus"] < 2:
        fail(
            f"the cap was met with {s['fus']} shared unit(s); with 5 dependent "
            f"adds on one adder the latency could not have been under "
            f"{s['latency']}, so the schedule summary and the cap disagree"
        )
    if "ERROR: TIMING NOT MET" in out:
        fail("the capped build did not meet timing")
    print(
        f"  capped: {s['ops']} ops -> {s['fus']} units, {s['states']} states, "
        f"latency {s['latency']} (cap {CAP}) -- met by unsharing"
    )

    # ── 2. a cap the tool cannot meet ───────────────────────────────────────
    rc2, out2 = run_build(os.path.join(base, "impossible"), impossible=True)
    print(out2[-4000:])
    if rc2 == 0:
        fail(
            "a max_latency=2 cap on a 5-deep dependency chain at 100 MHz was "
            "reported as met; an impossible cap must fail the build"
        )
    if "cannot be met" not in out2:
        fail("the impossible cap failed the build without explaining why")
    m = re.search(r"Raise max_latency to at least (\d+)", out2)
    if not m:
        fail(
            "the failure message does not say what latency the FSM actually "
            "needs -- which is the one thing the user has to know"
        )
    print(f"  impossible: build failed as it should, needs latency {m.group(1)}")

    print("AUTOFSM max_latency test passed.")


if __name__ == "__main__":
    main()
