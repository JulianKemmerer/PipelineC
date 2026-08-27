#!/usr/bin/env python3
"""Pure unit coverage for the sky130 area model: liberty area extraction,
mapped-netlist area summation, the leaf area_cache (SYN.GET_AREA_CACHE_DIR
and friends), and the whole-hierarchy estimate
(SYN.GET_ESTIMATED_COMBINATIONAL_AREA/ESTIMATE_DESIGN_AREA).

No yosys/GHDL is invoked anywhere here -- fixtures are tiny synthetic
mapped-JSON netlists and hand-built C_TO_LOGIC.Logic objects, matching
device_models_sta_test.py's own pattern for the STA engine.
"""

import json
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import DEVICE_MODELS
import C_TO_LOGIC
import SYN


DFF = "sky130_fd_sc_hvl__dfxtp_1"
INV = "sky130_fd_sc_hvl__inv_1"
AND2 = "sky130_fd_sc_hvl__and2_1"


def _write_netlist(module):
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="pipelinec_area_unit_"
    )
    json.dump({"modules": {"top": module}}, tmp)
    tmp.close()
    return tmp.name


class _ParserState:
    part = DEVICE_MODELS.SELECTED_LIBRARY
    func_marked_wires = set()
    func_marked_blackbox = set()

    def __init__(self):
        self.FuncLogicLookupTable = {}


def _leaf_logic(func_name):
    logic = C_TO_LOGIC.Logic()
    logic.func_name = func_name
    logic.is_c_built_in = True
    logic.inputs = ["a", "b"]
    logic.outputs = ["return_output"]
    logic.wire_to_c_type = {
        "a": "uint32_t",
        "b": "uint32_t",
        "return_output": "uint32_t",
    }
    return logic


def _hier_logic(func_name, sub_func_names):
    logic = C_TO_LOGIC.Logic()
    logic.func_name = func_name
    logic.is_c_built_in = False
    logic.inputs = []
    logic.outputs = []
    logic.wire_to_c_type = {}
    logic.submodule_instances = {
        f"inst_{i}": sub for i, sub in enumerate(sub_func_names)
    }
    return logic


def test_load_cell_areas_spot_values_and_full_coverage():
    areas = DEVICE_MODELS.LOAD_CELL_AREAS()
    assert areas[DFF] == 48.84, areas[DFF]
    # 57 cells total in the vendored liberty -- see src/liberty_data/README.
    assert len(areas) == 57, len(areas)
    for name, area in areas.items():
        assert area > 0.0, (name, area)


def test_get_sequential_cell_area_matches_dfxtp():
    area, unit = DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA()
    assert unit == "um2"
    assert area == 48.84


def test_measure_netlist_area_hand_computable_split():
    # 2 DFFs + 1 AND2 + 1 INV: sequential = 2*48.84, combinational = the rest.
    module = {
        "ports": {
            "clk": {"direction": "input", "bits": [1]},
            "d": {"direction": "input", "bits": [2]},
            "q": {"direction": "output", "bits": [6]},
        },
        "cells": {
            "ff0": {"type": DFF, "connections": {"CLK": [1], "D": [2], "Q": [3]}},
            "gate0": {"type": AND2, "connections": {"A": [3], "B": [2], "X": [4]}},
            "gate1": {"type": INV, "connections": {"A": [4], "Y": [5]}},
            "ff1": {"type": DFF, "connections": {"CLK": [1], "D": [5], "Q": [6]}},
        },
    }
    path = _write_netlist(module)
    try:
        result = DEVICE_MODELS.MEASURE_NETLIST_AREA(path, top="top")
    finally:
        os.unlink(path)

    areas = DEVICE_MODELS.LOAD_CELL_AREAS()
    expected_seq = 2 * areas[DFF]
    expected_comb = areas[AND2] + areas[INV]
    assert result["sequential_cell_area"] == expected_seq, result
    assert result["combinational_cell_area"] == expected_comb, result
    assert result["total_cell_area"] == expected_seq + expected_comb, result
    assert result["n_sequential_cells"] == 2, result
    assert result["n_unpriced_cells"] == 0, result
    assert result["area_unit"] == DEVICE_MODELS.AREA_UNIT, result
    assert result["cell_area_histogram"] == {DFF: 2, AND2: 1, INV: 1}, result


def test_measure_netlist_area_reports_unpriced_cells_without_crashing():
    module = {
        "ports": {},
        "cells": {
            "mystery": {"type": "not_a_real_cell", "connections": {}},
            "gate0": {"type": AND2, "connections": {}},
        },
    }
    path = _write_netlist(module)
    try:
        result = DEVICE_MODELS.MEASURE_NETLIST_AREA(path, top="top")
    finally:
        os.unlink(path)
    areas = DEVICE_MODELS.LOAD_CELL_AREAS()
    assert result["n_unpriced_cells"] == 1, result
    assert result["combinational_cell_area"] == areas[AND2], result


