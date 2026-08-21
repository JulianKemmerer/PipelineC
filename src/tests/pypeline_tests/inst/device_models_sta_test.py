#!/usr/bin/env python3
"""Pure unit coverage for sky130 recipe identity and STA diagnostics.

The fixtures are tiny already-liberty-mapped yosys JSON netlists, so this
test needs neither yosys nor GHDL and belongs in the fast unit category.
"""

import json
import hashlib
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


def _run_fixture(module):
    with tempfile.TemporaryDirectory(prefix="pipelinec_sta_unit_") as work_dir:
        path = os.path.join(work_dir, "mapped.json")
        with open(path, "w") as f:
            json.dump({"modules": {"top": module}}, f)
        return DEVICE_MODELS.run_sta(path, top="top")


def test_register_path_components_and_arc_trace():
    # launch.Q -> inverter -> capture.D. The primary input feeding launch.D
    # and capture.Q output ensure unconstrained endpoints coexist with it.
    result = _run_fixture(
        {
            "ports": {
                "clk": {"direction": "input", "bits": [1]},
                "data_in": {"direction": "input", "bits": [2]},
                "data_out": {"direction": "output", "bits": [5]},
            },
            "cells": {
                "launch": {
                    "type": DFF,
                    "connections": {"CLK": [1], "D": [2], "Q": [3]},
                },
                "logic": {
                    "type": INV,
                    "connections": {"A": [3], "Y": [4]},
                },
                "capture": {
                    "type": DFF,
                    "connections": {"CLK": [1], "D": [4], "Q": [5]},
                },
            },
        }
    )

    assert result["start_reg_name"] == "launch", result
    assert result["end_reg_name"] == "capture", result
    assert result["critical_endpoint_kind"] == "register", result
    assert result["critical_endpoint_pin"] == "D", result
    assert result["critical_output_port"] is None, result
    assert result["launch_clock_to_q_ns"] > 0.0, result
    assert result["combinational_delay_ns"] > 0.0, result
    assert result["setup_ns"] != 0.0, result
    component_sum = (
        result["launch_clock_to_q_ns"]
        + result["combinational_delay_ns"]
        + result["setup_ns"]
    )
    assert abs(result["worst_period_ns"] - component_sum) < 1e-12, result
    assert result["critical_path_arc_count"] == 2, result
    assert [a["kind"] for a in result["critical_path"]] == [
        "clock_to_q",
        "combinational",
    ]
    assert [a["instance"] for a in result["critical_path"]] == [
        "launch",
        "logic",
    ]
    assert sum(a["delay_ns"] for a in result["critical_path"]) == (
        result["launch_clock_to_q_ns"] + result["combinational_delay_ns"]
    )


def test_primary_input_to_output_has_explicit_zero_components():
    result = _run_fixture(
        {
            "ports": {
                "data_in": {"direction": "input", "bits": [1]},
                "data_out": {"direction": "output", "bits": [2]},
            },
            "cells": {
                "logic": {
                    "type": INV,
                    "connections": {"A": [1], "Y": [2]},
                }
            },
        }
    )
    assert result["start_reg_name"] is None, result
    assert result["end_reg_name"] is None, result
    assert result["critical_endpoint_kind"] == "primary_output", result
    assert result["critical_output_port"] == "data_out", result
    assert result["launch_clock_to_q_ns"] == 0.0, result
    assert result["setup_ns"] == 0.0, result
    assert result["combinational_delay_ns"] == result["worst_period_ns"], result
    assert result["critical_path_arc_count"] == 1, result


def test_zero_logic_path_has_explicit_empty_diagnostics():
    result = _run_fixture(
        {
            "ports": {
                "data_in": {"direction": "input", "bits": [1]},
                "data_out": {"direction": "output", "bits": [1]},
            },
            "cells": {},
        }
    )
    assert result["worst_period_ns"] == 0.0, result
    assert result["launch_clock_to_q_ns"] == 0.0, result
    assert result["combinational_delay_ns"] == 0.0, result
    assert result["setup_ns"] == 0.0, result
    assert result["critical_endpoint_kind"] is None, result
    assert result["critical_path"] == [], result


