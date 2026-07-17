#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipelinec elaboration + autopipelining + synthesis tests (no --no_synth).

Run standalone: python3 synth_tests.py [-j N]
"""

import sys

from common import EXAMPLES_PYPELINE_DIR, INST_DIR, PIPELINEC, Test, main

# fmt: off
# (filename, source_dir, extra_args)
SYNTH_TEST_FILES = [
    # stream_pipeline_test.py's full-sweep build runs inside the
    # autopipeline_latency_test wrapper (added in get_tests below), which also
    # asserts on the AUTOPIPELINE .latency pin-and-confirm output -- not
    # listed here so the same sweep isn't paid for twice.
    # Planned throughput sweep tests (full sweep, no --comb)
    ("sweep_comb_test.py", INST_DIR, []),
    ("sweep_two_mains_test.py", INST_DIR, []),
    ("sweep_fsm_autopipeline_test.py", INST_DIR, []),
    ("sweep_stateful_boundary_test.py", INST_DIR, []),
    ("fir_sweep_test.py", INST_DIR, []),  # FIR blob retimes to a @MAIN goal
    ("valid_ready_mcp_test.py", INST_DIR, ["--comb"]),
    ("vga_donut.py", EXAMPLES_PYPELINE_DIR, ["--comb"]),
    ("vga_test_pattern.py", EXAMPLES_PYPELINE_DIR, ["--comb"]),
    ("float32_add_test.py", INST_DIR, ["--comb"]),
    ("float_ops_test.py", INST_DIR, ["--comb"]),
    ("fixed_point_test.py", INST_DIR, ["--comb"]),
    ("pypeline_test.py", INST_DIR, ["--comb"]),
    ("reg_init_test.py", INST_DIR, ["--comb"]),
    ("if_test.py", INST_DIR, ["--comb"]),
    ("var_ref_test.py", INST_DIR, ["--comb"]),
    ("bit_math_test.py", INST_DIR, ["--comb"]),
    ("old_sw_lib_ops.py", INST_DIR, ["--comb"]),
    ("vhdl_text_test.py", INST_DIR, ["--comb"]),
    ("fifo_test.py", INST_DIR, ["--comb"]),
    ("stream_fifo_test.py", INST_DIR, ["--comb"]),
    ("axis_test.py", INST_DIR, ["--comb"]),
    ("dwidth_converter_test.py", INST_DIR, ["--comb"]),
    ("enum_test.py", INST_DIR, ["--comb"]),
    ("char_array_test.py", INST_DIR, ["--comb"]),
    ("sim_print_test.py", INST_DIR, ["--comb"]),
    ("sim_assert_finish_test.py", INST_DIR, ["--comb"]),
    ("two_factory_wrappers_mixed_test.py", INST_DIR, ["--comb"]),
    ("underscore_name_test.py", INST_DIR, ["--comb"]),
    ("fir_test.py", INST_DIR, ["--comb"]),
    ("fir_decim_test.py", INST_DIR, ["--comb"]),
    ("fir_interp_test.py", INST_DIR, ["--comb"]),
    ("fm_radio_decim.py", EXAMPLES_PYPELINE_DIR / "dsp", ["--comb"]),
    # Structurally richest multi-writer global wire design (3 writers splitting
    # nested struct leaves + a mixed-depth whole-subtree claim + readback):
    # proves the per-region top-level VHDL through real synthesis, not just GHDL.
    ("global_wire_nested_split_test.py", INST_DIR, ["--comb"]),
]
# fmt: on


def get_tests() -> list:
    tests = [
        Test(
            name=filename[: -len(".py")],
            category="synth",
            cmd=[PIPELINEC, source_dir / filename] + extra_args,
            needs_out_dir=True,
        )
        for filename, source_dir, extra_args in SYNTH_TEST_FILES
    ]
    # Wrapper scripts (run pipelinec themselves and assert on the sweep's output)
    tests.append(
        Test(
            name="sweep_floor_detect_test",
            category="synth",
            cmd=[INST_DIR / "sweep_floor_detect_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_unpipelinable_test",
            category="synth",
            cmd=[INST_DIR / "sweep_unpipelinable_test.py"],
            needs_out_dir=True,
        )
    )
    tests.append(
        Test(
            name="sweep_planless_test",
            category="synth",
            cmd=[INST_DIR / "sweep_planless_test.py"],
            needs_out_dir=True,
        )
    )
    # Full-sweep build of stream_pipeline_test.py plus assertions on the
    # AUTOPIPELINE .latency pin-and-confirm loop (pass 2 runs, discovers a
    # real >0 latency, one seeded confirmation syn passes with no fallback
    # sweep and no pass 3, harvested latency appears in sweep_history.json).
    tests.append(
        Test(
            name="autopipeline_latency_test",
            category="synth",
            cmd=[INST_DIR / "autopipeline_latency_test.py"],
            needs_out_dir=True,
        )
    )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline full elaboration + synthesis tests."))