def test_path_report_parses_area_lines():
    text = (
        "Worst period (ns): 1.0\n"
        "Total cell area: 1013.918400 um2\n"
        "Combinational cell area: 1013.918400 um2\n"
        "Sequential cell area: 0.000000 um2\n"
        "N sequential cells: 0\n"
        "N unpriced cells: 0\n"
        "Area model version: 1\n"
    )
    report = DEVICE_MODELS.PathReport(text)
    assert report.total_cell_area == 1013.9184
    assert report.combinational_cell_area == 1013.9184
    assert report.sequential_cell_area == 0.0
    assert report.area_unit == "um2"
    assert report.n_sequential_cells == 0
    assert report.n_unpriced_cells == 0
    assert report.area_model_version == 1


def test_path_report_area_fields_default_none_when_absent():
    report = DEVICE_MODELS.PathReport("Worst period (ns): 1.0\n")
    assert report.total_cell_area is None
    assert report.area_unit is None
    assert report.area_model_version is None


def test_area_cache_dir_identity():
    parser_state = _ParserState()
    old_tool = SYN.SYN_TOOL
    old_recipe = DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE
    try:
        # No area source for a non-DEVICE_MODELS tool.
        SYN.SYN_TOOL = SYN.PYRTL
        assert SYN.GET_AREA_CACHE_DIR(parser_state) is None

        SYN.SYN_TOOL = DEVICE_MODELS
        DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE = (
            DEVICE_MODELS._DEFAULT_SYNTHESIS_RECIPE
        )
        production_path = SYN.GET_AREA_CACHE_DIR(parser_state)
        assert f"_a{DEVICE_MODELS.AREA_MODEL_VERSION}" in production_path, (
            production_path
        )
        # Independent of MODEL_VERSION: an STA-only version bump must not
        # appear in (or invalidate) the area cache identity.
        assert f"_v{DEVICE_MODELS.MODEL_VERSION}" not in production_path, (
            production_path
        )
        assert production_path.endswith("/syn")

        DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE = "synth_flatten"
        flatten_path = SYN.GET_AREA_CACHE_DIR(parser_state)
        suffix = DEVICE_MODELS.GET_SYNTHESIS_RECIPE_CACHE_SUFFIX("synth_flatten")
        assert suffix in flatten_path, flatten_path
        assert suffix not in production_path, production_path
    finally:
        SYN.SYN_TOOL = old_tool
        DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE = old_recipe


def test_area_cache_dir_honours_env_override():
    parser_state = _ParserState()
    old_tool = SYN.SYN_TOOL
    old_env = os.environ.get("PYPELINEC_AREA_CACHE_DIR")
    try:
        SYN.SYN_TOOL = DEVICE_MODELS
        os.environ["PYPELINEC_AREA_CACHE_DIR"] = "/tmp/some_override_dir/"
        path = SYN.GET_AREA_CACHE_DIR(parser_state)
        assert path.startswith("/tmp/some_override_dir/"), path
    finally:
        SYN.SYN_TOOL = old_tool
        if old_env is None:
            os.environ.pop("PYPELINEC_AREA_CACHE_DIR", None)
        else:
            os.environ["PYPELINEC_AREA_CACHE_DIR"] = old_env


def test_leaf_area_cache_round_trip_and_unit_mismatch():
    parser_state = _ParserState()
    logic = _leaf_logic("BIN_OP_AND_uint32_t_uint32_t")
    old_tool = SYN.SYN_TOOL
    with tempfile.TemporaryDirectory(prefix="pipelinec_area_cache_unit_") as tmp_dir:
        old_env = os.environ.get("PYPELINEC_AREA_CACHE_DIR")
        try:
            SYN.SYN_TOOL = DEVICE_MODELS
            os.environ["PYPELINEC_AREA_CACHE_DIR"] = tmp_dir + "/"

            assert SYN.GET_CACHED_LEAF_AREA(logic, parser_state) is None

            SYN.WRITE_CACHED_LEAF_AREA(logic, parser_state, 255886.4, "um2")
            value, unit = SYN.GET_CACHED_LEAF_AREA(logic, parser_state)
            assert value == 255886.4
            assert unit == "um2"

            path = SYN.GET_CACHED_LEAF_AREA_FILE_PATH(logic, parser_state)
            assert open(path).read().strip() == "255886.4 um2"

            # A stored unit that disagrees with the active model's own unit
            # is a miss, not a silent mix.
            with open(path, "w") as f:
                f.write("255886.4 lut\n")
            assert SYN.GET_CACHED_LEAF_AREA(logic, parser_state) is None
        finally:
            SYN.SYN_TOOL = old_tool
            if old_env is None:
                os.environ.pop("PYPELINEC_AREA_CACHE_DIR", None)
            else:
                os.environ["PYPELINEC_AREA_CACHE_DIR"] = old_env