def test_fixed_recipe_commands_and_cache_identity():
    expected = {
        "current",
        "synth_flatten",
        "synth_flatten_noabc",
        "early_flatten_opt",
        "early_flatten_noabc",
    }
    assert set(DEVICE_MODELS._SYNTHESIS_RECIPE_CACHE_TAGS) == expected
    suffixes = {
        name: DEVICE_MODELS.GET_SYNTHESIS_RECIPE_CACHE_SUFFIX(name)
        for name in expected
    }
    default_recipe = DEVICE_MODELS._DEFAULT_SYNTHESIS_RECIPE
    assert default_recipe == "early_flatten_noabc"
    assert suffixes[default_recipe] == ""
    assert len(set(suffixes.values())) == len(expected), suffixes
    identities = {
        name: DEVICE_MODELS.GET_MODEL_CACHE_IDENTITY(recipe_name=name)
        for name in expected
    }
    assert len(set(identities.values())) == len(expected), identities
    assert identities[default_recipe].endswith(
        f"_v{DEVICE_MODELS.MODEL_VERSION}"
    )

    commands = {
        name: DEVICE_MODELS._get_synthesis_recipe_commands(
            "frozen_top", "/tmp/sky130.lib", name
        )
        for name in expected
    }
    for command in commands.values():
        assert command.count("abc -liberty /tmp/sky130.lib -fast") == 1, command
        assert command.endswith("flatten; "), command
    assert "synth -top frozen_top -flatten;" in commands["synth_flatten"]
    assert (
        "synth -top frozen_top -flatten -noabc; opt -full;"
        in commands["synth_flatten_noabc"]
    )
    assert (
        "synth -top frozen_top; flatten; opt -full;"
        in commands["early_flatten_opt"]
    )
    assert (
        "synth -top frozen_top -noabc; flatten; opt -full;"
        in commands["early_flatten_noabc"]
    )

    try:
        DEVICE_MODELS._get_synthesis_recipe_name("arbitrary-yosys-flags")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown recipe did not fail closed")
    try:
        DEVICE_MODELS._get_synthesis_recipe_name("")
    except ValueError:
        pass
    else:
        raise AssertionError("empty explicit recipe did not fail closed")


def test_syn_disk_caches_are_recipe_scoped():
    class ParserState:
        part = DEVICE_MODELS.SELECTED_LIBRARY

    old_tool = SYN.SYN_TOOL
    old_recipe = DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE
    old_comb_weights = SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS
    try:
        SYN.SYN_TOOL = DEVICE_MODELS
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = False
        DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE = (
            DEVICE_MODELS._DEFAULT_SYNTHESIS_RECIPE
        )
        production_path = SYN.GET_PATH_DELAY_CACHE_DIR(ParserState())
        DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE = "synth_flatten"
        flatten_path = SYN.GET_PATH_DELAY_CACHE_DIR(ParserState())
        flatten_period_path = SYN.GET_PATH_DELAY_CACHE_DIR(
            ParserState(), "pipeline_min_period_cache"
        )
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = True
        comb_planner_suffix = SYN.GET_PLANNER_DELAY_CACHE_SUFFIX()
        comb_planner_path = SYN.GET_PATH_DELAY_CACHE_DIR(ParserState())
    finally:
        SYN.SYN_TOOL = old_tool
        DEVICE_MODELS._SELECTED_SYNTHESIS_RECIPE = old_recipe
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = old_comb_weights

    suffix = DEVICE_MODELS.GET_SYNTHESIS_RECIPE_CACHE_SUFFIX("synth_flatten")
    assert suffix not in production_path, production_path
    assert suffix in flatten_path, flatten_path
    assert suffix in flatten_period_path, flatten_period_path
    assert production_path != flatten_path
    assert comb_planner_suffix == "__comb_planner_v1"
    assert comb_planner_suffix in comb_planner_path, comb_planner_path


