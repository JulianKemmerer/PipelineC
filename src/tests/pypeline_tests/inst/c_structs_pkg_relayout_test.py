#!/usr/bin/env python3
"""c_structs_pkg stays valid VHDL when a type's layout changes between parse
passes of one run but its emitted VHDL name doesn't.

WireGuard's shared build failed in AUTO_PIPELINE pass 2 with Vivado
"[Synth 8-989] ... is already declared". Its Poly1305 powers_t is sized by an
AUTO_PIPELINE .latency, not a factory parameter: 2 lanes in pass 1, 5 in
pass 2. The logical C type changed, but each pass's emitted name was the
same. The grow-only package merged its chunks by logical C type, so it kept
the pass-1 declaration and appended the pass-2 one.

This test runs the same passes in process, as the pypelinec pin-and-confirm
loop does (no synthesis): parse c_structs_pkg_relayout_design.py with an
empty latency cache, then with encrypt/decrypt latencies 3/5 (lanes 5/7),
writing the package into one output directory each time. After every pass
GHDL must analyze the package, and after pass 2 each powers_t must be
declared once, with pass 2's lane count. A third, identical pass must leave
the file untouched. generated_vhdl_stability_test covers the merge rules.
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC  # noqa: F401  (import order: VHDL's import chain)
import PY_TO_LOGIC
import SYN
import VHDL
import pypeline

INST_DIR = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.join(INST_DIR, "c_structs_pkg_relayout_design.py")
# body_ap.latency per direction in pass 2; lanes = latency + 2.
PASS2_LATENCY = {"encrypt": 3, "decrypt": 5}


def _package_path():
    return os.path.join(SYN.SYN_OUTPUT_DIRECTORY, "c_structs_pkg" + VHDL.VHDL_PKG_EXT)


def _parse_and_write_package(latency_cache):
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE(latency_cache)
    parser_state = PY_TO_LOGIC.PARSE_FILE(DESIGN)
    VHDL.WRITE_C_DEFINED_VHDL_STRUCTS_PACKAGE(parser_state)
    with open(_package_path()) as f:
        return parser_state, f.read()


def _powers_types(parser_state):
    """direction -> (logical C type, emitted VHDL name) of its powers_t."""
    names = parser_state.pypeline_emission_names
    rv = {}
    for raw in parser_state.struct_to_field_type_dict:
        if raw.startswith("powers_t_"):
            direction = raw.rsplit("_direction_", 1)[1]
            rv[direction] = (raw, names.identifier(raw))
    assert sorted(rv) == ["decrypt", "encrypt"], rv
    return rv


def _ghdl_analyze(label):
    work = tempfile.mkdtemp(prefix="ghdl_work_", dir=SYN.SYN_OUTPUT_DIRECTORY)
    result = subprocess.run(
        ["ghdl", "-a", "--std=08", "-frelaxed", "--workdir=" + work, _package_path()],
        cwd=work,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{label}: GHDL rejected c_structs_pkg:\n{result.stdout}{result.stderr}"
    )


def _values_array_type(package, emitted_name):
    declarations = re.findall(
        rf"(?im)^\s*type\s+{re.escape(emitted_name)}\s+is\s+record\s+values\s*:\s*(\w+)\s*;",
        package,
    )
    assert len(declarations) == 1, (
        f"{emitted_name} declared {len(declarations)} times (expected once)"
    )
    return declarations[0]


def _check_relayout_passes():
    ps1, package1 = _parse_and_write_package({})
    _ghdl_analyze("pass 1")
    pass1 = _powers_types(ps1)
    for direction, (_raw, emitted) in pass1.items():
        assert _values_array_type(package1, emitted) == "uint32_t_2", direction

    # Pass 2: the harvested latencies, keyed like the driver's cache.
    keys = {
        key
        for logic in ps1.FuncLogicLookupTable.values()
        for key in logic.sub_inst_to_auto_pipeline_key.values()
    }
    cache = {}
    for direction, latency in PASS2_LATENCY.items():
        (key,) = [k for k in keys if f"direction_{direction}" in k]
        cache[key] = latency
    ps2, package2 = _parse_and_write_package(cache)
    pass2 = _powers_types(ps2)
    for direction in PASS2_LATENCY:
        # The WireGuard shape: a new logical type, the same VHDL name.
        assert pass1[direction][0] != pass2[direction][0], direction
        assert pass1[direction][1] == pass2[direction][1], (
            f"{direction}: emitted names differ between passes, so this "
            "no longer exercises one VHDL name with two layouts"
        )
    _ghdl_analyze("pass 2")
    for direction, latency in PASS2_LATENCY.items():
        lanes = latency + 2
        emitted = pass2[direction][1]
        assert _values_array_type(package2, emitted) == f"uint32_t_{lanes}", (
            direction
        )

    # A confirmation pass with the same latencies rewrites nothing.
    before = os.stat(_package_path()).st_mtime_ns
    _ps3, package3 = _parse_and_write_package(cache)
    assert package3 == package2
    assert os.stat(_package_path()).st_mtime_ns == before, (
        "an unchanged package was rewritten"
    )


def test_relayout_between_passes_keeps_package_valid():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_relayout_test_") as out_dir:
        SYN.SYN_OUTPUT_DIRECTORY = out_dir
        try:
            _check_relayout_passes()
        finally:
            pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
