# pyright: reportInvalidTypeForm=none
"""@initial/@final hooks through the pypelinec driver: runs hooks_design.py in
a pypelinec subprocess and checks where its "HOOK: <name>" markers land in the
output, relative to the driver's own progress lines.

  --variant native_comb       --sim --comb: native simulation only
  --variant native_pipelined  --sim (sky130 build, then native sim)
  --variant vhdl_comb         --sim --comb --cocotb --ghdl
  --variant no_synth          --no_synth: build only
  --variant call_from_hw      a MAIN calling a hook fails elaboration

Build-only runs produce no hook events. On simulation runs the initial and
final markers surround the clocks exactly once.
"""

import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_SRC = os.path.join(HERE, "..", "..", "..")
PYPELINEC = os.path.join(REPO_SRC, "pypelinec")
DESIGN = os.path.join(HERE, "hooks_design.py")

VARIANT_ARGS = {
    "native_comb": ["--sim", "--comb", "--run", "all"],
    "native_pipelined": ["--sim", "--run", "all", "--syn_tool", "device_models"],
    "vhdl_comb": [
        "--sim", "--comb", "--cocotb", "--ghdl", "--run", "all",
        "--syn_tool", "device_models",
    ],
    "no_synth": ["--no_synth"],
    "call_from_hw": ["--no_synth"],
}
SIM_INITIALS = ["bare_initial", "sim_initial_a", "sim_initial_b"]
SIM_FINALS = ["bare_final", "sim_final"]


def _run(variant, out_dir):
    mode = "call_from_hw" if variant == "call_from_hw" else "finish"
    cmd = [sys.executable, PYPELINEC, DESIGN, "--out_dir", out_dir, "-D", f"HOOKS_TEST_MODE={mode}"]
    cmd += VARIANT_ARGS[variant]
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(proc.stdout, flush=True)
    return proc.returncode, proc.stdout.splitlines()


def _index(lines, pred, last=False):
    hits = [i for i, l in enumerate(lines) if pred(l)]
    assert hits, "expected output line not found"
    return hits[-1] if last else hits[0]


def _hook_positions(lines):
    """[(line index, hook name)] in output order."""
    return [
        (i, l.split("HOOK:", 1)[1].strip())
        for i, l in enumerate(lines)
        if l.startswith("HOOK:")
    ]


def _check_sim(lines, hooks):
    first_clk = _index(lines, lambda l: l.startswith("Clock:"))
    last_clk = _index(lines, lambda l: l.startswith("Clock:"), last=True)
    init = hooks[: len(SIM_INITIALS)]
    fin = hooks[len(SIM_INITIALS) :]
    assert sorted(n for _, n in init) == sorted(SIM_INITIALS), hooks
    assert sorted(n for _, n in fin) == sorted(SIM_FINALS), hooks
    assert all(i < first_clk for i, _ in init), (first_clk, init)
    assert all(i > last_clk for i, _ in fin), (last_clk, fin)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=sorted(VARIANT_ARGS))
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()

    rc, lines = _run(args.variant, args.out_dir)
    if args.variant == "call_from_hw":
        assert rc != 0, "a MAIN calling a hook elaborated"
        assert any("is an @initial/@final hook" in l for l in lines), "wrong error"
        print("hooks_order_test call_from_hw: passed")
        return
    assert rc == 0, f"pypelinec exited {rc}"
    hooks = _hook_positions(lines)
    if args.variant == "no_synth":
        assert not hooks, hooks
    else:
        _check_sim(lines, hooks)
    print(f"hooks_order_test {args.variant}: passed")


if __name__ == "__main__":
    main()