def test_get_estimated_combinational_area_sums_across_hierarchy():
    parser_state = _ParserState()
    leaf_a = _leaf_logic("BIN_OP_AND_uint32_t_uint32_t")
    leaf_b = _leaf_logic("BIN_OP_OR_uint32_t_uint32_t")
    # Two calls to leaf_a, one to leaf_b -- area must scale with call count,
    # not unique-leaf count (mirrors GET_REGISTERS_ESTIMATE_TEXT_AND_FFS's
    # own per-instance-not-per-function counting).
    mid = _hier_logic("mid", [leaf_a.func_name, leaf_a.func_name])
    top = _hier_logic("top", [mid.func_name, leaf_b.func_name])
    parser_state.FuncLogicLookupTable = {
        leaf_a.func_name: leaf_a,
        leaf_b.func_name: leaf_b,
        mid.func_name: mid,
        top.func_name: top,
    }

    old_tool = SYN.SYN_TOOL
    with tempfile.TemporaryDirectory(prefix="pipelinec_area_cache_unit_") as tmp_dir:
        old_env = os.environ.get("PYPELINEC_AREA_CACHE_DIR")
        try:
            SYN.SYN_TOOL = DEVICE_MODELS
            os.environ["PYPELINEC_AREA_CACHE_DIR"] = tmp_dir + "/"
            SYN.WRITE_CACHED_LEAF_AREA(leaf_a, parser_state, 10.0, "um2")
            SYN.WRITE_CACHED_LEAF_AREA(leaf_b, parser_state, 100.0, "um2")

            area, unit, missing = SYN.GET_ESTIMATED_COMBINATIONAL_AREA(
                top, parser_state
            )
            assert area == 2 * 10.0 + 100.0, area
            assert unit == "um2"
            assert missing == frozenset()
        finally:
            SYN.SYN_TOOL = old_tool
            if old_env is None:
                os.environ.pop("PYPELINEC_AREA_CACHE_DIR", None)
            else:
                os.environ["PYPELINEC_AREA_CACHE_DIR"] = old_env


def test_get_estimated_combinational_area_reports_missing_leaf():
    parser_state = _ParserState()
    leaf = _leaf_logic("BIN_OP_AND_uint32_t_uint32_t")
    top = _hier_logic("top", [leaf.func_name])
    parser_state.FuncLogicLookupTable = {leaf.func_name: leaf, top.func_name: top}

    old_tool = SYN.SYN_TOOL
    with tempfile.TemporaryDirectory(prefix="pipelinec_area_cache_unit_") as tmp_dir:
        old_env = os.environ.get("PYPELINEC_AREA_CACHE_DIR")
        try:
            SYN.SYN_TOOL = DEVICE_MODELS
            os.environ["PYPELINEC_AREA_CACHE_DIR"] = tmp_dir + "/"
            # No WRITE_CACHED_LEAF_AREA call -- cache stays cold.
            area, unit, missing = SYN.GET_ESTIMATED_COMBINATIONAL_AREA(
                top, parser_state
            )
            assert area == 0.0, area
            assert missing == frozenset({leaf.func_name}), missing
        finally:
            SYN.SYN_TOOL = old_tool
            if old_env is None:
                os.environ.pop("PYPELINEC_AREA_CACHE_DIR", None)
            else:
                os.environ["PYPELINEC_AREA_CACHE_DIR"] = old_env


def test_get_estimated_combinational_area_zero_delay_leaf_not_counted_missing():
    # A pure-wiring leaf (bit concat, matched by SW_LIB.IS_BIT_MANIP_NAME's
    # "u?intN_uintM" pattern) is excluded from synthesis entirely by
    # LOGIC_IS_ZERO_DELAY, so it correctly has no area_cache entry -- that
    # must not be reported as a coverage gap.
    parser_state = _ParserState()
    wiring_leaf = _leaf_logic("uint32_uint32")
    top = _hier_logic("top", [wiring_leaf.func_name])
    parser_state.FuncLogicLookupTable = {
        wiring_leaf.func_name: wiring_leaf,
        top.func_name: top,
    }

    old_tool = SYN.SYN_TOOL
    with tempfile.TemporaryDirectory(prefix="pipelinec_area_cache_unit_") as tmp_dir:
        old_env = os.environ.get("PYPELINEC_AREA_CACHE_DIR")
        try:
            SYN.SYN_TOOL = DEVICE_MODELS
            os.environ["PYPELINEC_AREA_CACHE_DIR"] = tmp_dir + "/"
            area, unit, missing = SYN.GET_ESTIMATED_COMBINATIONAL_AREA(
                top, parser_state
            )
            assert area == 0.0, area
            assert missing == frozenset(), missing
        finally:
            SYN.SYN_TOOL = old_tool
            if old_env is None:
                os.environ.pop("PYPELINEC_AREA_CACHE_DIR", None)
            else:
                os.environ["PYPELINEC_AREA_CACHE_DIR"] = old_env


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