def test_planner_component_weight_is_optional_and_deepcopied():
    class PathReport:
        path_delay_ns = 1.5
        launch_clock_to_q_ns = 0.4
        combinational_delay_ns = 0.9
        setup_ns = 0.2

    components = SYN._PATH_REPORT_DELAY_COMPONENTS(PathReport())
    assert components == {
        "path_delay_ns": 1.5,
        "launch_clock_to_q_ns": 0.4,
        "combinational_delay_ns": 0.9,
        "setup_ns": 0.2,
    }
    logic = C_TO_LOGIC.Logic()
    logic.delay = 15
    SYN._SET_LOGIC_DELAY_COMPONENTS(logic, components)
    assert logic.planner_delay == 9

    old_comb_weights = SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS
    try:
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = False
        assert SYN.GET_PLANNER_DELAY(logic) == 15
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = True
        assert SYN.GET_PLANNER_DELAY(logic) == 9
    finally:
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = old_comb_weights

    copied = logic.DEEPCOPY()
    assert copied.planner_delay == logic.planner_delay
    assert copied.delay_components == logic.delay_components
    assert copied.delay_components is not logic.delay_components


def test_component_cache_sidecar_round_trip_and_validation():
    logic = C_TO_LOGIC.Logic()
    logic.func_name = "cache_test"
    logic.is_c_built_in = True

    class ParserState:
        part = DEVICE_MODELS.SELECTED_LIBRARY

    components = {
        "path_delay_ns": 2.0,
        "launch_clock_to_q_ns": 0.5,
        "combinational_delay_ns": 1.25,
        "setup_ns": 0.25,
    }
    original_cache_dir = SYN.GET_PATH_DELAY_CACHE_DIR
    with tempfile.TemporaryDirectory(prefix="pipelinec_component_cache_unit_") as td:
        try:
            SYN.GET_PATH_DELAY_CACHE_DIR = lambda parser_state, dir_name="path_delay_cache": td
            SYN._WRITE_CACHED_PATH_DELAY_COMPONENTS(
                logic, ParserState(), components
            )
            loaded = SYN.GET_CACHED_PATH_DELAY_COMPONENTS(
                logic, ParserState(), expected_delay_ns=2.0
            )
            mismatched = SYN.GET_CACHED_PATH_DELAY_COMPONENTS(
                logic, ParserState(), expected_delay_ns=2.1
            )
        finally:
            SYN.GET_PATH_DELAY_CACHE_DIR = original_cache_dir
    assert loaded == components
    assert mismatched is None


def test_log_and_structured_report_round_trip():
    result = _run_fixture(
        {
            "ports": {
                "data_in": {"direction": "input", "bits": [1]},
                "data_out": {"direction": "output", "bits": [2]},
            },
            "cells": {
                "logic": {
                    "type": INV,
                    "connections": {"A": [1], "Y": [2]},
                }
            },
        }
    )
    with tempfile.TemporaryDirectory(prefix="pipelinec_sta_report_unit_") as work_dir:
        log_path = os.path.join(work_dir, "timing.log")
        DEVICE_MODELS._write_sta_log(
            log_path,
            result,
            DEVICE_MODELS.DEFAULT_LIBRARY,
            DEVICE_MODELS.DEFAULT_CORNER,
            "synth_flatten",
        )
        timing_json_path = DEVICE_MODELS._write_sta_json(
            log_path,
            result,
            DEVICE_MODELS.DEFAULT_LIBRARY,
            DEVICE_MODELS.DEFAULT_CORNER,
            "synth_flatten",
        )
        with open(log_path) as f:
            cached_log_text = f.read()
            report = DEVICE_MODELS.PathReport(cached_log_text)
        with open(timing_json_path) as f:
            structured = json.load(f)

    assert report.synthesis_recipe == "synth_flatten"
    assert report.launch_clock_to_q_ns == 0.0
    assert report.setup_ns == 0.0
    assert report.critical_path_arc_count == 1
    assert structured["synthesis_recipe"] == "synth_flatten"
    assert structured["fmax_mhz"] == 1000.0 / structured["worst_period_ns"]
    assert structured["model_version"] == DEVICE_MODELS.MODEL_VERSION
    assert structured["model_cache_identity"] == (
        DEVICE_MODELS.GET_MODEL_CACHE_IDENTITY(recipe_name="synth_flatten")
    )
    assert structured["critical_path"][0]["instance"] == "logic"
    assert DEVICE_MODELS._timing_report_has_components(
        DEVICE_MODELS.ParsedTimingReport(cached_log_text)
    )
    assert not DEVICE_MODELS._timing_report_has_components(
        DEVICE_MODELS.ParsedTimingReport(
            "Worst period (ns): 1.000000\nStart reg: None\nEnd reg: None\n"
        )
    )


