#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pypelinec elaboration + auto-pipelining + synthesis tests (no --no_synth).

"Does it build" -- exit code is the entire verdict. Every entry names its
synthesis tool, which picks its run_all category (synth_device_models,
synth_vivado or synth_pyrtl -- see common.SYN_TOOLS). DEVICE_MODELS (sky130)
is the default: measured several times faster than PyRTL. Vivado is only for
designs that need it (multi-cycle path constraints, the PDW tops' real-part
Block RAM and 125 MHz checks). See build_report_tests.py
for wrapper scripts that run pypelinec themselves and assert on its log
output/artifacts, and native_vs_vhdl_sim_tests.py for the AUTO_FSM/AUTO_PIPELINE
cycle-accuracy compares that used to live here (auto_fsm_native_sim_test +
auto_fsm_vhdl_sim_test, native_vs_vhdl_pipelined_ap_test,
native_vs_vhdl_pipelined_main_test).

Run standalone: python3 synth_tests.py [-j N]
"""

import sys

from common import (
    EXAMPLES_PYPELINE_DIR,
    INST_DIR,
    PYPELINEC,
    QOR_DIR,
    SYN_TOOL_ARGS,
    Test,
    main,
    syn_tool_category,
)

DM = "device_models"  # --syn_tool sky130; overrides any PART in the design
VIVADO = "vivado"  # the design's own PART("xc...") selects Vivado

# fmt: off
# (filename, source_dir, extra_args, tool)
SYNTH_TEST_FILES = [
    ("self_check_stream_auto_comb_share_test.py", INST_DIR, [], DM),
    ("self_check_stream_auto_comb_unshare_test.py", INST_DIR, [], DM),
    # The slowest synth_device_models test (a ~48-stage unrolled float32
    # divider, ~8 minutes of sky130 synth+STA; over 25 minutes under PyRTL, see
    # float_ops_div_test.py's own comment) -- listed early so run_all.py's FIFO dispatch starts it
    # building at t=0, concurrent with the rest of the suite, instead of
    # gating on whatever alphabetically/positionally precedes it.
    ("float_ops_div_test.py", INST_DIR, ["--comb"], DM),
    # stream_auto_pipeline_test.py's full-sweep build runs inside the
    # auto_pipeline_latency_test wrapper (added in get_tests below), which also
    # asserts on the AUTO_PIPELINE .latency pin-and-confirm output -- not
    # listed here so the same sweep isn't paid for twice.
    # Planned throughput sweep tests (full sweep, no --comb)
    ("sweep_comb_test.py", INST_DIR, [], DM),
    ("sweep_two_mains_test.py", INST_DIR, [], DM),
    ("sweep_fsm_auto_pipeline_test.py", INST_DIR, [], DM),
    ("sweep_stateful_boundary_test.py", INST_DIR, [], DM),
    ("fir_sweep_test.py", INST_DIR, [], DM),  # FIR blob retimes to a @MAIN goal
    # Non---comb build: proves make_stream_auto_fsm elaborates and synthesises
    # with a real AUTO_FSM schedule installed underneath its handshake
    # registers, independent of the native-vs-VHDL cycle diff registered in
    # native_vs_vhdl_sim_tests.py. Under sky130 this is also the real-toolchain
    # regression for DEVICE_MODELS' long-filename fix: its soft_cmp prefix-tree
    # leaves have ~190-byte generated entity names, which used to overflow the
    # 255-byte filename limit in DEVICE_MODELS' synthesis artifact names.
    ("self_check_stream_auto_fsm_test.py", INST_DIR, [], DM),
    # MULTI_CYCLE path constraints are Vivado-only
    # (SYN.GET_MCP_PATH_CONSTRAINTS), so these need their Xilinx PART.
    ("stream_multi_cycle_test.py", INST_DIR, ["--comb"], VIVADO),
    ("stream_auto_multi_cycle_test.py", INST_DIR, ["--comb"], VIVADO),
    # vga_donut stays on its board's Vivado part: under sky130 its whole-design
    # yosys run sat in `opt -full` for over an hour on the flattened
    # int28*int28 / int21*int16 multipliers (Vivado: ~30 minutes).
    ("vga_donut.py", EXAMPLES_PYPELINE_DIR, ["--comb"], VIVADO),
    # The other board examples: their board import sets a Xilinx PART, but
    # nothing in them is Vivado-specific, so --syn_tool sky130 builds them.
    ("vga_test_pattern.py", EXAMPLES_PYPELINE_DIR, ["--comb"], DM),
    ("float32_add_test.py", INST_DIR, ["--comb"], DM),
    ("float_ops_test.py", INST_DIR, ["--comb"], DM),
    ("fixed_point_test.py", INST_DIR, ["--comb"], DM),
    # DSP primitives added for the PDW measurement engine. Native sim never
    # emits VHDL, so a synthesis run is the only thing that can catch e.g. a
    # local variable whose name is a VHDL reserved word (this file's PDW
    # entries below were bitten by exactly that, three times).
    #
    # dsp/cordic.py is deliberately NOT listed here. Its own --comb build took
    # ~21 minutes under the PyRTL timing model -- an unrolled 14-iteration
    # pipeline, twice -- and it buys nothing: both of its modes are already
    # synthesized against the real xc7a100t part in under three minutes each,
    # vectoring mode inside pulse_extract_synth_top.py and rotation mode inside
    # pulse_gen_synth_top.py (both synth_vivado). Those give better coverage
    # (real part, real timing).
    ("log2_db_test.py", INST_DIR, ["--comb"], DM),
    ("pypeline_test.py", INST_DIR, ["--comb"], DM),
    ("reg_init_test.py", INST_DIR, ["--comb"], DM),
    ("if_test.py", INST_DIR, ["--comb"], DM),
    ("var_ref_test.py", INST_DIR, ["--comb"], DM),
    ("bit_math_test.py", INST_DIR, ["--comb"], DM),
    ("old_sw_lib_ops.py", INST_DIR, ["--comb"], DM),
    ("vhdl_text_test.py", INST_DIR, ["--comb"], DM),
    ("fifo_test.py", INST_DIR, ["--comb"], DM),
    ("stream_fifo_test.py", INST_DIR, ["--comb"], DM),
    # Every make_ram / make_stream_ram shape in these files is its own @MAIN:
    # the generated raw VHDL (memory inference, init aggregates, struct and
    # array element conversions) only meets a synthesis tool here.
    ("ram_test.py", INST_DIR, ["--comb"], DM),
    ("stream_ram_test.py", INST_DIR, ["--comb"], DM),
    # All four skid-buffer modes plus the AXIS face are separate @MAIN tops in
    # this one file, so this entry elaborates every generated body.
    ("skid_buffer_test.py", INST_DIR, ["--comb"], DM),
    ("interface_factory_two_widths_test.py", INST_DIR, ["--comb"], DM),
    ("axis_test.py", INST_DIR, ["--comb"], DM),
    ("dwidth_converter_test.py", INST_DIR, ["--comb"], DM),
    ("axis_byte_stream_test.py", INST_DIR, ["--comb"], DM),
    # One --comb synth entry per new byte-stream/AXIS module: native sim never
    # emits VHDL, so these are what catch reserved words, mismatched operand
    # widths and the rest of the VHDL-only error class.
    ("serdes_test.py", INST_DIR, ["--comb"], DM),
    ("type_byte_stream_test.py", INST_DIR, ["--comb"], DM),
    ("axis_max_len_limiter_test.py", INST_DIR, ["--comb"], DM),
    ("type_axis_test.py", INST_DIR, ["--comb"], DM),
    ("type_axis_synth_test.py", INST_DIR, ["--comb"], DM),
    ("enum_test.py", INST_DIR, ["--comb"], DM),
    ("char_array_test.py", INST_DIR, ["--comb"], DM),
    ("sim_print_test.py", INST_DIR, ["--comb"], DM),
    ("sim_assert_finish_test.py", INST_DIR, ["--comb"], DM),
    # Contains make_stream_multi_cycle: Vivado-only MULTI_CYCLE constraints.
    ("two_factory_wrappers_mixed_test.py", INST_DIR, ["--comb"], VIVADO),
    ("underscore_name_test.py", INST_DIR, ["--comb"], DM),
    ("array_compare_bracket_name_test.py", INST_DIR, ["--comb"], DM),
    ("fir_test.py", INST_DIR, ["--comb"], DM),
    ("fir_decim_test.py", INST_DIR, ["--comb"], DM),
    ("fir_interp_test.py", INST_DIR, ["--comb"], DM),
    ("magnitude_test.py", INST_DIR, ["--comb"], DM),
    ("dc_block_test.py", INST_DIR, ["--comb"], DM),
    ("moving_avg_test.py", INST_DIR, ["--comb"], DM),
    ("interface_test.py", INST_DIR, ["--comb"], DM),
    ("interface_func_test.py", INST_DIR, ["--comb"], DM),
    ("interface_func_loop_test.py", INST_DIR, ["--comb"], DM),
    ("interface_boundary_test.py", INST_DIR, ["--comb"], DM),
    ("interface_array_port_test.py", INST_DIR, ["--comb"], DM),
    ("interface_mixing_rules_test.py", INST_DIR, ["--comb"], DM),
    ("fm_radio_decim.py", EXAMPLES_PYPELINE_DIR / "dsp", ["--comb"], DM),
    # PDW synth tops stay on their real Artix-7 part: each proves its block
    # closes 125 MHz on real hardware ports (and pulse_extract that its data
    # FIFO infers Block RAM).
    ("pulse_detect_synth_top.py", EXAMPLES_PYPELINE_DIR / "dsp" / "pdw", ["--comb"], VIVADO),
    ("pulse_extract_synth_top.py", EXAMPLES_PYPELINE_DIR / "dsp" / "pdw", ["--comb"], VIVADO),
    ("pulse_gen_synth_top.py", EXAMPLES_PYPELINE_DIR / "dsp" / "pdw", ["--comb"], VIVADO),
    # (The composed PDW design, examples/pypeline/dsp/pdw/top.py, is registered
    # in get_tests() below rather than here -- this list names each test after
    # its file, and a bare "top" is too generic for a suite-wide registry.)
    # global_wire_nested_split_test.py (structurally richest multi-writer global
    # wire design: 3 writers splitting nested struct leaves + a mixed-depth
    # whole-subtree claim + readback) moved to known_issues_tests.py --
    # ElaborationError: 'combined' reported as having two whole-wire writers
    # even though their driven fields are disjoint. See
    # global_wire_nested_split_known_issue there.
]
# fmt: on


def _synth_test(name, args, tool, **kwargs) -> Test:
    return Test(
        name=name,
        category=syn_tool_category("synth", tool),
        cmd=[PYPELINEC] + args + SYN_TOOL_ARGS[tool],
        needs_out_dir=True,
        **kwargs,
    )


def get_tests() -> list:
    tests = [
        _synth_test(filename[: -len(".py")], [source_dir / filename] + extra_args, tool)
        for filename, source_dir, extra_args, tool in SYNTH_TEST_FILES
    ]
    # The composed PDW design (pulse_gen + pulse_detect + pulse_extract). The
    # pulse_detect/pulse_extract entries above check their blocks in isolation;
    # only this one proves the whole thing builds together, and that the
    # README-sized 16,384-deep packet FIFO plus the Path B delay line really do
    # infer Block RAM rather than a wall of flops. Named explicitly because the
    # source file is just "top.py".
    tests.append(
        _synth_test(
            "pdw_top",
            [EXAMPLES_PYPELINE_DIR / "dsp" / "pdw" / "top.py", "--comb"],
            VIVADO,
        )
    )
    # Pipelined (non---comb) NATIVE simulation: full build first, then the
    # native sim runs with the discovered latencies emulated. Self-checking
    # elastic stream design -- proves build -> harvest -> latency-emulated
    # native sim end to end (including the .latency-sized FIFO). Not in
    # native_vs_vhdl_sim_tests.py: its VHDL/cocotb run produced no debug
    # output at all despite the build succeeding cleanly -- see that file's
    # own comment for what's known about the discrepancy.
    tests.append(
        _synth_test(
            "native_pipelined_sim_test",
            [INST_DIR / "self_check_stream_auto_pipeline_test.py", "--sim", "--run", "all"],
            DM,
        )
    )
    # AUTO_PIPELINE -> make_stream_auto_fsm conversions of the qor/ QoR designs
    # (real valid/ready handshake, ready genuinely wired -- not a constant 1).
    # Each lives at qor/<domain>/auto_fsm.py -- named explicitly here rather
    # than through the SYNTH_TEST_FILES comprehension above, since that
    # derives a Test's name from the bare filename and all three share the
    # name "auto_fsm". Clock goals are lowered from each design's AUTO_PIPELINE
    # original: AUTO_FSM shares hardware across states instead of spreading it
    # across pipeline stages, so the goal that mattered for a free-running
    # pipeline does not carry over -- what matters here is a clean
    # synthesizing build, not matching the pipelined design's fmax (each
    # file's own comment records its measured floor). The multiplier is also
    # what exposed and pins the _TypeResolver array-reconstruction fix in
    # AUTO_FSM.py (an AUTO_FSM over a descended soft multiplier's local
    # partial-products array used to crash codegen with "cannot reconstruct a
    # live Python type for C type 'uint8_t[8]'").
    #
    # timeout=1800: these are the only registered tests that run AUTO_FSM's
    # min-area search (see AUTO_FSM.py's Area sweep constants), whose cost is
    # superlinear in folds-per-shared-unit -- when register_soft_mult()'s
    # default switched to a 30-level carry-save multiplier, this design (then
    # uint16 x uint16) folded 247 adds onto one unit and hung for hours with
    # no output before the fix (uint16 -> uint8) landed. Measured after the
    # fix: divider ~30-50s, sqrt ~100-200s, multiplier (the slowest, and the
    # only one of the three that actually opens up an operator) ~400-450s.
    # 1800s keeps real headroom without hiding a real regression behind the
    # 7200s category default.
    for qor_name in ("multiplier", "divider", "sqrt"):
        tests.append(
            _synth_test(
                f"qor_{qor_name}_auto_fsm_test",
                [QOR_DIR / qor_name / "auto_fsm.py"],
                DM,
                timeout=1800,
            )
        )
    return tests


if __name__ == "__main__":
    sys.exit(main(get_tests, "PipelineC pypeline full elaboration + synthesis tests."))
