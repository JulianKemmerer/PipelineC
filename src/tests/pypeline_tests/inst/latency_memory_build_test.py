#!/usr/bin/env python3
"""Sky130: all-MAIN replay, cross-goal/store reuse, stale pieces and partial failure."""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "latency_memory_stale_design.py")


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def build(out_dir, *extra, design=DESIGN, fails=False):
    cmd = [sys.executable, PYPELINEC, design, "--syn_tool", "device_models", "-j", "1",
           "--out_dir", out_dir] + list(extra)
    print("Running:", " ".join(cmd), flush=True)
    env = dict(os.environ, PIPELINEC_INTERNAL_NO_LATENCY_MEMORY="0")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    with open(out_dir + ".log", "w") as f:
        f.write(result.stdout)
    expect((result.returncode != 0) if fails else (result.returncode == 0),
           f"exit {result.returncode}: {out_dir}.log\n{result.stdout[-3000:]}")
    with open(os.path.join(out_dir, "latency_profile.json")) as f:
        profile = json.load(f)
    return result.stdout, profile


def pieces(out_dir):
    with open(os.path.join(out_dir, "latency_memory.json")) as f:
        return json.load(f)["pieces"]


def full_syntheses(out):
    return len(re.findall(r"^Running syn w timing params|^Running confirmation synthesis", out, re.M))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir")
    args = parser.parse_args()
    root = args.out_dir or tempfile.mkdtemp(prefix="latency_memory_v2_")
    os.makedirs(root, exist_ok=True)
    sub = lambda name: os.path.join(root, name)
    store = sub("store")
    first, profile = build(sub("g1"), "--syn_cache", store)
    depth = profile["entries"][0]["latency"]
    expect(depth > 0 and "AUTO_PIPELINE Pass 2" in first, "cold G1 must find depth and reparse")
    expect({e["kind"] for e in pieces(sub("g1"))} == {"AUTO_PIPELINE", "main"}, "depth and MAIN not recorded")
    again, profile = build(sub("g1"), "--syn_cache", store)
    expect("Replaying MAIN" in again and full_syntheses(again) == 1, "same-goal rebuild did not replay in one confirmation")
    expect("0 new run(s)" in again and "from the store" in again, "same-goal rebuild synthesized new inputs")
    expect("AUTO_PIPELINE Pass 2" not in again, "replay needed pass 2")
    # Different out_dir, same library key/store: G1 starts G2, and beats cold G2.
    warm, profile = build(sub("g2"), "--syn_cache", store, "-D", "LATENCY_MEMORY_GOAL=55")
    expect(f"core: starts at {depth} (latency memory (store)" in warm, "lower-goal piece was not served")
    expect("50 MHz goal" in warm and "Replaying MAIN" not in warm, "lower goal MAIN replayed")
    expect(profile["entries"][0]["latency"] >= depth, "higher-goal build went below its remembered depth floor")
    cold, _ = build(sub("g2_cold"), "--no_latency_memory", "-D", "LATENCY_MEMORY_GOAL=55")
    expect(full_syntheses(warm) < full_syntheses(cold), "warm G2 did not reduce full syntheses")
    # A store containing only G2 must not seed G1.
    high_store = sub("high_store")
    build(sub("high"), "--syn_cache", high_store, "-D", "LATENCY_MEMORY_GOAL=55")
    lower, _ = build(sub("lower"), "--syn_cache", high_store)
    expect("core: starts at" not in lower and "Replaying MAIN" not in lower, "higher goal piece used at lower goal")
    before = open(os.path.join(sub("g1"), "latency_memory.json")).read()
    off, _ = build(sub("g1"), "--syn_cache", store, "--no_latency_memory")
    expect("[latency memory]" not in off and "AUTO_PIPELINE Pass 2" in off, "memory-off build was seeded")
    expect(before == open(os.path.join(sub("g1"), "latency_memory.json")).read(), "memory-off build rewrote memory")
    hints = sub("hints.json")
    with open(hints, "w") as f:
        json.dump({"AUTO_PIPELINE": {"core": depth, "absent": 2}}, f)
    hinted, hinted_profile = build(sub("hinted"), "--latency_hints", hints)
    expect(f"core: starts at {depth} (hints hints.json)" in hinted, "hint did not behave as a start")
    expect("AUTO_PIPELINE Pass 2" not in hinted and "absent (hints" in hinted, "hint/unused-note semantics changed")
    # Same key, edited callee: reject the stale depth before serving it.
    stale, light_profile = build(sub("g1"), "--syn_cache", store, "-D", "LATENCY_MEMORY_HEAVY=0")
    expect("core: starts at" not in stale and "Replaying MAIN" not in stale, "stale piece survived its digest change")
    _, fresh_profile = build(sub("light"), "--no_latency_memory", "-D", "LATENCY_MEMORY_HEAVY=0")
    expect(light_profile["entries"][0]["latency"] == fresh_profile["entries"][0]["latency"], "stale piece changed the light result")
    # Two independent MAINs: one failure preserves its previous records while
    # the passing MAIN records its own pieces.
    partial_design = sub("partial.py")
    with open(partial_design, "w") as f:
        f.write('''from pypeline import MAIN, AUTO_PIPELINE, Reg, hw_func, param, uint8_t
@hw_func
def good(x: uint8_t) -> uint8_t:
    return x * x
@hw_func
def bad(x: uint8_t) -> uint8_t:
    return x + 1
GOOD = AUTO_PIPELINE(good, name="good", start_latency=1)
BAD = AUTO_PIPELINE(bad, name="bad", start_latency=1)
@MAIN(30.0)
def good_main(x: uint8_t) -> uint8_t:
    return GOOD(x)
@MAIN(param("BAD_GOAL", 30.0, type=float))
def bad_main(x: uint8_t) -> uint8_t:
    acc: Reg[uint8_t]
    acc = acc + 1
    return BAD(x) + acc
''')
    build(sub("partial"), design=partial_design)
    old_bad = [e for e in pieces(sub("partial")) if e["key"] in ("bad", "bad_main")]
    failed, _ = build(sub("partial"), "-D", "BAD_GOAL=100000", design=partial_design, fails=True)
    expect("not every MAIN matches" in failed, "partial replay did not skip confirmation")
    now = pieces(sub("partial"))
    expect([e for e in now if e["key"] in ("bad", "bad_main")] == old_bad, "failed MAIN overwrote its pieces")
    expect(any(e["key"] == "good" for e in now), "met MAIN's piece was not recorded")
    print("PASS: latency pieces replay, seed higher goals across output directories and retain per-MAIN results")


if __name__ == "__main__":
    main()
