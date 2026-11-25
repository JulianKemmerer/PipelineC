#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducers for known, unfixed compiler bugs -- every Test here has
expect_fail=True (its underlying command is expected to exit nonzero), so a
passing run means the bug is still present (reported as XFAIL) and a CLEAN
run means it got fixed without anyone updating this file (reported as XPASS,
which run_all.py treats as a FAILURE -- promote that test out of
known_issues into whichever category now fits it).

Deliberately EXCLUDED from run_all.py's default category set (see
run_all.py's module docstring) -- run explicitly:
    python3 known_issues_tests.py [-j N]
    python3 run_all.py --category known_issues

Do not fix these bugs as part of touching this file. If you fix one
elsewhere, this file's XPASS (or, for the exit-code entry, its own FAIL) will
tell you to move its test out.
"""

import sys

from common import (
    EXAMPLES_PYPELINE_DIR,
    INST_DIR,
    PYPELINE_SIM_DEBUG,
    PYPELINEC,
    SYN_TOOL_ARGS,
    Test,
    main,
)

# Backends the per-SYN_TOOL sweep matrix cannot run on this machine. Each is a
# real, reproducible failure of that tool -- none of them is a PipelineC bug,
# which is why the fix is not in this repo:
#
#   gowin     gw_sh exits "License verification failed  License hostid not
#             match." The IDE is installed; its license is not valid for this
#             host.
#   diamond   "Error: License checkout failed. FlexNet Licensing error:-10,32"
#             from diamondc. Same situation.
#   cc_tools  yosys synthesis succeeds and writes the netlist, then CologneChip
#             p_r crashes inside itself: "Exception Handler called. ExitCode:
#             112, Exception Class: ERangeError". The design presents 357
#             inputs / 480 outputs to p_r, far past a CCGM1A1's real I/O count,
#             and the tool range-errors instead of reporting that.
#
# These stay registered so the matrix documents every backend, and so a fixed
# license or a working part/tool combination shows up as an XPASS telling
# someone to move the entry back into synth_<tool>.
SWEEP_FLOAT32_BLOCKED = {
    "gowin": "gw_sh license hostid mismatch",
    "diamond": "diamondc FlexNet license checkout failed (-10,32)",
    "cc_tools": "CologneChip p_r crashes (ERangeError, exit 112)",
}


def get_tests() -> list:
    tests = []
    # Native sim keeps the Python values of a struct built with _replace() or
    # _make(): a uint8_t field set to 300 holds 300 (hardware: 44) and a
    # uint8_t[2] field set to [1, 2] packs to 5 (hardware: 0x0201), on a wire,
    # in a typed local and in a Reg. The constructor types them. Issue #401.
    tests.append(
        Test(
            name="native_struct_replace_cast_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "native_struct_replace_cast_test.py"],
            expect_fail=True,
        )
    )
    # A module-level struct or array constant, typed by its class or an
    # annotation, used directly in a hardware function does not elaborate:
    # passing K.lanes to a function, writing K or T to a port, indexing T
    # with a signal, or assigning a struct taken from a module-level table by
    # a loop each stop the build. A typed local (`t: uint8_t[2] = T`) works.
    # Native simulation runs the design. Issue #402.
    tests.append(
        Test(
            name="module_compound_const_known_issue",
            category="known_issues",
            cmd=[
                PYPELINEC,
                INST_DIR / "module_compound_const_design.py",
                "--comb",
                "--no_synth",
            ],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # AUTO_PIPELINE(f, latency=2) of a function with a variable multiply cannot
    # place its cuts ("realized 1 clock(s)"); a constant multiply or an
    # adder-only body can. Issue #391.
    tests.append(
        Test(
            name="fixed_latency_variable_multiply_known_issue",
            category="known_issues",
            cmd=[
                PYPELINEC,
                INST_DIR / "fixed_latency_variable_multiply_design.py",
                "--comb",
                "--no_synth",
            ],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # sky130 area estimate/measurement reporting, both operating modes: mode 1
    # (--no_hier_syn --no_sweep) must leave every leaf area-cached, but a
    # primitive whose delay is modeled from measured widths is never
    # synthesized, so its area is never cached and the test exits at mode 1;
    # modes 2 and 3 (measured area, stored measurements) do not run until it is
    # fixed. Issue #393. On XPASS move it back to build_report_device_models.
    tests.append(
        Test(
            name="area_estimate_build_report_test",
            category="known_issues",
            cmd=[INST_DIR / "area_estimate_build_report_test.py"],
            needs_out_dir=True,
            requires=["yosys", "ghdl"],
            expect_fail=True,
        )
    )
    # A path inside an imported helper: the call is labeled with the bare
    # name, the func_name module-prefixed, so attribution never finds the
    # helper and blames the region root around it. Issue #389.
    tests.append(
        Test(
            name="imported_helper_attribution_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "imported_helper_attribution_test.py"],
            expect_fail=True,
        )
    )
    # Native sim after a build looks up the build's pipeline placements by
    # instance name, but live elaboration labels a sub-module MAIN's call to a
    # same-module function without the module prefix the build gives it
    # (h[...] vs pl_sub_h[...]), so those placements are dropped. Issue #379.
    tests.append(
        Test(
            name="live_root_submodule_labels_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "live_root_submodule_labels_test.py"],
            expect_fail=True,
        )
    )
    # The C front end's INST_ARRAY connections in the top level
    # (VHDL.WRITE_MULTIMAIN_TOP) loop over unsorted sets, so top.vhd changes
    # with PYTHONHASHSEED: two --no_synth builds, top.vhd compared. Issue #403
    # (the C part of #380).
    tests.append(
        Test(
            name="c_inst_array_order_known_issue",
            category="known_issues",
            cmd=[
                INST_DIR / "top_level_reader_order_test.py",
                INST_DIR / "c_inst_array_order_design.c",
            ],
            expect_fail=True,
        )
    )
    # After the sweep meets timing, a failing trim trial whose path ends at an
    # output port (blamed on MAINs nothing can pipeline) ends the build TIMING
    # NOT MET instead of restoring the passing implementation. Issue #381.
    # About 75 seconds on device_models.
    tests.append(
        Test(
            name="sweep_failed_trim_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "sweep_failed_trim_design.py"]
            + SYN_TOOL_ARGS["device_models"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # Factory specializations that differ only inside a numpy array argument
    # over 1000 elements share one identity (numpy's repr elides the middle),
    # so the second elaborates as a DUPLICATE of the first: wrong hardware.
    # Issue #370.
    tests.append(
        Test(
            name="numpy_factory_arg_identity_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "numpy_factory_arg_identity_test.py"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # A pipelined top-level function folding a .latency-derived module value
    # keeps pass 1's entity file in pin-and-confirm pass 2 when the folded
    # constant keeps its width and the slices are replayed: wrong hardware.
    # Issue #369.
    tests.append(
        Test(
            name="latency_constant_entity_reuse_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "latency_constant_entity_reuse_test.py"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # Python supplies a @hw_func default, but HDL calls leave an omitted input
    # undriven. DSP reset inputs are explicit until this is supported.
    # Issue #386.
    tests.append(
        Test(
            name="hw_func_default_arg_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "hw_func_default_arg_design.py", "--no_synth"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # Nested record names starting with signed_ take the scalar conversion
    # branch in VHDL emission. NCO sideband records avoid this prefix.
    # Issue #383.
    tests.append(
        Test(
            name="struct_signed_prefix_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "struct_signed_prefix_design.py",
                 "--comb", "--sim", "--cocotb", "--ghdl", "--run", "4"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # @pipeline_latency(N >= 1) (C: FUNC_LATENCY) on a wire-only body renders a
    # process sensitivity list ending in a dangling comment: illegal VHDL that
    # GHDL rejects. Issue #371.
    tests.append(
        Test(
            name="pipeline_latency_wire_body_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "pipeline_latency_wire_body_design.py",
                 "--comb", "--sim", "--cocotb", "--ghdl", "--run", "all"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # AUTO_PIPELINE(func, latency=N) still places N cuts when func's
    # @pipeline_latency calls already supply N cycles; they land in a parallel
    # branch (extra registers there, later VOLATILE/C global writes from it).
    # Issue #372.
    tests.append(
        Test(
            name="fixed_auto_pipeline_extra_cuts_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "fixed_auto_pipeline_extra_cuts_test.py"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # C float-format conversion (float -> float_5_10_t) is the inline VHDL
    # function resize_float_e_m_t, not an operator: out-of-range values wrap
    # (GHDL), and its logic sits in user function bodies where no delay
    # measurement sees it. Issue #376.
    tests.append(
        Test(
            name="float_format_cast_wraps_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "float_format_cast_test.py", "--check", "values"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    tests.append(
        Test(
            name="float_format_cast_inline_logic_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "float_format_cast_test.py", "--check", "inline"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # Library factories that make "n of the caller's type" write elem_t[n],
    # which nests the wrong way when elem_t is an array (make_shift_into_top,
    # make_kept_data_bus_t, serializer/deserializer). Native sim passes; VHDL
    # emission fails. Issue #378.
    tests.append(
        Test(
            name="library_factory_array_elem_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "library_factory_array_elem_design.py",
                 "--comb", "--sim", "--cocotb", "--ghdl", "--run", "all"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # Native sim gives two instances of a stateful callee one state when only
    # a stateless caller separates them: a stateless wrapper called twice, or
    # two make_stream_fifo FIFOs called from one MAIN. pypeline_sim_debug.py
    # reports MISMATCH. Issue #382.
    tests.append(
        Test(
            name="stateless_caller_sim_state_known_issue",
            category="known_issues",
            cmd=[PYPELINE_SIM_DEBUG, INST_DIR / "stateless_caller_sim_state_design.py",
                 "--sim", "--comb", "--run", "all"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # scope= registrations: ignored on a plain top-level @hw_func (PARSE_FILE
    # Step 7), and a callee shared by a scoped and an unscoped caller is one
    # entity built under whichever came first. Issue #385.
    tests.append(
        Test(
            name="scoped_operator_registration_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "scoped_operator_registration_test.py"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # An Output[T] declared inside a module-level `if` that ran gets no port
    # and the MAIN's write to it is dropped, with no error; native sim treats
    # it as a wire. In process: fails while led is missing from
    # output_wires, passes if it is a port or PARSE_FILE refuses it by name.
    # Issue #404.
    tests.append(
        Test(
            name="conditional_global_decl_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "conditional_global_decl_test.py"],
            expect_fail=True,
        )
    )
    # A sim_print or sim_assert inside a called function is trimmed with the
    # call: removed when the call's result is unused, merged when two calls
    # have the same inputs. Native simulation runs every call, so the cycle
    # diff fails while either happens. Issue #410.
    tests.append(
        Test(
            name="sim_statement_call_trim_known_issue",
            category="known_issues",
            cmd=[PYPELINE_SIM_DEBUG, INST_DIR / "sim_statement_call_trim_design.py",
                 "--sim", "--comb", "--run", "all"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # x[0:7] (low index first) is accepted: the VHDL reads x(7 downto 0),
    # unreversed, and native sim raises "negative shift count". The cycle diff
    # fails while native sim raises and GHDL's sim_assert (y == 0x80) fails;
    # it passes once both reverse. Issue #405.
    tests.append(
        Test(
            name="reversed_bit_slice_known_issue",
            category="known_issues",
            cmd=[PYPELINE_SIM_DEBUG, INST_DIR / "reversed_bit_slice_design.py",
                 "--sim", "--comb", "--run", "all"],
            needs_out_dir=True,
            expect_fail=True,
            requires=["ghdl"],
        )
    )
    # --sim --comb --verilator --run all stops with a TypeError in
    # VERILATOR.DO_SIM (args.run is "all"), and the Verilator model ignores
    # sim_finish(). Fails while the crash is present; passes when the run
    # exits 0 by the cycle after sim_finish(). About 40 s. Issue #406.
    tests.append(
        Test(
            name="verilator_run_all_known_issue",
            category="known_issues",
            cmd=[INST_DIR / "verilator_run_all_test.py"],
            expect_fail=True,
            requires=["ghdl", "yosys", "verilator"],
        )
    )
    # Bit-slice assignment (x[hi:lo] = v) elaborates, and GHDL holds the
    # design's sim_asserts, but native sim raises "'SimVal' object does not
    # support item assignment". Fails while native sim raises; passes once it
    # stores the bits and the sim_asserts hold. Native sim only. Issue #408.
    tests.append(
        Test(
            name="native_bit_store_known_issue",
            category="known_issues",
            cmd=[PYPELINEC, INST_DIR / "native_bit_store_design.py",
                 "--sim", "--comb", "--run", "all"],
            needs_out_dir=True,
            expect_fail=True,
        )
    )
    # (operator_library_predicate_never_fires_known_issue was here while
    # SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE, meant to put operator-library
    # delays in the name-keyed cache/delay, never fired (#364). The predicate
    # is removed: those synthesis runs are reused by their exact inputs
    # instead, see SYN.LOGIC_PATH_DELAY_IS_CACHEABLE.)
    # (pdw_tb was here while Path B's delay line was misaligned. That is
    # fixed -- make_delay_line is now self-timed off the FSM's gate_advance --
    # so it lives in native_sim_tests.py as a normal passing test.)
    # (global_wire_nested_split_known_issue was here while the multi-writer
    # overlap check misread a soft_cmp_prefix helper as a second whole-wire
    # writer of Global Output 'combined'. That no longer reproduces, so
    # global_wire_nested_split_test.py is back in synth_tests.py as a normal
    # --comb entry.)
    # Per-SYN_TOOL sweep matrix entries whose backend cannot run here. Same
    # design and goal as the synth_<tool> entries in synth_tests.py; only the
    # category and expect_fail differ. See SWEEP_FLOAT32_BLOCKED above.
    from synth_tests import SWEEP_FLOAT32_MHZ

    for tool, why in SWEEP_FLOAT32_BLOCKED.items():
        tests.append(
            Test(
                name=f"sweep_float32_{tool}_known_issue",
                category="known_issues",
                cmd=[PYPELINEC, INST_DIR / "sweep_float32_test.py",
                     "-D", f"SWEEP_FLOAT32_MHZ={SWEEP_FLOAT32_MHZ[tool]}"]
                + SYN_TOOL_ARGS[tool],
                needs_out_dir=True,
                expect_fail=True,
            )
        )
    return tests


if __name__ == "__main__":
    sys.exit(
        main(get_tests, "PipelineC pypeline known-issue (expected-to-fail) reproducers.")
    )
