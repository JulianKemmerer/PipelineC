# pyright: reportInvalidTypeForm=none
"""Fast parser/schema tests for the opt-in Divider QoR harness.

No synthesis or GHDL run belongs here; the expensive end-to-end benchmark is
invoked explicitly through ``divider_qor_bench.py``.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "divider_qor_bench.py"
SPEC = importlib.util.spec_from_file_location("divider_qor_bench", BENCH)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)
sys.modules.setdefault("divider_qor_bench", bench)

CONTINUITY_BENCH = HERE.parent / "divider_continuity_bench.py"
CONTINUITY_SPEC = importlib.util.spec_from_file_location(
    "divider_continuity_bench", CONTINUITY_BENCH
)
continuity = importlib.util.module_from_spec(CONTINUITY_SPEC)
CONTINUITY_SPEC.loader.exec_module(continuity)


def test_depth_and_timing_parsers_use_slice_stage_semantics():
    text = """
[sweep] solution: met timing, 48 slice(s) built (49 pipeline stages)
[sweep] Pipeline depth summary:
[sweep]   solution: 48 slice(s) total (49 pipeline stages)
"""
    assert bench._parse_depth(text) == 48
    with tempfile.TemporaryDirectory() as td:
        timing = Path(td) / "device_models_deadbeef.log"
        timing.write_text(
            "Worst period (ns): 6.5\nFmax (MHz): 153.846\n"
            "N cells: 123\nN max_capacitance violations: 2\n"
        )
        parsed = bench._parse_timing_log(timing)
        assert parsed == {
            "worst_period_ns": 6.5,
            "fmax_mhz": 153.846,
            "cells": 123,
            "max_capacitance_violations": 2,
        }


def test_forced_step_request_is_generic_and_bounded():
    value = bench._placement_request(["bit_internal:some/path@0.5"])
    assert value["version"] == 1
    assert value["mode"] == "replace"
    assert value["selectors"] == [
        {
            "kind": "instance_output",
            "func_name": "step_gates",
            "all": True,
            "fixed": True,
        }
    ]
    assert value["placements"][0]["candidate_id"].startswith("bit_internal:")
    try:
        bench._placement_request([str(i) for i in range(17)])
    except AssertionError:
        pass
    else:
        raise AssertionError("17 extra placements were accepted")

    hand = bench._placement_request(hand_equivalent=True)
    assert hand["mode"] == "replace"
    assert hand["selectors"] == [
        {
            "kind": "instance_output",
            "func_name": "MUX_uint32_t",
            "ancestor_func": "radix2_div_gates",
            "fixed": True,
        },
        {
            "kind": "instance_output",
            "func_name": "step_gates",
            "limit": 31,
            "fixed": True,
        },
    ]


def test_stream_type_discovery_uses_payload_fields_not_hash_constants():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "c_structs_pkg.pkg.vhd"
        path.write_text(
            """type in_payload is record
 dividend : unsigned(31 downto 0); divisor : unsigned(31 downto 0);
end record;
type out_payload is record
 v1 : unsigned(31 downto 0); v2 : unsigned(31 downto 0);
end record;
type stream_t_changed1 is record data : in_payload; valid : unsigned(0 downto 0); end record;
type stream_t_changed2 is record data : out_payload; valid : unsigned(0 downto 0); end record;
"""
        )
        assert bench._discover_stream_types(Path(td)) == (
            "stream_t_changed1",
            "stream_t_changed2",
        )


def test_exact_sim_workdir_is_recreated_between_toolchains():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "c_structs_pkg.pkg.vhd").write_text(
            """type in_payload is record
 dividend : unsigned(31 downto 0); divisor : unsigned(31 downto 0);
end record;
type out_payload is record
 v1 : unsigned(31 downto 0); v2 : unsigned(31 downto 0);
