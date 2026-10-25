#!/usr/bin/env python3
"""Known issue: scoped operator registrations (register_*(..., scope=f)) do
not reach the hardware the way native simulation applies them.

Elaborates two designs with PY_TO_LOGIC.PARSE_FILE, each in its own process
(registrations are process-global), and checks which operator entities got
instantiated:

  scoped_operator_top_level_design.py
    scope= on a plain top-level @hw_func is ignored: the scoped soft adder is
    not used, and a scoped @struct `+` stops the build.
  scoped_operator_shared_callee_design.py
    a factory-closure callee reached from a scoped and an unscoped caller is
    one entity, built under whichever caller came first.

Same in-process approach as operator_scope_test.py: this is about what got
instantiated, which native sim never sees.

Exits 1 while either bug is present (registered expect_fail in
known_issues_tests.py), 0 once both are fixed.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..", "..")
TOP_LEVEL_DESIGN = os.path.join(HERE, "scoped_operator_top_level_design.py")
SHARED_CALLEE_DESIGN = os.path.join(HERE, "scoped_operator_shared_callee_design.py")


def child(design, out_dir):
    """Elaborates design and prints {func_name: [submodule func_names]}."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, os.path.join(ROOT, "include", "pypeline"))
    import PY_TO_LOGIC
    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    parser_state = PY_TO_LOGIC.PARSE_FILE(design)
    subs = {
        name: sorted(set(logic.submodule_instances.values()))
        for name, logic in parser_state.FuncLogicLookupTable.items()
    }
    print("SUBMODULES_JSON " + json.dumps(subs))


def elaborate(design, out_dir):
    """Returns (submodule map, None), or (None, the error's last line)."""
    os.makedirs(out_dir, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--child", design, out_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("SUBMODULES_JSON "):
            return json.loads(line[len("SUBMODULES_JSON "):]), None
    lines = proc.stdout.strip().splitlines()
    return None, lines[-1] if lines else f"exit {proc.returncode}"


def find(subs, prefix):
    names = [n for n in subs if n == prefix or n.startswith(prefix + "_s")]
    assert len(names) == 1, f"expected one {prefix} function, got {names}"
    return names[0]


def adder_kind(subs, func_name):
    kinds = set()
    for sub in subs[func_name]:
        if "soft_add_ripple" in sub:
            kinds.add("soft")
        elif sub.startswith("BIN_OP_PLUS_uint9_t_uint9_t"):
            kinds.add("built-in")
    return ",".join(sorted(kinds)) or "none"


def main():
    out_dir = sys.argv[sys.argv.index("--out_dir") + 1]
    failures = []

    subs, err = elaborate(TOP_LEVEL_DESIGN, os.path.join(out_dir, "top_level"))
    if subs is None:
        failures.append(f"top-level design does not elaborate: {err}")
    else:
        kind = adder_kind(subs, "top_scoped_int")
        print(f"top_scoped_int adder: {kind}")
        if kind != "soft":
            failures.append(f"top_scoped_int uses the {kind} adder, not the scoped soft one")
        if not any(s == "pair_add" for s in subs["top_scoped_struct"]):
            failures.append("top_scoped_struct does not instantiate pair_add")

    subs, err = elaborate(SHARED_CALLEE_DESIGN, os.path.join(out_dir, "shared_callee"))
    if subs is None:
        failures.append(f"shared-callee design does not elaborate: {err}")
    else:
        for caller, want in (("scoped_caller", "soft"), ("plain_caller", "built-in")):
            helpers = subs[find(subs, caller)]
            assert len(helpers) == 1, f"{caller} submodules: {helpers}"
            kind = adder_kind(subs, helpers[0])
            print(f"{caller} -> {helpers[0]}: {kind} adder")
            if kind != want:
                failures.append(f"{caller}'s helper uses the {kind} adder, expected {want}")

    for f in failures:
        print("FAIL: " + f)
    if failures:
        return 1
    print("PASS: scoped registrations reach the hardware")
    return 0


if __name__ == "__main__":
    if "--child" in sys.argv:
        i = sys.argv.index("--child")
        child(sys.argv[i + 1], sys.argv[i + 2])
        sys.exit(0)
    sys.exit(main())
