#!/usr/bin/env python3
"""Latency memory end to end (build_report_device_models, sky130).

Builds stream_auto_pipeline_test.py -- whose make_stream_auto_pipeline sizes
its FIFO from the core AUTO_PIPELINE's .latency, so an unseeded build always
needs the pin-and-confirm pass 2 -- six times:

  1. fresh output directory with --syn_cache: pass 2 runs, and the verified
     latency is recorded in the output directory and the store;
  2. the same output directory again: the core starts at the remembered
     latency, pass 2 is skipped, and the build ends at the same latency;
  3. the same directory with --no_latency_memory: no starting latency, pass 2
     runs again, same latency, memory left alone;
  4. the output directory deleted, --syn_cache: seeded from the store's copy;
  5. a fresh output directory without a store, --latency_hints <the first
     build's latency_profile.json>: seeded from the hints, pass 2 skipped;
  6. a stale memory entry: latency_memory_stale_design.py's named core
     ("core") is built heavy, then rebuilt light in the same directory. The
     remembered heavy latency was recorded for another function, so it only
     serves the first .latency read: the sweep plans the light core as it
     would unseeded and ends where a memory-less build does, through pass 2.
     An unmatched hint is reported.

The harness sets PIPELINEC_INTERNAL_NO_LATENCY_MEMORY=1 for every test; this
one turns it back off for its own builds. See docs/SWEEP_DESIGN.md#5-latency-memory.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "stream_auto_pipeline_test.py")
STALE_DESIGN = os.path.join(THIS_DIR, "latency_memory_stale_design.py")
PASS2 = "AUTO_PIPELINE Pass 2"
SKIPPED = "skipping pin-and-confirm pass 2"


def build(out_dir, *extra, design=DESIGN):
    cmd = [sys.executable, PYPELINEC, design, "--syn_tool", "device_models", "-j", "1"]
    cmd += ["--out_dir", out_dir] + list(extra)
    env = dict(os.environ, PIPELINEC_INTERNAL_NO_LATENCY_MEMORY="0")
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    out = result.stdout
    log = out_dir.rstrip("/") + ".log"
    with open(log, "w") as f:
        f.write(out)
    if result.returncode != 0:
        print(out[-4000:])
        fail(f"pypelinec exited {result.returncode} (log: {log})")
    latencies = dict(re.findall(r"^AUTO_PIPELINE (\S+): (\d+) clks$", out, re.M))
    seeds = re.findall(r"^\[latency memory\] AUTO_PIPELINE (\S+): starts at (\d+) \((.*)\)$", out, re.M)
    return out, {k: int(v) for k, v in latencies.items()}, seeds


def profile_latencies(out_dir):
    """key -> built latency, from the build's latency_profile.json (written by
    every synthesizing build, whether or not pass 2 printed a harvest line)."""
    with open(os.path.join(out_dir, "latency_profile.json")) as f:
        return {e["key"]: e["latency"] for e in json.load(f)["entries"]}


def fail(msg):
    print("FAIL:", msg, flush=True)
    sys.exit(1)


def expect(cond, msg):
    if not cond:
        fail(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    root = args.out_dir or tempfile.mkdtemp(prefix="latency_memory_build_test_")
    os.makedirs(root, exist_ok=True)
    out_dir = os.path.join(root, "build")
    store = os.path.join(root, "store")
    for path in (
        out_dir, store, os.path.join(root, "hinted"), os.path.join(root, "stale"),
        os.path.join(root, "light"),
    ):
        shutil.rmtree(path, ignore_errors=True)

    # 1. Fresh: unseeded, pass 2, recorded in both places
    out, first, seeds = build(out_dir, "--syn_cache", store)
    expect(first and all(v > 0 for v in first.values()), f"no latency > 0 built: {first}")
    expect(PASS2 in out and not seeds, "a fresh build must run pass 2, unseeded")
    expect(
        re.search(r"^Latency memory: recorded 1 \(out_dir, store\)$", out, re.M),
        "the verified latency was not recorded in the output directory and the store",
    )
    with open(os.path.join(out_dir, "latency_profile.json")) as f:
        profile = json.load(f)
    (entry,) = profile["entries"]
    expect(entry["verified"] and entry["latency"] == list(first.values())[0], profile)
    expect(entry["seed"] is None and profile["tool"] == "device_models", profile)
    expect(profile["part"] is not None, f"the resolved part was not recorded: {profile}")
    with open(os.path.join(out_dir, "latency_memory.json")) as f:
        memory = json.load(f)
    expect(memory["AUTO_PIPELINE"][entry["key"]]["latency"] == entry["latency"], memory)
    store_files = [
        os.path.join(d, n) for d, _, ns in os.walk(os.path.join(store, "latency")) for n in ns
    ]
    expect(len(store_files) == 1, f"expected one store copy: {store_files}")

    # 2. Rebuild: seeded from the output directory, pass 2 skipped
    out, again, seeds = build(out_dir, "--syn_cache", store)
    expect(again == first, f"latency changed on a seeded rebuild: {first} -> {again}")
    expect(
        [(k, int(v)) for k, v, _ in seeds] == list(first.items()),
        f"the rebuild did not start from the remembered latency: {seeds}",
    )
    expect(seeds[0][2].startswith("latency memory:"), seeds)
    expect(SKIPPED in out and PASS2 not in out, "a seeded rebuild must skip pass 2")
    with open(os.path.join(out_dir, "latency_profile.json")) as f:
        entry = json.load(f)["entries"][0]
    expect(entry["seed"]["latency"] == entry["latency"], entry)

    # 3. --no_latency_memory: unseeded, pass 2, memory untouched
    before = os.path.getmtime(os.path.join(out_dir, "latency_memory.json"))
    out, off, seeds = build(out_dir, "--syn_cache", store, "--no_latency_memory")
    expect(off == first and not seeds and PASS2 in out, "--no_latency_memory must not seed")
    expect("(latency memory off)" in out, "the profile line should say the memory is off")
    expect(
        os.path.getmtime(os.path.join(out_dir, "latency_memory.json")) == before,
        "--no_latency_memory rewrote the memory",
    )

    # 4. Output directory gone: the store's copy seeds it
    shutil.rmtree(out_dir)
    out, restored, seeds = build(out_dir, "--syn_cache", store)
    expect(restored == first and SKIPPED in out, "the store's copy did not seed the build")
    expect(seeds and seeds[0][2].startswith("latency memory (store)"), seeds)

    # 5. A fresh directory, hints from the first profile
    hinted = os.path.join(root, "hinted")
    hints = os.path.join(root, "hints_profile.json")
    shutil.copy(os.path.join(out_dir, "latency_profile.json"), hints)
    out, from_hints, seeds = build(hinted, "--latency_hints", hints)
    expect(from_hints == first and SKIPPED in out, "hints did not seed a fresh directory")
    expect(seeds and seeds[0][2] == "hints hints_profile.json", seeds)

    # 6. A stale memory entry: same tag key, another function
    stale_dir = os.path.join(root, "stale")
    unmatched = os.path.join(root, "unmatched_hints.json")
    with open(unmatched, "w") as f:
        json.dump({"AUTO_PIPELINE": {"renamed_tag": 2}}, f)
    build(stale_dir, design=STALE_DESIGN)
    heavy = profile_latencies(stale_dir)
    expect(heavy.get("core", 0) > 0, f"the heavy core needs registers at 50 MHz: {heavy}")
    light_out, _, seeds = build(
        stale_dir, "-D", "LATENCY_MEMORY_HEAVY=0", "--latency_hints", unmatched,
        design=STALE_DESIGN,
    )
    expect(
        seeds and int(seeds[0][1]) == heavy["core"],
        f"the light rebuild should first read the remembered {heavy['core']}: {seeds}",
    )
    expect(
        "core: its function changed, so its sweep doesn't start at" in light_out,
        "the stale remembered latency was not recognized",
    )
    expect(
        "latency hint(s) matched no AUTO_PIPELINE" in light_out and "renamed_tag (hints" in light_out,
        "an unmatched hint was not reported",
    )
    light = profile_latencies(stale_dir)
    build(
        os.path.join(root, "light"), "-D", "LATENCY_MEMORY_HEAVY=0", "--no_latency_memory",
        design=STALE_DESIGN,
    )
    fresh = profile_latencies(os.path.join(root, "light"))
    expect(light == fresh, f"a stale entry changed the result: {light} vs memory-less {fresh}")
    print("PASS: latency memory seeds rebuilds, survives in the store, and stale entries are corrected")


if __name__ == "__main__":
    main()
