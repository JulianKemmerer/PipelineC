#!/usr/bin/env python3
"""AUTOFSM real-sky130-area A/B: does ranking with real cached leaf/register/
multiplexer um2 (docs/AUTOFSM_DESIGN.md section 3.8) ever measure WORSE than
the abstract per-bit model, AS BUILT?

Ground truth throughout this test is real sky130 synthesis output --
DEVICE_MODELS.MEASURE_NETLIST_AREA's exact per-cell sum, printed as
"Measured area: ..." -- never the abstract model's own estimate. That
mirrors autofsm_area_sweep_compare_test.py's and autofsm_min_area_verify_test
.py's own method (build alternatives, count what synthesis actually produced)
but swaps their yosys-cell-count signal for the more direct one sky130
provides: a real measured um2 total for the whole design.

Method: build qor/divider/autofsm.py three ways.
  (default)               real sky130 um2 ranks the area search
  --autofsm_abstract_area the abstract per-bit model ranks it instead
  --autofsm_no_area_sweep no search at all -- the plain share-everything
                          schedule, common anchor for both rankings above
Then compare each variant's real measured area, and separately check the
register-count fidelity question docs/AUTOFSM_DESIGN.md section 3.8 raises
explicitly: does AUTOFSM's OWN register allocator (AUTOFSM.ALLOCATE_REGISTERS,
printed as "register bits: ..." by DESCRIBE_SCHEDULE) have anything like the
5.7-5.9x overshoot SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS's whole-design
estimate is already known to have. If it does, a real-um2 register term
(_ff_area_um2) would be amplifying a bad count rather than fixing one, and
that is worth knowing before trusting this ranking on a state-heavy design.

Uses an isolated PYPELINEC_AREA_CACHE_DIR (shared across the three builds, so
later variants benefit from what an earlier one already measured, but never
touching -- or depending on -- the real committed area_cache/) matching
area_estimate_build_report_test.py's own pattern.

What this design does NOT exercise: qor/divider/autofsm.py's schedule is AT
FLOOR (one indivisible 34-bit subtract sets a hard per-state ceiling, see
that file's own comment) -- the search has no open/unshare move available at
all (0 kind(s) opened up, 0 kind(s) given extra unit(s) in every variant's
own build log), so all three rankings necessarily land on the SAME schedule
here and measure IDENTICAL real area. That is itself a useful check (a
divergence between them on a floor design, where only one schedule is even
feasible, would be a real bug), but it is not the stronger "does real data
pick a DIFFERENT, smaller schedule than the abstract model would have"
question -- autofsm_min_area_verify_test.py's div-share design is built
specifically to have that decision, under PYRTL; redoing it under sky130
would be the natural next step and is not attempted here.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "..", "qor", "divider", "autofsm.py")

# The real-area-ranked build may not measure worse than the abstract-ranked
# build by more than this. A tolerance, not a target -- both are per-leaf
# sums over the same kind of cross-instance-sharing blind spot (see the note
# on GET_ESTIMATED_COMBINATIONAL_AREA), so a couple of percent of noise
# between two reasonable rankings is expected; a real regression (real data
# choosing a systematically worse schedule) blows straight through it.
MAX_REGRESSION = 0.05


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(out_dir, extra, area_cache_dir):
    cmd = [sys.executable, PYPELINEC, DESIGN, "--out_dir", out_dir] + extra
    env = dict(os.environ)
    env["PYPELINEC_AREA_CACHE_DIR"] = area_cache_dir
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        fail(f"build {extra} exited nonzero ({result.returncode})")
    return result.stdout


def measured_area(out):
    m = re.search(r"Measured area: ([\d.]+) um2", out)
    if not m:
        fail("no 'Measured area: ...' line -- expected a real sky130 "
             "confirmation synthesis to have run")
    return float(m.group(1))


def n_sequential_cells(out_dir):
    """Real synthesized flip-flop count, from the whole-design STA log
    DEVICE_MODELS writes beside the multimain top (same file
    area_estimate_build_report_test.py's mode-2 check confirms exists)."""
    top_dir = os.path.join(out_dir, "top")
    logs = [
        os.path.join(top_dir, f)
        for f in os.listdir(top_dir)
        if f.startswith("device_models_") and f.endswith(".log")
        and "_synth" not in f
    ]
    if not logs:
        fail(f"no device_models_*.log found under {top_dir}")
    logs.sort(key=os.path.getmtime)
    text = open(logs[-1]).read()
    m = re.search(r"N sequential cells:\s*(\d+)", text)
    if not m:
        fail(f"no 'N sequential cells: ...' line in {logs[-1]}")
    return int(m.group(1))


def register_bits(out):
    m = re.search(r"register bits:\s*(\d+)", out)
    if not m:
        fail("no 'register bits: ...' line -- expected DESCRIBE_SCHEDULE to "
             "print AUTOFSM's own register allocation")
    return int(m.group(1))


def area_model_line(out):
    m = re.search(r"area model:\s*(.+)", out)
    return m.group(1).strip() if m else None


def area_model_counts(out):
    """(measured, estimated) leaf count parsed out of a "sky130 um2 (N
    leaf/leaves measured, M estimated)" area model line, or None if the line
    isn't in that shape (abstract, or missing). A build reporting "sky130"
    with 0 measured is NOT the same thing as this test passing -- it means
    every term fell back to the abstract estimate, i.e. the real cache
    lookup path never actually engaged, which is silent unless something
    checks the counts and not just the word "sky130"."""
    m = re.search(
        r"area model:\s*sky130 um2 \((\d+) leaf/leaves measured, "
        r"(\d+) estimated\)",
        out,
    )
    return (int(m.group(1)), int(m.group(2))) if m else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    base = args.out_dir
    cleanup = False
    if base is None:
        base = tempfile.mkdtemp(prefix="autofsm_real_area_compare_")
        cleanup = True
    area_cache_dir = os.path.join(base, "area_cache")

    variants = [
        ("real sky130 um2 (default)", "real", []),
        ("abstract model", "abstract", ["--autofsm_abstract_area"]),
        ("no area sweep (anchor)", "anchor", ["--autofsm_no_area_sweep"]),
    ]

    results = {}
    for label, sub, extra in variants:
        out_dir = os.path.join(base, sub)
        out = run_build(out_dir, extra, area_cache_dir)
        results[sub] = {
            "label": label,
            "out": out,
            "out_dir": out_dir,
            "measured": measured_area(out),
            "reg_bits": register_bits(out),
            "n_seq": n_sequential_cells(out_dir),
        }

    real_counts = area_model_counts(results["real"]["out"])
    if real_counts is None:
        fail(
            "default build's area model line does not match the expected "
            "'sky130 um2 (N measured, M estimated)' shape -- got "
            f"{area_model_line(results['real']['out'])!r}. "
            "qor/divider/autofsm.py declares PART(\"sky130\"); is "
            "SYN_TOOL resolving to DEVICE_MODELS?"
        )
    if real_counts[0] == 0:
        fail(
            f"default build's area model measured 0 real leaves (all "
            f"{real_counts[1]} estimated) -- the real sky130 cache lookup "
            "path never actually engaged (a silently broken cache key or "
            "lookup would look exactly like this: 'sky130' still appears in "
            "the line, just with nothing real behind it), which is the "
            "thing this test exists to catch"
        )
    if "area model: abstract" not in results["abstract"]["out"]:
        fail(
            "--autofsm_abstract_area build's area model line does not say "
            f"abstract -- got {area_model_line(results['abstract']['out'])!r}"
        )

    print()
    print("=== AUTOFSM real-sky130-area A/B (measured um2, whole design) ===")
    for sub in ("anchor", "abstract", "real"):
        r = results[sub]
        print(
            f"  {r['label']:<28} {r['measured']:>10.1f} um2  "
            f"(AUTOFSM reg bits {r['reg_bits']:>4}, real seq cells {r['n_seq']:>4})"
        )
    real_vs_abstract = (
        (results["real"]["measured"] - results["abstract"]["measured"])
        / results["abstract"]["measured"]
    )
    print(f"  real vs abstract                : {real_vs_abstract * 100:+.1f}%")
    print()

    if real_vs_abstract > MAX_REGRESSION:
        fail(
            f"ranking with real sky130 um2 measured {real_vs_abstract * 100:.1f}%"
            f" WORSE than ranking with the abstract model "
            f"({results['abstract']['measured']:.1f} -> "
            f"{results['real']['measured']:.1f} um2). Ground truth here is "
            f"real synthesis, so this is the model that should be losing, "
            f"not winning -- see docs/AUTOFSM_DESIGN.md section 3.8 for the "
            f"known cross-instance-sharing and FF-count caveats before "
            f"assuming a fix is needed in the ranking itself."
        )

    # The register-fidelity question section 3.8 asks to check explicitly:
    # does AUTOFSM's OWN allocator have anything like the 5.7-5.9x overshoot
    # already documented for SYN's generic whole-design FF estimate? Report
    # it either way -- this is a measurement, not a pass/fail gate, since a
    # real gap here would be a finding for AUTOFSM's allocator, not evidence
    # against ranking with real per-FF um2 (a 48.84 um2 flip-flop is what
    # sky130 actually charges regardless of how many of them there are).
    r = results["real"]
    if r["n_seq"] > 0:
        ratio = r["reg_bits"] / r["n_seq"]
        print(
            f"AUTOFSM register allocator: {r['reg_bits']} bits vs "
            f"{r['n_seq']} real synthesized sequential cells "
            f"({ratio:.2f}x). SYN.GET_REGISTERS_ESTIMATE_TEXT_AND_FFS's own "
            f"whole-design estimate is separately documented to overshoot "
            f"real FF count 5.7-5.9x on a state-heavy design -- this is "
            f"AUTOFSM's allocator, a different and narrower count, reported "
            f"here for the record rather than gated on."
        )

    print(
        f"AUTOFSM real-area A/B passed: real sky130 um2 measured "
        f"{real_vs_abstract * 100:+.1f}% vs the abstract model, as built "
        f"(within the {MAX_REGRESSION * 100:.0f}% regression tolerance)."
    )


if __name__ == "__main__":
    main()