def test_cached_timing_requires_exact_inputs_model_and_mapped_json_hash():
    with tempfile.TemporaryDirectory(prefix="pipelinec_sta_cache_identity_") as td:
        log_path = os.path.join(td, "timing.log")
        mapped_path = os.path.join(td, "mapped.json")
        with open(mapped_path, "w") as f:
            f.write('{"modules": {}}\n')
        synthesis_inputs = {"identity_sha256": "a" * 64}
        result = {
            "worst_period_ns": 1.0,
            "mapping_succeeded": True,
            "mapped_json_path": mapped_path,
            "mapped_json_sha256": DEVICE_MODELS._sha256_file(mapped_path),
        }
        DEVICE_MODELS._write_sta_json(
            log_path,
            result,
            DEVICE_MODELS.DEFAULT_LIBRARY,
            DEVICE_MODELS.DEFAULT_CORNER,
            "current",
            synthesis_inputs,
        )
        assert DEVICE_MODELS._cached_timing_matches(
            log_path, synthesis_inputs, "current"
        )
        assert not DEVICE_MODELS._cached_timing_matches(
            log_path, {"identity_sha256": "b" * 64}, "current"
        )
        assert not DEVICE_MODELS._cached_timing_matches(
            log_path, synthesis_inputs, "synth_flatten"
        )
        with open(mapped_path, "a") as f:
            f.write(" ")
        assert not DEVICE_MODELS._cached_timing_matches(
            log_path, synthesis_inputs, "current"
        )


