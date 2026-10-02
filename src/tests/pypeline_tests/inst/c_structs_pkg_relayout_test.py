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

import C_TO_LOGIC  # (also first: VHDL's import chain)
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


def _declaration(package, emitted_name):
    """The one record declaration of emitted_name (asserted unique)."""
    declarations = re.findall(
        rf"(?ims)^\s*type\s+{re.escape(emitted_name)}\s+is\s+record\b(.*?)end\s+record\s*;",
        package,
    )
    assert len(declarations) == 1, (
        f"{emitted_name} declared {len(declarations)} times (expected once)"
    )
    return " ".join(declarations[0].split())


def _lane_sel_name(parser_state, direction):
    names = parser_state.pypeline_emission_names
    (raw,) = [
        r for r in parser_state.struct_to_field_type_dict
        if r.startswith("lane_sel_t_") and r.endswith("_direction_" + direction)
    ]
    return raw, names.identifier(raw)


def test_resize_through_discovered_depths_in_one_out_dir():
    """Harvested body depths 0, 1, 3, 6 (lanes 2, 3, 5, 8), then back to 1,
    all in one output directory. Each pass re-elaborates the outer design
    with that depth: powers_t and lane_sel_t (whose index width follows the
    lane count) keep one VHDL name, are declared once with the current
    layout, and the package plus the lane-select RTL analyze in GHDL. Only
    encrypt's cache entry changes; decrypt's types stay byte-identical."""
    decrypt_latency = 3
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_depths_test_") as out_dir:
        SYN.SYN_OUTPUT_DIRECTORY = out_dir
        top = SYN.TOP_LEVEL_MODULE
        SYN.TOP_LEVEL_MODULE = top or "top"
        try:
            ps1, _ = _parse_and_write_package({})
            keys = {
                k for logic in ps1.FuncLogicLookupTable.values()
                for k in logic.sub_inst_to_auto_pipeline_key.values()
            }
            (enc_key,) = [k for k in keys if "direction_encrypt" in k]
            (dec_key,) = [k for k in keys if "direction_decrypt" in k]
            decrypt_declaration = None
            for depth in (0, 1, 3, 6, 1):
                lanes = depth + 2
                cache = {enc_key: depth, dec_key: decrypt_latency}
                ps, package = _parse_and_write_package(cache)
                # The outer design was re-elaborated with this depth: one
                # encrypt body call per lane.
                calls = [
                    local
                    for logic in ps.FuncLogicLookupTable.values()
                    for local, key in logic.sub_inst_to_auto_pipeline_key.items()
                    if key == enc_key
                ]
                assert len(calls) == lanes, (depth, calls)
                powers = _powers_types(ps)
                assert _values_array_type(package, powers["encrypt"][1]) == f"uint32_t_{lanes}"
                assert _values_array_type(package, powers["decrypt"][1]) == f"uint32_t_{decrypt_latency + 2}"
                raw, emitted = _lane_sel_name(ps, "encrypt")
                width = max(1, (lanes - 1).bit_length())
                assert ps.struct_to_field_type_dict[raw]["lane"] == f"uint{width}_t", raw
                assert f"lane : unsigned({width - 1} downto 0);" in _declaration(package, emitted), (
                    depth, _declaration(package, emitted)
                )
                _raw_dec, emitted_dec = _lane_sel_name(ps, "decrypt")
                current = (
                    _declaration(package, powers["decrypt"][1]),
                    _declaration(package, emitted_dec),
                    powers["decrypt"][0],
                )
                if decrypt_declaration is None:
                    decrypt_declaration = current
                assert current == decrypt_declaration, (depth, current, decrypt_declaration)
                _ghdl_analyze(f"depth {depth}")
                C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(ps)
                pick = _isolated_files(ps, "pick")
                _ghdl_analyze_files(pick, f"depth {depth} pick")
        finally:
            SYN.TOP_LEVEL_MODULE = top
            pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})


def _isolated_files(parser_state, func_prefix):
    """Isolated-synthesis VHDL list for the first encrypt-direction func_prefix call."""
    import AUTO_PIPELINE

    inst = min(
        i for i, logic in parser_state.LogicInstLookupTable.items()
        if logic.func_name.startswith(func_prefix + "_direction_encrypt")
    )
    logic = parser_state.LogicInstLookupTable[inst]
    params = AUTO_PIPELINE.MultiMainTimingParams()
    params.TimingParamsLookupTable = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
    # As an isolated synthesis does: entity, then its top wrapper, then the list.
    directory = SYN.GET_OUTPUT_DIRECTORY(logic)
    os.makedirs(directory, exist_ok=True)
    VHDL.WRITE_LOGIC_ENTITY(inst, logic, directory, parser_state, params.TimingParamsLookupTable)
    VHDL.WRITE_LOGIC_TOP(inst, logic, directory, parser_state, params.TimingParamsLookupTable)
    files, _top = SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP(params, parser_state, inst)
    return files.split()


def _scoped_package(files):
    (pkg,) = [f for f in files if os.path.basename(f).startswith("c_structs_pkg")]
    assert os.path.dirname(pkg).endswith(VHDL.C_STRUCTS_PKG_SCOPED_DIR), pkg
    with open(pkg) as f:
        return pkg, f.read()