end record;
type stream_t_input is record data : in_payload; valid : unsigned(0 downto 0); end record;
type stream_t_output is record data : out_payload; valid : unsigned(0 downto 0); end record;
"""
        )
        stale = root / "exact_final_vhdl_sim" / "sim_build" / "work-obj08.cf"
        stale.parent.mkdir(parents=True)
        stale.write_text("objects from a different GHDL build\n")

        sim_dir, _wrapper, makefile = bench._write_sim_files(root)
        assert sim_dir == root / "exact_final_vhdl_sim"
        assert not stale.exists()
        make_text = makefile.read_text()
        assert "--std=08 -Wno-hide" in make_text
        assert "--ieee-asserts=disable\n" in make_text
        assert "COCOTB_CONFIG ?= cocotb-config" in make_text


def test_fixture_sources_are_143_mhz_and_divide_by_zero_model_is_defined():
    for variant in ("gate", "arithmetic"):
        source = (bench.FIXTURE_DIR / f"{variant}.py").read_text()
        assert "CLK_RATE_MHZ = 143.0" in source
    assert bench.SLICE_LIMITS == {"gate": 48, "arithmetic": 63}


def test_frozen_script_discovery_and_manifest_self_hash_exclusion():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "top").mkdir()
        one = root / "one.vhd"
        two = root / "two.vhd"
        one.write_text("entity dep is end dep; architecture a of dep is begin end a;\n")
        two.write_text("entity frozen_top is end frozen_top; architecture a of frozen_top is begin end a;\n")
        script = root / "top" / "frozen_top_syn.sh"
        script.write_text(
            f"yosys -p 'ghdl --std=08 {one} {two} -e frozen_top; synth -top frozen_top;'\n"
        )
        frozen = bench._discover_frozen_vhdl(script)
        assert frozen["top"] == "frozen_top"
        assert frozen["vhdl_paths"] == [one, two]
        snapshot = bench._vhdl_source_snapshot(
            frozen["vhdl_paths"], frozen["source_root"]
        )
        copied = bench._copy_vhdl_source_snapshot(
            frozen["vhdl_paths"], frozen["source_root"], root / "evidence"
        )
        assert [path.read_bytes() for path in copied["snapshot_paths"]] == [
            path.read_bytes() for path in frozen["vhdl_paths"]
        ]
        bench._assert_vhdl_source_unchanged(
            snapshot,
            frozen["vhdl_paths"],
            frozen["source_root"],
            "during unit test",
        )
        two.write_text(two.read_text() + "-- drift\n")
        try:
            bench._assert_vhdl_source_unchanged(
                snapshot,
                frozen["vhdl_paths"],
                frozen["source_root"],
                "during unit test",
            )
        except RuntimeError as exc:
            assert "refusing mixed-input QoR evidence" in str(exc)
        else:
            raise AssertionError("frozen VHDL source drift was accepted")

        (root / "manifest.json").write_text("{}\n")
        (root / "recipe_evidence.json").write_text("{}\n")
        (root / "evidence.log").write_text("evidence\n")
        names = {record["path"] for record in bench._artifact_records(root)}
        assert "manifest.json" not in names
        assert "recipe_evidence.json" not in names
        assert "evidence.log" in names


def test_vpi_abi_failure_is_narrowly_recognized():
    assert bench._looks_like_vpi_abi_failure(
        "libcocotbvpi_ghdl.so: version `GLIBC_2.32' not found"
    )
    assert not bench._looks_like_vpi_abi_failure("ordinary VHDL assertion failure")


def test_nonzero_simulator_return_cannot_be_overridden_by_result_json():
    process = {
        "passed": False,
        "returncode": 7,
        "runtime_seconds": 1.0,
        "toolchain": {},
        "fallback_used": False,
    }
    reported = {"passed": True, "returncode": 0, "cycles": 10}
    value = bench._merge_functional_result(process, reported)
    assert value["test_reported_passed"]
    assert not value["passed"]
    assert value["returncode"] == 7


def test_existing_runtime_requires_existing_build():
    args = bench._parse_args(
        [
            "--variant",
            "gate",
            "--out_dir",
            "/tmp/existing-qor-test",
            "--existing-build",
            "--existing-runtime-seconds",
            "123.5",
            "--existing-returncode",
            "0",
            "--compiler-commit",
            "c81ca31f",
            "--source-sha256",
            "deadbeef",
        ]
    )
    assert args.existing_runtime_seconds == 123.5
    assert args.existing_returncode == 0
    assert args.compiler_commit == "c81ca31f"
    assert args.recipe == bench.DEFAULT_RECIPE == "early_flatten_noabc"
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            bench._parse_args(
                [
                    "--variant",
                    "gate",
                    "--out_dir",
                    "/tmp/existing-qor-test",
                    "--existing-runtime-seconds",
                    "123.5",
                ]
            )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("standalone --existing-runtime-seconds was accepted")


def test_existing_manifest_derives_stages_from_known_slices():
    # The full existing-build path is covered by the opt-in Divider evidence;
    # this focused check protects the reporting rule without invoking tools.
    assert bench._parse_pipeline_stages("") is None
    assert bench._reported_pipeline_stages("", 64) == 65
    assert bench._reported_pipeline_stages(
        "[sweep] solution: 64 slice(s) total (65 pipeline stages)", 64
    ) == 65


def test_generated_python_and_delay_caches_do_not_enter_snapshot_hash():
    assert bench._is_generated_untracked_path(
        Path("src/tests/pypeline_tests/qor/divider/__pycache__/gate.pyc")
    )
    assert bench._is_generated_untracked_path(
        Path("path_delay_cache/backend/library/op.delay")
    )
    assert not bench._is_generated_untracked_path(
        Path("src/tests/pypeline_tests/qor/divider/gate.py")
    )


def test_model_record_rejects_external_liberty_override():
    old = os.environ.get("PIPELINEC_SKY130_LIB_PATH")
    try:
        os.environ["PIPELINEC_SKY130_LIB_PATH"] = "/tmp/not-the-pinned-lib.lib"
        try:
            bench._model_record("current")
        except RuntimeError as exc:
            assert "not allowed for acceptance QoR" in str(exc)
        else:
            raise AssertionError("external mapping-liberty override was accepted")
    finally:
        if old is None:
            os.environ.pop("PIPELINEC_SKY130_LIB_PATH", None)
        else:
            os.environ["PIPELINEC_SKY130_LIB_PATH"] = old

    record = bench._model_record("current")
    assert record["mapping_liberty"]["path"].endswith(".lib")
    assert record["sta_condensed_json"]["path"].endswith(".json")


def test_new_runs_reject_nonempty_evidence_and_generator_manifest_mismatch():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "old.txt").write_text("stale evidence\n")
        args = SimpleNamespace(existing_build=False)
        try:
            bench._build_one(args, "gate", occupied)
        except ValueError as exc:
            assert "must be empty" in str(exc)
        else:
            raise AssertionError("a new build accepted a nonempty output directory")
        try:
            bench._run_frozen_recipe(None, "gate", occupied)
        except ValueError as exc:
            assert "must be empty" in str(exc)
        else:
            raise AssertionError("a frozen recipe accepted a nonempty evidence directory")

        source = root / "source"
        source.mkdir()
        vhdl = source / "top.vhd"
        vhdl.write_text(
            "entity top is end top; architecture a of top is begin end a;\n"
        )
        (source / "vhdl_files.txt").write_text(str(vhdl) + "\n")
        frozen = bench._discover_frozen_vhdl(source)
        records = bench._vhdl_path_records([vhdl], source)
        (source / "manifest.json").write_text(
            json.dumps({"final_vhdl": records, "metrics": {"slices": 0, "stages": 1}})
            + "\n"
        )
        provenance = bench._frozen_generator_provenance(frozen)
        assert provenance["final_vhdl_validation"]["matched"]
        broken = [dict(records[0], sha256="0" * 64)]
        (source / "manifest.json").write_text(
            json.dumps({"final_vhdl": broken, "metrics": {"slices": 0, "stages": 1}})
            + "\n"
        )
        try:
            bench._frozen_generator_provenance(frozen)
        except RuntimeError as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError("mismatched generator manifest was trusted")


def test_continuity_source_derivation_changes_only_clock_assignment():
    source = "before\nCLK_RATE_MHZ = 135.5\nafter\n"
    derived = continuity._derive_source(source, 180.0)
    assert derived == "before\nCLK_RATE_MHZ = 180\nafter\n"
    try:
        continuity._derive_source("no clock here\n", 180.0)
    except ValueError as exc:
        assert "expected one" in str(exc)
    else:
        raise AssertionError("source without CLK_RATE_MHZ was accepted")


def test_continuity_fingerprint_ignores_known_duplicate_name_order_only():
    def trace(path, duplicate_name):
        Path(path).write_text(
            json.dumps(
                {
                    "mains": {
                        "solution": {
                            "final_selected": [
                                {
                                    "kind": "bit_internal",
                                    "instance_path": duplicate_name,
                                    "function": "BIN_OP_MINUS_uint34_t_uint34_t",
                                    "axis_unit": 42,
                                    "bit_width": 34,
                                    "bit_boundary": 17,
                                    "realized": True,
                                }
                            ]
                        }
                    }
                }
            )
            + "\n"
        )

    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "a.json"
        b = Path(td) / "b.json"
        trace(a, "x_py_l35_l34_DUPLICATE_abcd")
        trace(b, "x_py_l34_l35_DUPLICATE_1234")
        fp_a, placements_a = continuity.placement_fingerprint(a)
        fp_b, placements_b = continuity.placement_fingerprint(b)
        assert fp_a == fp_b
        assert placements_a == placements_b
        assert placements_a[0]["instance_path"] == "x_py_l34_l35_DUPLICATE"


def test_continuity_acceptance_enforces_monotonic_depth_and_real_mid_gain():
    physical = {
        "stage_semantics": True,
        "mapping_succeeded": True,
        "zero_unmapped_cells": True,
        "complete_timing_topology": True,
        "timing_recipe_matches": True,
        "timing_model_identity_matches": True,
        "timing_vhdl_bytes_match_snapshot": True,
    }

    def plan(goal, stages, fmax):
        value = {
            "goal_mhz": goal,
            "slices": stages - 1,
            "stages": stages,
            "placement_fingerprint": f"p{stages}",
        }
        mapping = {
            "metrics": {"fmax_mhz": fmax},
            "functional": {"passed": True},
            "mapping_checks": physical,
        }
        return value, {**value, "mapping": mapping}

    low_plan, low_map = plan(135.5, 33, 170.0)
    mid_plan, mid_map = plan(180.0, 49, 190.0)
    high_plan, high_map = plan(210.0, 65, 223.0)
    sweeps = []
    for plan_value, mapped_value in (
        (low_plan, low_map),
        (mid_plan, mid_map),
        (high_plan, high_map),
    ):
        sweeps.append(
            {
                **plan_value,
                "build": {"returncode": 0},
                "exact_final": mapped_value["mapping"],
            }
        )
    result = continuity._acceptance(
        [low_plan, mid_plan, high_plan],
        [low_map, mid_map, high_map],
        sweeps,
        model_unchanged=True,
    )
    assert result["passed"], result

    regressed_sweeps = [dict(value) for value in sweeps]
    regressed_sweeps[1] = {
        **regressed_sweeps[1],
        "exact_final": {
            **regressed_sweeps[1]["exact_final"],
            "metrics": {"fmax_mhz": 164.7},
        },
    }
    result = continuity._acceptance(
        [low_plan, mid_plan, high_plan],
        [low_map, mid_map, high_map],
        regressed_sweeps,
        model_unchanged=True,
    )
    assert not result["checks"]["automatic_fmax_nondecreasing_with_depth"]
    assert not result["checks"]["deeper_automatic_schedule_has_meaningful_gain"]
    assert not result["checks"]["midpoint_at_least_10_percent_above_low"]


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