def test_durable_qor_evidence_matrices_are_self_consistent():
    qor_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "qor")
    )
    with open(os.path.join(qor_dir, "synthesis_recipe_pre_divzero_matrix.json")) as f:
        pre = json.load(f)
    wrapper_path = os.path.join(
        qor_dir, "synthesis_recipe_pre_divzero_wrapper.vhd"
    )
    with open(wrapper_path, "rb") as f:
        wrapper_hash = hashlib.sha256(f.read()).hexdigest()
    assert wrapper_hash == pre["provenance"]["frozen_wrapper"]["sha256"]
    # Historical matrices are frozen evidence for the recipe set that existed
    # when they were taken; a later promotion may add recipes they never ran.
    assert set(pre["recipes"]) <= set(
        DEVICE_MODELS._SYNTHESIS_RECIPE_CACHE_TAGS
    )
    current = pre["recipes"]["current"]
    flatten = pre["recipes"]["synth_flatten"]
    assert current["metrics"]["n_max_capacitance_violations"] > 0
    assert flatten["metrics"]["n_max_capacitance_violations"] == 0
    assert flatten["metrics"]["worst_period_ns"] < (
        0.5 * current["metrics"]["worst_period_ns"]
    )

    with open(
        os.path.join(qor_dir, "synthesis_recipe_forced32_matrix.json")
    ) as f:
        full = json.load(f)
    assert set(full["recipes"]) <= set(
        DEVICE_MODELS._SYNTHESIS_RECIPE_CACHE_TAGS
    )
    assert full["target"]["measured_stages"] == (
        full["target"]["measured_slices"] + 1
    )
    # This matrix promoted V3/early_flatten_opt on a "maximise our own fmax"
    # policy. It stays valid as a record of that decision, but it is no
    # longer what selects the production recipe -- see the latchup-match
    # matrix below, whose policy is to predict latchup's number, not beat it.
    former = full["selected_production_recipe"]
    assert former in DEVICE_MODELS._SYNTHESIS_RECIPE_CACHE_TAGS
    assert full["promoted_model_version"] < DEVICE_MODELS.MODEL_VERSION
    winner = full["recipes"][former]
    assert winner["fmax_mhz"] == max(
        result["fmax_mhz"] for result in full["recipes"].values()
    )
    assert winner["mapper_sources_unchanged_through_mapping"]
    assert winner["n_unmapped_cells"] == 0
    assert not winner["incomplete_topo"]
    assert all(result["acceptance_passed"] for result in full["recipes"].values())

    # Current production selection: reproduce latchup's post-early-flatten
    # netlists and reported period.
    with open(
        os.path.join(qor_dir, "latchup_early_flatten_match_matrix.json")
    ) as f:
        match = json.load(f)
    assert set(match["recipes"]) == set(
        DEVICE_MODELS._SYNTHESIS_RECIPE_CACHE_TAGS
    )
    selected = match["selected_production_recipe"]
    assert selected == DEVICE_MODELS._DEFAULT_SYNTHESIS_RECIPE
    assert match["promoted_model_version"] == DEVICE_MODELS.MODEL_VERSION
    assert match["previous_model_version"] < DEVICE_MODELS.MODEL_VERSION
    # The promoted recipe must be the most accurate one on BOTH scores, or the
    # selection policy quoted in the file is not what actually chose it.
    scores = {
        name: result["period_error_mae_pct"]
        for name, result in match["recipes"].items()
    }
    assert scores[selected] == min(scores.values()), scores
    worst = {
        name: result["period_error_worst_pct"]
        for name, result in match["recipes"].items()
    }
    assert worst[selected] == min(worst.values()), worst
    # ...and it must actually reproduce their mapping, not merely their number.
    assert len(
        match["recipes"][selected]["designs_with_exact_latchup_histogram"]
    ) >= 3
    # Every design's VHDL was hash-verified identical to latchup's own build.
    for design, truth in match["ground_truth"].items():
        assert truth["stages"] == truth["slices"] + 1, design
        assert truth["reproduced_top_entity"].startswith("solution_"), design
    # Engine-only physics is recipe-independent and must stay at its bar.
    engine = match["engine_only_on_latchup_netlists"]
    assert engine["post_early_flatten_mae_pct"] < 5.0
    assert engine["post_early_flatten_worst_pct"] < 10.0

    with open(os.path.join(qor_dir, "divider_qor_acceptance.json")) as f:
        acceptance = json.load(f)
    # The full Divider QoR acceptance run is expensive (one gate build is
    # about an hour) and was NOT re-run for the V4/early_flatten_noabc
    # promotion, which was selected purely on latchup-match evidence. So this
    # file legitimately describes an earlier production configuration; assert
    # exactly that, rather than pretending it tracks the current default.
    assert acceptance["production"]["model_version"] < DEVICE_MODELS.MODEL_VERSION
    assert acceptance["production"]["synthesis_recipe"] in (
        DEVICE_MODELS._SYNTHESIS_RECIPE_CACHE_TAGS
    )
    for variant in ("gate", "arithmetic"):
        baseline = acceptance[variant]["clean_c81ca31f"]
        result = acceptance[variant]["automatic_v3"]
        target = acceptance["targets"][variant]
        assert baseline["stages"] == baseline["slices"] + 1
        assert result["stages"] == result["slices"] + 1
        assert not baseline["acceptance_passed"]
        assert result["acceptance_passed"]
        assert result["functional_passed"]
        assert result["fmax_mhz"] > target["strict_fmax_mhz"]
        assert result["slices"] <= target["maximum_slices"]
        assert result["n_unmapped_cells"] == 0
        assert not result["incomplete_topo"]
        assert result["slices"] < baseline["slices"]

    with open(
        os.path.join(qor_dir, "divider_gate_clean_baseline_critical_paths.json")
    ) as f:
        baseline = json.load(f)
    assert [point["slices"] for point in baseline["points"]] == [
        28,
        50,
        63,
        67,
        70,
        73,
        66,
    ]
    for point in baseline["points"]:
        assert point["pipeline_stages"] == point["slices"] + 1
        metrics = point["metrics"]
        component_sum = sum(
            metrics[name]
            for name in (
                "launch_clock_to_q_ns",
                "combinational_delay_ns",
                "setup_ns",
            )
        )
        assert abs(metrics["worst_period_ns"] - component_sum) < 1e-12
        assert abs(
            metrics["fmax_mhz"] - 1000.0 / metrics["worst_period_ns"]
        ) < 1e-12
    assert baseline["points"][-3]["metrics"]["worst_period_ns"] == (
        baseline["points"][-4]["metrics"]["worst_period_ns"]
    )
    point_73 = next(point for point in baseline["points"] if point["slices"] == 73)
    assert point_73["pre_step_floor_knee"][
        "left_eff_mux_latency_slices"
    ] == 2
    assert point_73["timing_met"]
    assert baseline["points"][-1]["slices"] == 66
    assert baseline["points"][-1]["timing_met"]


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