def _ghdl_analyze_files(files, label):
    work = tempfile.mkdtemp(prefix="ghdl_work_", dir=SYN.SYN_OUTPUT_DIRECTORY)
    # Vivado orders read_vhdl itself; GHDL needs packages, then submodules
    # (listed after their users) before the entities that use them.
    packages = [f for f in files if f.endswith(VHDL.VHDL_PKG_EXT)]
    ordered = packages + [f for f in reversed(files) if f not in packages]
    result = subprocess.run(
        ["ghdl", "-a", "--std=08", "-frelaxed", "--workdir=" + work] + ordered,
        cwd=work, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"{label}: GHDL rejected:\n{result.stdout}{result.stderr}"


def test_isolated_synthesis_reads_only_its_types():
    """The WireGuard pass-2 cost: a lane-sized powers_t change invalidated
    every isolated synthesis, used or not. Each isolated synthesis now reads
    a c_structs_pkg holding only the types its files use. body (uint32_t
    only) keeps the same package bytes across the relayout; mac (acc_t,
    powers_t) gets a new one. Both analyze in GHDL."""
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_scoped_test_") as out_dir:
        SYN.SYN_OUTPUT_DIRECTORY = out_dir
        top = SYN.TOP_LEVEL_MODULE
        SYN.TOP_LEVEL_MODULE = top or "top"  # set by the driver
        try:
            ps1, _ = _parse_and_write_package({})
            C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(ps1)  # every entity, as the driver does
            names = _powers_types(ps1)
            body1, mac1 = _isolated_files(ps1, "body_v"), _isolated_files(ps1, "mac")
            body_pkg1, body_text = _scoped_package(body1)
            mac_pkg1, mac_text = _scoped_package(mac1)
            for direction, (_raw, emitted) in names.items():
                assert emitted.lower() not in body_text.lower(), direction
            emitted = names["encrypt"][1]
            assert re.search(rf"(?im)^\s*type\s+{re.escape(emitted)}\s+is\s+record", mac_text)
            # Unused: the other direction's types.
            assert names["decrypt"][1].lower() not in mac_text.lower()
            _ghdl_analyze_files(body1, "pass 1 body")
            _ghdl_analyze_files(mac1, "pass 1 mac")

            keys = {k for logic in ps1.FuncLogicLookupTable.values()
                    for k in logic.sub_inst_to_auto_pipeline_key.values()}
            cache = {k: PASS2_LATENCY["encrypt" if "direction_encrypt" in k else "decrypt"] for k in keys}
            ps2, _ = _parse_and_write_package(cache)
            C_TO_LOGIC.WRITE_0_ADDED_CLKS_INIT_FILES(ps2)
            body2, mac2 = _isolated_files(ps2, "body_v"), _isolated_files(ps2, "mac")
            assert _scoped_package(body2)[0] == body_pkg1, "unrelated type change moved body's package"
            assert _scoped_package(mac2)[0] != mac_pkg1, "mac's powers_t change was not seen"
            _ghdl_analyze_files(mac2, "pass 2 mac")
        finally:
            SYN.TOP_LEVEL_MODULE = top
            pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})


def test_scoped_package_selection_rules():
    """Synthetic chunk index: a use of only an enum literal or a conversion
    function pulls in its type; record fields pull in their element types;
    unused types stay out; an unreadable input falls back (None)."""
    import json
    from types import SimpleNamespace

    chunks = [
        ["state_t", "type state_t is (IDLE, RUN);\n", ""],
        ["pair_t", "type pair_t is record a : uint8_t; end record;\nfunction pair_t_to_slv(x : pair_t) return std_logic_vector;\n",
         "function pair_t_to_slv(x : pair_t) return std_logic_vector is begin return std_logic_vector(x.a); end function;\n"],
        ["outer_t", "type outer_t is record p : pair_t; end record;\n", ""],
        ["unused_t", "type unused_t is record b : uint8_t; end record;\n", ""],
    ]
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_scoped_rules_") as out_dir:
        SYN.SYN_OUTPUT_DIRECTORY = out_dir
        with open(os.path.join(out_dir, VHDL.C_STRUCTS_PKG_CHUNKS_FILE), "w") as f:
            json.dump({"format": VHDL.C_STRUCTS_PKG_CHUNKS_FORMAT,
                       "prefix": ["package c_structs_pkg is\n", ""], "chunks": chunks}, f)
        entity = os.path.join(out_dir, "e.vhd")
        with open(entity, "w") as f:
            f.write("signal s : outer_t;\n-- x <= IDLE;\nif st = IDLE then\n")
        ps = SimpleNamespace()
        with open(VHDL.SCOPED_C_STRUCTS_PACKAGE([entity], ps)) as f:
            text = f.read()
        for name in ("state_t", "pair_t", "outer_t", "pair_t_to_slv"):
            assert name in text, name
        assert "unused_t" not in text
        # Package (dependency) order is kept.
        assert text.index("type state_t") < text.index("type pair_t") < text.index("type outer_t")
        assert VHDL.SCOPED_C_STRUCTS_PACKAGE([entity + ".missing"], ps) is None


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
