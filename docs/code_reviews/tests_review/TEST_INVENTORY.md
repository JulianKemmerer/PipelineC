# Pypeline HDL test inventory

Written for: you, as the basis for reorganizing the suite.

Review snapshot: commit `ddd87701`; provenance is recorded under [History](#history). No tests were run and no compiler, test or registration source was edited. The snapshot includes the multi-clock and issue-reproducer additions. Historical timings are from a retained partial run; they do not establish current pass status.

Companion: [TEST_REVIEW.md](TEST_REVIEW.md). Reference: [docs/pypeline_TESTS.md](../../pypeline_TESTS.md). Machine-readable commands, required tools, environment, timeouts, case declarations and source hashes: [REVIEW_MANIFEST.json](REVIEW_MANIFEST.json).

Snapshot commit: `ddd87701a255e8e9de9383f94cf7814e4b0055b7`. Worktree status at refresh: contains local changes.

## Scope and reading the inventory

- **454 registered invocations**, including **20 opt-in known issues**; the default set contains **434**. Each category table has one row per `(category, name)` identity, including parameter/backend variants and registered examples outside this directory.
- **425 source/support/evidence files** under the directory: **408 Python/C files** and **17 other assets**. **311** are direct registration targets; **114** others are individually listed below. Every current `inst/*_test.py` has an actual registration target, independently checked from `get_tests()` rather than filename comments.
- The case appendix lists all **1,271 top-level `test_*` declarations** in these source files. **15** are `@MAIN` HDL entrypoints, not Python assertion tests. Custom `main()`/`check()` scripts and embedded designs contain additional assertions; the registration row is the execution unit, not each assertion.
- Generated `__pycache__`, `.Xil`, `lextab.py` and `yacctab.py` artifacts are not source tests and are excluded. Fixtures can be exercised by a wrapper without being independently registered.
- **M** = measured elapsed seconds for that registration in the old partial run, with its old PASS/FAIL. **D** = documented estimate, explicitly not a new measurement. **U** = unknown. No duration is inferred from category names; 87 registrations have no historical sample.
- Proposed lanes and verdicts are recommendations, not applied changes. A “remove candidate” needs the stated preservation check. “Keep” means the contract remains useful, not that it has passed on the current tree.
- `--comb` avoids automatic scheduling but does not erase explicit fixed-latency hardware. Plain `python file.py`, native multi-MAIN simulation, HDL compilation, native/GHDL parity and synthesis prove different things. A native/GHDL comparison already runs native simulation, but does **not** execute a file’s ordinary `__main__` test functions.
- Tool names on wrapper rows describe current category routing; some `build_report_device_models` wrappers perform no synthesis at all. Exact command arguments and `requires` live in the manifest. Known-issue race reproducer has normal exit semantics; the other 19 invert exit status.

Navigation: [registered categories](#category-totals) · [supporting files and manual tests](#supporting-files-and-manual-tests) · [individual case declarations](#test-case-declaration-index).

## Category totals

| Category | Registered | Old timed samples | Old elapsed sum (s) |
|---|---:|---:|---:|
| [native_sim](#native_sim) | 125 | 124 | 1080.6 |
| [native_vs_vhdl_sim](#native_vs_vhdl_sim) | 74 | 73 | 22052.9 |
| [elab](#elab) | 20 | 20 | 123.3 |
| [elab_introspect](#elab_introspect) | 34 | 32 | 1107.9 |
| [unit](#unit) | 53 | 51 | 2708.5 |
| [multi_clock](#multi_clock) | 3 | 0 | 0.0 |
| [synth_device_models](#synth_device_models) | 67 | 67 | 5672.1 |
| [synth_vivado](#synth_vivado) | 8 | 0 | 0.0 |
| [synth_open_tools](#synth_open_tools) | 5 | 0 | 0.0 |
| [synth_pyrtl](#synth_pyrtl) | 1 | 0 | 0.0 |
| [synth_quartus](#synth_quartus) | 1 | 0 | 0.0 |
| [synth_efinity](#synth_efinity) | 1 | 0 | 0.0 |
| [build_report_open_tools](#build_report_open_tools) | 3 | 0 | 0.0 |
| [build_report_vivado](#build_report_vivado) | 3 | 0 | 0.0 |
| [build_report_device_models](#build_report_device_models) | 33 | 0 | 0.0 |
| [build_report_pyrtl](#build_report_pyrtl) | 3 | 0 | 0.0 |
| [known_issues](#known_issues) | 20 | 0 | 0.0 |

The 367 old samples total **32,745.3 test-seconds (9.10 h)**, including two failures. This is summed per-test elapsed time under concurrency, not CPU time or full-suite wall time. Empty configured backend categories have zero rows.

## native_sim

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `array_2d_order_test` | [inst/array_2d_order_test.py](../../../src/tests/pypeline_tests/inst/array_2d_order_test.py) | Python / sim_call | M 0.3 s / PASS | Non-square T[A][B] dimensions, row type and legal indexes preserve C array order. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `auto_fsm_test` | [inst/auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_test.py) | Python / sim_call | M 0.4 s / PASS | Native AUTO_FSM passthrough semantics and latency metadata before any schedule is installed. | Keep native passthrough API; revise 'registered three ways': no direct elab entry, and scheduling is checked by wrappers. | fast candidate |
| `auto_pipeline_fixed_latency_sim_test` | [inst/auto_pipeline_fixed_latency_sim_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_fixed_latency_sim_test.py) | Python / sim_call | M 0.4 s / PASS | Native fixed-latency calls delay outputs by exactly N clocks with typed-zero warm-up, independent call sites and reset; unset/start/max hints stay passthrough. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `auto_pipeline_test` | [inst/auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_test.py) | Python / sim_call | M 0.4 s / PASS | AUTO_PIPELINE construction, native passthrough/zero latency, and nested tagged submodules. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `axis_byte_stream_test` | [inst/axis_byte_stream_test.py](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py) | Python / sim_call | M 0.6 s / PASS | AXIS byte source/sink round trips, partial final beats, keep-mask validation, pauses and scoreboard behavior. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `axis_max_len_limiter_test` | [inst/axis_max_len_limiter_test.py](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py) | Python / sim_call | M 1.0 s / PASS | AXIS frame limiting discards padding without desynchronizing later structs; covers the four historical limiter regressions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `axis_test` | [inst/axis_test.py](../../../src/tests/pypeline_tests/inst/axis_test.py) | Python / sim_call | M 0.5 s / PASS | AXIS keep/count conversions, passthrough interfaces and video-fragment end-of-data wiring. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `bit_math_test` | [inst/bit_math_test.py](../../../src/tests/pypeline_tests/inst/bit_math_test.py) | Python / sim_call | M 0.4 s / PASS | Typed local and inferred assignments truncate at hardware widths, including nested calls, register wrap and render-coordinate arithmetic. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `cast_hw_func_test` | [inst/cast_hw_func_test.py](../../../src/tests/pypeline_tests/inst/cast_hw_func_test.py) | Python / sim_call | M 1.4 s / PASS | User-defined computational casts and floating/integer converter registrations preserve values and hardware call lowering. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `cast_interface_test` | [inst/cast_interface_test.py](../../../src/tests/pypeline_tests/inst/cast_interface_test.py) | Python / sim_call | M 0.3 s / PASS | Stream-interface wrap/unwrap casts preserve payload and feedback types in both directions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `cast_test` | [inst/cast_test.py](../../../src/tests/pypeline_tests/inst/cast_test.py) | Python / sim_call | M 0.7 s / PASS | Explicit integer casts agree with typed assignment across widening, narrowing, signedness and call/field contexts. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `char_array_test` | [inst/char_array_test.py](../../../src/tests/pypeline_tests/inst/char_array_test.py) | Python / sim_call | M 0.4 s / PASS | Character literals, strings, nested arrays/structs, length and char-versus-byte type identity. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `cordic_test` | [inst/cordic_test.py](../../../src/tests/pypeline_tests/inst/cordic_test.py) | Python / sim_call | M 8.4 s / PASS | CORDIC atan2 agrees bit-for-bit with its golden model and within a numerical error bound of math.atan2. | Keep numeric oracle; add a small HDL compile/behavior check. Its MAINs have no direct elab/synth registration; old PyRTL timing is not a current exclusion benchmark. | fast candidate |
| `dc_block_tb` | [examples/pypeline/dsp/dc_block_tb.py](../../../examples/pypeline/dsp/dc_block_tb.py) | CLI native comb | M 26.0 s / PASS | Run the documented DC-removal example with golden checking and a settled-mean check. | Keep as example integration; library unit cases do not verify that this documented composition still works. | fast candidate |
| `dc_block_test` | [inst/dc_block_test.py](../../../src/tests/pypeline_tests/inst/dc_block_test.py) | Python / sim_call | M 1.3 s / PASS | dsp/dc_block.py make_dc_block tests: random stimulus vs the exact integer golden model (dsp/dsp_tb.golden_dc_block), full precision vs resized/ saturated output, valid_only mode, consumer backpressure stalls, and input valid gaps. Plain `python3 dc_block_test.py` runs the sim_call tests; the @MAIN entry points below also give `pypelinec dc_block_test.py --comb` elaboration coverage of every mode. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `dwidth_converter_test` | [inst/dwidth_converter_test.py](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py) | Python / sim_call | M 1.2 s / PASS | Width split/assembly and narrow/wide AXIS conversion preserve full/partial beats and packet boundaries. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `enum_test` | [inst/enum_test.py](../../../src/tests/pypeline_tests/inst/enum_test.py) | Python / sim_call | M 0.5 s / PASS | Static, factory, plain-class and automatic enums work in ports, state and nested records. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `example_blink_sim` | [examples/pypeline/blink.py](../../../examples/pypeline/blink.py) | CLI native comb | M 1.0 s / PASS | Run the getting-started LED blinker through the native CLI for three cycles. | Keep as documentation/CLI smoke, not a numeric oracle; consolidate entrypoint setup where practical. | fast candidate |
| `example_counter_sim` | [examples/pypeline/counter.py](../../../examples/pypeline/counter.py) | CLI native comb | M 0.8 s / PASS | Run the getting-started counter through the native CLI for three cycles. | Keep as documentation/CLI smoke, not a numeric oracle; consolidate entrypoint setup where practical. | fast candidate |
| `example_fsm_sim` | [examples/pypeline/fsm.py](../../../examples/pypeline/fsm.py) | CLI native comb | M 0.7 s / PASS | Run the introductory three-state FSM through the native CLI for seven cycles. | Keep as documentation/CLI smoke, not a numeric oracle; consolidate entrypoint setup where practical. | fast candidate |
| `example_pipeline_sim` | [examples/pypeline/pipeline.py](../../../examples/pypeline/pipeline.py) | CLI native comb | M 1.9 s / PASS | Exercise the float pipeline example CLI with undriven zero-valued inputs for two cycles. | Keep as documentation/CLI smoke, not a numeric oracle; consolidate entrypoint setup where practical. | fast candidate |
| `example_stream_pipeline_sim` | [examples/pypeline/stream_pipeline.py](../../../examples/pypeline/stream_pipeline.py) | CLI native comb | M 1.0 s / PASS | Run the documented global-wire stream-pipeline example for twenty cycles. | Keep as documentation/CLI smoke, not a numeric oracle; consolidate entrypoint setup where practical. | fast candidate |
| `factory_arg_port_annotation_test` | [inst/factory_arg_port_annotation_test.py](../../../src/tests/pypeline_tests/inst/factory_arg_port_annotation_test.py) | Python / sim_call | M 1.8 s / PASS | Port annotations that reach a type through a factory argument (`p: src.pair_t`). | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `factory_main_pipeline_latency_test` | [inst/factory_main_pipeline_latency_test.py](../../../src/tests/pypeline_tests/inst/factory_main_pipeline_latency_test.py) | Python assertions / wrapper | M 3.6 s / PASS | Native simulation of factory-made @MAINs that reach a @pipeline_latency function, with build timing that differs between them. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `factory_main_sim_test` | [inst/factory_main_sim_test.py](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py) | Python assertions / wrapper | M 3.0 s / PASS | Native simulation of @MAINs made in code (MAIN(fn, name=...)). Each design below runs through pypeline_sim.py in a subprocess; the test checks its output. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `feedback_reeval_test` | [inst/feedback_reeval_test.py](../../../src/tests/pypeline_tests/inst/feedback_reeval_test.py) | Python / sim_call | M 0.3 s / PASS | Feedback convergence advances stateful children/registers once per clock across evaluation orders. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fifo_sim_model_convergence_test` | [inst/fifo_sim_model_test.py](../../../src/tests/pypeline_tests/inst/fifo_sim_model_test.py) | multi-MAIN native | M 0.3 s / PASS | Wire-convergence stress test for make_fifo's _FifoFwftModel: run only via the multi-MAIN runner (pypeline_sim.py fifo_sim_model_test.py --run N). Not a plain-python3 test (no __main__ block) and not elaborated/synthesized by pypelinec -- mirrors global_wires_sim_test.py's structure/registration. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fifo_test` | [inst/fifo_test.py](../../../src/tests/pypeline_tests/inst/fifo_test.py) | Python / sim_call | M 0.4 s / PASS | FWFT FIFO empty/full behavior, rounded capacity, simultaneous push/pop, ordering and reference-model soak. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fir_decim_tb` | [examples/pypeline/dsp/fir_decim_tb.py](../../../examples/pypeline/dsp/fir_decim_tb.py) | CLI native comb | M 49.5 s / PASS | Run the documented 5x FIR decimator example through the shared exact testbench. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/slow |
| `fir_decim_test` | [inst/fir_decim_test.py](../../../src/tests/pypeline_tests/inst/fir_decim_test.py) | Python / sim_call | M 2.5 s / PASS | dsp/fir_decim.py make_fir_decim tests: golden = every decim-th convolution output; phase alignment across consumer stalls and input valid gaps; valid_only mode; decim=1 equivalence with make_fir. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fir_interp_tb` | [examples/pypeline/dsp/fir_interp_tb.py](../../../examples/pypeline/dsp/fir_interp_tb.py) | CLI native comb | M 87.0 s / PASS | Run the documented 4x interpolation/zero-stuffing FIR example through the shared exact testbench. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/slow |
| `fir_interp_test` | [inst/fir_interp_test.py](../../../src/tests/pypeline_tests/inst/fir_interp_test.py) | Python / sim_call | M 4.0 s / PASS | dsp/fir_interp.py tests: make_zero_stuffer beat sequence/backpressure and make_fir_interp vs golden (zero-stuff + convolve), output ordering, the rate law (outputs = interp x accepted inputs), and stall recovery. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fir_lowpass_tb` | [examples/pypeline/dsp/fir_lowpass_tb.py](../../../examples/pypeline/dsp/fir_lowpass_tb.py) | CLI native comb | M 43.5 s / PASS | Run the documented lowpass FIR example through the shared exact FIR testbench. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/slow |
| `fir_sim_tb_test` | [inst/fir_sim_tb_test.py](../../../src/tests/pypeline_tests/inst/fir_sim_tb_test.py) | multi-MAIN native | M 16.2 s / PASS | dsp/fir_tb.py testbench-library end-to-end test: two filters (elastic with random consumer backpressure + valid_only) each driven cycle-by-cycle through @sim_input and checked against the exact golden model by a @sim_output. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fir_test` | [inst/fir_test.py](../../../src/tests/pypeline_tests/inst/fir_test.py) | Python / sim_call | M 3.7 s / PASS | dsp/fir.py make_fir tests: impulse/step/random stimulus vs the exact integer golden model (dsp/fir_tb.golden_fir), symmetry-folded vs unfolded bit-identity, half-band zero-tap skipping, antisymmetric folding, full precision mode, valid_only mode, consumer backpressure stalls, and input valid gaps. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `fixed_point_test` | [inst/fixed_point_test.py](../../../src/tests/pypeline_tests/inst/fixed_point_test.py) | Python / sim_call | M 1.7 s / PASS | Fixed-point arithmetic versus Fraction, signedness, rounding ties, wrap/saturation and coefficient quantization. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `float32_add_test` | [inst/float32_add_test.py](../../../src/tests/pypeline_tests/inst/float32_add_test.py) | Python / sim_call | M 1.8 s / PASS | Float32 addition values plus HDL shapes for negation, absolute value, shifts, leading-zero count and constants. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `float_ops_test` | [inst/float_ops_test.py](../../../src/tests/pypeline_tests/inst/float_ops_test.py) | Python / sim_call | M 1.6 s / PASS | Registered floating arithmetic/conversion and negate behavior, including unsupported operators and primitive width boundaries. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `func_wires_test` | [inst/func_wires_test.py](../../../src/tests/pypeline_tests/inst/func_wires_test.py) | Python / sim_call | M 0.4 s / PASS | Explicit wiring-only helpers and MAINs preserve field/byte connections and native values. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `global_fifo_sim_test` | [inst/global_fifo_sim_test.py](../../../src/tests/pypeline_tests/inst/global_fifo_sim_test.py) | CLI native comb | M 4.5 s / PASS | Native simulation of global FIFOs, Fifo[T], with each kind of initializer: global_fifo(n), global_sync_fifo(n), make_stream_fifo(T, n) and make_skid_buffer(T), plus a FIFO declared in an imported module (global_fifo_sim_sub_design.e). | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `global_inst_sim_test` | [inst/global_inst_sim_test.py](../../../src/tests/pypeline_tests/inst/global_inst_sim_test.py) | CLI native comb | M 2.1 s / PASS | Native simulation of global instances, Inst[f], each checked by sim_assert in the functions that use it: | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `global_wire_array_split_test` | [inst/global_wire_array_split_test.py](../../../src/tests/pypeline_tests/inst/global_wire_array_split_test.py) | CLI native comb | M 0.9 s / PASS | Self-checking @MAIN test for an ARRAY-typed global Wire[T] split by constant element indices between two writer functions: main_01 drives arr_w[0..1] via an unrolled `for i in range(2)` loop, main_23 drives arr_w[2..3] via `range(2, 4)`. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_cond_driver_test` | [inst/global_wire_cond_driver_test.py](../../../src/tests/pypeline_tests/inst/global_wire_cond_driver_test.py) | CLI native comb | M 0.9 s / PASS | Self-checking @MAIN test for CONDITIONALLY driven fields of a split compound Wire[T] -- the clock-enable idiom. main_cond drives w.en and w.x only on odd cycles, inside a bare `if` with no else; on even cycles those leaves must read ZERO everywhere (the implicit zero-init default is the else-value of the write mux). main_always drives w.y every cycle. checker uses w.en as a clock enable gating a counting Reg. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_dynamic_index_write_test` | [inst/global_wire_dynamic_index_write_test.py](../../../src/tests/pypeline_tests/inst/global_wire_dynamic_index_write_test.py) | CLI native comb | M 0.7 s / PASS | Self-checking @MAIN test for a genuinely RUNTIME (non-unrolled) variable index write to an array-typed global Wire[T]: writer computes its target index from a free-running Reg (`idx = n & 3`, a real hardware value, not a Python `for` loop constant), so elaboration must go through _emit_var_ref_assign / VAR_REF_ASSIGN rather than unrolling to constant indices the way global_wire_array_split_test.py's `for i in range(N)` loops do. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_hier_writer_test` | [inst/global_wire_hier_writer_test.py](../../../src/tests/pypeline_tests/inst/global_wire_hier_writer_test.py) | CLI native comb | M 0.8 s / PASS | Self-checking @MAIN test for a global Wire[T] field driven from INSIDE the instance hierarchy, not a plain top-level @MAIN body: main_a -> mid -> leaf_writer, where leaf_writer (two call levels deep) drives w.x, while main_b drives w.y directly at MAIN level -- a split-field wire whose writers sit at different hierarchy depths. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_nested_split_test` | [inst/global_wire_nested_split_test.py](../../../src/tests/pypeline_tests/inst/global_wire_nested_split_test.py) | CLI native comb | M 1.0 s / PASS | Three writers own criss-crossed nested struct leaves; whole-subtree writes and readback preserve ownership. | Keep native and synthesis coverage; add/recheck the missing GHDL nested-writer case, tracking a narrow failure if it still reproduces. | fast candidate |
| `global_wire_partial_field_test` | [inst/global_wire_partial_field_test.py](../../../src/tests/pypeline_tests/inst/global_wire_partial_field_test.py) | CLI native comb | M 0.8 s / PASS | Self-checking @MAIN test for compound-type Wire[T] partial-field driving (single writer): the sole writer of a Wire[point_t] drives only `.x`, leaving `.y` untouched. `.y` must read as zero everywhere -- the base wire behaves as if implicitly driven with zeros before the writer's real assignments, exactly like a local variable's implicit zero-init. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_read_write_test` | [inst/global_wire_read_write_test.py](../../../src/tests/pypeline_tests/inst/global_wire_read_write_test.py) | CLI native comb | M 0.8 s / PASS | Self-checking @MAIN test for reading AND writing the same global Wire[T] within its one writer function: normal local-variable semantics apply -- writes and reads interleave in program order, the final value at the end of the function is what every other function sees that cycle, and reading a leaf before it has been written (even within the writer itself) returns zero (the writer's own implicit zero-init), not an elaboration error. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_readback_test` | [inst/global_wire_readback_test.py](../../../src/tests/pypeline_tests/inst/global_wire_readback_test.py) | CLI native comb | M 1.0 s / PASS | Self-checking @MAIN test for cross-writer readback on a split compound Wire[T]: a writer reading a leaf ANOTHER writer drives must see that writer's live value (flattened-leaf semantics), not local zeros and not an error -- while its own read-before-write leaves still read zero. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wire_split_driver_test` | [inst/global_wire_split_driver_test.py](../../../src/tests/pypeline_tests/inst/global_wire_split_driver_test.py) | CLI native comb | M 0.9 s / PASS | Self-checking @MAIN test for compound-type Wire[T] split across multiple writer functions: main_a drives only `.x` of a shared struct wire, main_b drives only `.y` -- disjoint top-level fields of the SAME wire, each with its own writer function (elaboration validates the fields are non-overlapping; VHDL.py emits one per-field concurrent assignment per field, sourced from its own writer, instead of the single whole-wire assignment used when a wire has exactly one writer). | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `global_wires_sim_test` | [inst/global_wires_sim_test.py](../../../src/tests/pypeline_tests/inst/global_wires_sim_test.py) | multi-MAIN native | M 0.3 s / PASS | Two register-bearing MAINs exchange global wires; current test prints activity but asserts no expected values. | Strengthen with expected cycle values or merge into an existing asserted convergence test; printing alone is only a smoke check. | fast candidate |
| `hooks_order_native_comb` | [inst/hooks_order_test.py](../../../src/tests/pypeline_tests/inst/hooks_order_test.py) | Python assertions / wrapper | M 0.9 s / PASS | @initial/@final hooks through the pypelinec driver: runs hooks_design.py in a pypelinec subprocess and checks where its "HOOK: <name>" markers land in the output, relative to the driver's own progress lines. Variant: native_comb. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `hooks_test` | [inst/hooks_test.py](../../../src/tests/pypeline_tests/inst/hooks_test.py) | Python assertions / wrapper | M 0.4 s / PASS | Initial/final hook order, exactly-once calls, mode filtering and original errors survive normal termination, cutoffs and failures. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `host_types_test` | [inst/host_types_test.py](../../../src/tests/pypeline_tests/inst/host_types_test.py) | Python assertions / wrapper | M 1.6 s / PASS | Generated host encode/decode works outside this repository and matches Pypeline field values for raw random bytes in both endians. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `if_test` | [inst/if_test.py](../../../src/tests/pypeline_tests/inst/if_test.py) | Python / sim_call | M 1.8 s / PASS | Conditional dynamic array/struct reads and writes, default branch values, and nonzero integer conditions. | Share fixtures with var_ref_test, preserving both conditional and unconditional shapes. Native run currently tests integer conditions only. | fast candidate |
| `interface_array_port_test` | [inst/interface_array_port_test.py](../../../src/tests/pypeline_tests/inst/interface_array_port_test.py) | Python / sim_call | M 0.7 s / PASS | Array-valued interface ports support independently backpressured broadcast lanes. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `interface_boundary_test` | [inst/interface_boundary_test.py](../../../src/tests/pypeline_tests/inst/interface_boundary_test.py) | Python / sim_call | M 0.5 s / PASS | Generated reverse wiring composes with manually written FSM/interface-port modules in both directions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `interface_func_loop_test` | [inst/interface_func_loop_test.py](../../../src/tests/pypeline_tests/inst/interface_func_loop_test.py) | Python / sim_call | M 0.4 s / PASS | Feedforward loops and multi-output callees generate feedback edges correctly across FSM/datapath call ordering. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `interface_func_test` | [inst/interface_func_test.py](../../../src/tests/pypeline_tests/inst/interface_func_test.py) | Python / sim_call | M 0.7 s / PASS | Generated interface wiring matches a hand-written chain across bundles, multi-field reverse channels and invalid forms. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `interface_hw_func_pairing_error_test` | [inst/interface_hw_func_pairing_error_test.py](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py) | Python assertions / wrapper | M 0.4 s / PASS | Decoration rejects missing forward/reverse port halves; complete and intentionally one-directional interfaces remain legal. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `interface_mixing_rules_test` | [inst/interface_mixing_rules_test.py](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py) | Python / sim_call | M 0.7 s / PASS | Handwritten/generated interface composition rejects unpaired port halves and illegal statement access; separate factory instances retain distinct identities. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `interface_test` | [inst/interface_test.py](../../../src/tests/pypeline_tests/inst/interface_test.py) | Python / sim_call | M 0.3 s / PASS | Derived forward/reverse interface types preserve nesting, arrays, multi-bit credit feedback, memoized identity and legal declaration rules. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `live_root_default_ops_test` | [inst/live_root_default_ops_test.py](../../../src/tests/pypeline_tests/inst/live_root_default_ops_test.py) | Python / sim_call | M 25.7 s / PASS | Plain sim_call of a function that reaches a @pipeline_latency callee and contains an integer compare. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `log2_db_test` | [inst/log2_db_test.py](../../../src/tests/pypeline_tests/inst/log2_db_test.py) | Python / sim_call | M 44.5 s / PASS | ROM and piecewise-linear dB conversion match exact golden and math.log10 oracles, including nonpositive floors, binary points, monotonicity and independent ROM latencies. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | feature/slow |
| `lut_atan2_test` | [inst/lut_atan2_test.py](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py) | Python / sim_call | M 352.7 s / PASS | Independent numeric angle oracle, corner/table-boundary vectors, selected RAM plans and exact native/HDL latency alignment. | Keep numeric oracle and distinct width/unequal-latency variants. Split dense numeric sweep from a small fast sample; batch HDL configurations only if all cases remain observable. | feature/slow |
| `lut_nco_test` | [inst/lut_nco_test.py](../../../src/tests/pypeline_tests/inst/lut_nco_test.py) | Python / sim_call | M 12.0 s / PASS | ROM oscillator values match bit-exact and independent trigonometric oracles, covering quadrants, saturation, envelope, spur/frequency bounds and pipeline latency. | Keep math and bit-exact native oracles. self_check_dsp_rom supplies HDL coverage; audit configuration differences before adding another full run. | fast candidate |
| `magnitude_tb` | [examples/pypeline/dsp/magnitude_tb.py](../../../examples/pypeline/dsp/magnitude_tb.py) | CLI native comb | M 6.8 s / PASS | Run the documented I/Q power example with golden checking in elastic and valid-only modes. | Keep as example integration; library unit cases do not verify that this documented composition still works. | fast candidate |
| `magnitude_test` | [inst/magnitude_test.py](../../../src/tests/pypeline_tests/inst/magnitude_test.py) | Python / sim_call | M 1.7 s / PASS | dsp/magnitude.py make_magnitude tests: random I/Q stimulus vs the exact integer golden model (dsp/dsp_tb.golden_magnitude), full precision vs resized/saturated output, valid_only mode, consumer backpressure stalls, and input valid gaps. Plain `python3 magnitude_test.py` runs the sim_call tests; the @MAIN entry points below also give `pypelinec magnitude_test.py --comb` elaboration coverage of every mode. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `main_args_sim_test` | [inst/main_args_sim_test.py](../../../src/tests/pypeline_tests/inst/main_args_sim_test.py) | multi-MAIN native | M 0.3 s / PASS | Native MAIN scalar/struct/array input ports receive fresh typed zeros on each evaluation, even after a callee mutates an input array. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `moving_avg_tb` | [examples/pypeline/dsp/moving_avg_tb.py](../../../examples/pypeline/dsp/moving_avg_tb.py) | CLI native comb | M 20.9 s / PASS | Run the documented noisy-step smoothing example with golden checking and noise-reduction assertions. | Keep as example integration; library unit cases do not verify that this documented composition still works. | fast candidate |
| `moving_avg_test` | [inst/moving_avg_test.py](../../../src/tests/pypeline_tests/inst/moving_avg_test.py) | Python / sim_call | M 1.6 s / PASS | dsp/moving_avg.py make_moving_avg tests: random stimulus vs the exact integer golden model (dsp/dsp_tb.golden_moving_avg), normalized vs raw-sum (non-power-of-two) modes, full precision vs resized/saturated output, valid_only mode, consumer backpressure stalls, and input valid gaps. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `multi_rate_sim_refusal_test` | [inst/multi_rate_sim_refusal_test.py](../../../src/tests/pypeline_tests/inst/multi_rate_sim_refusal_test.py) | Python assertions / wrapper | M 2.2 s / PASS | Native simulation refuses a design whose @MAINs name more than one clock (issue #354): it would step every MAIN once per cycle, running the clocks in lockstep. Both entry points, pypeline_sim.py and pypelinec --sim --comb, must exit non-zero and name both clocks and their MAINs: two rates, and two named clocks of one rate. A bare @MAIN next to one clock names no clock of its own, so that design still simulates. | Keep both CLI refusal paths and the one-clock positive control; unsupported multi-clock native sim must fail explicitly. | fast candidate |
| `pdw_tb` | [examples/pypeline/dsp/pdw/pdw_tb.py](../../../examples/pypeline/dsp/pdw/pdw_tb.py) | CLI native comb | D ≈9000 s old CORDIC projection; current ROM unmeasured | Whole PDW chain: control-frame writes, pulse detection/measurement/extraction, record serialization and exact golden field values across eight pulse scenarios. | Keep as application integration/nightly. Add a reduced-pulse targeted run; the documented 9000 s projection was CORDIC, while current default is ROM and its liveness deadline has since doubled. Re-measure before budgeting. | deep/nightly |
| `pipeline_latency_test` | [inst/pipeline_latency_test.py](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py) | Python / sim_call | M 51.8 s / PASS | Fixed user pipelines: native alignment and compiler metadata regressions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | feature/slow |
| `pipelinec_native_sim_test` | [inst/global_wires_sim_test.py](../../../src/tests/pypeline_tests/inst/global_wires_sim_test.py) | CLI native comb | M 0.8 s / PASS | Two register-bearing MAINs exchange global wires; current test prints activity but asserts no expected values. | Consolidate CLI-entry smoke: direct runner covers this fixture and many other asserted native tests cover pypelinec. Savings are under one second each; low priority. | fast candidate |
| `pylist_value_context_test` | [inst/pylist_value_context_test.py](../../../src/tests/pypeline_tests/inst/pylist_value_context_test.py) | Python / sim_call | M 0.3 s / PASS | Module/closure Python-list constants are usable inside hardware value expressions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `pypeline_test` | [inst/pypeline_test.py](../../../src/tests/pypeline_tests/inst/pypeline_test.py) | Python / sim_call | M 1.5 s / PASS | Broad language smoke shapes: registers/instances, feedback, clock enable, aggregates, loops, calls and typed arithmetic. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `ram_sim_model_convergence_test` | [inst/ram_sim_model_test.py](../../../src/tests/pypeline_tests/inst/ram_sim_model_test.py) | multi-MAIN native | M 0.7 s / PASS | Wire-convergence stress test for the RAM simulation model: run only via the multi-MAIN runner (pypeline_sim.py ram_sim_model_test.py --run N). Not a plain-python3 test (no __main__ block) and not built by pypelinec -- mirrors fifo_sim_model_test.py's structure and registration. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `ram_test` | [inst/ram_test.py](../../../src/tests/pypeline_tests/inst/ram_test.py) | Python / sim_call | M 9.8 s / PASS | RAM read-first timing, write gating/collisions, byte enables, init/reset, instance isolation and independent reference soaks; matching MAINs exercise generated RAM HDL. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `reg_aug_assign_convergence_test` | [inst/reg_aug_assign_test.py](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py) | multi-MAIN native | M 0.8 s / PASS | Augmented assignments match plain assignments for width wrapping, repeated evaluation, aggregate leaves, feedback and instance isolation; parameter writes cannot alias caller registers. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `reg_aug_assign_test` | [inst/reg_aug_assign_test.py](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py) | Python / sim_call | M 0.9 s / PASS | Augmented assignments match plain assignments for width wrapping, repeated evaluation, aggregate leaves, feedback and instance isolation; parameter writes cannot alias caller registers. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `reg_bitwise_mask_test` | [inst/reg_bitwise_mask_test.py](../../../src/tests/pypeline_tests/inst/reg_bitwise_mask_test.py) | Python / sim_call | M 0.4 s / PASS | Typed register bitwise operations truncate negative/raw operands and retain state across clocks. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `reg_init_test` | [inst/reg_init_test.py](../../../src/tests/pypeline_tests/inst/reg_init_test.py) | Python / sim_call | M 0.3 s / PASS | Scalar/signed/array/struct register initialization, field writes and reset restore the declared values. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `reg_undefined_width_test` | [inst/reg_undefined_width_test.py](../../../src/tests/pypeline_tests/inst/reg_undefined_width_test.py) | Python / sim_call | M 1.0 s / PASS | Nonstandard-width register state persists; bogus register types are rejected. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `self_check_auto_fsm_comb_test` | [inst/self_check_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_test.py) | CLI native comb | M 0.7 s / PASS | Golden arithmetic values through raw AUTO_FSM launch/completion, in passthrough or scheduled mode. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_check_bit_math_test` | [inst/self_check_bit_math_test.py](../../../src/tests/pypeline_tests/inst/self_check_bit_math_test.py) | CLI native comb | M 1.0 s / PASS | A native MAIN checks a subset of typed-truncation/render-coordinate constants already covered by bit_math_test. | Merge/remove candidate after mapping every constant into bit_math_test; native-only today. Its claimed HDL registration and no-argument-MAIN limitation are stale. | fast candidate |
| `self_check_counter_test` | [inst/self_check_counter_test.py](../../../src/tests/pypeline_tests/inst/self_check_counter_test.py) | CLI native comb | M 0.7 s / PASS | Self-checking @MAIN test: a free-running counter checks its own value against the expected sequential count via sim_assert, then calls sim_finish() once done -- no external Python sim_call/assert harness needed. Pass/fail is entirely determined by whether the simulation halts cleanly (sim_finish, no assertion failure) vs. aborts (sim_assert failure) vs. runs forever without finishing. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_check_fifo_test` | [inst/self_check_fifo_test.py](../../../src/tests/pypeline_tests/inst/self_check_fifo_test.py) | CLI native comb | M 1.0 s / PASS | Self-checking @MAIN test: pushes a fixed stimulus table into a FIFO, then pops it back and checks FWFT order against the same table via sim_assert, then calls sim_finish() once the last expected value is confirmed -- no external Python sim_call/assert harness needed, mirroring self_check_counter_test.py and wireguard-fpga's syn_tb testbenches (fixed expected-value table, shift-register- style push/pop state machine, sim_assert + sim_finish for in-hardware checking). | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_check_loop_unpack_test` | [inst/self_check_loop_unpack_test.py](../../../src/tests/pypeline_tests/inst/self_check_loop_unpack_test.py) | CLI native comb | M 1.2 s / PASS | Self-checking @MAIN test: real end-to-end (GHDL-analyzed) coverage for the iteration-ordinal loop-naming scheme (_elab_for/_bind_const_target/ _elab_unpack_assign, plus _elab_call's expression-callee branch) -- loop_iter_naming_test.py already checks the elaborator's internal name/error-path contract in-process; this file proves the resulting VHDL actually builds and simulates correctly through real GHDL, not just that PARSE_FILE accepts it. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_check_ram_test` | [inst/self_check_ram_test.py](../../../src/tests/pypeline_tests/inst/self_check_ram_test.py) | CLI native comb | M 10.4 s / PASS | Self-checking make_ram / make_stream_ram design, diffed cycle by cycle between native simulation and real GHDL (native_vs_vhdl_sim_tests.py, with and without --comb; also run natively in native_sim_tests.py). | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_check_stream_auto_fsm_comb_test` | [inst/self_check_stream_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_fsm_test.py) | CLI native comb | M 1.0 s / PASS | AUTO_FSM stream data order and output backpressure, with passthrough or a real shared schedule. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_check_stream_auto_pipeline_ii1_test` | [inst/self_check_stream_auto_pipeline_ii1_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_pipeline_ii1_test.py) | CLI native comb | M 1.5 s / PASS | make_stream_auto_pipeline at one word per cycle, checked in native sim and cocotb+GHDL. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `self_timed_factory_test` | [inst/self_timed_factory_test.py](../../../src/tests/pypeline_tests/inst/self_timed_factory_test.py) | Python assertions / wrapper | M 5.6 s / PASS | Construct the self-timed datapath when automatic latency queries are forbidden. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `serdes_test` | [inst/serdes_test.py](../../../src/tests/pypeline_tests/inst/serdes_test.py) | Python / sim_call | M 6.0 s / PASS | Base-layer element-stream serializer/deserializer (stream/serializer.py, stream/deserializer.py). | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_assert_finish_test` | [inst/sim_assert_finish_test.py](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py) | Python / sim_call | M 2.0 s / PASS | sim_assert success/failure messages, sim_finish termination and legal bare-call elaboration. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_input_test` | [inst/sim_input_test.py](../../../src/tests/pypeline_tests/inst/sim_input_test.py) | multi-MAIN native | M 0.3 s / PASS | @sim_input + Input[T] test: exercises both supported call forms in the same design, per-cycle-varying Python-side counters (not Reg[T], to keep the driving value purely simulation-side), and a downstream @sim_output checker that asserts the exact expected combined value every cycle. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_loop_reg_state_loose_test` | [inst/sim_loop_reg_state_test.py](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py) | multi-MAIN native | M 0.2 s / PASS | Loop source span and iteration ordinal identify independent native state across for/while, repeated iterator values, nesting, stateless helpers and runtime gating. Variant: loose. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_loop_reg_state_raw_test` | [inst/sim_loop_reg_state_test.py](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py) | multi-MAIN native | M 0.4 s / PASS | Loop source span and iteration ordinal identify independent native state across for/while, repeated iterator values, nesting, stateless helpers and runtime gating. Variant: raw. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_loop_reg_state_test` | [inst/sim_loop_reg_state_test.py](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py) | Python / sim_call | M 0.3 s / PASS | Loop source span and iteration ordinal identify independent native state across for/while, repeated iterator values, nesting, stateless helpers and runtime gating. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_model_convergence_test` | [inst/sim_model_test.py](../../../src/tests/pypeline_tests/inst/sim_model_test.py) | multi-MAIN native | M 0.6 s / PASS | Python hardware models preserve delegation, return casts, independent state, reset and mutation semantics; multi-MAIN evaluation must not commit twice per clock. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_model_test` | [inst/sim_model_test.py](../../../src/tests/pypeline_tests/inst/sim_model_test.py) | Python / sim_call | M 0.8 s / PASS | Python hardware models preserve delegation, return casts, independent state, reset and mutation semantics; multi-MAIN evaluation must not commit twice per clock. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_output_direct_wire_test` | [inst/sim_output_direct_wire_test.py](../../../src/tests/pypeline_tests/inst/sim_output_direct_wire_test.py) | multi-MAIN native | M 0.5 s / PASS | Direct-read-by-bare-name test for @sim_output + Wire[T]/Output[T]: proves a @sim_output function can reference a global wire directly inside its own body (not merely receive it as a passed-in argument, the only pattern used by every pre-existing @sim_output usage in this repo), including when called from a nested non-MAIN helper rather than straight from a @MAIN body. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `sim_print_test` | [inst/sim_print_test.py](../../../src/tests/pypeline_tests/inst/sim_print_test.py) | Python / sim_call | M 3.7 s / PASS | Simulation printing frequency/arguments and hardware string-versus-character restrictions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `skid_buffer_test` | [inst/skid_buffer_test.py](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py) | Python / sim_call | M 1.1 s / PASS | All four buffer modes preserve data under stalls, advertise correct capacity/latency and cut the intended handshake paths. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `soft_ops_test` | [inst/soft_ops_test.py](../../../src/tests/pypeline_tests/inst/soft_ops_test.py) | Python / sim_call | M 154.7 s / PASS | Native-sim golden tests for the include/pypeline/operators soft library (src/pypeline.py's matcher-based generic operator registry + the soft implementations themselves), plus a small end-to-end check that register_soft_ops() actually causes plain `a + b` / `a < b` to dispatch to the soft implementation rather than the built-in path. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | feature/slow |
| `stream_auto_fsm_test` | [inst/stream_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/stream_auto_fsm_test.py) | Python / sim_call | M 2.2 s / PASS | Native-sim handshake test for make_stream_auto_fsm (include/pypeline/stream/stream_auto_fsm.py). Plain native sim never installs an AUTO_FSM schedule (pypeline_sim.py run directly), so ADD_FSM.fsm.latency stays 0 throughout and the wrapper's own latency/II are both 1 -- this test exercises the wrapper's HANDSHAKE PROTOCOL, not any particular schedule. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_auto_multi_cycle_test` | [inst/stream_auto_multi_cycle_test.py](../../../src/tests/pypeline_tests/inst/stream_auto_multi_cycle_test.py) | Python / sim_call | M 0.8 s / PASS | Fixed/start MCP stream counts determine handshake latency and generate the associated Vivado constraints. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_auto_pipeline_test` | [inst/stream_auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_test.py) | Python / sim_call | M 0.7 s / PASS | Elastic AUTO_PIPELINE stream steady drain and stall/recovery, plus its reusable full-build fixture. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_fifo_test` | [inst/stream_fifo_test.py](../../../src/tests/pypeline_tests/inst/stream_fifo_test.py) | Python / sim_call | M 0.6 s / PASS | Ready/valid FIFO ordering and backpressure through the stream wrapper. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_ii1_throughput_test` | [inst/stream_ii1_throughput_test.py](../../../src/tests/pypeline_tests/inst/stream_ii1_throughput_test.py) | Python / sim_call | M 17.9 s / PASS | One word per cycle (II=1) through every elastic AUTO_PIPELINE stream block. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_multi_cycle_test` | [inst/stream_multi_cycle_test.py](../../../src/tests/pypeline_tests/inst/stream_multi_cycle_test.py) | Python / sim_call | M 0.4 s / PASS | Fixed multi-cycle divider launch/wait/output handshake and Vivado timing exceptions. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_perf_probe_test` | [inst/stream_perf_probe_test.py](../../../src/tests/pypeline_tests/inst/stream_perf_probe_test.py) | CLI native comb | M 4.0 s / PASS | stream/stream_perf_probe.py end to end, under the real native simulator (`pypelinec stream_perf_probe_test.py --sim --comb --run 200`) and through VHDL elaboration (`--comb` synth entry): the probes must vanish from the hardware and, in sim, report the right numbers. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_perf_tb_test` | [inst/stream_perf_tb_test.py](../../../src/tests/pypeline_tests/inst/stream_perf_tb_test.py) | CLI native comb | M 7.6 s / PASS | A complete stream performance testbench under the real native simulator (`pypelinec stream_perf_tb_test.py --sim --comb --run all`) -- the shape pypeline_stream_perf_guide.md documents: | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_perf_test` | [inst/stream_perf_test.py](../../../src/tests/pypeline_tests/inst/stream_perf_test.py) | Python / sim_call | M 0.7 s / PASS | stream/stream_perf*.py + stream/stream_bottleneck.py + the converged AXIS sim source/sink: the metric definitions every measured design is compared on, checked against hand-worked synthetic traces, plus a sim_call run of a probed FIFO driven by axi.axis_sim.ConvergedAxisSimSource. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `stream_ram_test` | [inst/stream_ram_test.py](../../../src/tests/pypeline_tests/inst/stream_ram_test.py) | Python / sim_call | M 1.2 s / PASS | make_stream_ram (include/pypeline/stream/stream_ram.py): handshake checks plus synthesis tops. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `struct_ctor_narrow_test` | [inst/struct_ctor_narrow_test.py](../../../src/tests/pypeline_tests/inst/struct_ctor_narrow_test.py) | Python / sim_call | M 0.5 s / PASS | Struct construction truncates signed/unsigned and byte-boundary values like typed assignment. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `struct_ctor_positional_test` | [inst/struct_ctor_positional_test.py](../../../src/tests/pypeline_tests/inst/struct_ctor_positional_test.py) | CLI native comb | M 0.8 s / PASS | Self-checking @MAIN test for a compiler bug where a hw_func's `return` statement constructing a @struct with positional args (e.g. `return pair_t(a, b)` instead of `return pair_t(a=a, b=b)`) silently failed to wire any struct field, leaving the function's return_output permanently undriven -- SYN.py's pipeline scheduler would then spin to its stage_num cap and sys.exit(-1) instead of raising a clear elaboration error. | Keep for fast native-only runs; omit this redundant native branch when its comb native/GHDL compare is selected. Same design/mode, not extra full-suite coverage. | fast candidate |
| `type_axis_test` | [inst/type_axis_test.py](../../../src/tests/pypeline_tests/inst/type_axis_test.py) | Python / sim_call | M 7.6 s / PASS | All four struct/AXIS framing variants preserve packets, partial keep masks, length limits, back-to-back alignment and explicit runt recovery policies. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `type_byte_stream_test` | [inst/type_byte_stream_test.py](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py) | Python / sim_call | M 4.1 s / PASS | Struct streams match software byte layout exactly, including partial beats, per-value end markers, loopbacks, padding errors and externally encoded frames. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `type_bytes_sw_test` | [inst/type_bytes_sw_test.py](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py) | Python / sim_call | M 1.2 s / PASS | Software-side type <-> bytes conversion: pypeline.type_to_bytes / type_from_bytes and the @struct T.to_bytes / T.from_bytes classmethods. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `type_bytes_test` | [inst/type_bytes_test.py](../../../src/tests/pypeline_tests/inst/type_bytes_test.py) | Python / sim_call | M 1.3 s / PASS | Hardware type/byte layout and endian round trips for scalars, enums, arrays and nested ragged-width records. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `valid_join_test` | [inst/valid_join_test.py](../../../src/tests/pypeline_tests/inst/valid_join_test.py) | Python / sim_call | M 3.1 s / PASS | Independent arrivals, II=1, CE pauses, drain/reset and overflow for joins. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `vhdl_text_test` | [inst/vhdl_text_test.py](../../../src/tests/pypeline_tests/inst/vhdl_text_test.py) | Python / sim_call | M 0.3 s / PASS | Raw VHDL wrapper emission and the explicit refusal to execute unmodeled raw HDL in native sim. | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |
| `wire_discovery_passthrough_native_sim_test` | [inst/wire_discovery_passthrough_sim_test.py](../../../src/tests/pypeline_tests/inst/wire_discovery_passthrough_sim_test.py) | CLI native comb | M 0.7 s / PASS | Regression test for the pypeline_sim.py _discover_wire_names two-hop recursion gap: the top design here only imports wire_discovery_dataflow (a pure cross-module wiring file with zero Wire[T] of its own), which in turn imports wire_discovery_leaf_a/_b (which DO declare Wire[T]). | Consolidate CLI-entry smoke: direct runner covers this fixture and many other asserted native tests cover pypelinec. Savings are under one second each; low priority. | fast candidate |
| `wire_discovery_passthrough_sim_test` | [inst/wire_discovery_passthrough_sim_test.py](../../../src/tests/pypeline_tests/inst/wire_discovery_passthrough_sim_test.py) | multi-MAIN native | M 0.5 s / PASS | Regression test for the pypeline_sim.py _discover_wire_names two-hop recursion gap: the top design here only imports wire_discovery_dataflow (a pure cross-module wiring file with zero Wire[T] of its own), which in turn imports wire_discovery_leaf_a/_b (which DO declare Wire[T]). | Keep: native value/protocol assertions exercise semantics that successful HDL compilation does not check. | fast candidate |

## native_vs_vhdl_sim

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `call_arg_width_test_comb` | [inst/call_arg_width_test.py](../../../src/tests/pypeline_tests/inst/call_arg_width_test.py) | native + GHDL diff / comb | M 25.9 s / PASS | Scalar integer call arguments whose type differs from the callee's parameter. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `factory_arg_port_annotation_test_comb` | [inst/factory_arg_port_annotation_test.py](../../../src/tests/pypeline_tests/inst/factory_arg_port_annotation_test.py) | native + GHDL diff / comb | M 25.7 s / PASS | Port annotations that reach a type through a factory argument (`p: src.pair_t`). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_array_split_test_comb` | [inst/global_wire_array_split_test.py](../../../src/tests/pypeline_tests/inst/global_wire_array_split_test.py) | native + GHDL diff / comb | M 27.3 s / PASS | Self-checking @MAIN test for an ARRAY-typed global Wire[T] split by constant element indices between two writer functions: main_01 drives arr_w[0..1] via an unrolled `for i in range(2)` loop, main_23 drives arr_w[2..3] via `range(2, 4)`. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_cond_driver_test_comb` | [inst/global_wire_cond_driver_test.py](../../../src/tests/pypeline_tests/inst/global_wire_cond_driver_test.py) | native + GHDL diff / comb | M 25.4 s / PASS | Self-checking @MAIN test for CONDITIONALLY driven fields of a split compound Wire[T] -- the clock-enable idiom. main_cond drives w.en and w.x only on odd cycles, inside a bare `if` with no else; on even cycles those leaves must read ZERO everywhere (the implicit zero-init default is the else-value of the write mux). main_always drives w.y every cycle. checker uses w.en as a clock enable gating a counting Reg. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_dynamic_index_write_test_comb` | [inst/global_wire_dynamic_index_write_test.py](../../../src/tests/pypeline_tests/inst/global_wire_dynamic_index_write_test.py) | native + GHDL diff / comb | M 25.4 s / PASS | Self-checking @MAIN test for a genuinely RUNTIME (non-unrolled) variable index write to an array-typed global Wire[T]: writer computes its target index from a free-running Reg (`idx = n & 3`, a real hardware value, not a Python `for` loop constant), so elaboration must go through _emit_var_ref_assign / VAR_REF_ASSIGN rather than unrolling to constant indices the way global_wire_array_split_test.py's `for i in range(N)` loops do. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_hier_writer_test_comb` | [inst/global_wire_hier_writer_test.py](../../../src/tests/pypeline_tests/inst/global_wire_hier_writer_test.py) | native + GHDL diff / comb | M 25.8 s / PASS | Self-checking @MAIN test for a global Wire[T] field driven from INSIDE the instance hierarchy, not a plain top-level @MAIN body: main_a -> mid -> leaf_writer, where leaf_writer (two call levels deep) drives w.x, while main_b drives w.y directly at MAIN level -- a split-field wire whose writers sit at different hierarchy depths. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_partial_field_test_comb` | [inst/global_wire_partial_field_test.py](../../../src/tests/pypeline_tests/inst/global_wire_partial_field_test.py) | native + GHDL diff / comb | M 26.7 s / PASS | Self-checking @MAIN test for compound-type Wire[T] partial-field driving (single writer): the sole writer of a Wire[point_t] drives only `.x`, leaving `.y` untouched. `.y` must read as zero everywhere -- the base wire behaves as if implicitly driven with zeros before the writer's real assignments, exactly like a local variable's implicit zero-init. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_pipeline_aligned_test_comb` | [inst/global_wire_pipeline_aligned_test.py](../../../src/tests/pypeline_tests/inst/global_wire_pipeline_aligned_test.py) | native + GHDL diff / comb | M 68.9 s / PASS | Global wires used directly in the body of a pipelined function (pypeline_guide.md, "Global wires in pipelined code"). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_pipelined_main_test` | [inst/global_wire_pipelined_main_test.py](../../../src/tests/pypeline_tests/inst/global_wire_pipelined_main_test.py) | native + GHDL diff / scheduled/swept; device_models | M 309.7 s / PASS | A naturally pipelined pure @MAIN using global wires in its own body (pypeline_guide.md, "Global wires in pipelined code"), cycle-diffed native vs pipelined VHDL (native_vs_vhdl_sim, non---comb). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_read_write_test_comb` | [inst/global_wire_read_write_test.py](../../../src/tests/pypeline_tests/inst/global_wire_read_write_test.py) | native + GHDL diff / comb | M 27.3 s / PASS | Self-checking @MAIN test for reading AND writing the same global Wire[T] within its one writer function: normal local-variable semantics apply -- writes and reads interleave in program order, the final value at the end of the function is what every other function sees that cycle, and reading a leaf before it has been written (even within the writer itself) returns zero (the writer's own implicit zero-init), not an elaboration error. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_readback_test_comb` | [inst/global_wire_readback_test.py](../../../src/tests/pypeline_tests/inst/global_wire_readback_test.py) | native + GHDL diff / comb | M 29.9 s / PASS | Self-checking @MAIN test for cross-writer readback on a split compound Wire[T]: a writer reading a leaf ANOTHER writer drives must see that writer's live value (flattened-leaf semantics), not local zeros and not an error -- while its own read-before-write leaves still read zero. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `global_wire_split_driver_test_comb` | [inst/global_wire_split_driver_test.py](../../../src/tests/pypeline_tests/inst/global_wire_split_driver_test.py) | native + GHDL diff / comb | M 27.8 s / PASS | Self-checking @MAIN test for compound-type Wire[T] split across multiple writer functions: main_a drives only `.x` of a shared struct wire, main_b drives only `.y` -- disjoint top-level fields of the SAME wire, each with its own writer function (elaboration validates the fields are non-overlapping; VHDL.py emits one per-field concurrent assignment per field, sourced from its own writer, instead of the single whole-wire assignment used when a wire has exactly one writer). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `lut_atan2_angle_slow` | [inst/lut_atan2_test.py](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py) | native + GHDL diff / comb | M 94.7 s / PASS | Independent numeric angle oracle, corner/table-boundary vectors, selected RAM plans and exact native/HDL latency alignment. Variant: ATAN2_TEST_RECIP_LATENCY=1, ATAN2_TEST_ANGLE_LATENCY=3. | Keep numeric oracle and distinct width/unequal-latency variants. Split dense numeric sweep from a small fast sample; batch HDL configurations only if all cases remain observable. | feature/HDL |
| `lut_atan2_pdw_width` | [inst/lut_atan2_test.py](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py) | native + GHDL diff / comb | M 94.0 s / PASS | Independent numeric angle oracle, corner/table-boundary vectors, selected RAM plans and exact native/HDL latency alignment. Variant: ATAN2_TEST_INPUT_WIDTH=40. | Keep numeric oracle and distinct width/unequal-latency variants. Split dense numeric sweep from a small fast sample; batch HDL configurations only if all cases remain observable. | feature/HDL |
| `lut_atan2_recip_slow` | [inst/lut_atan2_test.py](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py) | native + GHDL diff / comb | M 103.7 s / PASS | Independent numeric angle oracle, corner/table-boundary vectors, selected RAM plans and exact native/HDL latency alignment. Variant: ATAN2_TEST_RECIP_LATENCY=3, ATAN2_TEST_ANGLE_LATENCY=1. | Keep numeric oracle and distinct width/unequal-latency variants. Split dense numeric sweep from a small fast sample; batch HDL configurations only if all cases remain observable. | feature/HDL |
| `lut_atan2_test_comb` | [inst/lut_atan2_test.py](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py) | native + GHDL diff / comb | M 80.6 s / PASS | Independent numeric angle oracle, corner/table-boundary vectors, selected RAM plans and exact native/HDL latency alignment. | Keep numeric oracle and distinct width/unequal-latency variants. Split dense numeric sweep from a small fast sample; batch HDL configurations only if all cases remain observable. | feature/HDL |
| `native_vs_vhdl_ap_test` | [inst/native_vs_vhdl_ap_test.py](../../../src/tests/pypeline_tests/inst/native_vs_vhdl_ap_test.py) | native + GHDL diff / scheduled/swept; device_models | M 186.4 s / PASS | Cycle-accuracy design for pypeline_sim_debug.py WITHOUT --comb: a stateful @MAIN feeding an AUTO_PIPELINE'd (with IO regs) comb stream every cycle. | Keep discovered AUTO_PIPELINE cycle parity; fix stale reference to synth_tests.py registration. | feature/HDL |
| `native_vs_vhdl_pipelined_main_test` | [inst/native_vs_vhdl_pipelined_main_test.py](../../../src/tests/pypeline_tests/inst/native_vs_vhdl_pipelined_main_test.py) | native + GHDL diff / scheduled/swept; device_models | M 174.3 s / PASS | Cycle-accuracy design for pypeline_sim_debug.py WITHOUT --comb: a PURE comb @MAIN (no AUTO_PIPELINE anywhere) that the throughput sweep slices naturally, plus a stateful checker @MAIN wired to it through global Wire[T]s. | Keep natural MAIN slicing/alignment parity; fix stale reference to synth_tests.py registration. | feature/HDL |
| `nested_truncate_test_comb` | [inst/nested_truncate_test.py](../../../src/tests/pypeline_tests/inst/nested_truncate_test.py) | native + GHDL diff / comb | M 25.8 s / PASS | Was nested_truncate_vhdl_mismatch_known_issue.py: int16_t squaring-then- truncating a value that overflows int16_t range used to compute a DIFFERENT result in real GHDL hardware than in native sim, because VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS's signed->signed NARROWING case emitted a plain numeric_std.resize(SIGNED, N) -- which is sign-preserving (copies the sign bit into the new MSB, keeps the low N-1 bits) -- instead of C's actual truncation rule (take the low N bits of the two's-complement representation… | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `pipeline_latency_sim_test` | [inst/pipeline_latency_sim_test.py](../../../src/tests/pypeline_tests/inst/pipeline_latency_sim_test.py) | native + GHDL diff / scheduled/swept; device_models | M 72.7 s / PASS | Native/GHDL oracle for fixed pipelines, bypass alignment and added stages. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `pipeline_latency_sim_test_comb` | [inst/pipeline_latency_sim_test.py](../../../src/tests/pypeline_tests/inst/pipeline_latency_sim_test.py) | native + GHDL diff / comb | M 43.6 s / PASS | Native/GHDL oracle for fixed pipelines, bypass alignment and added stages. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `reg_aug_assign_test_comb` | [inst/reg_aug_assign_test.py](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py) | native + GHDL diff / comb | M 32.7 s / PASS | Augmented assignments match plain assignments for width wrapping, repeated evaluation, aggregate leaves, feedback and instance isolation; parameter writes cannot alias caller registers. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_auto_comb_area_opt_composition_test` | [inst/self_check_auto_comb_area_opt_composition_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_comb_area_opt_composition_test.py) | native + GHDL diff / scheduled/swept; device_models | M 297.1 s / PASS | AREA_OPT composed with fixed/discovered pipelines and default AUTO_FSM. | Keep area-opt composition with pipeline/FSM. Correct docstring tool from pyrtl to device_models. | feature/HDL |
| `self_check_auto_comb_area_opt_composition_test_comb` | [inst/self_check_auto_comb_area_opt_composition_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_comb_area_opt_composition_test.py) | native + GHDL diff / comb | M 67.2 s / PASS | AREA_OPT composed with fixed/discovered pipelines and default AUTO_FSM. | Keep area-opt composition with pipeline/FSM. Correct docstring tool from pyrtl to device_models. | feature/HDL |
| `self_check_auto_comb_delay_opt_composition_test` | [inst/self_check_auto_comb_delay_opt_composition_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_comb_delay_opt_composition_test.py) | native + GHDL diff / scheduled/swept; device_models | M 190.1 s / PASS | DELAY_OPT composed with fixed/discovered pipelines and default AUTO_FSM. | Keep delay-opt composition with pipeline/FSM. Correct docstring tool from pyrtl to device_models. | feature/HDL |
| `self_check_auto_comb_delay_opt_composition_test_comb` | [inst/self_check_auto_comb_delay_opt_composition_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_comb_delay_opt_composition_test.py) | native + GHDL diff / comb | M 51.3 s / PASS | DELAY_OPT composed with fixed/discovered pipelines and default AUTO_FSM. | Keep delay-opt composition with pipeline/FSM. Correct docstring tool from pyrtl to device_models. | feature/HDL |
| `self_check_auto_fsm_array_mux_test` | [inst/self_check_auto_fsm_array_mux_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_array_mux_test.py) | native + GHDL diff / scheduled/swept; device_models | M 211.6 s / PASS | Self-checking AUTO_FSM design whose shared unit takes and returns ARRAYS, so its operand multiplexers select between whole `uint2_t[4]` values. | Keep array-valued operand mux shape in both modes; scalar FSM tests cannot replace it. | feature/HDL |
| `self_check_auto_fsm_array_mux_test_comb` | [inst/self_check_auto_fsm_array_mux_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_array_mux_test.py) | native + GHDL diff / comb | M 48.6 s / PASS | Self-checking AUTO_FSM design whose shared unit takes and returns ARRAYS, so its operand multiplexers select between whole `uint2_t[4]` values. | Keep array-valued operand mux shape in both modes; scalar FSM tests cannot replace it. | feature/HDL |
| `self_check_auto_fsm_constants_test` | [inst/self_check_auto_fsm_constants_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_constants_test.py) | native + GHDL diff / scheduled/swept; device_models | M 275.1 s / PASS | Typed constant cleanup and scoped constant arithmetic through real GHDL. | Keep independent constant/truncation golden values in both passthrough and scheduled hardware. | feature/HDL |
| `self_check_auto_fsm_constants_test_comb` | [inst/self_check_auto_fsm_constants_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_constants_test.py) | native + GHDL diff / comb | M 66.0 s / PASS | Typed constant cleanup and scoped constant arithmetic through real GHDL. | Keep independent constant/truncation golden values in both passthrough and scheduled hardware. | feature/HDL |
| `self_check_auto_fsm_pipelined_unit_test` | [inst/self_check_auto_fsm_pipelined_unit_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_pipelined_unit_test.py) | native + GHDL diff / scheduled/swept; device_models | M 943.2 s / PASS | Shared pipelined arithmetic, exact latency and stream stalls through GHDL. | Keep: selected pipelined shared units, busy requests, exact completion latency and stalls are not covered by a simple FSM. | deep/nightly |
| `self_check_auto_fsm_pipelined_unit_test_comb` | [inst/self_check_auto_fsm_pipelined_unit_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_pipelined_unit_test.py) | native + GHDL diff / comb | M 30.6 s / PASS | Shared pipelined arithmetic, exact latency and stream stalls through GHDL. | Keep: selected pipelined shared units, busy requests, exact completion latency and stalls are not covered by a simple FSM. | feature/HDL |
| `self_check_auto_fsm_poly1305_prologue` | [inst/self_check_auto_fsm_poly1305_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_poly1305_test.py) | native + GHDL diff / scheduled/swept; device_models | M 2969.6 s / PASS | Reduced-capacity unchanged Poly1305 fixture through native and GHDL. Variant: KERNEL=prologue. | Keep in nightly/integration: prologue arithmetic differs from epilogue; historical pass cost 2,969.6 s. | deep/nightly |
| `self_check_auto_fsm_poly1305_test` | [inst/self_check_auto_fsm_poly1305_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_poly1305_test.py) | native + GHDL diff / scheduled/swept; device_models | M 6617.6 s / FAIL | Reduced-capacity unchanged Poly1305 fixture through native and GHDL. Variant: KERNEL=epilogue. | Retain unchanged application arithmetic in nightly/integration; epilogue historically failed after 6,617.6 s with an empty log. Cause remains unresolved. | deep/nightly |
| `self_check_auto_fsm_select_share_test` | [inst/self_check_auto_fsm_select_share_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_select_share_test.py) | native + GHDL diff / scheduled/swept; device_models | M 676.3 s / PASS | Indexed compound reads, exclusive selection and arithmetic sharing in GHDL. | Keep: compound indexed results, width adaptation and pair sharing are distinct generated-datapath risks. | deep/nightly |
| `self_check_auto_fsm_select_share_test_comb` | [inst/self_check_auto_fsm_select_share_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_select_share_test.py) | native + GHDL diff / comb | M 107.1 s / PASS | Indexed compound reads, exclusive selection and arithmetic sharing in GHDL. | Keep: compound indexed results, width adaptation and pair sharing are distinct generated-datapath risks. | feature/HDL |
| `self_check_auto_fsm_split_test` | [inst/self_check_auto_fsm_split_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_split_test.py) | native + GHDL diff / scheduled/swept; device_models | M 2721.0 s / PASS | Self-checking AUTO_FSM design whose operations are too slow for one state, so forced descent must open them: a 32-bit add and subtract and a 16x16 inferred multiply are split into half-width built-in operators (operators/ soft_add.make_soft_add_split, make_soft_sub_split, operators/soft_mult. make_soft_mult_split), recursively, until each piece fits. | Retain forced-descent semantics in the deep FSM lane; derive a smaller fast witness before reducing this 2,721 s run. | deep/nightly |
| `self_check_auto_fsm_test` | [inst/self_check_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_test.py) | native + GHDL diff / scheduled/swept; device_models | M 747.6 s / PASS | Golden arithmetic values through raw AUTO_FSM launch/completion, in passthrough or scheduled mode. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | deep/nightly |
| `self_check_auto_fsm_test_comb` | [inst/self_check_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_fsm_test.py) | native + GHDL diff / comb | M 111.2 s / PASS | Golden arithmetic values through raw AUTO_FSM launch/completion, in passthrough or scheduled mode. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_auto_pipeline_ram_cli_target` | [inst/self_check_auto_pipeline_ram_target_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_pipeline_ram_target_test.py) | native + GHDL diff / comb | M 30.9 s / PASS | Fixed RAM geometry must agree in native and HDL, including a late PART. Variant: RAM_TARGET_IN_SOURCE=0. | Keep source-PART versus CLI-PART target reconciliation: their factory-construction timing differs. | feature/HDL |
| `self_check_auto_pipeline_ram_selected_plan` | [inst/self_check_auto_pipeline_ram_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_pipeline_ram_test.py) | native + GHDL diff / scheduled/swept; open_tools | M 382.1 s / PASS | Cycle oracle: banked raw RAM, pure-caller alignment, and stalled streams. Variant: AUTO_PIPELINE_RAM_AUTO=1. | Keep fixed-plan parity and real selected-plan replay; separate open_tools and Vivado lanes, whose geometry/mapping differs. | feature/HDL |
| `self_check_auto_pipeline_ram_selected_plan_vivado` | [inst/self_check_auto_pipeline_ram_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_pipeline_ram_test.py) | native + GHDL diff / scheduled/swept; vivado | M 1226.0 s / PASS | Cycle oracle: banked raw RAM, pure-caller alignment, and stalled streams. Variant: AUTO_PIPELINE_RAM_AUTO=1. | Keep fixed-plan parity and real selected-plan replay; separate open_tools and Vivado lanes, whose geometry/mapping differs. | deep/nightly |
| `self_check_auto_pipeline_ram_target_test_comb` | [inst/self_check_auto_pipeline_ram_target_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_pipeline_ram_target_test.py) | native + GHDL diff / comb | M 34.4 s / PASS | Fixed RAM geometry must agree in native and HDL, including a late PART. | Keep source-PART versus CLI-PART target reconciliation: their factory-construction timing differs. | feature/HDL |
| `self_check_auto_pipeline_ram_test_comb` | [inst/self_check_auto_pipeline_ram_test.py](../../../src/tests/pypeline_tests/inst/self_check_auto_pipeline_ram_test.py) | native + GHDL diff / comb | M 52.0 s / PASS | Cycle oracle: banked raw RAM, pure-caller alignment, and stalled streams. | Keep fixed-plan parity and real selected-plan replay; separate open_tools and Vivado lanes, whose geometry/mapping differs. | feature/HDL |
| `self_check_counter_test_comb` | [inst/self_check_counter_test.py](../../../src/tests/pypeline_tests/inst/self_check_counter_test.py) | native + GHDL diff / comb | M 27.3 s / PASS | Self-checking @MAIN test: a free-running counter checks its own value against the expected sequential count via sim_assert, then calls sim_finish() once done -- no external Python sim_call/assert harness needed. Pass/fail is entirely determined by whether the simulation halts cleanly (sim_finish, no assertion failure) vs. aborts (sim_assert failure) vs. runs forever without finishing. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_dsp_rom_swap` | [inst/self_check_dsp_rom_test.py](../../../src/tests/pypeline_tests/inst/self_check_dsp_rom_test.py) | native + GHDL diff / comb | M 93.0 s / PASS | NCO and log ROM latency alignment, bubbles and CE in native and GHDL. Variant: DSP_ROM_SWAP=1. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_dsp_rom_test_comb` | [inst/self_check_dsp_rom_test.py](../../../src/tests/pypeline_tests/inst/self_check_dsp_rom_test.py) | native + GHDL diff / comb | M 81.6 s / PASS | NCO and log ROM latency alignment, bubbles and CE in native and GHDL. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_factory_main_test_comb` | [inst/self_check_factory_main_test.py](../../../src/tests/pypeline_tests/inst/self_check_factory_main_test.py) | native + GHDL diff / comb | M 31.3 s / PASS | @MAINs made by factories, native against VHDL: three counter lanes made in a loop, each driving its own element of one wire; two stateless lanes made by one factory, each pushing its own word through its own instance of one make_stream_fifo FIFO; and a factory closure (not a MAIN) that drives a wire from a MAIN. | Keep factory lane/state parity; the companion sky130 build is a separate synthesis gate, not an exact duplicate. | feature/HDL |
| `self_check_fifo_test_comb` | [inst/self_check_fifo_test.py](../../../src/tests/pypeline_tests/inst/self_check_fifo_test.py) | native + GHDL diff / comb | M 31.9 s / PASS | Self-checking @MAIN test: pushes a fixed stimulus table into a FIFO, then pops it back and checks FWFT order against the same table via sim_assert, then calls sim_finish() once the last expected value is confirmed -- no external Python sim_call/assert harness needed, mirroring self_check_counter_test.py and wireguard-fpga's syn_tb testbenches (fixed expected-value table, shift-register- style push/pop state machine, sim_assert + sim_finish for in-hardware checking). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_fixed_auto_pipeline_test` | [inst/self_check_fixed_auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/self_check_fixed_auto_pipeline_test.py) | native + GHDL diff / scheduled/swept; device_models | M 205.4 s / PASS | Cycle-accuracy design for pypeline_sim_debug.py: a stateful @MAIN feeding an AUTO_PIPELINE(func, latency=2) call site every cycle. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_fixed_auto_pipeline_test_comb` | [inst/self_check_fixed_auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/self_check_fixed_auto_pipeline_test.py) | native + GHDL diff / comb | M 248.7 s / PASS | Cycle-accuracy design for pypeline_sim_debug.py: a stateful @MAIN feeding an AUTO_PIPELINE(func, latency=2) call site every cycle. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_global_fifo_test_comb` | [inst/self_check_global_fifo_test.py](../../../src/tests/pypeline_tests/inst/self_check_global_fifo_test.py) | native + GHDL diff / comb | M 29.4 s / PASS | Self-checking @MAIN test of a global FIFO, Fifo[T] of a struct: a producer offers numbered words on 3 cycles out of 4, a consumer takes them on 1 cycle out of 4, so the FIFO fills and pushes back. The consumer checks order with sim_assert and calls sim_finish() after the last word. | Keep behavioral parity; run the additional sky130 synthesis only in the synthesis lane unless its synthesis-specific value is deliberately retired. | feature/HDL |
| `self_check_global_inst_test_comb` | [inst/self_check_global_inst_test.py](../../../src/tests/pypeline_tests/inst/self_check_global_inst_test.py) | native + GHDL diff / comb | M 41.0 s / PASS | Self-checking @MAIN test of global instances, Inst[f]: a combinational instance whose inputs come from two MAINs, two instances of one stateful counter, a skid buffer instance between a producer and a consumer with backpressure, an AUTO_PIPELINE(f, latency=2) instance, and a make_ram instance (a pipeline_latency function, which native sim models without aligning anything around it: an instance's MAIN takes no added latency). | Keep behavioral parity; the companion sky130 build additionally tests synthesizability, not merely HDL legality. | feature/HDL |
| `self_check_loop_unpack_test_comb` | [inst/self_check_loop_unpack_test.py](../../../src/tests/pypeline_tests/inst/self_check_loop_unpack_test.py) | native + GHDL diff / comb | M 32.8 s / PASS | Self-checking @MAIN test: real end-to-end (GHDL-analyzed) coverage for the iteration-ordinal loop-naming scheme (_elab_for/_bind_const_target/ _elab_unpack_assign, plus _elab_call's expression-callee branch) -- loop_iter_naming_test.py already checks the elaborator's internal name/error-path contract in-process; this file proves the resulting VHDL actually builds and simulates correctly through real GHDL, not just that PARSE_FILE accepts it. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_mult_karatsuba_pipelined_test` | [inst/self_check_mult_karatsuba_pipelined_test.py](../../../src/tests/pypeline_tests/inst/self_check_mult_karatsuba_pipelined_test.py) | native + GHDL diff / scheduled/swept; device_models | M 213.4 s / PASS | Pipelined Karatsuba with inferred leaves, native vs real sliced VHDL (native_vs_vhdl_sim_tests.py, non---comb, sky130). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_mult_karatsuba_test_comb` | [inst/self_check_mult_karatsuba_test.py](../../../src/tests/pypeline_tests/inst/self_check_mult_karatsuba_test.py) | native + GHDL diff / comb | M 45.7 s / PASS | Self-checking Karatsuba multipliers, native vs generated VHDL (native_vs_vhdl_sim_tests.py, --comb). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_named_clock_pin_test_comb` | [inst/self_check_named_clock_pin_test.py](../../../src/tests/pypeline_tests/inst/self_check_named_clock_pin_test.py) | native + GHDL diff / comb | U (not measured) | Self-checking @MAIN test of a named clock arriving on a pin: two MAINs on sys_clk, make_clock(50.0, name="sys"), whose pin SYS_CLK replaces its port clk_50p0_sys. A producer pushes a counting sequence through a global FIFO, and a consumer checks its order with sim_assert and calls sim_finish() after the last word. | Keep: clock generation on an explicitly named input pin is separate from two-clock FIFO behavior. | feature/HDL |
| `self_check_ram_test` | [inst/self_check_ram_test.py](../../../src/tests/pypeline_tests/inst/self_check_ram_test.py) | native + GHDL diff / scheduled/swept; device_models | M 160.7 s / PASS | Self-checking make_ram / make_stream_ram design, diffed cycle by cycle between native simulation and real GHDL (native_vs_vhdl_sim_tests.py, with and without --comb; also run natively in native_sim_tests.py). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_ram_test_comb` | [inst/self_check_ram_test.py](../../../src/tests/pypeline_tests/inst/self_check_ram_test.py) | native + GHDL diff / comb | M 58.5 s / PASS | Self-checking make_ram / make_stream_ram design, diffed cycle by cycle between native simulation and real GHDL (native_vs_vhdl_sim_tests.py, with and without --comb; also run natively in native_sim_tests.py). | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_stream_auto_comb_area_opt_test_comb` | [inst/self_check_stream_auto_comb_area_opt_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_comb_area_opt_test.py) | native + GHDL diff / comb | M 50.2 s / PASS | AREA_OPT registered stream preserves two-cycle latency, II=1 and stable output under stalls. | Keep stream stalls/II and synthesis mode: its synth registration is non-comb, unlike the comb HDL comparison. | feature/HDL |
| `self_check_stream_auto_comb_delay_opt_test_comb` | [inst/self_check_stream_auto_comb_delay_opt_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_comb_delay_opt_test.py) | native + GHDL diff / comb | M 36.2 s / PASS | DELAY_OPT registered stream preserves two-cycle latency, II=1 and stable output under stalls. | Keep stream stalls/II and synthesis mode: its synth registration is non-comb, unlike the comb HDL comparison. | feature/HDL |
| `self_check_stream_auto_fsm_test` | [inst/self_check_stream_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_fsm_test.py) | native + GHDL diff / scheduled/swept; device_models | M 734.2 s / PASS | AUTO_FSM stream data order and output backpressure, with passthrough or a real shared schedule. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | deep/nightly |
| `self_check_stream_auto_fsm_test_comb` | [inst/self_check_stream_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_fsm_test.py) | native + GHDL diff / comb | M 118.0 s / PASS | AUTO_FSM stream data order and output backpressure, with passthrough or a real shared schedule. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_stream_auto_pipeline_ii1_test_comb` | [inst/self_check_stream_auto_pipeline_ii1_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_pipeline_ii1_test.py) | native + GHDL diff / comb | M 44.5 s / PASS | make_stream_auto_pipeline at one word per cycle, checked in native sim and cocotb+GHDL. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_two_struct_wire_writes_test_comb` | [inst/self_check_two_struct_wire_writes_test.py](../../../src/tests/pypeline_tests/inst/self_check_two_struct_wire_writes_test.py) | native + GHDL diff / comb | M 25.7 s / PASS | Regression: one function writing fields of two compound global wires of different struct types. Each written wire gets an implicit zero-init constant, declared at the function's def line; both constants once had the same name, so the second wire's type replaced the first's and VHDL writing failed ("Cant support this assignment in vhdl?"). Two MAINs split each wire's fields; a checker prints them every cycle. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `self_check_type_axis_test_comb` | [inst/self_check_type_axis_test.py](../../../src/tests/pypeline_tests/inst/self_check_type_axis_test.py) | native + GHDL diff / comb | M 51.0 s / PASS | Self-checking @MAIN test: a struct is serialized onto an AXI-Stream by make_type_to_axis, decoded straight back by make_axis_to_type, and checked field by field with sim_assert -- no external Python harness. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `sim_loop_reg_state_test_comb` | [inst/sim_loop_reg_state_test.py](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py) | native + GHDL diff / comb | M 28.3 s / PASS | Loop source span and iteration ordinal identify independent native state across for/while, repeated iterator values, nesting, stateless helpers and runtime gating. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `single_stateful_main_fixed_latency_test` | [inst/single_stateful_main_fixed_latency_test.py](../../../src/tests/pypeline_tests/inst/single_stateful_main_fixed_latency_test.py) | native + GHDL diff / scheduled/swept; device_models | M 52.8 s / PASS | A design whose ONLY @MAIN is stateful and has no target frequency, calling a fixed-latency (@pipeline_latency) function it consumes self-timed. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `single_stateful_main_fixed_latency_test_comb` | [inst/single_stateful_main_fixed_latency_test.py](../../../src/tests/pypeline_tests/inst/single_stateful_main_fixed_latency_test.py) | native + GHDL diff / comb | M 26.7 s / PASS | A design whose ONLY @MAIN is stateful and has no target frequency, calling a fixed-latency (@pipeline_latency) function it consumes self-timed. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `struct_ctor_positional_test_comb` | [inst/struct_ctor_positional_test.py](../../../src/tests/pypeline_tests/inst/struct_ctor_positional_test.py) | native + GHDL diff / comb | M 27.2 s / PASS | Self-checking @MAIN test for a compiler bug where a hw_func's `return` statement constructing a @struct with positional args (e.g. `return pair_t(a, b)` instead of `return pair_t(a=a, b=b)`) silently failed to wire any struct field, leaving the function's return_output permanently undriven -- SYN.py's pipeline scheduler would then spin to its stage_num cap and sys.exit(-1) instead of raising a clear elaboration error. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `typed_placement_alignment_test` | [inst/typed_placement_alignment_test.py](../../../src/tests/pypeline_tests/inst/typed_placement_alignment_test.py) | native + GHDL diff / scheduled/swept; device_models | M 50.7 s / PASS | Cycle-accurate VHDL regression for typed physical pipeline placement. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `valid_join_test_comb` | [inst/valid_join_test.py](../../../src/tests/pypeline_tests/inst/valid_join_test.py) | native + GHDL diff / comb | M 37.7 s / PASS | Independent arrivals, II=1, CE pauses, drain/reset and overflow for joins. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `var_ref_assign_cond_loop_test_comb` | [inst/var_ref_assign_cond_loop_test.py](../../../src/tests/pypeline_tests/inst/var_ref_assign_cond_loop_test.py) | native + GHDL diff / comb | M 28.2 s / PASS | Self-checking @MAIN test reproducing a crash in the elaboration of a dynamic-indexed array WRITE nested inside an `if` inside a `for` loop: _assemble_var_ref_coverage (PY_TO_LOGIC.py) does not forward branch_tag to its per-position _read_ref calls, so once a second unrolled loop iteration's `if`-false branch reads the first iteration's own if-mux alias (itself variable-indexed, same VAR-shaped ref_toks), the true and false per-position CONST_REF_RD reads collide on one generated instance name and elaboration… | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |
| `var_ref_assign_readback_test_comb` | [inst/var_ref_assign_readback_test.py](../../../src/tests/pypeline_tests/inst/var_ref_assign_readback_test.py) | native + GHDL diff / comb | M 29.9 s / PASS | Self-checking @MAIN test reproducing two data-corruption bugs in the elaboration of dynamic-indexed (runtime-index) array WRITES, both found via wireguard-fpga's append_auth_tag.py (issue #44 tkeep work): a dynamic write produced correct results in native sim but wrong data under real GHDL sim. | Keep: generated HDL cycle/data behavior is distinct from native values and build success. | feature/HDL |

## elab

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `array_2d_order_test` | [inst/array_2d_order_test.py](../../../src/tests/pypeline_tests/inst/array_2d_order_test.py) | elab/HDL emit, no synthesis | M 5.7 s / PASS | Non-square T[A][B] dimensions, row type and legal indexes preserve C array order. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `auto_pipeline_test` | [inst/auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_test.py) | elab/HDL emit, no synthesis | M 9.0 s / PASS | AUTO_PIPELINE construction, native passthrough/zero latency, and nested tagged submodules. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `bit_manip_test` | [inst/bit_manip_test.py](../../../src/tests/pypeline_tests/inst/bit_manip_test.py) | elab/HDL emit, no synthesis | M 5.7 s / PASS | HDL elaboration of selects/slices, concatenation, bit replication, rotates, byte swap, bit assignment and endian pack/unpack. | Expand: only elaboration runs. Native primitive bodies now exist; add independent value vectors and one HDL self-check for width/endian edges. | fast candidate |
| `cast_hw_func_test` | [inst/cast_hw_func_test.py](../../../src/tests/pypeline_tests/inst/cast_hw_func_test.py) | elab/HDL emit, no synthesis | M 11.6 s / PASS | User-defined computational casts and floating/integer converter registrations preserve values and hardware call lowering. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `cast_interface_test` | [inst/cast_interface_test.py](../../../src/tests/pypeline_tests/inst/cast_interface_test.py) | elab/HDL emit, no synthesis | M 6.1 s / PASS | Stream-interface wrap/unwrap casts preserve payload and feedback types in both directions. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `cast_test` | [inst/cast_test.py](../../../src/tests/pypeline_tests/inst/cast_test.py) | elab/HDL emit, no synthesis | M 5.6 s / PASS | Explicit integer casts agree with typed assignment across widening, narrowing, signedness and call/field contexts. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `clock_domain_inference_test` | [inst/clock_domain_inference_test.py](../../../src/tests/pypeline_tests/inst/clock_domain_inference_test.py) | elab/HDL emit, no synthesis | M 6.4 s / PASS | Regression test: clock assignment must trace a global Wire[T] access up through a called helper function, not just uses directly inside a MAIN's own top-level body. | Candidate to consolidate the helper-depth clock inference shape into clock_domains_elab_test with an explicit clock assertion. | fast candidate |
| `compound_init_test` | [inst/compound_init_test.py](../../../src/tests/pypeline_tests/inst/compound_init_test.py) | elab/HDL emit, no synthesis | M 6.0 s / PASS | Aggregate initialization/reassignment from calls, constant/wire lists, integer-key dictionaries and nested fields. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `dangling_logic_test` | [inst/dangling_logic_test.py](../../../src/tests/pypeline_tests/inst/dangling_logic_test.py) | elab/HDL emit, no synthesis | M 4.4 s / PASS | Unused/dangling logic elaborates and can be trimmed without corrupting the remaining design. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `func_wires_test` | [inst/func_wires_test.py](../../../src/tests/pypeline_tests/inst/func_wires_test.py) | elab/HDL emit, no synthesis | M 4.9 s / PASS | Explicit wiring-only helpers and MAINs preserve field/byte connections and native values. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `global_wires_test` | [inst/global_wires_test.py](../../../src/tests/pypeline_tests/inst/global_wires_test.py) | elab/HDL emit, no synthesis | M 6.0 s / PASS | Global Input/Output and cross-MAIN wire connectivity elaborate, including the legacy combinational-loop example. | Replace legacy loop-shaped smoke with an asserted legal connectivity fixture; preserve Input/Output elaboration coverage. | fast candidate |
| `hooks_order_call_from_hw` | [inst/hooks_order_test.py](../../../src/tests/pypeline_tests/inst/hooks_order_test.py) | Python assertions / wrapper | M 3.7 s / PASS | @initial/@final hooks through the pypelinec driver: runs hooks_design.py in a pypelinec subprocess and checks where its "HOOK: <name>" markers land in the output, relative to the driver's own progress lines. Variant: call_from_hw. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `hooks_order_no_synth` | [inst/hooks_order_test.py](../../../src/tests/pypeline_tests/inst/hooks_order_test.py) | Python assertions / wrapper | M 5.6 s / PASS | @initial/@final hooks through the pypelinec driver: runs hooks_design.py in a pypelinec subprocess and checks where its "HOOK: <name>" markers land in the output, relative to the driver's own progress lines. Variant: no_synth. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `import_test` | [inst/import_test.py](../../../src/tests/pypeline_tests/inst/import_test.py) | elab/HDL emit, no synthesis | M 5.9 s / PASS | Cross-file/transitive imports discover structs, functions, MAINs and global-wire connections. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `keyword_call_test` | [inst/keyword_call_test.py](../../../src/tests/pypeline_tests/inst/keyword_call_test.py) | elab/HDL emit, no synthesis | M 5.6 s / PASS | Elaboration of submodule calls whose arguments are passed by keyword. | Keep elaboration regression. Its test_keyword_calls_sim helper has no direct runner entry; decide whether to register that oracle or mark it manual. | fast candidate |
| `pylist_value_context_test` | [inst/pylist_value_context_test.py](../../../src/tests/pypeline_tests/inst/pylist_value_context_test.py) | elab/HDL emit, no synthesis | M 6.7 s / PASS | Module/closure Python-list constants are usable inside hardware value expressions. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `sim_input_output_elab_test` | [inst/sim_input_output_elab_test.py](../../../src/tests/pypeline_tests/inst/sim_input_output_elab_test.py) | elab/HDL emit, no synthesis | M 5.2 s / PASS | Elaboration-only (--no_synth) regression for @sim_input/@sim_output: proves a design combining both supported @sim_input call forms (direct-write and return-value) and a bare @sim_output call nested one level inside a plain, non-MAIN @hw_func elaborates cleanly -- no ElaborationError about writing a read-only Input[T]/reading an Output[T], no NotImplementedError about an unsupported statement -- with every sim-only call vanishing from the generated hardware. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `type_bytes_sw_test` | [inst/type_bytes_sw_test.py](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py) | elab/HDL emit, no synthesis | M 6.2 s / PASS | Software-side type <-> bytes conversion: pypeline.type_to_bytes / type_from_bytes and the @struct T.to_bytes / T.from_bytes classmethods. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `type_bytes_test` | [inst/type_bytes_test.py](../../../src/tests/pypeline_tests/inst/type_bytes_test.py) | elab/HDL emit, no synthesis | M 8.8 s / PASS | Hardware type/byte layout and endian round trips for scalars, enums, arrays and nested ragged-width records. | Keep lightweight syntax/elaboration smoke; add an artifact/value assertion only where the claimed behavior is invisible to successful exit. | fast candidate |
| `user_clock_test` | [inst/user_clock_test.py](../../../src/tests/pypeline_tests/inst/user_clock_test.py) | elab/HDL emit, no synthesis | M 4.2 s / PASS | Regression test: make_clock() tags a top-level Input[uint1_t] as a clock, the pypeline equivalent of PipelineC's DECL_INPUT + CLK_MHZ. `pll_clk` should become a real, fixed-name top-level port instead of the default rate-named clock port, with an internal clk_85p0 net driven from it. | Candidate to consolidate pin-binding smoke into clock_mhz_pragma_test; retain at least one emitted-top/clock-pin check. | fast candidate |

## elab_introspect

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `async_fifo_elab_test` | [inst/async_fifo_elab_test.py](../../../src/tests/pypeline_tests/inst/async_fifo_elab_test.py) | PARSE_FILE + assertions | U (not measured) | In-process checks of async global FIFOs: a Fifo[T] whose ends are used on two clocks. Each design is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE, then checked against the parser state, the raised ElaborationError, or the written crossing report. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | measure first |
| `auto_comb_area_opt_test` | [inst/auto_comb_area_opt_test.py](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py) | PARSE_FILE + assertions | M 209.9 s / PASS | Combinational sharing API, generated graph, and semantic regressions. | Keep graph/semantic checks; split expensive elaboration from constructor/native cases for targeted runs. | feature/slow |
| `auto_comb_delay_opt_test` | [inst/auto_comb_delay_opt_test.py](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py) | PARSE_FILE + assertions | M 263.3 s / PASS | Delay-first combinational API, graph, equivalence and timing regressions. | Keep timing-dependency and equivalence checks; split expensive elaboration from constructor/native cases. | feature/slow |
| `auto_fsm_purity_test` | [inst/auto_fsm_purity_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_purity_test.py) | PARSE_FILE + assertions | M 11.4 s / PASS | AUTO_FSM requires a pure function in its whole subtree (AUTO.FIND_EFFECTS), not just in the levels the scheduler opens. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `auto_fsm_var_index_read_test` | [inst/auto_fsm_var_index_read_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_var_index_read_test.py) | PARSE_FILE + assertions | M 68.9 s / PASS | Regression for #377: direct and nested variable-index array reads. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | feature/slow |
| `c_structs_pkg_relayout_test` | [inst/c_structs_pkg_relayout_test.py](../../../src/tests/pypeline_tests/inst/c_structs_pkg_relayout_test.py) | PARSE_FILE + assertions | M 77.6 s / PASS | c_structs_pkg stays valid VHDL when a type's layout changes between parse passes of one run but its emitted VHDL name doesn't. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | feature/slow |
| `cast_error_test` | [inst/cast_error_test.py](../../../src/tests/pypeline_tests/inst/cast_error_test.py) | PARSE_FILE + assertions | M 7.6 s / PASS | Unsupported cast pairs, arity/keywords, arrays and interface-half constructors fail with useful errors. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `clock_domains_elab_test` | [inst/clock_domains_elab_test.py](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py) | PARSE_FILE + assertions | U (not measured) | In-process checks of clock assignment and the clock-crossing check: each design below is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE, then checked against the parser state, the raised ElaborationError, or the printed notes and warnings. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | measure first |
| `clock_mhz_pragma_test` | [inst/clock_mhz_pragma_test.py](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py) | PARSE_FILE + assertions | M 3.2 s / PASS | In-process regression test for clocks bound to pins (pll_clk: Input[uint1_t] = make_clock(85.0), pypeline's CLK_MHZ equivalent). | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `closure_local_nested_struct_test` | [inst/closure_local_nested_struct_test.py](../../../src/tests/pypeline_tests/inst/closure_local_nested_struct_test.py) | PARSE_FILE + assertions | M 1.5 s / PASS | Factory-closure nested structs/enums register canonical hardware field types recursively. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `conditional_import_test` | [inst/conditional_import_test.py](../../../src/tests/pypeline_tests/inst/conditional_import_test.py) | PARSE_FILE + assertions | M 23.7 s / PASS | Design modules chosen by module-level `if`/`try` imports. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `cross_file_helper_name_test` | [inst/cross_file_helper_name_test.py](../../../src/tests/pypeline_tests/inst/cross_file_helper_name_test.py) | PARSE_FILE + assertions | M 1.8 s / PASS | A sub-file's helper call binds to the function that name means in THAT file. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `double_parse_file_test` | [inst/double_parse_file_test.py](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py) | PARSE_FILE + assertions | M 203.1 s / PASS | Repeated in-process parsing preserves modules, trimmed graphs, names, schedules and first-read source bytes. | Keep repeat-parse/source-freeze coverage; share setup within a coherent case group, not across tests that require fresh imports. | feature/slow |
| `factory_main_elab_test` | [inst/factory_main_elab_test.py](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py) | PARSE_FILE + assertions | M 13.3 s / PASS | In-process checks of @MAINs made in code (MAIN(fn, name=...)): each design below is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE, then checked against the parser state or the raised ElaborationError (the pattern of global_fifo_elab_test.py). | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `global_fifo_elab_test` | [inst/global_fifo_elab_test.py](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py) | PARSE_FILE + assertions | M 18.9 s / PASS | In-process checks of global FIFO (Fifo[T]) realization and its errors: each design below is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE, then checked against the parser state or the raised ElaborationError (the pattern of global_wire_errors_test.py). | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `global_fifo_pipeline_latency_test` | [inst/global_fifo_pipeline_latency_test.py](../../../src/tests/pypeline_tests/inst/global_fifo_pipeline_latency_test.py) | PARSE_FILE + assertions | M 3.1 s / PASS | A global FIFO's MAIN, added after the other functions are trimmed (PY_TO_LOGIC._add_late_mains), must not re-check those functions. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `global_inst_elab_test` | [inst/global_inst_elab_test.py](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py) | PARSE_FILE + assertions | M 16.3 s / PASS | In-process checks of global instances (Inst[f]) and their errors: each design below is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE, then checked against the parser state or the raised ElaborationError (the pattern of global_fifo_elab_test.py). | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `global_wire_errors_test` | [inst/global_wire_errors_test.py](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py) | PARSE_FILE + assertions | M 11.0 s / PASS | Wire ownership/direction, overlapping fields, constant/dynamic array writes and clean elaboration diagnostics. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `importfrom_test` | [inst/importfrom_test.py](../../../src/tests/pypeline_tests/inst/importfrom_test.py) | PARSE_FILE + assertions | M 1.8 s / PASS | Transitive from-import discovery registers a deeply imported struct's fields. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `interface_type_error_test` | [inst/interface_type_error_test.py](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py) | PARSE_FILE + assertions | M 25.5 s / PASS | Interface port-half types are rejected in registers, feedback and local non-port contexts; plain payload types remain valid. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `loc_str_multiline_binop_test` | [inst/loc_str_multiline_binop_test.py](../../../src/tests/pypeline_tests/inst/loc_str_multiline_binop_test.py) | PARSE_FILE + assertions | M 1.7 s / PASS | Source coordinates distinguish nested multiline binary-operator instances. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `local_binds_global_wire_test` | [inst/local_binds_global_wire_test.py](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py) | PARSE_FILE + assertions | M 13.2 s / PASS | Global Wire/Input/Output names vs. function locals. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `local_shadows_global_const_test` | [inst/local_shadows_global_const_test.py](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py) | PARSE_FILE + assertions | M 9.6 s / PASS | A hardware local must shadow a same-named Python global/closure name. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `loop_iter_naming_test` | [inst/loop_iter_naming_test.py](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py) | PARSE_FILE + assertions | M 16.4 s / PASS | In-process regression tests for the iteration-ordinal loop-naming scheme (PY_TO_LOGIC.py's _elab_for/_bind_const_target/_elab_unpack_assign, plus the expression-callee branch of _elab_call) -- covers every previously-unworkable loop shape this unlocks (tuple/dict/string/enumerate/zip iteration, a nested tuple target, tuple-unpacking assignment, an indexed/expression call target) and the FOR_<var>_ITER_<n>_ name-shape guarantee, plus its error paths (set/frozenset rejection, starred targets, arity mismatch, a… | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `mixed_granularity_reassign_test` | [inst/mixed_granularity_reassign_test.py](../../../src/tests/pypeline_tests/inst/mixed_granularity_reassign_test.py) | PARSE_FILE + assertions | M 2.8 s / PASS | A coarse aggregate write invalidates stale finer-field bindings before conditional readback. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `name_index_test` | [inst/name_index_test.py](../../../src/tests/pypeline_tests/inst/name_index_test.py) | PARSE_FILE + assertions | M 9.2 s / PASS | In-process PARSE_FILE regression tests for the name_index.log side-tables added alongside the generated-name readability work (see docs/PY_TO_LOGIC_DESIGN.md / docs/SYN_DESIGN.md): - parser_state.pypeline_name_full: collapsed canonical func name -> full, uncollapsed name (populated only when collapsing actually happened). - parser_state.pypeline_type_canonical: same idea for @struct/@enum types. - parser_state.pypeline_canonical_name_owner: collision guard -- two genuinely different closures landing on the… | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `operator_scope_test` | [inst/operator_scope_test.py](../../../src/tests/pypeline_tests/inst/operator_scope_test.py) | PARSE_FILE + assertions | M 3.9 s / PASS | Generic operator matching/priority, global exact INFERRED override, type validation and legal array-comparison names. | Keep the current registry oracle; scope= on top-level functions and shared scoped/unscoped callees are separately represented by the new known-issue test. | fast candidate |
| `ord_char_literal_test` | [inst/ord_char_literal_test.py](../../../src/tests/pypeline_tests/inst/ord_char_literal_test.py) | PARSE_FILE + assertions | M 10.0 s / PASS | Scalar character constants in a hardware function body. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `pylist_value_context_error_test` | [inst/pylist_value_context_error_test.py](../../../src/tests/pypeline_tests/inst/pylist_value_context_error_test.py) | PARSE_FILE + assertions | M 1.6 s / PASS | An undefined indexed reference raises ElaborationError rather than leaking KeyError. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `sim_input_local_error_test` | [inst/sim_input_local_error_test.py](../../../src/tests/pypeline_tests/inst/sim_input_local_error_test.py) | PARSE_FILE + assertions | M 11.2 s / PASS | A @sim_input/@sim_output value reaches hardware only through a module-level wire. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `soft_mult_karatsuba_leaves_test` | [inst/soft_mult_karatsuba_leaves_test.py](../../../src/tests/pypeline_tests/inst/soft_mult_karatsuba_leaves_test.py) | PARSE_FILE + assertions | M 51.4 s / PASS | Elaborated hierarchy of Karatsuba leaf policies (operators/soft_mult.py's make_soft_mult_karatsuba leaf=, make_inferred_mult and make_mult_karatsuba_inferred_leaves). | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | feature/slow |
| `two_factory_wrappers_test` | [inst/two_factory_wrappers_test.py](../../../src/tests/pypeline_tests/inst/two_factory_wrappers_test.py) | PARSE_FILE + assertions | M 4.2 s / PASS | Closure-callable and list-parameter identities select distinct correct elaborated implementations. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `wires_contract_test` | [inst/wires_contract_test.py](../../../src/tests/pypeline_tests/inst/wires_contract_test.py) | PARSE_FILE + assertions | M 8.8 s / PASS | Reject state, arithmetic and variable-index logic under @wires; accept actual rewiring and simulation-only control. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |
| `wiring_only_leaf_zero_delay_test` | [inst/wiring_only_leaf_zero_delay_test.py](../../../src/tests/pypeline_tests/inst/wiring_only_leaf_zero_delay_test.py) | PARSE_FILE + assertions | M 2.0 s / PASS | Stateless wire/constant-only leaves are untimed; stateful/operator leaves still require timing. | Keep: graph/type/diagnostic assertions catch errors that a successful build can miss. | fast candidate |

## unit

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `added_latency_context_test` | [inst/added_latency_context_test.py](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py) | Python assertions / wrapper | M 21.4 s / PASS | Compiler-added latency stays within an absorbing caller context; no synthesis. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `area_model_test` | [inst/area_model_test.py](../../../src/tests/pypeline_tests/inst/area_model_test.py) | Python assertions / wrapper | M 1.5 s / FAIL | Pure unit coverage for the sky130 area model: liberty area extraction, mapped-netlist area summation, the leaf cache/area (SYN.GET_AREA_CACHE_DIR and friends), and the whole-hierarchy estimate (SYN.GET_ESTIMATED_COMBINATIONAL_AREA/ESTIMATE_DESIGN_AREA). | Repair isolation: retain synthetic unit cases; move committed-cache calibration to a pinned dataset/QoR check. The old absolute-MAE failure is now addressed in source by a per-bit residual bound; current pass status was not rechecked. | fast candidate |
| `async_fifo_path_unit_test` | [inst/async_fifo_path_unit_test.py](../../../src/tests/pypeline_tests/inst/async_fifo_path_unit_test.py) | Python assertions / wrapper | U (not measured) | Unit checks of how the sweep and the back end treat an async global FIFO: a parsed two-clock FIFO design (PY_TO_LOGIC.PARSE_FILE, no synthesis) and fake timing path reports. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | measure first |
| `auto_fsm_attribution_test` | [inst/auto_fsm_attribution_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py) | Python assertions / wrapper | M 3.1 s / PASS | Ordered timing arcs, register writers, late selection and local scheduling. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `auto_fsm_cache_test` | [inst/auto_fsm_cache_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py) | Python assertions / wrapper | M 206.5 s / PASS | Carried schedule validity, pinned recipe integrity, model-only updates and call sites new to a build (AUTO_FSM.REPARSE). | Keep cache invalidation, deterministic generation and new-call-site cases; separate slow real parses from cheap synthetic fixtures. | feature/slow |
| `auto_fsm_prefix_tree_test` | [inst/auto_fsm_prefix_tree_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_prefix_tree_test.py) | Python assertions / wrapper | M 273.1 s / PASS | Measured helper delays prevent unnecessary descent; scheduled FSMs render array inputs correctly and supply clock enable to an otherwise stateless MAIN. | Keep: measurement-before-descent and clock-enable emission are unique; move real-parse cases out of the fast tier. | feature/slow |
| `auto_fsm_transforms_test` | [inst/auto_fsm_transforms_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py) | Python assertions / wrapper | M 9.0 s / PASS | Proof/refusal cases for balanced selectors, width adapters and closed fusion. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `auto_fsm_unit_test` | [inst/auto_fsm_unit_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py) | Python assertions / wrapper | M 1648.3 s / PASS | Real scheduler/codegen invariants: binding, state dependencies, register lifetimes, budgets, determinism, serialization, constant cleanup and pipelined units. | Split slow scheduling/reparse cases from small invariants; retain both. Historical 1,648.3 s makes the current fast-unit description misleading. | deep/nightly |
| `auto_multi_cycle_unit_test` | [inst/auto_multi_cycle_unit_test.py](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py) | Python assertions / wrapper | M 57.0 s / PASS | AUTO_MULTI_CYCLE unit tests -- no synthesis tool involved: - AUTO_MULTI_CYCLE constructor validation and .latency resolution (default/start/ fixed/cache), construction-site keys, the inline-construction guard, design-read tracking (served / unread); - the naming identity (pypeline._name_identity) follows the resolved cycle count; - SYN: MCP_EFFECTIVE_NCYCLES, ELABORATED/HARVEST_AUTO_MULTI_CYCLE_NCYCLES, the MultiMainTimingParams hash (unchanged unless a count was overridden); - SWEEP: timing-report register… | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | feature/slow |
| `auto_pipeline_harvest_test` | [inst/auto_pipeline_harvest_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py) | Python assertions / wrapper | M 1.0 s / PASS | Harvest/replay concrete region placements across re-parses, identity, named groups, seeded latency and divergence handling. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `auto_pipeline_ram_test` | [inst/auto_pipeline_ram_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_ram_test.py) | Python assertions / wrapper | M 41.7 s / PASS | Contract tests for RAM plans, native memory state, and stream credits. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | feature/slow |
| `auto_pipeline_region_planning_test` | [inst/auto_pipeline_region_planning_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_planning_test.py) | Python assertions / wrapper | M 1.1 s / PASS | Unit coverage for the constrained-AUTO_PIPELINE region planner in SWEEP.py (AUTO_PIPELINE(func, latency= / start_latency= / max_latency=)): | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `bottom_up_report_test` | [inst/bottom_up_report_test.py](../../../src/tests/pypeline_tests/inst/bottom_up_report_test.py) | Python assertions / wrapper | M 10.7 s / PASS | In-process unit tests for the bottom-up value report (the pin-and-confirm pass table and sweep_history.json "latency_passes"): - an AUTO_PIPELINE .latency read records the design line that read it; a read inside a library factory (make_stream_auto_pipeline sizing its FIFO) records the library line and the design line that called the factory; - AUTO_MULTI_CYCLE .latency and .ncycles reads record their sites too, and a read inside a hardware body (folded by the elaborator) records the body's own file and line;… | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `clock_api_unit_test` | [inst/clock_api_unit_test.py](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py) | Python assertions / wrapper | U (not measured) | Clock identity, hashing, generated pin names, MAIN declaration forms, conflicts, wire markers and async FIFO constructor validation. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | measure first |
| `design_params_test` | [inst/design_params_test.py](../../../src/tests/pypeline_tests/inst/design_params_test.py) | Python assertions / wrapper | M 2.9 s / PASS | In-process unit tests for design parameters (pypeline.param, -D NAME=VALUE): - precedence: -D, then the env= variable (only when set and non-empty), then the default; - conversion by type (bool spellings, int incl. 0x, float, str, tuple/list from comma lists, literal-or-string without a type) and the errors, which name the parameter, where the value came from and the declaration site; - choices, duplicate declarations, a bare -D NAME, invalid names; - one resolution per process (a later environment change is… | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `device_models_sta_test` | [inst/device_models_sta_test.py](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py) | Python assertions / wrapper | M 1.3 s / PASS | Pure unit coverage for sky130 recipe identity and STA diagnostics. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `divider_qor_bench_unit_test` | [inst/divider_qor_bench_unit_test.py](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py) | Python assertions / wrapper | M 0.9 s / PASS | Fast parser/schema tests for the opt-in Divider QoR harness. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `doc_links_test` | [inst/doc_links_test.py](../../../src/tests/pypeline_tests/inst/doc_links_test.py) | Python assertions / wrapper | M 2.1 s / PASS | Meta-test: every markdown link in the repo resolves. | Keep as repository/documentation validation, selected by docs/layout changes rather than an HDL unit lane. | repo/meta |
| `factory_api_test` | [inst/factory_api_test.py](../../../src/tests/pypeline_tests/inst/factory_api_test.py) | Python assertions / wrapper | M 6.9 s / PASS | Single-callable factory metadata, return/port types, operation bundles and cache identity survive decorators, native wrappers and hardware use. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `factory_closure_naming_test` | [inst/factory_closure_naming_test.py](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py) | Python assertions / wrapper | M 5.0 s / PASS | Readable deterministic factory names preserve closure identity, types, annotations, recursion safety and user names. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `factory_main_api_unit_test` | [inst/factory_main_api_unit_test.py](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py) | Python assertions / wrapper | M 1.7 s / PASS | In-process checks of @MAIN registration, the API that lets code make @MAINs (factories, loops, generated functions): | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `floor_and_bits_cap_unit_test` | [inst/floor_and_bits_cap_unit_test.py](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py) | Python assertions / wrapper | M 0.5 s / PASS | Floor-stop evidence, restored winner verdicts, useful bit-cut caps and coherent placement-group removal. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `generated_naming_test` | [inst/generated_naming_test.py](../../../src/tests/pypeline_tests/inst/generated_naming_test.py) | Python assertions / wrapper | M 2.7 s / PASS | Identity and readability contracts, including interfaces and overflow. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `generated_vhdl_stability_test` | [inst/generated_vhdl_stability_test.py](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py) | Python assertions / wrapper | M 0.8 s / PASS | Generated VHDL doesn't change between parse passes of one run. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `global_fifo_api_unit_test` | [inst/global_fifo_api_unit_test.py](../../../src/tests/pypeline_tests/inst/global_fifo_api_unit_test.py) | Python assertions / wrapper | M 0.6 s / PASS | Unit checks of pypeline.py's global FIFO API, with no design build: Fifo[T] and its wire type, the global_fifo(n) / global_sync_fifo(n) initializers and the depth they build, the stream-module port helper that native sim and the compiler share, and the FIFO MAIN generator's names. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `global_fifo_path_unit_test` | [inst/global_fifo_path_unit_test.py](../../../src/tests/pypeline_tests/inst/global_fifo_path_unit_test.py) | Python assertions / wrapper | M 2.7 s / PASS | Unit checks of how the sweep treats a global FIFO's MAIN: a parsed FIFO design (PY_TO_LOGIC.PARSE_FILE, no synthesis) and fake timing path reports. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `global_inst_api_unit_test` | [inst/global_inst_api_unit_test.py](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py) | Python assertions / wrapper | M 0.8 s / PASS | Unit checks of pypeline.py's global instance API, with no design build: Inst[f], the ports it derives from f (_global_inst_ports) and the wire type they make, the errors for hardware that cannot be an instance, the MAIN generator's source, the MAIN name native sim gives an instance, and MAIN() checking a user's name= where an instance's own MAIN name is not checked. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `global_inst_path_unit_test` | [inst/global_inst_path_unit_test.py](../../../src/tests/pypeline_tests/inst/global_inst_path_unit_test.py) | Python assertions / wrapper | M 2.9 s / PASS | Unit checks of how the sweep treats a global instance's MAIN: a parsed design (PY_TO_LOGIC.PARSE_FILE, no synthesis) with a stateful instance and an AUTO_PIPELINE instance, and fake timing path reports. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `isolated_top_name_test` | [inst/isolated_top_name_test.py](../../../src/tests/pypeline_tests/inst/isolated_top_name_test.py) | Python assertions / wrapper | M 3.0 s / PASS | Isolated wrapper selection, filename and emitted declaration agree. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `latency_memory_unit_test` | [inst/latency_memory_unit_test.py](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py) | Python assertions / wrapper | M 46.7 s / PASS | Independent latency pieces: identity, goal selection, recording, JSON and prune. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | feature/slow |
| `leaf_split_unit_test` | [inst/leaf_split_unit_test.py](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py) | Python assertions / wrapper | M 0.8 s / PASS | Leaf split kinds/caps, balanced and exact bit chunks, aggregate MUX reconstruction and physical split invariants. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `long_file_list_arg_len_test` | [inst/long_file_list_arg_len_test.py](../../../src/tests/pypeline_tests/inst/long_file_list_arg_len_test.py) | Python assertions / wrapper | M 5.9 s / PASS | Regression coverage for the "Argument list too long" bug: `./build.py --shared --sim --syn_tb` (wireguard-fpga) failed before GHDL even started, deep inside make/execvp, once a design's VHDL file list crossed ~128 KiB. | Keep the real GHDL/make integration; label required tools so a unit-only environment does not unexpectedly need them. | fast candidate |
| `mux_fanout_planning_test` | [inst/mux_fanout_planning_test.py](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py) | Python assertions / wrapper | M 8.5 s / PASS | Drop cuts that do not deepen the real schedule, retain effective/locked-region cuts and reduce selected MUX bank fanout without weakening hard floors. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `native_pipeline_region_test` | [inst/native_pipeline_region_test.py](../../../src/tests/pypeline_tests/inst/native_pipeline_region_test.py) | Python assertions / wrapper | M 0.4 s / PASS | Native sim's pipelined-region model of global wires (pypeline._sim_regions, docs/pypeline_sim_DESIGN.md "Pipelined native sim"), unit-tested without a build. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `openxc7_unit_test` | [inst/openxc7_unit_test.py](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py) | Python assertions / wrapper | M 0.9 s / PASS | Pure unit coverage for PipelineC's open-source Xilinx 7-series flow. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `path_attribution_test` | [inst/path_attribution_test.py](../../../src/tests/pypeline_tests/inst/path_attribution_test.py) | Python assertions / wrapper | M 1.6 s / PASS | Critical path evidence selects the deepest relevant pipelinable helper, with endpoint and fallback cases. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `path_portability_test` | [inst/path_portability_test.py](../../../src/tests/pypeline_tests/inst/path_portability_test.py) | Python assertions / wrapper | M 1.4 s / PASS | Every repo path must check out on Windows. | Keep as repository validation; its tracked-plus-untracked file scan intentionally depends on worktree contents. | repo/meta |
| `pipeline_map_scheduler_scalability_test` | [inst/pipeline_map_scheduler_scalability_test.py](../../../src/tests/pypeline_tests/inst/pipeline_map_scheduler_scalability_test.py) | Python assertions / wrapper | M 5.2 s / PASS | Complexity and failure-mode regression for GET_PIPELINE_MAP scheduling. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `plan_cuts_boundary_snap_test` | [inst/plan_cuts_boundary_snap_test.py](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py) | Python assertions / wrapper | M 183.0 s / PASS | Cut placement respects serial-step boundaries, physical budgets and minimal useful cut counts under stress. | Keep boundary geometry/stress invariants; separate large stress loops from a small deterministic fast set. | feature/slow |
| `registration_audit_test` | [inst/registration_audit_test.py](../../../src/tests/pypeline_tests/inst/registration_audit_test.py) | Python assertions / wrapper | M 0.6 s / PASS | Meta-test: every `*_test.py` file in inst/ must be registered as a Test in at least one category module (native_sim_tests.py, native_vs_vhdl_sim_tests.py, elab_tests.py, elab_introspect_tests.py, unit_tests.py, synth_tests.py, build_report_tests.py, known_issues_tests.py, multi_clock_tests.py). A `*_test.py` file registered nowhere is dead: nothing runs it, and it silently rots. | Strengthen: current quoted-filename scan can count comments; inspect actual Test objects, exact paths, unique IDs and runnable case entrypoints. | repo/meta |
| `sim_elab_operator_parity_test` | [inst/sim_elab_operator_parity_test.py](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py) | Python assertions / wrapper | M 2.4 s / PASS | Parity between native simulation and hardware elaboration for operators. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `src_module_import_test` | [inst/src_module_import_test.py](../../../src/tests/pypeline_tests/inst/src_module_import_test.py) | Python assertions / wrapper | M 31.8 s / PASS | Import-structure checks for the compiler modules in src/. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | feature/slow |
| `stream_auto_pipeline_latency_args_test` | [inst/stream_auto_pipeline_latency_args_test.py](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py) | Python assertions / wrapper | M 6.7 s / PASS | In-process unit tests for make_stream_auto_pipeline(func, *, latency=, start_latency=, max_latency=) and the DSP factories that forward the same keyword-only arguments to their single core AUTO_PIPELINE: - the arguments reach the eagerly constructed core AUTO_PIPELINE (which also sizes the FIFO), and bad combinations raise its errors; - .latency served per build mode: a sweep build's bootstrap reads start_latency, --comb-like builds read 0, latency=N reads N everywhere; - a pinned latency in the cache flows… | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `sweep_cross_main_test` | [inst/sweep_cross_main_test.py](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py) | Python assertions / wrapper | M 1.1 s / PASS | Cross-MAIN timing paths, per-MAIN attribution scope, best-result ties and the mini-sweep ladder inside start_latency= regions (in-process, no tool). | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `sweep_evidence_test` | [inst/sweep_evidence_test.py](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py) | Python assertions / wrapper | M 16.9 s / PASS | Sweep implementation identity, concrete replay and backend evidence contracts. | Keep both hash seeds: deliberate determinism coverage through real control flow and scripted timing. | fast candidate |
| `sweep_evidence_test_seed777` | [inst/sweep_evidence_test.py](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py) | Python assertions / wrapper | M 14.3 s / PASS | Sweep implementation identity, concrete replay and backend evidence contracts. | Keep: second pinned hash seed exposes order dependence; this is deliberate coverage, not a duplicate. | fast candidate |
| `sweep_history_record_unit_test` | [inst/sweep_history_record_unit_test.py](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py) | Python assertions / wrapper | M 0.7 s / PASS | Final history selects evidence for the retained implementation and preserves clock, fit, confirmation and failure provenance. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `sweep_plateau_unit_test` | [inst/sweep_plateau_unit_test.py](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py) | Python assertions / wrapper | M 0.6 s / PASS | Flat measured timing while cuts grow triggers a bounded plateau stop, with negative controls. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `sweep_refinement_recovery_test` | [inst/sweep_refinement_recovery_test.py](../../../src/tests/pypeline_tests/inst/sweep_refinement_recovery_test.py) | Python assertions / wrapper | M 0.8 s / PASS | Sweep recovery, fresh locks, opaque refinement and flattened STA attribution. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `synthesis_scope_test` | [inst/synthesis_scope_test.py](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py) | Python assertions / wrapper | M 64.1 s / PASS | Cold synthesis scheduling over an elaborated design; no vendor tools run. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | feature/slow |
| `typed_pipeline_placement_test` | [inst/typed_pipeline_placement_test.py](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py) | Python assertions / wrapper | M 0.6 s / PASS | Pure unit coverage for typed auto-pipeline placement and lowering. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `vhdl_submodule_port_map_test` | [inst/vhdl_submodule_port_map_test.py](../../../src/tests/pypeline_tests/inst/vhdl_submodule_port_map_test.py) | Python assertions / wrapper | M 3.7 s / PASS | Every submodule instance gets its own port map, with every port, in order. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |
| `vivado_version_unit_test` | [inst/vivado_version_unit_test.py](../../../src/tests/pypeline_tests/inst/vivado_version_unit_test.py) | Python assertions / wrapper | M 0.6 s / PASS | `vivado -version` parsing (VIVADO.PARSE_VIVADO_VERSION). No Vivado run. | Keep compiler-contract checks; select by feature and measured cost, since this category alone does not guarantee a cheap run. | fast candidate |

## multi_clock

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `multi_clock_ghdl_test` | [inst/multi_clock_ghdl_test.py](../../../src/tests/pypeline_tests/inst/multi_clock_ghdl_test.py) | Python assertions / wrapper | D ≈20 s | Build multi_clock_design.py (two clocks, an async global FIFO, a sync global FIFO and an async wire) with --comb --no_synth, then check the generated design in GHDL: no synthesis tool runs. | Keep hardware-only asynchronous-clock oracle. Extend clock ratios/phases, FIFO wrap/full/empty and stalls without requiring unsupported native multi-clock sim. | feature/tool |
| `multi_clock_open_tools_test` | [inst/multi_clock_open_tools_test.py](../../../src/tests/pypeline_tests/inst/multi_clock_open_tools_test.py) | Python assertions / wrapper; open_tools category | D 50–120 s | Build multi-clock designs with open_tools (ECP5 nextpnr) and check what the timing reports and the sweep do with more than one clock. | Keep ECP5 clock attribution, pin naming, selective cuts and FIFO-only timing failure; place in a tool-specific integration lane. | feature/tool |
| `multi_clock_vivado_test` | [inst/multi_clock_vivado_test.py](../../../src/tests/pypeline_tests/inst/multi_clock_vivado_test.py) | Python assertions / wrapper; vivado category | D ≈150 s | Build multi_clock_synth_design.py with Vivado (the Arty's xc7a35ti) and check the async FIFO hardware and the clock constraints. | Keep XPM and builtin FIFO plus asynchronous clock-group checks; backend behavior differs from ECP5 and needs its own lane. | feature/tool |

## synth_device_models

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `array_compare_bracket_name_test` | [inst/array_compare_bracket_name_test.py](../../../src/tests/pypeline_tests/inst/array_compare_bracket_name_test.py) | comb synthesis; device_models | M 11.9 s / PASS | Regression test for array-typed == / != producing an illegal VHDL entity name. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `axis_byte_stream_test` | [inst/axis_byte_stream_test.py](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py) | comb synthesis; device_models | M 167.2 s / PASS | AXIS byte source/sink round trips, partial final beats, keep-mask validation, pauses and scoreboard behavior. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `axis_max_len_limiter_test` | [inst/axis_max_len_limiter_test.py](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py) | comb synthesis; device_models | M 29.6 s / PASS | AXIS frame limiting discards padding without desynchronizing later structs; covers the four historical limiter regressions. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `axis_test` | [inst/axis_test.py](../../../src/tests/pypeline_tests/inst/axis_test.py) | comb synthesis; device_models | M 14.7 s / PASS | AXIS keep/count conversions, passthrough interfaces and video-fragment end-of-data wiring. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `bit_math_test` | [inst/bit_math_test.py](../../../src/tests/pypeline_tests/inst/bit_math_test.py) | comb synthesis; device_models | M 21.7 s / PASS | Typed local and inferred assignments truncate at hardware widths, including nested calls, register wrap and render-coordinate arithmetic. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `char_array_test` | [inst/char_array_test.py](../../../src/tests/pypeline_tests/inst/char_array_test.py) | comb synthesis; device_models | M 16.4 s / PASS | Character literals, strings, nested arrays/structs, length and char-versus-byte type identity. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `dc_block_test` | [inst/dc_block_test.py](../../../src/tests/pypeline_tests/inst/dc_block_test.py) | comb synthesis; device_models | M 51.6 s / PASS | dsp/dc_block.py make_dc_block tests: random stimulus vs the exact integer golden model (dsp/dsp_tb.golden_dc_block), full precision vs resized/ saturated output, valid_only mode, consumer backpressure stalls, and input valid gaps. Plain `python3 dc_block_test.py` runs the sim_call tests; the @MAIN entry points below also give `pypelinec dc_block_test.py --comb` elaboration coverage of every mode. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `dwidth_converter_test` | [inst/dwidth_converter_test.py](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py) | comb synthesis; device_models | M 30.2 s / PASS | Width split/assembly and narrow/wide AXIS conversion preserve full/partial beats and packet boundaries. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `enum_test` | [inst/enum_test.py](../../../src/tests/pypeline_tests/inst/enum_test.py) | comb synthesis; device_models | M 13.8 s / PASS | Static, factory, plain-class and automatic enums work in ports, state and nested records. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `example_counter` | [examples/pypeline/counter.py](../../../examples/pypeline/counter.py) | comb synthesis; device_models | M 9.2 s / PASS | Compile/synthesize the documented counter example. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `example_fsm` | [examples/pypeline/fsm.py](../../../examples/pypeline/fsm.py) | comb synthesis; device_models | M 9.8 s / PASS | Compile/synthesize the documented FSM example. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `example_pipeline` | [examples/pypeline/pipeline.py](../../../examples/pypeline/pipeline.py) | comb synthesis; device_models | M 23.4 s / PASS | Compile/synthesize the documented typed floating-point pipeline example. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `example_stream_pipeline` | [examples/pypeline/stream_pipeline.py](../../../examples/pypeline/stream_pipeline.py) | comb synthesis; device_models | M 23.0 s / PASS | Compile/synthesize the documented stream wrapper and global-wire composition. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `fifo_test` | [inst/fifo_test.py](../../../src/tests/pypeline_tests/inst/fifo_test.py) | comb synthesis; device_models | M 16.0 s / PASS | FWFT FIFO empty/full behavior, rounded capacity, simultaneous push/pop, ordering and reference-model soak. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `fir_decim_test` | [inst/fir_decim_test.py](../../../src/tests/pypeline_tests/inst/fir_decim_test.py) | comb synthesis; device_models | M 51.1 s / PASS | dsp/fir_decim.py make_fir_decim tests: golden = every decim-th convolution output; phase alignment across consumer stalls and input valid gaps; valid_only mode; decim=1 equivalence with make_fir. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `fir_interp_test` | [inst/fir_interp_test.py](../../../src/tests/pypeline_tests/inst/fir_interp_test.py) | comb synthesis; device_models | M 50.2 s / PASS | dsp/fir_interp.py tests: make_zero_stuffer beat sequence/backpressure and make_fir_interp vs golden (zero-stuff + convolve), output ordering, the rate law (outputs = interp x accepted inputs), and stall recovery. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `fir_sweep_test` | [inst/fir_sweep_test.py](../../../src/tests/pypeline_tests/inst/fir_sweep_test.py) | synthesis/sweep; device_models | M 63.6 s / PASS | Full auto-pipelining throughput-sweep coverage for one dsp/fir.py filter: proves the FIR comb blob (pre-adders + const multiplies + adder tree + resize) actually retimes to meet a @MAIN frequency goal, rather than only elaborating under --comb. Kept to a single small filter so the sweep stays fast; broad per-mode elaboration coverage lives in fir_test.py (--comb). | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `fir_test` | [inst/fir_test.py](../../../src/tests/pypeline_tests/inst/fir_test.py) | comb synthesis; device_models | M 84.5 s / PASS | dsp/fir.py make_fir tests: impulse/step/random stimulus vs the exact integer golden model (dsp/fir_tb.golden_fir), symmetry-folded vs unfolded bit-identity, half-band zero-tap skipping, antisymmetric folding, full precision mode, valid_only mode, consumer backpressure stalls, and input valid gaps. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `fixed_point_test` | [inst/fixed_point_test.py](../../../src/tests/pypeline_tests/inst/fixed_point_test.py) | comb synthesis; device_models | M 46.0 s / PASS | Fixed-point arithmetic versus Fraction, signedness, rounding ties, wrap/saturation and coefficient quantization. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `float32_add_test` | [inst/float32_add_test.py](../../../src/tests/pypeline_tests/inst/float32_add_test.py) | comb synthesis; device_models | M 46.5 s / PASS | Float32 addition values plus HDL shapes for negation, absolute value, shifts, leading-zero count and constants. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `float_ops_div_test` | [inst/float_ops_div_test.py](../../../src/tests/pypeline_tests/inst/float_ops_div_test.py) | comb synthesis; device_models | M 1068.1 s / PASS | Generated float32 divider elaborates and synthesizes; this registration has no independent arithmetic simulation oracle. | Move large float32 synthesis to deep arithmetic; add a smaller bounded HDL numeric oracle before reducing routine coverage. | deep/nightly |
| `float_ops_test` | [inst/float_ops_test.py](../../../src/tests/pypeline_tests/inst/float_ops_test.py) | comb synthesis; device_models | M 60.1 s / PASS | Registered floating arithmetic/conversion and negate behavior, including unsupported operators and primitive width boundaries. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `global_wire_nested_split_test` | [inst/global_wire_nested_split_test.py](../../../src/tests/pypeline_tests/inst/global_wire_nested_split_test.py) | comb synthesis; device_models | M 17.4 s / PASS | Three writers own criss-crossed nested struct leaves; whole-subtree writes and readback preserve ownership. | Keep native and synthesis coverage; add/recheck the missing GHDL nested-writer case, tracking a narrow failure if it still reproduces. | feature/tool |
| `if_test` | [inst/if_test.py](../../../src/tests/pypeline_tests/inst/if_test.py) | comb synthesis; device_models | M 45.4 s / PASS | Conditional dynamic array/struct reads and writes, default branch values, and nonzero integer conditions. | Share fixtures with var_ref_test, preserving both conditional and unconditional shapes. Native run currently tests integer conditions only. | feature/tool |
| `interface_array_port_test` | [inst/interface_array_port_test.py](../../../src/tests/pypeline_tests/inst/interface_array_port_test.py) | comb synthesis; device_models | M 14.5 s / PASS | Array-valued interface ports support independently backpressured broadcast lanes. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `interface_boundary_test` | [inst/interface_boundary_test.py](../../../src/tests/pypeline_tests/inst/interface_boundary_test.py) | comb synthesis; device_models | M 17.6 s / PASS | Generated reverse wiring composes with manually written FSM/interface-port modules in both directions. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `interface_factory_two_widths_test` | [inst/interface_factory_two_widths_test.py](../../../src/tests/pypeline_tests/inst/interface_factory_two_widths_test.py) | comb synthesis; device_models | M 18.6 s / PASS | Two widths of interface-taking broadcast and skid-buffer factories. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `interface_func_loop_test` | [inst/interface_func_loop_test.py](../../../src/tests/pypeline_tests/inst/interface_func_loop_test.py) | comb synthesis; device_models | M 9.8 s / PASS | Feedforward loops and multi-output callees generate feedback edges correctly across FSM/datapath call ordering. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `interface_func_test` | [inst/interface_func_test.py](../../../src/tests/pypeline_tests/inst/interface_func_test.py) | comb synthesis; device_models | M 15.7 s / PASS | Generated interface wiring matches a hand-written chain across bundles, multi-field reverse channels and invalid forms. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `interface_mixing_rules_test` | [inst/interface_mixing_rules_test.py](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py) | comb synthesis; device_models | M 12.9 s / PASS | Handwritten/generated interface composition rejects unpaired port halves and illegal statement access; separate factory instances retain distinct identities. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `interface_test` | [inst/interface_test.py](../../../src/tests/pypeline_tests/inst/interface_test.py) | comb synthesis; device_models | M 12.3 s / PASS | Derived forward/reverse interface types preserve nesting, arrays, multi-bit credit feedback, memoized identity and legal declaration rules. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `log2_db_test` | [inst/log2_db_test.py](../../../src/tests/pypeline_tests/inst/log2_db_test.py) | comb synthesis; device_models | M 181.8 s / PASS | ROM and piecewise-linear dB conversion match exact golden and math.log10 oracles, including nonpositive floors, binary points, monotonicity and independent ROM latencies. Variant: LOG2_DB_AUTO_RAM=0. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `magnitude_test` | [inst/magnitude_test.py](../../../src/tests/pypeline_tests/inst/magnitude_test.py) | comb synthesis; device_models | M 117.1 s / PASS | dsp/magnitude.py make_magnitude tests: random I/Q stimulus vs the exact integer golden model (dsp/dsp_tb.golden_magnitude), full precision vs resized/saturated output, valid_only mode, consumer backpressure stalls, and input valid gaps. Plain `python3 magnitude_test.py` runs the sim_call tests; the @MAIN entry points below also give `pypelinec magnitude_test.py --comb` elaboration coverage of every mode. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `moving_avg_test` | [inst/moving_avg_test.py](../../../src/tests/pypeline_tests/inst/moving_avg_test.py) | comb synthesis; device_models | M 54.4 s / PASS | dsp/moving_avg.py make_moving_avg tests: random stimulus vs the exact integer golden model (dsp/dsp_tb.golden_moving_avg), normalized vs raw-sum (non-power-of-two) modes, full precision vs resized/saturated output, valid_only mode, consumer backpressure stalls, and input valid gaps. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `native_pipelined_sim_test` | [inst/self_check_stream_auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_pipeline_test.py) | sweep + native; device_models | M 88.4 s / PASS | Build-discovered stream latency and FIFO sizing preserve throughput in pipelined native simulation. | Keep until an HDL compare covers discovered FIFO sizing; investigate the documented zero-probe VHDL failure rather than treating fixed-latency coverage as equivalent. | feature/tool |
| `old_sw_lib_ops` | [inst/old_sw_lib_ops.py](../../../src/tests/pypeline_tests/inst/old_sw_lib_ops.py) | comb synthesis; device_models | M 22.7 s / PASS | Mixed-width unsigned greater-than-or-equal operator still lowers through the compiler's operator path. | Merge candidate into the operator lowering fixture; retain this uint32-versus-uint16 comparison as a named case. | feature/tool |
| `pypeline_test` | [inst/pypeline_test.py](../../../src/tests/pypeline_tests/inst/pypeline_test.py) | comb synthesis; device_models | M 91.3 s / PASS | Broad language smoke shapes: registers/instances, feedback, clock enable, aggregates, loops, calls and typed arithmetic. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `qor_divider_auto_fsm_test` | [qor/divider/auto_fsm.py](../../../src/tests/pypeline_tests/qor/divider/auto_fsm.py) | synthesis/sweep; device_models | M 317.8 s / PASS | Resource-shared 32-step restoring divider builds with a real valid/ready interface and a feasible FSM clock goal. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `qor_multiplier_auto_fsm_test` | [qor/multiplier/auto_fsm.py](../../../src/tests/pypeline_tests/qor/multiplier/auto_fsm.py) | synthesis/sweep; device_models | M 89.5 s / PASS | Resource-shared multiplier and descended soft-operator array reconstruction build with the chosen min-area schedule. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `qor_sqrt_auto_fsm_test` | [qor/sqrt/auto_fsm.py](../../../src/tests/pypeline_tests/qor/sqrt/auto_fsm.py) | synthesis/sweep; device_models | M 474.2 s / PASS | Resource-shared iterative square-root logic builds with handshake and an achievable FSM clock goal. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `ram_test` | [inst/ram_test.py](../../../src/tests/pypeline_tests/inst/ram_test.py) | comb synthesis; device_models | M 27.5 s / PASS | RAM read-first timing, write gating/collisions, byte enables, init/reset, instance isolation and independent reference soaks; matching MAINs exercise generated RAM HDL. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `reg_init_test` | [inst/reg_init_test.py](../../../src/tests/pypeline_tests/inst/reg_init_test.py) | comb synthesis; device_models | M 16.2 s / PASS | Scalar/signed/array/struct register initialization, field writes and reset restore the declared values. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `self_check_factory_main_test` | [inst/self_check_factory_main_test.py](../../../src/tests/pypeline_tests/inst/self_check_factory_main_test.py) | comb synthesis; device_models | M 18.0 s / PASS | @MAINs made by factories, native against VHDL: three counter lanes made in a loop, each driving its own element of one wire; two stateless lanes made by one factory, each pushing its own word through its own instance of one make_stream_fifo FIFO; and a factory closure (not a MAIN) that drives a wire from a MAIN. | Keep factory lane/state parity; the companion sky130 build is a separate synthesis gate, not an exact duplicate. | feature/tool |
| `self_check_global_fifo_test` | [inst/self_check_global_fifo_test.py](../../../src/tests/pypeline_tests/inst/self_check_global_fifo_test.py) | comb synthesis; device_models | M 17.7 s / PASS | Self-checking @MAIN test of a global FIFO, Fifo[T] of a struct: a producer offers numbered words on 3 cycles out of 4, a consumer takes them on 1 cycle out of 4, so the FIFO fills and pushes back. The consumer checks order with sim_assert and calls sim_finish() after the last word. | Keep behavioral parity; run the additional sky130 synthesis only in the synthesis lane unless its synthesis-specific value is deliberately retired. | feature/tool |
| `self_check_global_inst_test` | [inst/self_check_global_inst_test.py](../../../src/tests/pypeline_tests/inst/self_check_global_inst_test.py) | comb synthesis; device_models | M 32.4 s / PASS | Self-checking @MAIN test of global instances, Inst[f]: a combinational instance whose inputs come from two MAINs, two instances of one stateful counter, a skid buffer instance between a producer and a consumer with backpressure, an AUTO_PIPELINE(f, latency=2) instance, and a make_ram instance (a pipeline_latency function, which native sim models without aligning anything around it: an instance's MAIN takes no added latency). | Keep behavioral parity; the companion sky130 build additionally tests synthesizability, not merely HDL legality. | feature/tool |
| `self_check_stream_auto_comb_area_opt_test` | [inst/self_check_stream_auto_comb_area_opt_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_comb_area_opt_test.py) | synthesis/sweep; device_models | M 29.9 s / PASS | AREA_OPT registered stream preserves two-cycle latency, II=1 and stable output under stalls. | Keep stream stalls/II and synthesis mode: its synth registration is non-comb, unlike the comb HDL comparison. | feature/tool |
| `self_check_stream_auto_comb_delay_opt_test` | [inst/self_check_stream_auto_comb_delay_opt_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_comb_delay_opt_test.py) | synthesis/sweep; device_models | M 24.2 s / PASS | DELAY_OPT registered stream preserves two-cycle latency, II=1 and stable output under stalls. | Keep stream stalls/II and synthesis mode: its synth registration is non-comb, unlike the comb HDL comparison. | feature/tool |
| `self_check_stream_auto_fsm_test` | [inst/self_check_stream_auto_fsm_test.py](../../../src/tests/pypeline_tests/inst/self_check_stream_auto_fsm_test.py) | synthesis/sweep; device_models | M 409.0 s / PASS | AUTO_FSM stream data order and output backpressure, with passthrough or a real shared schedule. | Strong removal candidate: scheduled native/GHDL comparison already builds this design with device_models. Preserve explicit long-filename/tool evidence in that job first (409 s baseline). | feature/tool |
| `serdes_test` | [inst/serdes_test.py](../../../src/tests/pypeline_tests/inst/serdes_test.py) | comb synthesis; device_models | M 214.6 s / PASS | Base-layer element-stream serializer/deserializer (stream/serializer.py, stream/deserializer.py). | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `sim_assert_finish_test` | [inst/sim_assert_finish_test.py](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py) | comb synthesis; device_models | M 18.3 s / PASS | sim_assert success/failure messages, sim_finish termination and legal bare-call elaboration. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `sim_print_test` | [inst/sim_print_test.py](../../../src/tests/pypeline_tests/inst/sim_print_test.py) | comb synthesis; device_models | M 18.4 s / PASS | Simulation printing frequency/arguments and hardware string-versus-character restrictions. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `skid_buffer_test` | [inst/skid_buffer_test.py](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py) | comb synthesis; device_models | M 17.6 s / PASS | All four buffer modes preserve data under stalls, advertise correct capacity/latency and cut the intended handshake paths. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `stream_fifo_test` | [inst/stream_fifo_test.py](../../../src/tests/pypeline_tests/inst/stream_fifo_test.py) | comb synthesis; device_models | M 17.3 s / PASS | Ready/valid FIFO ordering and backpressure through the stream wrapper. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `stream_perf_probe_test` | [inst/stream_perf_probe_test.py](../../../src/tests/pypeline_tests/inst/stream_perf_probe_test.py) | comb synthesis; device_models | M 16.0 s / PASS | stream/stream_perf_probe.py end to end, under the real native simulator (`pypelinec stream_perf_probe_test.py --sim --comb --run 200`) and through VHDL elaboration (`--comb` synth entry): the probes must vanish from the hardware and, in sim, report the right numbers. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `stream_perf_tb_test` | [inst/stream_perf_tb_test.py](../../../src/tests/pypeline_tests/inst/stream_perf_tb_test.py) | comb synthesis; device_models | M 17.0 s / PASS | A complete stream performance testbench under the real native simulator (`pypelinec stream_perf_tb_test.py --sim --comb --run all`) -- the shape pypeline_stream_perf_guide.md documents: | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `stream_ram_test` | [inst/stream_ram_test.py](../../../src/tests/pypeline_tests/inst/stream_ram_test.py) | comb synthesis; device_models | M 17.8 s / PASS | make_stream_ram (include/pypeline/stream/stream_ram.py): handshake checks plus synthesis tops. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `sweep_comb_test` | [inst/sweep_comb_test.py](../../../src/tests/pypeline_tests/inst/sweep_comb_test.py) | synthesis/sweep; device_models | M 169.4 s / PASS | Throughput sweep pipelines a pure combinational MAIN to its requested frequency. | Keep a real pure-MAIN sweep; update PyRTL comments to device_models. Its standalone test_sweep_comb_sim is not run by this registration. | feature/tool |
| `sweep_float32_device_models` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; device_models | M 64.8 s / PASS | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=60.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |
| `sweep_fsm_auto_pipeline_test` | [inst/sweep_fsm_auto_pipeline_test.py](../../../src/tests/pypeline_tests/inst/sweep_fsm_auto_pipeline_test.py) | synthesis/sweep; device_models | M 142.5 s / PASS | A sweep cuts a tagged child inside a stateful MAIN without adding latency to the FSM itself. | Keep tagged-stateful boundary sweep; standalone native helper is unregistered, so do not count its assertions as suite coverage. | feature/tool |
| `sweep_stateful_boundary_test` | [inst/sweep_stateful_boundary_test.py](../../../src/tests/pypeline_tests/inst/sweep_stateful_boundary_test.py) | synthesis/sweep; device_models | M 134.0 s / PASS | Pipeline cuts stop at untagged stateful child boundaries instead of disappearing inside them. | Keep untagged-stateful boundary sweep; standalone native helper is unregistered, so do not count its assertions as suite coverage. | feature/tool |
| `sweep_two_mains_test` | [inst/sweep_two_mains_test.py](../../../src/tests/pypeline_tests/inst/sweep_two_mains_test.py) | synthesis/sweep; device_models | M 224.0 s / PASS | Two MAINs receive independent sweep plans and timing-goal handling. | Keep multi-MAIN planning; update obsolete PyRTL no-attribution comments and explicitly assert the intended fallback. Standalone sim helper is not run. | feature/tool |
| `type_axis_synth_test` | [inst/type_axis_synth_test.py](../../../src/tests/pypeline_tests/inst/type_axis_synth_test.py) | comb synthesis; device_models | M 178.2 s / PASS | Standalone synthesis check for the struct<->AXIS blocks. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `type_axis_test` | [inst/type_axis_test.py](../../../src/tests/pypeline_tests/inst/type_axis_test.py) | comb synthesis; device_models | M 116.8 s / PASS | All four struct/AXIS framing variants preserve packets, partial keep masks, length limits, back-to-back alignment and explicit runt recovery policies. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `type_byte_stream_test` | [inst/type_byte_stream_test.py](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py) | comb synthesis; device_models | M 160.5 s / PASS | Struct streams match software byte layout exactly, including partial beats, per-value end markers, loopbacks, padding errors and externally encoded frames. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `underscore_name_test` | [inst/underscore_name_test.py](../../../src/tests/pypeline_tests/inst/underscore_name_test.py) | comb synthesis; device_models | M 9.9 s / PASS | Regression test for leading-underscore Python names producing illegal VHDL identifiers. PY_TO_LOGIC's identifier mangling (_sanitize_vhdl_name) covered illegal *variable* names (e.g. 'block' -> 'block_v') but not callee-derived instance names or VHDL entity names. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |
| `var_ref_test` | [inst/var_ref_test.py](../../../src/tests/pypeline_tests/inst/var_ref_test.py) | comb synthesis; device_models | M 34.3 s / PASS | Ten unconditional variable-index struct/array read/write HDL shapes, including nested indexes and read-after-write. | Share the ten base shapes with if_test; do not delete unconditional coverage simply because conditional code looks similar. | feature/tool |
| `vhdl_text_test` | [inst/vhdl_text_test.py](../../../src/tests/pypeline_tests/inst/vhdl_text_test.py) | comb synthesis; device_models | M 15.8 s / PASS | Raw VHDL wrapper emission and the explicit refusal to execute unmodeled raw HDL in native sim. | Keep the HDL shape; candidate for a GHDL compile lane if legality is the contract. Retain representative real synthesis for tool acceptance. | feature/tool |

## synth_vivado

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `example_arty_top` | [examples/pypeline/arty/top.py](../../../examples/pypeline/arty/top.py) | comb synthesis; vivado | U (not measured) | Build the Arty RGB LED plus VGA board top. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `fm_radio_decim` | [examples/pypeline/dsp/fm_radio_decim.py](../../../examples/pypeline/dsp/fm_radio_decim.py) | comb synthesis; vivado | U (not measured) | Build the I/Q 5x FIR decimator pair using the documented 49-tap radio coefficients. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `stream_auto_multi_cycle_test` | [inst/stream_auto_multi_cycle_test.py](../../../src/tests/pypeline_tests/inst/stream_auto_multi_cycle_test.py) | comb synthesis; vivado | U (not measured) | Fixed/start MCP stream counts determine handshake latency and generate the associated Vivado constraints. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `stream_multi_cycle_test` | [inst/stream_multi_cycle_test.py](../../../src/tests/pypeline_tests/inst/stream_multi_cycle_test.py) | comb synthesis; vivado | U (not measured) | Fixed multi-cycle divider launch/wait/output handshake and Vivado timing exceptions. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `sweep_float32_vivado` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; vivado | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=130.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |
| `two_factory_wrappers_mixed_test` | [inst/two_factory_wrappers_mixed_test.py](../../../src/tests/pypeline_tests/inst/two_factory_wrappers_mixed_test.py) | comb synthesis; vivado | U (not measured) | A shared callable wrapped with different pipeline/MCP factories keeps distinct generated logic under Vivado. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `vga_donut` | [examples/pypeline/vga_donut.py](../../../examples/pypeline/vga_donut.py) | comb synthesis; vivado | D ≈1800 s | Build the documented VGA donut renderer on its Xilinx board target. | Keep as board/example nightly smoke; documented ~30 min. A smaller VGA example can cover routine board changes. | deep/nightly |
| `vga_test_pattern` | [examples/pypeline/vga_test_pattern.py](../../../examples/pypeline/vga_test_pattern.py) | comb synthesis; vivado | U (not measured) | Build the documented VGA test-pattern hardware and board bindings. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |

## synth_open_tools

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `example_pico_ice_top` | [examples/pypeline/pico_ice/top.py](../../../examples/pypeline/pico_ice/top.py) | comb synthesis; open_tools | U (not measured) | Build the iCE40 pico-ice blinky board top. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `example_pico_ice_vga_top` | [examples/pypeline/pico_ice/vga_top.py](../../../examples/pypeline/pico_ice/vga_top.py) | comb synthesis; open_tools | U (not measured) | Build the iCE40 pico-ice VGA board top. | Keep as example integration; library unit cases do not verify that this documented composition still works. | feature/tool |
| `openxc7_bitstream_test` | [inst/openxc7_bitstream_test.py](../../../src/tests/pypeline_tests/inst/openxc7_bitstream_test.py) | Python assertions / wrapper; open_tools category | U (not measured) | OpenXC7 --pins builds end to end: board-facing implementation, Project X-Ray conversion, and a bitstream that honors the pin constraints. | Keep real synthesis/target coverage in its feature/tool lane; a native-only oracle cannot replace it. | feature/tool |
| `sweep_float32_open_tools` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; open_tools | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=60.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |
| `sweep_float32_openxc7` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; open_tools | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=200.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |

## synth_pyrtl

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `sweep_float32_pyrtl` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; pyrtl | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=40.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |

## synth_quartus

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `sweep_float32_quartus` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; quartus | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=60.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |

## synth_efinity

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `sweep_float32_efinity` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; efinity | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=500.0. | Keep one real planned sweep for this backend/part in its tool lane; common source is intentional. Add cheap report/constraint unit fixtures for routine changes. | feature/tool |

## build_report_open_tools

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `auto_pipeline_ram_build_test` | [inst/auto_pipeline_ram_build_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_ram_build_test.py) | Python assertions / wrapper; open_tools category | U (not measured) | ECP5/Vivado inference, constraints, measured search, and failure diagnostics. | Keep per-backend BRAM inference/resource assertions; a passing behavioral simulation cannot detect register-array fallback. | feature/tool |
| `auto_pipeline_ram_qor_test` | [auto_pipeline_ram_qor_bench.py](../../../src/tests/pypeline_tests/auto_pipeline_ram_qor_bench.py) | Python assertions / wrapper; open_tools category | U (not measured) | Reproducible ECP5 BRAM latency/frequency/resource frontier (no timeout). Registered subset: size 65536; latencies 3/7/9; seed 1; require improvement. | Keep a bounded regression separately from the full manual frontier; its registered 64K subset is currently in the default suite. | deep/nightly |
| `syn_cache_netlist_test` | [inst/syn_cache_test.py](../../../src/tests/pypeline_tests/inst/syn_cache_test.py) | Python assertions / wrapper; open_tools category | U (not measured) | Synthesis reuse respects HDL/constraint/tool/recipe identity, invalidation, store repair/pruning, warm replay, final HDL refresh and forced netlist exports. Variant: netlist. | Keep stale inputs, rewritten RTL and store reuse. --cases netlist and pyrtl check different artifacts and should remain separate tool lanes. | feature/tool |

## build_report_vivado

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `auto_multi_cycle_sweep_test` | [inst/auto_multi_cycle_sweep_test.py](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_sweep_test.py) | Python assertions / wrapper; vivado category | U (not measured) | Real Vivado MCP count growth, re-elaboration, handshake timing, caps, remembered counts and confirmation downwards. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_pipeline_ram_build_vivado_test` | [inst/auto_pipeline_ram_build_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_ram_build_test.py) | Python assertions / wrapper; vivado category | U (not measured) | ECP5/Vivado inference, constraints, measured search, and failure diagnostics. | Keep per-backend BRAM inference/resource assertions; a passing behavioral simulation cannot detect register-array fallback. | feature/tool |
| `mcp_dsp_packing_test` | [inst/mcp_dsp_packing_test.py](../../../src/tests/pypeline_tests/inst/mcp_dsp_packing_test.py) | Python assertions / wrapper; vivado category | U (not measured) | Native/GHDL MCP values, latency and stalls plus Vivado per-bit endpoint coverage, DSP packing and setup/hold exceptions, with negative audit controls. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |

## build_report_device_models

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `area_estimate_build_report_test` | [inst/area_estimate_build_report_test.py](../../../src/tests/pypeline_tests/inst/area_estimate_build_report_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Estimated and measured sky130 area, sidecar schema, cold leaf coverage and reuse of prior whole-MAIN evidence. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_comb_area_opt_build_test` | [inst/auto_comb_area_opt_build_test.py](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_build_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Real RTL equivalence and mapped-area checks for combinational HLS. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_comb_delay_opt_build_test` | [inst/auto_comb_delay_opt_build_test.py](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_build_test.py) | Python assertions / wrapper; device_models category | U (not measured) | SAT equivalence, register-free RTL, and mapped combinational timing. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_fsm_area_sweep_compare_test` | [inst/auto_fsm_area_sweep_compare_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_area_sweep_compare_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Abstract-area search versus sharing-everything, judged using real mapped sky130 cells. | Review consolidation with min_area_verify only after matching design, abstract-area flag, baseline and mapped-cell assertions; do not count it as already redundant. | feature/tool |
| `auto_fsm_latency_sized_test` | [inst/auto_fsm_latency_sized_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_latency_sized_test.py) | Python assertions / wrapper; device_models category | D ≈300 s | AUTO_FSM sized from an AUTO_PIPELINE depth: the call site the pin-and-confirm re-elaboration creates is scheduled, and the build finishes. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_fsm_latency_test` | [inst/auto_fsm_latency_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_latency_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A real schedule shares repeated operations, reports latency equal to state count, instantiates each shared unit once in VHDL and meets timing. | Keep schedule/unit-count/latency assertions; consider checking those artifacts in an existing FSM build to avoid repeated setup. | feature/tool |
| `auto_fsm_max_latency_test` | [inst/auto_fsm_max_latency_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_max_latency_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A feasible hard latency cap adds resources and meets its deadline; an impossible cap fails with the required latency and FSM identity. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_fsm_min_area_verify_test` | [inst/auto_fsm_min_area_verify_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_min_area_verify_test.py) | Python assertions / wrapper; device_models category | D 840–1800 s | Four independently built scheduling alternatives; the chosen abstract-area schedule must be within 3% of the smallest mapped implementation. | Keep four-point independent real-cell oracle in deep/QoR lane; retain the tolerance and alternatives when refactoring. | feature/tool |
| `auto_fsm_real_area_compare_test` | [inst/auto_fsm_real_area_compare_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_real_area_compare_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Real-area ranking versus abstract-area ranking, compared using measured sky130 square-micron area on divider schedules. | Keep: physical area ranking differs from the abstract/cell-count oracle; same topic does not imply duplicate coverage. | feature/tool |
| `auto_fsm_resources_compare_test` | [inst/auto_fsm_resources_compare_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_resources_compare_test.py) | Python assertions / wrapper; device_models category | U (not measured) | AUTO_FSM resource test: is the FSM actually SMALLER than the combinational logic it replaces? | Keep mapped area reduction: arithmetic correctness alone cannot prove resource sharing helps. | feature/tool |
| `auto_fsm_tighten_stall_test` | [inst/auto_fsm_tighten_stall_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_tighten_stall_test.py) | Python assertions / wrapper; device_models category | U (not measured) | AUTO_FSM tighten-loop termination: when rescheduling cannot move the critical path, the driver must stop promptly and say why. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_fsm_timing_iter_test` | [inst/auto_fsm_timing_iter_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_timing_iter_test.py) | Python assertions / wrapper; device_models category | U (not measured) | AUTO_FSM synthesis-iteration test: does the build FIND a critical path inside an AUTO_FSM and FIX it by rescheduling? | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_pipeline_c_pragma_test` | [inst/auto_pipeline_c_pragma_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_c_pragma_test.py) | Python assertions / wrapper; device_models category | U (not measured) | C AUTOPIPELINE pragma realizes exactly its fixed latency even in a comb build. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_pipeline_constraints_test` | [inst/auto_pipeline_constraints_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_constraints_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Fixed/start/max region depths, skipped confirmation passes, cap failures and latency-sized stream FIFO growth. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_pipeline_latency_test` | [inst/auto_pipeline_latency_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_latency_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A full stream sweep discovers latency, resizes its FIFO and confirms the harvested pipeline in pass 2. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `auto_pipeline_region_minisweep_test` | [inst/auto_pipeline_region_minisweep_test.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_minisweep_test.py) | Python assertions / wrapper; device_models category | D 360–840 s | Repeated-helper mini-sweep locks survive start hints and latency-memory replay, stale edits and raised goals. | Keep geometry and lock replay; separate minisweep correctness and extended memory scenarios so either feature can select only its cases. | feature/tool |
| `cocotb_verdict_test` | [inst/cocotb_verdict_test.py](../../../src/tests/pypeline_tests/inst/cocotb_verdict_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Actual GHDL/cocotb runs report PASS for clean sim_finish and FAIL for sim_assert, using results.xml rather than misleading console text. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `design_params_build_test` | [inst/design_params_build_test.py](../../../src/tests/pypeline_tests/inst/design_params_build_test.py) | Python assertions / wrapper; device_models category | D ≈300 s for pass-2 case only | Design parameters through the drivers (pypelinec, pypeline_sim.py): - -D WIDTH=16 / STEP=3 changes the generated VHDL (port width, constant); the build prints the parameter table and records it in source_provenance.json; - --list_params lists declarations without elaborating; - a value outside choices= and a misspelled -D name fail the build with a one-line reason; - cpp-style injected globals (no param()) reach module-level code and a hardware body; - native simulation sees -D values, both from… | Split fast CLI/diagnostic cases from the roughly five-minute re-elaboration build; retain both. | feature/tool |
| `duplicate_collapse_naming_test` | [inst/duplicate_collapse_naming_test.py](../../../src/tests/pypeline_tests/inst/duplicate_collapse_naming_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Two hash-seeded fresh builds emit byte-identical names/VHDL after duplicate-submodule collapse. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `generated_naming_build_test` | [inst/generated_naming_build_test.py](../../../src/tests/pypeline_tests/inst/generated_naming_build_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Compare fresh-process VHDL and verify names with a real VHDL compiler. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `global_wire_pipeline_instance_test` | [inst/global_wire_pipeline_instance_test.py](../../../src/tests/pypeline_tests/inst/global_wire_pipeline_instance_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Global wires used below the root of a pipelined function, and VOLATILE ones (pypeline_guide.md, "Global wires in pipelined code"). | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `hooks_order_native_pipelined` | [inst/hooks_order_test.py](../../../src/tests/pypeline_tests/inst/hooks_order_test.py) | Python assertions / wrapper; device_models category | U (not measured) | @initial/@final hooks through the pypelinec driver: runs hooks_design.py in a pypelinec subprocess and checks where its "HOOK: <name>" markers land in the output, relative to the driver's own progress lines. Variant: native_pipelined. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `hooks_order_vhdl_comb` | [inst/hooks_order_test.py](../../../src/tests/pypeline_tests/inst/hooks_order_test.py) | Python assertions / wrapper; device_models category | U (not measured) | @initial/@final hooks through the pypelinec driver: runs hooks_design.py in a pypelinec subprocess and checks where its "HOOK: <name>" markers land in the output, relative to the driver's own progress lines. Variant: vhdl_comb. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `host_types_build_test` | [inst/host_types_build_test.py](../../../src/tests/pypeline_tests/inst/host_types_build_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A real pypelinec build must drop a usable host module in its output dir. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `latency_memory_build_test` | [inst/latency_memory_build_test.py](../../../src/tests/pypeline_tests/inst/latency_memory_build_test.py) | Python assertions / wrapper; device_models category | D 840–1500 s | Sky130: all-MAIN replay, cross-goal/store reuse, stale pieces and partial failure. | Keep replay/staleness/partial-failure contract in deep integration; split cheap store/format cases from real multi-build confirmations. | feature/tool |
| `leaf_1ll_cap_test` | [inst/leaf_1ll_cap_test.py](../../../src/tests/pypeline_tests/inst/leaf_1ll_cap_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Real synthesis constrains one-logic-level cuts to useful operation boundaries and reports the physical bottleneck. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `split_model_build_report_test` | [inst/split_model_build_report_test.py](../../../src/tests/pypeline_tests/inst/split_model_build_report_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Planned/coarse builds report cuts before synthesis and distinguish slices, stages and total latency. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `sweep_floor_detect_test` | [inst/sweep_floor_detect_test.py](../../../src/tests/pypeline_tests/inst/sweep_floor_detect_test.py) | Python assertions / wrapper; device_models category | U (not measured) | An unreachable clock stops promptly at the documented floor/plateau and reports the limiting path. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `sweep_planless_test` | [inst/sweep_planless_test.py](../../../src/tests/pypeline_tests/inst/sweep_planless_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A goal-bearing stateful MAIN with no cuttable regions is confirmed once and reports met timing correctly. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `sweep_unpipelinable_test` | [inst/sweep_unpipelinable_test.py](../../../src/tests/pypeline_tests/inst/sweep_unpipelinable_test.py) | Python assertions / wrapper; device_models category | U (not measured) | An uncuttable MAIN with an unreachable goal fails with an actionable diagnostic and accurate final evidence. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `var_ref_naming_test` | [inst/var_ref_naming_test.py](../../../src/tests/pypeline_tests/inst/var_ref_naming_test.py) | Python assertions / wrapper; device_models category | U (not measured) | Variable-index helper names and emitted bytes stay deterministic across fresh processes, seeds and warm rebuilds. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `warm_copy_no_resynth_test` | [inst/warm_copy_no_resynth_test.py](../../../src/tests/pypeline_tests/inst/warm_copy_no_resynth_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A copy of a warm output directory re-synthesizes nothing. | Keep explicit no-resynthesis assertion; ordinary successful warm compares do not enforce it. Consider consuming a preserved FSM build snapshot within one integration job. | feature/tool |
| `zero_delay_helper_build_test` | [inst/zero_delay_helper_build_test.py](../../../src/tests/pypeline_tests/inst/zero_delay_helper_build_test.py) | Python assertions / wrapper; device_models category | U (not measured) | A real sky130 build recognizes recursively wiring-only helpers as zero delay and realizes both requested fixed AUTO_PIPELINE registers. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |

## build_report_pyrtl

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `auto_fsm_ctl_compare_test` | [inst/auto_fsm_ctl_compare_test.py](../../../src/tests/pypeline_tests/inst/auto_fsm_ctl_compare_test.py) | Python assertions / wrapper; pyrtl category | U (not measured) | Control v3 versus v2 cell cost and donut first-schedule timing under the specifically calibrated PyRTL backend. | Keep PyRTL-specific control comparison unless v2 support is deliberately retired; device_models is not an equivalent oracle. | feature/tool |
| `pyrtl_no_timing_paths_build_report_test` | [inst/pyrtl_no_timing_paths_build_report_test.py](../../../src/tests/pypeline_tests/inst/pyrtl_no_timing_paths_build_report_test.py) | Python assertions / wrapper; pyrtl category | U (not measured) | A no-output design fails cleanly with PyRTL's no-timing-paths diagnostic, rather than division-by-zero or a coarse-sweep crash. | Keep artifact/report assertions; share repeated builds only if inputs, cache state and every asserted artifact match. | feature/tool |
| `syn_cache_test` | [inst/syn_cache_test.py](../../../src/tests/pypeline_tests/inst/syn_cache_test.py) | Python assertions / wrapper; pyrtl category | D ≈60 s (pyrtl cases) | Synthesis reuse respects HDL/constraint/tool/recipe identity, invalidation, store repair/pruning, warm replay, final HDL refresh and forced netlist exports. Variant: pyrtl. | Keep stale inputs, rewritten RTL and store reuse. --cases netlist and pyrtl check different artifacts and should remain separate tool lanes. | feature/tool |

## known_issues

| Test name | Source | Current execution | Historical cost | Purpose | Still useful / recommendation | Proposed lane |
|---|---|---|---|---|---|---|
| `fixed_auto_pipeline_extra_cuts_known_issue` | [inst/fixed_auto_pipeline_extra_cuts_test.py](../../../src/tests/pypeline_tests/inst/fixed_auto_pipeline_extra_cuts_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Known issue: AUTO_PIPELINE(func, latency=N) plans N register cuts in func's own logic even when func's @pipeline_latency calls already supply the N cycles. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `float_format_cast_inline_logic_known_issue` | [inst/float_format_cast_test.py](../../../src/tests/pypeline_tests/inst/float_format_cast_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | C float-format conversion: out-of-range numeric results and hidden inline conversion logic are separate bug reproducers. Variant: inline. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `float_format_cast_wraps_known_issue` | [inst/float_format_cast_test.py](../../../src/tests/pypeline_tests/inst/float_format_cast_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | C float-format conversion: out-of-range numeric results and hidden inline conversion logic are separate bug reproducers. Variant: values. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `global_wire_unshared_readback_known_issue` | [inst/global_wire_unshared_readback_design.py](../../../src/tests/pypeline_tests/inst/global_wire_unshared_readback_design.py) | native + GHDL diff / comb; expect nonzero | U (not measured) | A sole writer's readback still emits the global-wire record package and legal HDL when no wire is shared. | Keep new issue #384 minimal fixture; existing shared-wire tests can mask missing package emission. Add a shared-wire positive control on promotion. | issue/manual |
| `hw_func_default_arg_known_issue` | [inst/hw_func_default_arg_design.py](../../../src/tests/pypeline_tests/inst/hw_func_default_arg_design.py) | elab/HDL emit, no synthesis; expect nonzero | U (not measured) | An omitted default hardware input is not wired; explicit input is a control. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `imported_auto_pipeline_attribution_known_issue` | [inst/imported_auto_pipeline_attribution_test.py](../../../src/tests/pypeline_tests/inst/imported_auto_pipeline_attribution_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Known issue: AUTO_PIPELINE(imported_f) loses the sweep's path attribution. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `latency_constant_entity_reuse_known_issue` | [inst/latency_constant_entity_reuse_test.py](../../../src/tests/pypeline_tests/inst/latency_constant_entity_reuse_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Known issue: a pipelined top-level function that folds a value derived from an AUTO_PIPELINE's .latency keeps pass 1's entity file in pin-and-confirm pass 2. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `library_factory_array_elem_known_issue` | [inst/library_factory_array_elem_design.py](../../../src/tests/pypeline_tests/inst/library_factory_array_elem_design.py) | GHDL self-check; expect nonzero | U (not measured) | Known issue #378: library factories that make "n values of the caller's type" write `elem_t[n]`, which is the wrong shape when elem_t is itself an array. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `live_root_submodule_labels_known_issue` | [inst/live_root_submodule_labels_test.py](../../../src/tests/pypeline_tests/inst/live_root_submodule_labels_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Known issue: native simulation after a build drops the build's pipeline placements inside a @MAIN of an imported module. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `numpy_factory_arg_identity_known_issue` | [inst/numpy_factory_arg_identity_test.py](../../../src/tests/pypeline_tests/inst/numpy_factory_arg_identity_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Known issue: factory specializations that differ only inside a large numpy array argument share one identity, so they elaborate as one function. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `pipeline_latency_wire_body_known_issue` | [inst/pipeline_latency_wire_body_design.py](../../../src/tests/pypeline_tests/inst/pipeline_latency_wire_body_design.py) | GHDL self-check; expect nonzero | U (not measured) | Known issue: @pipeline_latency(N >= 1) on a body that is only wiring (no registers, no operators) renders illegal VHDL. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `scoped_operator_registration_known_issue` | [inst/scoped_operator_registration_test.py](../../../src/tests/pypeline_tests/inst/scoped_operator_registration_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Scoped top-level integer/struct operators and a shared callee under scoped versus plain callers instantiate the intended implementations. | Keep new issue #385 reproducer; distinguish top-level scope from shared-callee specialization and test both caller orders when fixing it. Unexpected parse/setup errors must not count as the expected bug. | issue/manual |
| `sim_finish_debug_print_race_test` | [inst/sim_finish_debug_print_race_test.py](../../../src/tests/pypeline_tests/inst/sim_finish_debug_print_race_test.py) | Python assertions / wrapper; assert known bad behavior | U (not measured) | KNOWN ISSUE (reproducer, not a fix): a sim_print(..., debug=True) call on the SAME cycle as sim_finish() is silently DROPPED from the cocotb+GHDL log entirely -- not printed late, not printed with a warning, just absent -- even though the identical design's native (Python) sim prints it normally. | Keep as a diagnostic reproducer; it has expect_fail=False and asserts the bad behavior. Prefer uniform expected-good semantics in a later harness cleanup. | issue/manual |
| `stateless_caller_sim_state_known_issue` | [inst/stateless_caller_sim_state_design.py](../../../src/tests/pypeline_tests/inst/stateless_caller_sim_state_design.py) | native + GHDL diff / comb; expect nonzero | U (not measured) | Two counter/FIFO instances behind stateless callers retain independent state in native simulation, checked against GHDL. | Keep new issue #382 regression; existing factory-MAIN independence tests use different root frames and cannot replace same-MAIN stateless-wrapper coverage. | issue/manual |
| `struct_signed_prefix_known_issue` | [inst/struct_signed_prefix_design.py](../../../src/tests/pypeline_tests/inst/struct_signed_prefix_design.py) | GHDL self-check; expect nonzero | U (not measured) | A nested record starting with 'signed_' is mistaken for a VHDL scalar. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `sweep_failed_trim_known_issue` | [inst/sweep_failed_trim_design.py](../../../src/tests/pypeline_tests/inst/sweep_failed_trim_design.py) | synthesis/sweep; device_models; expect nonzero | D ≈75 s | Known issue: after the sweep meets timing, a failed trim trial is kept. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |
| `sweep_float32_cc_tools_known_issue` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; cc_tools; expect nonzero | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=25.0. | Keep backend probe separately from compiler bugs; classify license/tool setup explicitly and require the expected failure signature. | issue/manual |
| `sweep_float32_diamond_known_issue` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; diamond; expect nonzero | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=15.0. | Keep backend probe separately from compiler bugs; classify license/tool setup explicitly and require the expected failure signature. | issue/manual |
| `sweep_float32_gowin_known_issue` | [inst/sweep_float32_test.py](../../../src/tests/pypeline_tests/inst/sweep_float32_test.py) | synthesis/sweep; gowin; expect nonzero | U (not measured) | One float32-adder design exercises backend-specific characterization, real cuts and final timing confirmation. Variant: SWEEP_FLOAT32_MHZ=25.0. | Keep backend probe separately from compiler bugs; classify license/tool setup explicitly and require the expected failure signature. | issue/manual |
| `top_level_reader_order_known_issue` | [inst/top_level_reader_order_test.py](../../../src/tests/pypeline_tests/inst/top_level_reader_order_test.py) | Python assertions / wrapper; expect nonzero | U (not measured) | Known issue: the generated top level's global-wire connections come out in an order that depends on Python's string hashing. | Keep opt-in bug reproducer; match the intended error/artifact, not arbitrary nonzero exit. Promote to normal regression after a verified fix. | issue/manual |

## Supporting files and manual tests

These are not additional `run_all` invocations. Keep fixtures with their consumers; directory moves should follow selection/harness work. Consumer names below are static textual references, useful for navigation but not a complete dependency graph. Costs belong to the calling registration unless a benchmark is run manually.

| File | Role and purpose | Still useful / organization recommendation |
|---|---|---|
| [auto_fsm_div_share_test.py](../../../src/tests/pypeline_tests/auto_fsm_div_share_test.py) | Design for the AUTO_FSM minimum-area verification test (auto_fsm_min_area_verify_test.py): the OPEN showcase. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_fsm_min_area_verify_test.py`, `inst/registration_audit_test.py`. |
| [auto_fsm_resources_test.py](../../../src/tests/pypeline_tests/auto_fsm_resources_test.py) | Design for the AUTO_FSM resource-comparison test (auto_fsm_resources_compare_test.py). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_fsm_area_sweep_compare_test.py`, `inst/auto_fsm_ctl_compare_test.py`, `inst/auto_fsm_resources_compare_test.py`, `inst/registration_audit_test.py`. |
| [auto_fsm_tighten_test.py](../../../src/tests/pypeline_tests/auto_fsm_tighten_test.py) | Design for the AUTO_FSM tighten-stall test (auto_fsm_tighten_stall_test.py). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_fsm_tighten_stall_test.py`, `inst/auto_fsm_timing_iter_design.py`, `inst/registration_audit_test.py`. |
| [build_report_tests.py](../../../src/tests/pypeline_tests/build_report_tests.py) | Wrapper-script tests: each runs pypelinec itself (as a subprocess) and asserts on its build LOG output or generated artifacts -- yosys/PYRTL cell counts, "TIMING NOT MET" error text, sweep_history.json, AUTO_FSM schedule reports. This is a real full build in every case, just with the assertion living one process layer below the runner instead of being "exit code only" (that's synth_tests.py). | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `inst/registration_audit_test.py`, `native_sim_tests.py`, `native_vs_vhdl_sim_tests.py` (plus 2 others). |
| [common.py](../../../src/tests/pypeline_tests/common.py) | Shared infra for every category module (native_sim_tests.py, native_vs_vhdl_sim_tests.py, elab_tests.py, elab_introspect_tests.py, unit_tests.py, synth_tests.py, build_report_tests.py, known_issues_tests.py) and run_all.py. See docs/pypeline_TESTS.md for what belongs in each. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. |
| [constraints/openxc7_basys3_blink.xdc](../../../src/tests/pypeline_tests/constraints/openxc7_basys3_blink.xdc) | Basys 3 clock/LED pin constraints consumed by the bitstream pin-placement regression. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/openxc7_bitstream_test.py`. |
| [def/file_a.py](../../../src/tests/pypeline_tests/def/file_a.py) | Imported MAINs/wires/types; imports file_c to exercise transitive discovery. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. |
| [def/file_b.py](../../../src/tests/pypeline_tests/def/file_b.py) | Second imported hardware/wire module for cross-module import connectivity. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. |
| [def/file_c.py](../../../src/tests/pypeline_tests/def/file_c.py) | Deep imported module for the two-hop import test. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. |
| [def/importfrom_leaf.py](../../../src/tests/pypeline_tests/def/importfrom_leaf.py) | Leaf struct/function module discovered only through transitive from-imports. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `def/importfrom_mid.py`, `inst/importfrom_test.py`. |
| [def/importfrom_mid.py](../../../src/tests/pypeline_tests/def/importfrom_mid.py) | Middle from-import hop exposing the leaf type/function. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `def/importfrom_leaf.py`, `inst/importfrom_test.py`. |
| [def/pypeline_tests.py](../../../src/tests/pypeline_tests/def/pypeline_tests.py) | Shared point/aggregate types and hardware helpers used by language regression fixtures. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `auto_pipeline_ram_qor_bench.py`, `common.py`, `divider_struct_mux_bench.py`, `inst/bit_math_test.py` (plus 11 others). |
| [def/wire_discovery_dataflow.py](../../../src/tests/pypeline_tests/def/wire_discovery_dataflow.py) | Pure cross-module wiring, no Wire[T]/Input[T]/Output[T] of its own -- mirrors wireguard-fpga's encrypt_dataflow.py shape that exposed the _discover_wire_names two-hop recursion gap (regression test for that fix). One-directional connection only (leaf_a -> leaf_b) so this has no combinational loop of its own. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/wire_discovery_passthrough_sim_test.py`. |
| [def/wire_discovery_leaf_a.py](../../../src/tests/pypeline_tests/def/wire_discovery_leaf_a.py) | Wire-owning leaf A behind the wire-free dataflow import. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `def/wire_discovery_dataflow.py`, `inst/wire_discovery_passthrough_sim_test.py`. |
| [def/wire_discovery_leaf_b.py](../../../src/tests/pypeline_tests/def/wire_discovery_leaf_b.py) | Wire-owning leaf B behind the wire-free dataflow import. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `def/wire_discovery_dataflow.py`. |
| [divider_continuity_bench.py](../../../src/tests/pypeline_tests/divider_continuity_bench.py) | Opt-in arithmetic Divider latency/fmax continuity benchmark. | Keep opt-in benchmark; expose a bounded smoke subset only when it has a distinct contract. Record exact HDL/tool/cache identity. References: `divider_struct_mux_bench.py`, `inst/divider_qor_bench_unit_test.py`. |
| [divider_qor_bench.py](../../../src/tests/pypeline_tests/divider_qor_bench.py) | Opt-in sky130 QoR and exact-final-VHDL verification for Divider. | Keep opt-in benchmark; expose a bounded smoke subset only when it has a distinct contract. Record exact HDL/tool/cache identity. References: `divider_continuity_bench.py`, `inst/divider_qor_bench_unit_test.py`, `qor/divider/arithmetic.py`, `qor/divider/gate.py` (plus 1 others). |
| [divider_struct_mux_bench.py](../../../src/tests/pypeline_tests/divider_struct_mux_bench.py) | Focused sky130 acceptance for packed user-type MUX splitting. | Keep opt-in benchmark; expose a bounded smoke subset only when it has a distinct contract. Record exact HDL/tool/cache identity. |
| [elab_introspect_tests.py](../../../src/tests/pypeline_tests/elab_introspect_tests.py) | In-process compiler-internals tests: each calls PY_TO_LOGIC.PARSE_FILE directly (not via the pypelinec CLI) and asserts on the resulting parser_state / FuncLogicLookupTable / raised ElaborationError -- checks that are otherwise invisible to a bare "did it elaborate" check (elab_tests.py) or to sim_call (a native-Python path that never touches these compiler internals at all). | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `elab_tests.py`, `inst/auto_fsm_var_index_read_test.py`, `inst/global_fifo_pipeline_latency_test.py` (plus 4 others). |
| [elab_tests.py](../../../src/tests/pypeline_tests/elab_tests.py) | pypelinec --no_synth (elaboration only, no auto-pipelining/synthesis) tests. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `elab_introspect_tests.py`, `inst/registration_audit_test.py`, `inst/sim_print_test.py` (plus 2 others). |
| [inst/_cache_isolation.py](../../../src/tests/pypeline_tests/inst/_cache_isolation.py) | Shared cache-isolation helper for inst/*.py tests that want a FRESH area cache but a WARM delay cache (leading underscore: not a test, see docs/pypeline_TESTS.md naming convention). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/area_estimate_build_report_test.py`, `inst/auto_fsm_real_area_compare_test.py`. |
| [inst/_mcp_dsp_audit.tcl](../../../src/tests/pypeline_tests/inst/_mcp_dsp_audit.tcl) | Vivado audit queries for per-bit MCP endpoints, register packing and setup/hold requirements. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/mcp_dsp_packing_test.py`. |
| [inst/_test_main.py](../../../src/tests/pypeline_tests/inst/_test_main.py) | Shared __main__ harness for inst/*.py test files. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `inst/added_latency_context_test.py`, `inst/area_model_test.py`, `inst/async_fifo_elab_test.py`, `inst/auto_comb_area_opt_test.py` (plus 57 others). |
| [inst/added_latency_context_design.py](../../../src/tests/pypeline_tests/inst/added_latency_context_design.py) | One shared helper in two MAINs, tagged bodies, MCPs, and untagged gaps. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/added_latency_context_test.py`. |
| [inst/auto_fsm_latency_sized_design.py](../../../src/tests/pypeline_tests/inst/auto_fsm_latency_sized_design.py) | Build fixture for auto_fsm_latency_sized_test.py: an AUTO_FSM whose function is sized from an AUTO_PIPELINE depth, the shape of WireGuard's shared Poly1305 kernels (lane capacity = body depth + 2). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_fsm_latency_sized_test.py`. |
| [inst/auto_fsm_max_latency_design.py](../../../src/tests/pypeline_tests/inst/auto_fsm_max_latency_design.py) | Design for the AUTO_FSM max_latency test (auto_fsm_max_latency_test.py). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_fsm_max_latency_test.py`. |
| [inst/auto_fsm_timing_iter_design.py](../../../src/tests/pypeline_tests/inst/auto_fsm_timing_iter_design.py) | Design for the AUTO_FSM timing-iteration test (auto_fsm_timing_iter_test.py). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `auto_fsm_tighten_test.py`, `inst/auto_fsm_timing_iter_test.py`. |
| [inst/auto_multi_cycle_sweep_design.py](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_sweep_design.py) | AUTO_MULTI_CYCLE end to end under a real Vivado sweep (driven by auto_multi_cycle_sweep_test.py): a ~16-round add/xor mixing chain far slower than one 100 MHz clock period, behind make_stream_auto_multi_cycle. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_multi_cycle_sweep_test.py`, `inst/sweep_evidence_test.py`. |
| [inst/auto_multi_cycle_unread_design.py](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unread_design.py) | A raw AUTO_MULTI_CYCLE tag whose .latency nothing in the design reads (the handshake counter is hard-coded): a synthesizing build must refuse it (AUTO_MULTI_CYCLE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ). Used by auto_multi_cycle_unit_test.py. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_multi_cycle_unit_test.py`. |
| [inst/auto_pipeline_c_pragma_design.c](../../../src/tests/pypeline_tests/inst/auto_pipeline_c_pragma_design.c) | C fixture with fixed AUTOPIPELINE latency for the pragma wrapper. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_pipeline_c_pragma_test.py`. |
| [inst/auto_pipeline_constraints_design.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_constraints_design.py) | Build fixture for auto_pipeline_constraints_test.py: a fixed latency=2 and a start_latency=1 AUTO_PIPELINE call site under a stateful @MAIN with an easy clock goal. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_pipeline_constraints_test.py`. |
| [inst/auto_pipeline_max_latency_design.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_max_latency_design.py) | Build fixture for auto_pipeline_constraints_test.py: an unreachable clock goal whose only pipelinable logic is a max_latency=1 AUTO_PIPELINE call site. The sweep must build at most 1 register there, stop promptly with a warning naming the cap (not spin to its iteration limit), and fail the build. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_pipeline_constraints_test.py`. |
| [inst/auto_pipeline_ram_design.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_ram_design.py) | Observable RAM fixture; -D parameters set the backend/constraint matrix. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `auto_pipeline_ram_qor_bench.py`, `inst/auto_pipeline_ram_build_test.py`. |
| [inst/auto_pipeline_region_minisweep_design.py](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_minisweep_design.py) | Build fixture for auto_pipeline_region_minisweep_test.py: ChaCha-shaped serial geometry in miniature. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_pipeline_region_minisweep_test.py`. |
| [inst/c_structs_pkg_relayout_design.py](../../../src/tests/pypeline_tests/inst/c_structs_pkg_relayout_design.py) | Fixture for c_structs_pkg_relayout_test.py, shaped like WireGuard's make_poly1305_mac_pipelined(direction). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/c_structs_pkg_relayout_test.py`, `inst/sweep_evidence_test.py`. |
| [inst/deliberate_sim_assert_failure_design.py](../../../src/tests/pypeline_tests/inst/deliberate_sim_assert_failure_design.py) | Fixture for cocotb_verdict_test.py: a design whose sim_assert always fires, so real --cocotb --ghdl runs exit nonzero deterministically and independently of any particular compiler bug's lifecycle. (A previous revision of cocotb_verdict_test.py borrowed a known-issue reproducer for this instead -- nested_truncate_vhdl_mismatch_known_issue.py, whose failure depended on a since-fixed VHDL-emission bug; see docs/pypeline_DESIGN.md's Casting section. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/cocotb_verdict_test.py`. |
| [inst/design_params_design.py](../../../src/tests/pypeline_tests/inst/design_params_design.py) | Fixture for design_params_test.py / design_params_build_test.py: a data width, a clock goal and an increment, each declared with param() and set with -D NAME=VALUE. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/design_params_build_test.py`, `inst/design_params_test.py`. |
| [inst/design_params_injected_design.py](../../../src/tests/pypeline_tests/inst/design_params_injected_design.py) | Fixture for design_params_build_test.py: -D values read as plain globals, cpp-macro style, with no param() declaration -- INJ_WIDTH at module level, INJ_INC inside the hardware body. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/design_params_build_test.py`. |
| [inst/design_params_pass2_design.py](../../../src/tests/pypeline_tests/inst/design_params_pass2_design.py) | Fixture for design_params_build_test.py's re-elaboration case: a make_stream_auto_pipeline seeded with start_latency=START under a clock goal its core cannot meet with START registers, so the pin-and-confirm loop re-imports the design (pass 2). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/design_params_build_test.py`. |
| [inst/design_params_sim_design.py](../../../src/tests/pypeline_tests/inst/design_params_sim_design.py) | Fixture for design_params_build_test.py: native simulation sees -D values (STEP declared with param(), TAG read as an injected global). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/design_params_build_test.py`. |
| [inst/duplicate_collapse_naming_design.py](../../../src/tests/pypeline_tests/inst/duplicate_collapse_naming_design.py) | ONE bit-select (d[33]) read twice at two DIFFERENT source lines with the SAME driver wire (d). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/duplicate_collapse_naming_test.py`. |
| [inst/factory_api_design.py](../../../src/tests/pypeline_tests/inst/factory_api_design.py) | Factory-object attributes in hardware ports and direct submodule calls. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/factory_api_test.py`. |
| [inst/factory_api_shadow_design.py](../../../src/tests/pypeline_tests/inst/factory_api_shadow_design.py) | A hardware input shadows a Python operation bundle with the same name. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/factory_api_test.py`. |
| [inst/feedback_vars_order_design.py](../../../src/tests/pypeline_tests/inst/feedback_vars_order_design.py) | Five Feedback wires, declared out of alphabetical order: the emitted feedback_vars_t record must list its fields in declaration order, not sorted and not in the hash-seeded iteration order of a set of names. Built under two PYTHONHASHSEEDs by generated_naming_build_test.py. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/generated_naming_build_test.py`. |
| [inst/fixed_auto_pipeline_extra_cuts_design.py](../../../src/tests/pypeline_tests/inst/fixed_auto_pipeline_extra_cuts_design.py) | Known issue fixture for fixed_auto_pipeline_extra_cuts_test.py. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/fixed_auto_pipeline_extra_cuts_test.py`. |
| [inst/float_format_cast_design.c](../../../src/tests/pypeline_tests/inst/float_format_cast_design.c) | C float-to-half-format overflow/underflow and inline-logic fixture. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/float_format_cast_test.py`. |
| [inst/global_fifo_sim_sub_design.py](../../../src/tests/pypeline_tests/inst/global_fifo_sim_sub_design.py) | Fixture for global_fifo_sim_test.py: a global FIFO declared in an imported module. Its producer is here; the consumer is in the importing design, which reaches the read end as `global_fifo_sim_sub_design.e.rd`. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/global_fifo_sim_test.py`. |
| [inst/global_inst_sim_sub_design.py](../../../src/tests/pypeline_tests/inst/global_inst_sim_sub_design.py) | Fixture for global_inst_sim_test.py: a global instance declared in an imported module. Its driver is here; the importing design reads it as `global_inst_sim_sub_design.acc.out`. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/global_inst_sim_test.py`. |
| [inst/global_wire_pipeline_instance_design.py](../../../src/tests/pypeline_tests/inst/global_wire_pipeline_instance_design.py) | Per-instance timing of global wires inside pipelined code, checked in the generated hardware (cocotb/GHDL) by global_wire_pipeline_instance_test.py. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/global_wire_pipeline_instance_test.py`. |
| [inst/global_wire_pipeline_refusal_design.py](../../../src/tests/pypeline_tests/inst/global_wire_pipeline_refusal_design.py) | Global wire uses inside pipelined code that native sim refuses (pypeline.SimPipelineModelError), checked by global_wire_pipeline_instance_test.py. -D GWP_REFUSAL_CASE selects one: | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/global_wire_pipeline_instance_design.py`, `inst/global_wire_pipeline_instance_test.py`. |
| [inst/hooks_design.py](../../../src/tests/pypeline_tests/inst/hooks_design.py) | @initial/@final hooks design, shared by hooks_test.py (native sim, run in-process) and hooks_order_test.py (pypelinec subprocesses: native, pipelined native, cocotb+GHDL). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/hooks_order_test.py`, `inst/hooks_test.py`. |
| [inst/isolated_top_name_design.py](../../../src/tests/pypeline_tests/inst/isolated_top_name_design.py) | Small hardware body for the isolated-wrapper naming reproducer. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/isolated_top_name_test.py`. |
| [inst/latency_constant_entity_reuse_design.py](../../../src/tests/pypeline_tests/inst/latency_constant_entity_reuse_design.py) | Fixture for latency_constant_entity_reuse_test.py: a top-level function whose body folds a module-level value read from an AUTO_PIPELINE's .latency. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/latency_constant_entity_reuse_test.py`. |
| [inst/latency_memory_constraints_design.py](../../../src/tests/pypeline_tests/inst/latency_memory_constraints_design.py) | In-process latency-memory bounds fixture; MEMORY_CAP=0 leaves the tag uncapped. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/latency_memory_unit_test.py`. |
| [inst/latency_memory_stale_design.py](../../../src/tests/pypeline_tests/inst/latency_memory_stale_design.py) | Build fixture for latency_memory_build_test.py: one named stream AUTO_PIPELINE ("core") whose function a design parameter swaps for a much lighter one, so a latency remembered for the heavy function is stale for the light one under the same tag key. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/latency_memory_build_test.py`. |
| [inst/leaf_1ll_cap_design.py](../../../src/tests/pypeline_tests/inst/leaf_1ll_cap_design.py) | Synthetic stand-in for the real ~24k-gate gate-level radix-2 divider (outside this repo): a short serial chain of nothing but SPLIT_KIND_1LL leaves (AND/OR/XOR/MUX), no SPLIT_KIND_BITS leaf anywhere - the shape where the old false-interior split model was most misleading. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/area_estimate_build_report_test.py`, `inst/leaf_1ll_cap_test.py`. |
| [inst/mcp_dsp_packing_design.py](../../../src/tests/pypeline_tests/inst/mcp_dsp_packing_design.py) | Variable-input DSP chain shared by fixed/auto MCPs and an AUTO_PIPELINE call. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/mcp_dsp_packing_test.py`. |
| [inst/multi_clock_design.py](../../../src/tests/pypeline_tests/inst/multi_clock_design.py) | Fixture: a design on two clocks, in the shape of the guide's Part IV example, built by multi_clock_ghdl_test.py and the multi_clock synthesis tests. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/multi_clock_ghdl_test.py`, `inst/multi_clock_open_tools_test.py`, `inst/multi_clock_synth_design.py`. |
| [inst/multi_clock_fifo_timing_design.py](../../../src/tests/pypeline_tests/inst/multi_clock_fifo_timing_design.py) | Fixture: an async global FIFO whose read clock carries nothing else, for multi_clock_open_tools_test.py. mon_sink, on mon_clk (MON_MHZ, a -D parameter), pops the FIFO and drives its output straight to pins, so the only registers on that clock are the FIFO's own (paths to pins are not timed): at an unreachable goal its worst path is inside the FIFO, which the sweep must report as the FIFO's, without adding stages anywhere. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/multi_clock_open_tools_test.py`. |
| [inst/multi_clock_synth_design.py](../../../src/tests/pypeline_tests/inst/multi_clock_synth_design.py) | Fixture: a design on two clocks for the multi_clock synthesis tests (multi_clock_open_tools_test.py, multi_clock_vivado_test.py). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/multi_clock_open_tools_test.py`, `inst/multi_clock_vivado_test.py`. |
| [inst/mux_fanout_planning_design.py](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_design.py) | Minimal fixture for mux_fanout_planning_test.py's DROP_NON_DEEPENING_PLACEMENTS coverage: two independent (parallel) adders feeding a third (serial) adder, the smallest shape that reproduces the real bug's topology -- a candidate register on one parallel branch can be "free" (adds no pipeline stage) once the OTHER parallel branch already bounds the shared downstream consumer's readiness, exactly the mux select-fanout cliff's "MUX_uint5_t_if_eff_amt registered on top of an already-registered MUX_uint64_t_if_w… | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/mux_fanout_planning_test.py`. |
| [inst/no_outputs_design.py](../../../src/tests/pypeline_tests/inst/no_outputs_design.py) | A single stateful @MAIN with NO top-level outputs: synthesis optimizes the whole netlist away. Built by pyrtl_no_timing_paths_build_report_test.py, which requires the pipelined build to FAIL with a clear "no timing paths" error -- measuring an Fmax of a circuit with no paths must never pass silently. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/pyrtl_no_timing_paths_build_report_test.py`. |
| [inst/no_syn_tool_fallback_design.py](../../../src/tests/pypeline_tests/inst/no_syn_tool_fallback_design.py) | Build fixture for src_module_import_test.py's no-synthesis-tool fallback check: a start_latency=1 AUTO_PIPELINE call site whose .latency the design reads (and prints) at import, and no fixed latency= call site. A synthesizing build's first parse serves 1; with no tool for the part the build continues as --comb --no_synth, so the pypelinec driver must re-elaborate and the read becomes 0. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/src_module_import_test.py`. |
| [inst/numpy_factory_arg_identity_design.py](../../../src/tests/pypeline_tests/inst/numpy_factory_arg_identity_design.py) | Two factory specializations whose only difference is the middle of a 2000-element numpy array argument. They are different hardware: lookup_a adds 1000, lookup_b adds 7. See numpy_factory_arg_identity_test.py. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/numpy_factory_arg_identity_test.py`. |
| [inst/pipeline_latency_import_design.py](../../../src/tests/pypeline_tests/inst/pipeline_latency_import_design.py) | Imported fixed pipeline fixture; deliberately has no MAIN registration. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/pipeline_latency_test.py`. |
| [inst/scoped_operator_shared_callee_design.py](../../../src/tests/pypeline_tests/inst/scoped_operator_shared_callee_design.py) | Known issue: a callee shared by a scoped caller and an unscoped caller gets one entity, built under whichever caller is elaborated first. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/scoped_operator_registration_test.py`. |
| [inst/scoped_operator_top_level_design.py](../../../src/tests/pypeline_tests/inst/scoped_operator_top_level_design.py) | Known issue: register_*(..., scope=f) on a plain top-level @hw_func is ignored in hardware. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/scoped_operator_registration_test.py`. |
| [inst/scripted_sweep_backend.py](../../../src/tests/pypeline_tests/inst/scripted_sweep_backend.py) | Small decision-test backend: supplied paths keyed by realized implementation. | Keep shared scripted backend: cheap real decision-loop coverage reduces reliance on repeated real-tool builds. References: `inst/sweep_cross_main_test.py`, `inst/sweep_evidence_test.py`, `inst/sweep_refinement_recovery_test.py`. |
| [inst/sim_finish_debug_print_race_design.py](../../../src/tests/pypeline_tests/inst/sim_finish_debug_print_race_design.py) | Fixture for sim_finish_debug_print_race_test.py: breaks the "no debug print on the sim_finish() cycle" rule on purpose. See that file's docstring. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/sim_finish_debug_print_race_test.py`. |
| [inst/soft_mult_karatsuba_leaves_design.py](../../../src/tests/pypeline_tests/inst/soft_mult_karatsuba_leaves_design.py) | Fixture for soft_mult_karatsuba_leaves_test.py: Karatsuba leaf policies under different INFERRED_MULT registrations. -D CASE=<name> selects the registrations, since they are process-global, and the width of plain_mult_main's `*` (the only MAIN that reaches the registry): | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/soft_mult_karatsuba_leaves_test.py`. |
| [inst/split_model_design.py](../../../src/tests/pypeline_tests/inst/split_model_design.py) | A single wide subtract - exercises RAW_VHDL.GET_BITS_PER_STAGE_DICT's equal-width split (see docs/AUTO_PIPELINE_DESIGN.md) against a real multi-cut sky130 build. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/area_estimate_build_report_test.py`, `inst/split_model_build_report_test.py`. |
| [inst/stream_auto_pipeline_grow_design.py](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_grow_design.py) | Build fixture for auto_pipeline_constraints_test.py: a make_stream_auto_pipeline whose core AUTO_PIPELINE is seeded with start_latency=1 under a clock goal the core can't meet with 1 register. start_latency is only a starting guess: the sweep must grow the core past 1, and because the FIFO was sized from the served 1, the pin-and-confirm pass must re-elaborate with the built count. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_pipeline_constraints_test.py`. |
| [inst/stream_auto_pipeline_seeded_design.py](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_seeded_design.py) | Build fixture for auto_pipeline_constraints_test.py: a make_stream_auto_pipeline whose core AUTO_PIPELINE is seeded with start_latency=1 under an easy clock goal. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/auto_pipeline_constraints_test.py`. |
| [inst/sweep_floor_detect_design.py](../../../src/tests/pypeline_tests/inst/sweep_floor_detect_design.py) | Design for sweep_floor_detect_test.py (not registered as a test itself): a stateful submodule with a big internal comb path (division inside a Reg func) makes the clock goal unreachable - the sweep must predict the fmax floor up front, blame this submodule, and stop quickly instead of blindly adding more and more cuts. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/sweep_floor_detect_test.py`, `inst/sweep_plateau_unit_test.py`. |
| [inst/sweep_planless_design.py](../../../src/tests/pypeline_tests/inst/sweep_planless_design.py) | Design for sweep_planless_test.py (not registered as a test itself): the MAIN is a stateful (Reg) function with no AUTO_PIPELINE regions - nothing auto-pipelining can help - but unlike sweep_unpipelinable_design.py the clock goal is easily met as written. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/sweep_planless_test.py`. |
| [inst/sweep_unpipelinable_design.py](../../../src/tests/pypeline_tests/inst/sweep_unpipelinable_design.py) | Design for sweep_unpipelinable_test.py (not registered as a test itself): the MAIN is itself a stateful (Reg) function with no AUTO_PIPELINE regions and a slow divider inside - there is nothing auto-pipelining can help. The sweep must say so plainly (at planning time and when the timing report fails) instead of silently failing or blindly iterating. Path for pypeline import | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/sweep_planless_design.py`, `inst/sweep_unpipelinable_test.py`. |
| [inst/synthesis_scope_design.py](../../../src/tests/pypeline_tests/inst/synthesis_scope_design.py) | Pipeline geometry, blocked bank helpers, opaque text, MCP evidence and a stand-in for a scheduled AUTO_FSM (marked by the test after parsing). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/synthesis_scope_test.py`. |
| [inst/user_names_design.py](../../../src/tests/pypeline_tests/inst/user_names_design.py) | Every form of name=: a factory-produced @hw_func, @struct and @enum, two named AUTO_PIPELINE groups over one function, and named stream AUTO_PIPELINE and AUTO_MULTI_CYCLE tags. Used by double_parse_file_test (names are stable across re-parses) and native-simulated by its own __main__ check. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/double_parse_file_test.py`. |
| [inst/var_ref_naming_design.py](../../../src/tests/pypeline_tests/inst/var_ref_naming_design.py) | TWO sequential runtime (non-unrolled) variable-index writes to the SAME array, where the second write's covering wire is the first write's own alias -- an alias whose ref_toks contains a Python AST node (the variable index expression). | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/double_parse_file_test.py`, `inst/var_ref_naming_test.py`. |
| [inst/zero_delay_helper_build_design.py](../../../src/tests/pypeline_tests/inst/zero_delay_helper_build_design.py) | Build reproducer for recursively zero-delay wiring-only helpers. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/zero_delay_helper_build_test.py`. |
| [known_issues_tests.py](../../../src/tests/pypeline_tests/known_issues_tests.py) | Reproducers for known, unfixed compiler bugs -- every Test here has expect_fail=True (its underlying command is expected to exit nonzero), so a passing run means the bug is still present (reported as XFAIL) and a CLEAN run means it got fixed without anyone updating this file (reported as XPASS, which run_all.py treats as a FAILURE -- promote that test out of known_issues into whichever category now fits it). | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `inst/fixed_auto_pipeline_extra_cuts_test.py`, `inst/global_wire_unshared_readback_design.py`, `inst/imported_auto_pipeline_attribution_test.py` (plus 17 others). |
| [multi_clock_tests.py](../../../src/tests/pypeline_tests/multi_clock_tests.py) | Multi-clock build tests: wrapper scripts that build a design on two or more clocks and check what came out -- its crossing report, its top level, its constraints and timing results, its behavior in GHDL. sky130 and PyRTL cannot time a design with more than one clock (their constraint writers stop on one), so these build with open_tools (ECP5 nextpnr), Vivado, or no synthesis tool at all. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `inst/registration_audit_test.py`, `run_all.py`. |
| [native_sim_tests.py](../../../src/tests/pypeline_tests/native_sim_tests.py) | Native (Python-only) simulation tests -- no VHDL/GHDL involved. See native_vs_vhdl_sim_tests.py for the self-checking designs that ALSO run through real cocotb+GHDL, with the two sims' sim_print(debug=True) output diffed cycle by cycle. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `inst/factory_main_pipeline_latency_test.py`, `inst/factory_main_sim_test.py`, `inst/global_fifo_sim_test.py` (plus 14 others). |
| [native_vs_vhdl_sim_tests.py](../../../src/tests/pypeline_tests/native_vs_vhdl_sim_tests.py) | Cycle-accurate native-vs-VHDL simulation tests, via pypeline_sim_debug.py. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `inst/global_wire_array_split_test.py`, `inst/global_wire_cond_driver_test.py`, `inst/global_wire_dynamic_index_write_test.py` (plus 36 others). |
| [op_qor_bench.py](../../../src/tests/pypeline_tests/op_qor_bench.py) | QoR bench: measure per-stage (sliced) delay of every candidate implementation of PLUS/MINUS/INFERRED_MULT/GT/GTE/LT/LTE/EQ/NEQ. | Keep opt-in benchmark; expose a bounded smoke subset only when it has a distinct contract. Record exact HDL/tool/cache identity. |
| [op_qor_results_pyrtl.csv](../../../src/tests/pypeline_tests/op_qor_results_pyrtl.csv) | Recorded operator stage-delay/QoR samples for PyRTL; historical measurement data. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [op_qor_results_vivado.csv](../../../src/tests/pypeline_tests/op_qor_results_vivado.csv) | Recorded operator stage-delay/QoR samples for Vivado; historical measurement data. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [qor/auto_pipeline_ram_ecp5.json](../../../src/tests/pypeline_tests/qor/auto_pipeline_ram_ecp5.json) | Recorded ECP5 RAM latency/frequency/resource frontier and tool versions. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [qor/auto_pipeline_ram_ecp5_regression.json](../../../src/tests/pypeline_tests/qor/auto_pipeline_ram_ecp5_regression.json) | Recorded bounded 64K RAM split-plan improvement baseline. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [qor/divider/arithmetic.py](../../../src/tests/pypeline_tests/qor/divider/arithmetic.py) | Arithmetic radix-2 Divider QoR fixture. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `divider_continuity_bench.py`, `divider_qor_bench.py`, `divider_struct_mux_bench.py`, `inst/auto_comb_area_opt_test.py` (plus 31 others). |
| [qor/divider/arithmetic_struct_mux.py](../../../src/tests/pypeline_tests/qor/divider/arithmetic_struct_mux.py) | Arithmetic Divider fixture whose 32-bit MUX banks use a user struct. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `divider_struct_mux_bench.py`. |
| [qor/divider/divider_qor_cocotb.py](../../../src/tests/pypeline_tests/qor/divider/divider_qor_cocotb.py) | Cycle-accurate checker for the exact final Divider VHDL artifact. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `divider_qor_bench.py`. |
| [qor/divider/gate.py](../../../src/tests/pypeline_tests/qor/divider/gate.py) | Gate-level radix-2 Divider QoR fixture. | Keep as a fixture/helper alongside its owning feature; no standalone registration needed. References: `inst/divider_qor_bench_unit_test.py`. |
| [qor/divider_gate_clean_baseline_critical_paths.json](../../../src/tests/pypeline_tests/qor/divider_gate_clean_baseline_critical_paths.json) | Preserve the clean current-recipe baseline's stage-specific critical-path evidence and classify logic outside the 32 radix steps. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/device_models_sta_test.py`. |
| [qor/divider_qor_acceptance.json](../../../src/tests/pypeline_tests/qor/divider_qor_acceptance.json) | Versioned divider exact-final-VHDL correctness, fmax and maximum-slice acceptance evidence. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/device_models_sta_test.py`. |
| [qor/latchup_area_match_matrix.json](../../../src/tests/pypeline_tests/qor/latchup_area_match_matrix.json) | Calibrate and validate the sky130 area model (DEVICE_MODELS.MEASURE_NETLIST_AREA / LOAD_CELL_AREAS, SYN.ESTIMATE_DESIGN_AREA) against latchup.app's own reported total cell area for the same radix-2 divider used to select the delay model's production recipe. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/auto_fsm_real_area_compare_test.py`, `inst/device_models_sta_test.py`. |
| [qor/latchup_early_flatten_match_matrix.json](../../../src/tests/pypeline_tests/qor/latchup_early_flatten_match_matrix.json) | Select the production sky130 synthesis recipe by reproducing latchup.app's own post-early-flatten mapped netlists and reported fmax, on four designs whose generated VHDL was hash-verified identical to theirs. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/device_models_sta_test.py`. |
| [qor/multiplier/inferred_pipeline_unit.py](../../../src/tests/pypeline_tests/qor/multiplier/inferred_pipeline_unit.py) | Manual Artix-7 probe for the AUTO_PIPELINE lowering used by FSM units. | Keep manual/integration fixture; preserve canonical arithmetic and parameters. Do not register every manual QoR point in the default suite. |
| [qor/multiplier/karatsuba_inferred_leaves.py](../../../src/tests/pypeline_tests/qor/multiplier/karatsuba_inferred_leaves.py) | Manual Vivado area probe: native `*` vs the Karatsuba hybrid with inferred leaves (operators/soft_mult.py make_mult_karatsuba_inferred_leaves), on the WireGuard part. Not registered in run_all; results and the run recipe are in docs/SYN_DESIGN.md#karatsuba-with-inferred-leaves. | Keep manual/integration fixture; preserve canonical arithmetic and parameters. Do not register every manual QoR point in the default suite. References: `inst/auto_fsm_unit_test.py`, `inst/self_check_mult_karatsuba_pipelined_test.py`, `inst/self_check_mult_karatsuba_test.py`, `inst/soft_mult_karatsuba_leaves_design.py` (plus 3 others). |
| [qor/pdw_self_timed_vivado_200t.json](../../../src/tests/pypeline_tests/qor/pdw_self_timed_vivado_200t.json) | Recorded self-timed PDW out-of-context synthesis evidence on Artix-7. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [qor/pdw_vivado_200t.json](../../../src/tests/pypeline_tests/qor/pdw_vivado_200t.json) | Recorded earlier PDW out-of-context resource/timing evidence on Artix-7. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [qor/poly1305/arithmetic.py](../../../src/tests/pypeline_tests/qor/poly1305/arithmetic.py) | Unchanged canonical Poly1305 arithmetic for manual compiler QoR comparisons. | Keep manual/integration fixture; preserve canonical arithmetic and parameters. Do not register every manual QoR point in the default suite. References: `divider_continuity_bench.py`, `divider_qor_bench.py`, `divider_struct_mux_bench.py`, `inst/auto_comb_area_opt_test.py` (plus 30 others). |
| [qor/poly1305/auto_fsm.py](../../../src/tests/pypeline_tests/qor/poly1305/auto_fsm.py) | Manual Vivado comparison of unchanged Poly1305 services. | Keep manual/integration fixture; preserve canonical arithmetic and parameters. Do not register every manual QoR point in the default suite. References: `auto_fsm_div_share_test.py`, `auto_fsm_resources_test.py`, `auto_fsm_tighten_test.py`, `build_report_tests.py` (plus 46 others). |
| [qor/poly1305/kernels.py](../../../src/tests/pypeline_tests/qor/poly1305/kernels.py) | Unchanged shared Poly1305 kernels, with standalone factory scaffolding. | Keep manual/integration fixture; preserve canonical arithmetic and parameters. Do not register every manual QoR point in the default suite. References: `inst/auto_fsm_attribution_test.py`, `inst/auto_fsm_cache_test.py`, `inst/auto_fsm_latency_sized_design.py`, `qor/poly1305/auto_fsm.py` (plus 1 others). |
| [qor/poly1305/self_check.py](../../../src/tests/pypeline_tests/qor/poly1305/self_check.py) | Independent Python Poly1305 vectors checked against the generated FSM. | Keep manual/integration fixture; preserve canonical arithmetic and parameters. Do not register every manual QoR point in the default suite. References: `inst/auto_fsm_unit_test.py`, `inst/auto_pipeline_fixed_latency_sim_test.py`, `inst/cocotb_verdict_test.py`, `inst/nested_truncate_test.py` (plus 33 others). |
| [qor/poly1305_auto_fsm_vivado_200t.json](../../../src/tests/pypeline_tests/qor/poly1305_auto_fsm_vivado_200t.json) | Recorded manual full-capacity Poly1305 AUTO_FSM Vivado area/timing comparison. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [qor/synthesis_recipe_forced32_matrix.json](../../../src/tests/pypeline_tests/qor/synthesis_recipe_forced32_matrix.json) | Byte-frozen full gate-Divider synthesis-recipe selection at the generic hand-equivalent physical control placement | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/device_models_sta_test.py`. |
| [qor/synthesis_recipe_pre_divzero_matrix.json](../../../src/tests/pypeline_tests/qor/synthesis_recipe_pre_divzero_matrix.json) | Reproduce the gate Divider's pre-step divisor-nonzero reduction feeding a 32-bit select, and determine whether hierarchy before liberty mapping creates the observed high-fanout timing floor. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/device_models_sta_test.py`. |
| [qor/synthesis_recipe_pre_divzero_wrapper.vhd](../../../src/tests/pypeline_tests/qor/synthesis_recipe_pre_divzero_wrapper.vhd) | Frozen pre-divide-zero wrapper used by the synthesis-recipe experiment. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. References: `inst/device_models_sta_test.py`. |
| [qor/synthesis_recipe_step_gates_matrix.json](../../../src/tests/pypeline_tests/qor/synthesis_recipe_step_gates_matrix.json) | Screen the four fixed internal sky130 recipes on byte-identical unchanged gate Divider step VHDL before spending hours on full Divider mappings. | Retain evidence/provenance; label historical recipe/tool versions. Not a substitute for a current executable acceptance check. |
| [run_all.py](../../../src/tests/pypeline_tests/run_all.py) | Run all pypeline tests in parallel. See docs/pypeline_TESTS.md for what belongs in each category. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `build_report_tests.py`, `common.py`, `divider_continuity_bench.py`, `divider_qor_bench.py` (plus 13 others). |
| [sweep_float32_tool_compare.py](../../../src/tests/pypeline_tests/sweep_float32_tool_compare.py) | Opt-in cross-SYN_TOOL comparison for the float32 adder sweep. | Keep opt-in benchmark; expose a bounded smoke subset only when it has a distinct contract. Record exact HDL/tool/cache identity. References: `synth_tests.py`. |
| [synth_tests.py](../../../src/tests/pypeline_tests/synth_tests.py) | pypelinec elaboration + auto-pipelining + synthesis tests (no --no_synth). | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `build_report_tests.py`, `common.py`, `elab_tests.py`, `inst/factory_closure_naming_test.py` (plus 22 others). |
| [unit_tests.py](../../../src/tests/pypeline_tests/unit_tests.py) | Pure compiler-helper unit tests -- no design build (PARSE_FILE may be called incidentally, but that's not what's under test). See elab_introspect_tests.py for tests whose whole point IS parsing a design and inspecting the resulting parser_state/FuncLogicLookupTable/raised errors. | Keep harness/registration infrastructure; consolidate selection metadata here and audit actual commands/case entrypoints. References: `common.py`, `elab_introspect_tests.py`, `elab_tests.py`, `inst/factory_main_api_unit_test.py` (plus 3 others). |

## Test-case declaration index

Each row identifies the exact source declaration and its intent (docstring when available, otherwise a readable form of its name). Assessment is inherited from the registration/file verdict above. This index is **not a claim that all declarations execute**: compilation imports designs without running `__main__`; custom runners may use manual call lists. Module `check()` assertions and HDL `sim_assert`s are described by the main inventory, not counted as extra registered tests.

Five named test helpers have no direct Python registration: `keyword_call_test.test_keyword_calls_sim`, `sweep_comb_test.test_sweep_comb_sim`, `sweep_fsm_auto_pipeline_test.test_sweep_fsm_auto_pipeline_sim`, `sweep_stateful_boundary_test.test_sweep_boundary_sim`, and `sweep_two_mains_test.test_sweep_two_mains_sim`. Their only observed calls are their own `__main__` blocks, which current compilation registrations do not execute. Decide whether to activate their distinct oracles or label them manual; the four sweep helpers only print results today.

### inst/added_latency_context_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:added_latency_context_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_per_main_targets_and_all_boundary_strategies](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L110) | Per main targets and all boundary strategies. |
| [test_new_concrete_lock_invalidates_the_old_failing_cut_bound](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L159) | New concrete lock invalidates the old failing cut bound. |
| [test_boundary_policy_change_invalidates_the_old_failing_cut_bound](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L169) | Boundary policy change invalidates the old failing cut bound. |
| [test_guards_reject_before_mutating](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L177) | Guards reject before mutating. |
| [test_prewrite_safety_net_and_bookkeeping](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L196) | Prewrite safety net and bookkeeping. |
| [test_seeding_exact_and_renamed_paths](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L220) | Seeding exact and renamed paths. |
| [test_holder_rebuilt_for_a_new_count_reuses_its_datapath_evidence](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L266) | Count-only rebuilds reuse endpoint evidence, never a geometry scalar. |
| [test_jobs_cap_covers_mcp_characterization](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L318) | -j N bounds every synthesis pool. Pre-pipelining characterization of automatic MCP evidence and the AUTO_PIPELINE side shares one pool: -j 1 runs one backend process at a time, -j 3 overlaps them (so the probe can see concurrency). Every compiler ThreadPool is sized by GET_NUM_PROCESSES, and an invalid count stops pypelinec before it parses or creates anything. |
| [test_gap_planning_and_coarse_slicing](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L410) | Gap planning and coarse slicing. |
| [test_only_stateful_callers_and_self_timed_do_not_decouple](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L436) | Only stateful callers and self timed do not decouple. |
| [test_mcp_endpoint_attributes_and_cache_identity](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L466) | Mcp endpoint attributes and cache identity. |
| [test_mcp_constraints_and_lost_coverage_diagnostics](../../../src/tests/pypeline_tests/inst/added_latency_context_test.py#L506) | Mcp constraints and lost coverage diagnostics. |

### inst/area_model_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:area_model_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_load_cell_areas_spot_values_and_full_coverage](../../../src/tests/pypeline_tests/inst/area_model_test.py#L109) | Load cell areas spot values and full coverage. |
| [test_get_sequential_cell_area_matches_dfxtp](../../../src/tests/pypeline_tests/inst/area_model_test.py#L118) | Get sequential cell area matches dfxtp. |
| [test_measure_netlist_area_hand_computable_split](../../../src/tests/pypeline_tests/inst/area_model_test.py#L124) | Measure netlist area hand computable split. |
| [test_measure_netlist_area_reports_unpriced_cells_without_crashing](../../../src/tests/pypeline_tests/inst/area_model_test.py#L157) | Measure netlist area reports unpriced cells without crashing. |
| [test_path_report_parses_area_lines](../../../src/tests/pypeline_tests/inst/area_model_test.py#L175) | Path report parses area lines. |
| [test_path_report_area_fields_default_none_when_absent](../../../src/tests/pypeline_tests/inst/area_model_test.py#L195) | Path report area fields default none when absent. |
| [test_area_cache_dir_identity](../../../src/tests/pypeline_tests/inst/area_model_test.py#L202) | Area cache dir identity. |
| [test_area_cache_dir_honours_env_override](../../../src/tests/pypeline_tests/inst/area_model_test.py#L239) | Area cache dir honours env override. |
| [test_leaf_area_cache_round_trip_and_unit_mismatch](../../../src/tests/pypeline_tests/inst/area_model_test.py#L256) | Leaf area cache round trip and unit mismatch. |
| [test_get_estimated_combinational_area_sums_across_hierarchy](../../../src/tests/pypeline_tests/inst/area_model_test.py#L289) | Get estimated combinational area sums across hierarchy. |
| [test_get_estimated_combinational_area_reports_missing_leaf](../../../src/tests/pypeline_tests/inst/area_model_test.py#L328) | Get estimated combinational area reports missing leaf. |
| [test_get_estimated_combinational_area_zero_delay_leaf_not_counted_missing](../../../src/tests/pypeline_tests/inst/area_model_test.py#L354) | Get estimated combinational area zero delay leaf not counted missing. |
| [test_committed_cache_excludes_sta_harness_registers](../../../src/tests/pypeline_tests/inst/area_model_test.py#L386) | Regression guard for AREA_MODEL_VERSION 1 -> 2 (SYN.py's ADD_PATH_DELAY_TO_LOOKUP now caches combinational_cell_area, not total_cell_area): a 1-bit AND is where a harness regression would be loudest, since three 1-bit dont_touch registers on the isolated-leaf STA harness (VHDL.WRITE_LOGIC_TOP: two input ports, one output port) would cost 3*48.84 = 146.52 um2, dwarfing the and2_1 gate itself (13.6752 um2) if ever included again -- the v1-cached value for this exact leaf was 160.1952 um2, 11.7x the real gate. |
| [test_um2_per_abstract_area_unit_matches_committed_cache](../../../src/tests/pypeline_tests/inst/area_model_test.py#L415) | Refits AUTO.UM2_PER_ABSTRACT_AREA_UNIT the same way it was measured: least-squares area-vs-width, through the origin, jointly across every BIN_OP_PLUS_uintA_t_uintB_t and BIN_OP_MINUS_uintA_t_uintB_t entry in the committed cache/area, width = max(A, B) -- both operators cost AREA_PER_BIT_ADD per _leaf_area, so one fit covers both, and this repo's own qor/multiplier and qor/divider designs between them exercise enough distinct widths for a meaningful slope (PLUS from the multiplier's soft-adder tree, MINUS… |

### inst/array_2d_order_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:array_2d_order_test`, `elab:array_2d_order_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_shape_matches_declaration_order](../../../src/tests/pypeline_tests/inst/array_2d_order_test.py#L28) | Shape matches declaration order. |
| [test_row_is_second_bracket_length](../../../src/tests/pypeline_tests/inst/array_2d_order_test.py#L40) | Row is second bracket length. |
| [test_in_range_index_succeeds_and_reversed_index_raises](../../../src/tests/pypeline_tests/inst/array_2d_order_test.py#L49) | In range index succeeds and reversed index raises. |

### inst/async_fifo_elab_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:async_fifo_elab_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_realization](../../../src/tests/pypeline_tests/inst/async_fifo_elab_test.py#L81) | Realization. |
| [test_builtin_impl_and_depth](../../../src/tests/pypeline_tests/inst/async_fifo_elab_test.py#L104) | Builtin impl and depth. |
| [test_kind_errors](../../../src/tests/pypeline_tests/inst/async_fifo_elab_test.py#L114) | Kind errors. |
| [test_report_rows](../../../src/tests/pypeline_tests/inst/async_fifo_elab_test.py#L133) | Report rows. |

### inst/async_fifo_path_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:async_fifo_path_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_path_attribution](../../../src/tests/pypeline_tests/inst/async_fifo_path_unit_test.py#L77) | Path attribution. |
| [test_mains_and_slicing](../../../src/tests/pypeline_tests/inst/async_fifo_path_unit_test.py#L121) | Mains and slicing. |
| [test_xpm_choice](../../../src/tests/pypeline_tests/inst/async_fifo_path_unit_test.py#L140) | Xpm choice. |

### inst/auto_comb_area_opt_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:auto_comb_area_opt_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_native](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L27) | Native. |
| [test_native_without_optimizer](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L41) | Native without optimizer. |
| [test_reinsert_after_operand_rewrite_preserves_both_expressions](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L57) | Reinsert after operand rewrite preserves both expressions. |
| [test_elaboration](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L93) | Elaboration. |
| [test_arithmetic_and_casts](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L147) | Arithmetic and casts. |
| [test_scoped_operators_and_bounded_graph](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L243) | Scoped operators and bounded graph. |
| [test_shared_fsm_operand_keys_stay_dags](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L290) | Shared fsm operand keys stay dags. |
| [test_default_fsm_uses_shared_choices](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L325) | Default fsm uses shared choices. |
| [test_purity_and_repeat_parse](../../../src/tests/pypeline_tests/inst/auto_comb_area_opt_test.py#L361) | Purity and repeat parse. |

### inst/auto_comb_delay_opt_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:auto_comb_delay_opt_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_native](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py#L30) | Native. |
| [test_native_without_optimizer](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py#L39) | Native without optimizer. |
| [test_timing_dependencies](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py#L55) | Timing dependencies. |
| [test_cases](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py#L82) | Cases. |
| [test_nested_and_pure](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py#L124) | Nested and pure. |
| [test_elaboration](../../../src/tests/pypeline_tests/inst/auto_comb_delay_opt_test.py#L150) | Elaboration. |

### inst/auto_fsm_attribution_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:auto_fsm_attribution_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_vivado_ordered_arcs_keep_carry_routing_and_endpoint_times](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L59) | Vivado ordered arcs keep carry routing and endpoint times. |
| [test_vivado_coordinates_follow_the_fsm_instance_on_cells_only](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L103) | Vivado coordinates follow the fsm instance on cells only. |
| [test_unit_stage_measurements_follow_the_elaborated_fsm_instance](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L149) | Unit stage measurements follow the elaborated fsm instance. |
| [test_placements_measured_over_budget_are_rescheduled_before_building](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L208) | Placements measured over budget are rescheduled before building. |
| [test_endpoint_only_sky130_path_and_unattributed_evidence](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L243) | Endpoint only sky130 path and unattributed evidence. |
| [test_flattened_sky130_endpoints_use_only_verified_netlist_aliases](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L264) | Flattened sky130 endpoints use only verified netlist aliases. |
| [test_select_arrival_is_parallel_with_data_and_mux_is_serial](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L311) | Select arrival is parallel with data and mux is serial. |
| [test_no_chain_repair_waits_and_identical_trials_terminate](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L328) | No chain repair waits and identical trials terminate. |
| [test_separation_cuts_only_the_first_late_entity_pair_in_every_lane](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L339) | Separation cuts only the first late entity pair in every lane. |
| [test_decode_proxies_are_keyed_only_by_encoding_and_widths](../../../src/tests/pypeline_tests/inst/auto_fsm_attribution_test.py#L378) | Decode proxies are keyed only by encoding and widths. |

### inst/auto_fsm_cache_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:auto_fsm_cache_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_schedule_cache_rejects_stale_source_target_and_version](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L56) | Schedule cache rejects stale source target and version. |
| [test_reparse_schedules_call_sites_new_to_the_build](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L152) | Reparse schedules call sites new to the build. |
| [test_reparse_still_refuses_a_rejected_schedule](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L197) | Reparse still refuses a rejected schedule. |
| [test_call_site_created_during_a_pass_is_scheduled_blamed_and_tightened](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L226) | Call site created during a pass is scheduled blamed and tightened. |
| [test_unit_characterization_counts_repeated_serial_operations](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L346) | Unit characterization counts repeated serial operations. |
| [test_sparse_unit_recipe_restores_implicit_zero_placements](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L385) | Sparse unit recipe restores implicit zero placements. |
| [test_model_only_updates_keep_hardware_identity](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L422) | Model only updates keep hardware identity. |
| [test_forced_schedule_is_applied_on_reelaboration](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L446) | Forced schedule is applied on reelaboration. |
| [test_malformed_carried_data_is_always_a_cache_miss](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L463) | Malformed carried data is always a cache miss. |
| [test_different_hash_seeds_emit_identical_source](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L495) | Different hash seeds emit identical source. |
| [test_corrected_unit_tries_its_pipeline_before_forced_descent](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L516) | Corrected unit tries its pipeline before forced descent. |
| [test_encoding_memo_does_not_reuse_a_different_select_arrival](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L536) | Encoding memo does not reuse a different select arrival. |
| [test_binding_search_reuses_clean_graph_without_sharing_mutable_results](../../../src/tests/pypeline_tests/inst/auto_fsm_cache_test.py#L563) | Binding search reuses clean graph without sharing mutable results. |

### inst/auto_fsm_prefix_tree_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:auto_fsm_prefix_tree_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_estimated_descent_is_measured_and_kept_whole](../../../src/tests/pypeline_tests/inst/auto_fsm_prefix_tree_test.py#L105) | Estimated descent is measured and kept whole. |
| [test_pipelined_helper_is_not_a_blocked_descent](../../../src/tests/pypeline_tests/inst/auto_fsm_prefix_tree_test.py#L228) | An over-budget helper kept whole as a pipelined unit is a choice whose stages fit; reporting it as a blocked descent misled a Poly1305 report. |
| [test_array_input_elements_render_as_indexes](../../../src/tests/pypeline_tests/inst/auto_fsm_prefix_tree_test.py#L249) | Array input elements render as indexes. |
| [test_scheduled_fsm_drives_a_stateless_main_clock_enable](../../../src/tests/pypeline_tests/inst/auto_fsm_prefix_tree_test.py#L263) | Scheduled fsm drives a stateless main clock enable. |

### inst/auto_fsm_transforms_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:auto_fsm_transforms_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_distinct_equalities_have_one_balanced_selection_with_default](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L83) | Distinct equalities have one balanced selection with default. |
| [test_priority_and_unproved_index_chains_are_retained](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L97) | Priority and unproved index chains are retained. |
| [test_real_field_read_chain_is_prepared_before_scheduling](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L105) | Real field read chain is prepared before scheduling. |
| [test_prepared_fusion_matches_the_cleaned_scheduling_graph](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L140) | Prepared fusion matches the cleaned scheduling graph. |
| [test_measurement_roots_are_trimmed_like_instantiated_logic](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L181) | A scheduled FSM later instantiates its generated candidates, and the design trims what it instantiates: an untrimmed measurement root gets different entity text under the same name, so it is synthesized twice. |
| [test_unsigned_adapters_preserve_original_result_width](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L218) | Unsigned adapters preserve original result width. |
| [test_signed_and_nonmodular_operator_merges_are_refused](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L264) | Signed and nonmodular operator merges are refused. |
| [test_search_merges_step_to_the_next_wider_unit](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L279) | Search merges step to the next wider unit. |
| [test_fusion_requires_recurring_closed_pairs](../../../src/tests/pypeline_tests/inst/auto_fsm_transforms_test.py#L305) | Fusion requires recurring closed pairs. |

### inst/auto_fsm_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:auto_fsm_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_cleanup_constant_casts](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L491) | Cleanup constant casts. |
| [test_cleanup_identity_preserves_narrowing](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L507) | Cleanup identity preserves narrowing. |
| [test_cleanup_refuses_custom_operator_identity](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L528) | Cleanup refuses custom operator identity. |
| [test_cleanup_cse_is_deterministic](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L540) | Cleanup cse is deterministic. |
| [test_cleanup_factoring_preserves_reconvergent_glue](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L553) | Cleanup factoring preserves reconvergent glue. |
| [test_pipelined_unit_launches_each_cycle](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L585) | Pipelined unit launches each cycle. |
| [test_pipelined_dependency_waits_for_completion](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L600) | Pipelined dependency waits for completion. |
| [test_late_pipeline_result_waits_for_the_next_state](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L615) | Late pipeline result waits for the next state. |
| [test_pipelined_initiation_interval_and_cap](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L630) | Pipelined initiation interval and cap. |
| [test_mixed_units_break_only_registered_ordering_edges](../../../src/tests/pypeline_tests/inst/auto_fsm_unit_test.py#L655) | Mixed units break only registered ordering edges. |

### inst/auto_fsm_var_index_read_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:auto_fsm_var_index_read_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_nested_variable_index_read_opens](../../../src/tests/pypeline_tests/inst/auto_fsm_var_index_read_test.py#L85) | Nested variable index read opens. |
| [test_direct_variable_index_read_schedules](../../../src/tests/pypeline_tests/inst/auto_fsm_var_index_read_test.py#L91) | Direct variable index read schedules. |

### inst/auto_multi_cycle_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:auto_multi_cycle_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_constructor_validation](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L49) | Constructor validation. |
| [test_latency_resolution](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L61) | Latency resolution. |
| [test_keys_and_cache](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L71) | Keys and cache. |
| [test_inline_construction_rejected](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L104) | Inline construction rejected. |
| [test_read_tracking](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L115) | Read tracking. |
| [test_identity_follows_count_and_reg_tag](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L133) | Identity follows count and reg tag. |
| [test_syn_counts_and_hash](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L165) | Syn counts and hash. |
| [test_report_matching_and_feedback](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L204) | Report matching and feedback. |
| [test_elaboration_and_cache_reparse](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L259) | Elaboration and cache reparse. |
| [test_endpoint_selection_on_elaborated_wrapper](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L295) | The real stream wrapper's launch/capture registers, and nothing else: its cycles_since_launch controller, look-alike names and a CE pin are neither constrained nor attributed to the group. Also checks the isolated seed's delay-to-cycles rounding against the same elaborated groups. |
| [test_unread_tag_fails_build_check](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L404) | Unread tag fails build check. |
| [test_named_tags](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L418) | Named tags. |
| [test_seeds_are_provisional](../../../src/tests/pypeline_tests/inst/auto_multi_cycle_unit_test.py#L462) | A starting count from the latency memory or a hints file is elaborated like start_latency=, but registered as a provisional seed whose floor is the source start_latency, so confirm-down may lower it. |

### inst/auto_pipeline_fixed_latency_sim_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:auto_pipeline_fixed_latency_sim_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_fixed_latency_delay_line](../../../src/tests/pypeline_tests/inst/auto_pipeline_fixed_latency_sim_test.py#L108) | Fixed latency delay line. |
| [test_named_fixed_latency_delay_line](../../../src/tests/pypeline_tests/inst/auto_pipeline_fixed_latency_sim_test.py#L114) | Named fixed latency delay line. |
| [test_zero_fixed_and_unfixed_are_passthrough](../../../src/tests/pypeline_tests/inst/auto_pipeline_fixed_latency_sim_test.py#L120) | Zero fixed and unfixed are passthrough. |
| [test_nested_call_sites_keep_separate_delay_lines](../../../src/tests/pypeline_tests/inst/auto_pipeline_fixed_latency_sim_test.py#L127) | Nested call sites keep separate delay lines. |
| [test_reset_clears_delay_line](../../../src/tests/pypeline_tests/inst/auto_pipeline_fixed_latency_sim_test.py#L133) | Reset clears delay line. |

### inst/auto_pipeline_harvest_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:auto_pipeline_harvest_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_harvest_agreeing_instances](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L93) | Harvest agreeing instances. |
| [test_harvest_divergent_instances](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L109) | Harvest divergent instances. |
| [test_harvest_two_named_groups_on_one_function](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L123) | Harvest two named groups on one function. |
| [test_harvest_no_auto_pipeline_is_empty](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L138) | Harvest no auto pipeline is empty. |
| [test_seed_exact_path_function_fallback_and_unseeded_detection](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L145) | Seed exact path function fallback and unseeded detection. |
| [test_seed_preserves_relative_instances_and_independent_mains](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L193) | Seed preserves relative instances and independent mains. |
| [test_seed_ambiguous_region_implementations](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L221) | Seed ambiguous region implementations. |
| [test_seed_rejects_changed_region_interior](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L254) | Seed rejects changed region interior. |
| [test_harvest_skips_pinned_auto_fsm_units](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L270) | Harvest skips pinned auto fsm units. |
| [test_seed_does_not_require_previous_pinned_auto_fsm_units](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L290) | Seed does not require previous pinned auto fsm units. |
| [test_mcp_seed_only_passes_do_not_use_the_pass_budget](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L314) | Mcp seed only passes do not use the pass budget. |
| [test_hash_ext_is_content_aware](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L370) | Hash ext is content aware. |
| [test_canonical_callable_key_deterministic](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L403) | Canonical callable key deterministic. |
| [test_auto_pipeline_latency_cache_and_read_flag](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L413) | Auto pipeline latency cache and read flag. |
| [test_auto_pipeline_constructor_validation](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L453) | Auto pipeline constructor validation. |
| [test_auto_pipeline_latency_suffixes_and_identity](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L483) | Auto pipeline latency suffixes and identity. |
| [test_auto_pipeline_build_modes_and_served_values](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L519) | Auto pipeline build modes and served values. |
| [test_check_auto_pipeline_constraints_realized](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L572) | Check auto pipeline constraints realized. |
| [test_named_auto_pipeline_keys_and_groups](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L601) | Named auto pipeline keys and groups. |
| [test_latency_seeds_start_without_identity](../../../src/tests/pypeline_tests/inst/auto_pipeline_harvest_test.py#L664) | Latency seeds start without identity. |

### inst/auto_pipeline_region_planning_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:auto_pipeline_region_planning_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_exact_counts](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_planning_test.py#L50) | Exact counts. |
| [test_more_cuts_than_positions](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_planning_test.py#L64) | More cuts than positions. |
| [test_trim_plan_to_count](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_planning_test.py#L79) | Trim plan to count. |
| [test_region_caps_and_hotspot_attribution](../../../src/tests/pypeline_tests/inst/auto_pipeline_region_planning_test.py#L100) | Region caps and hotspot attribution. |

### inst/auto_pipeline_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:auto_pipeline_test`, `elab:auto_pipeline_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_pipeline](../../../src/tests/pypeline_tests/inst/auto_pipeline_test.py#L38) | Pipeline. |
| [test_auto_pipelined_submodules_sim](../../../src/tests/pypeline_tests/inst/auto_pipeline_test.py#L96) | Auto pipelined submodules sim. |
| [test_latency_reads_zero_in_sim](../../../src/tests/pypeline_tests/inst/auto_pipeline_test.py#L102) | Latency reads zero in sim. |

### inst/axis_byte_stream_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:axis_byte_stream_test`, `synth_device_models:axis_byte_stream_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_hw_round_trip_full_beats](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L70) | Frame length is an exact multiple of the lane width. |
| [test_hw_round_trip_partial_final_beat](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L76) | Frame length is NOT a multiple of the lane width -- exercises partial-keep on the last beat. |
| [test_hw_sink_rejects_mid_packet_hole](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L97) | byte_sink's Xilinx-style compliance check (wireguard-fpga issue #44): a partial-keep beat that does NOT carry eod (an embedded null byte mid packet) must raise via sim_assert. |
| [test_hw_sink_rejects_non_prefix_keep](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L111) | Even on the eod beat, a non-contiguous keep pattern (a hole before the last kept lane) must raise -- Xilinx-style tkeep is always a prefix. |
| [test_sim_source_sink_round_trip](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L124) | Plain-Python AxisSimSource/AxisSimSink, no hardware involved. |
| [test_sim_sink_rejects_mid_packet_hole](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L143) | AxisSimSink's Xilinx-style compliance check -- the plain-Python mirror of test_hw_sink_rejects_mid_packet_hole. |
| [test_sim_source_pause_generator](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L156) | set_pause_generator holds the emitted word at valid=0 for the generator's truthy entries, without losing/corrupting the frame. |
| [test_scoreboard_pass_and_fail](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L180) | Scoreboard.expect()/check() -- direct API, no AXIS involved. |
| [test_axis_sim_sink_check_nowait](../../../src/tests/pypeline_tests/inst/axis_byte_stream_test.py#L198) | AxisSimSink(scoreboard=...) -- check_nowait() combines recv + check. |

### inst/axis_max_len_limiter_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:axis_max_len_limiter_test`, `synth_device_models:axis_max_len_limiter_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sub_word_limit_actually_limits](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L123) | REGRESSION for axis.h:527. `max_byte_len - (axis_bits/8)` on an unsigned counter underflows to ~65534 when the type is smaller than one bus word, so `below` was always true and the limiter silently did nothing. With max_bytes=3 on a 4-byte bus, a 12-byte frame must yield exactly 3 bytes. |
| [test_non_multiple_limit](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L135) | REGRESSION for axis.h:527's `counter == last_word_limit`, which never fires when max_byte_len is not a whole number of bus words. max_bytes=6 on a 4-byte bus must cut mid-beat. |
| [test_keep_adjusted_on_truncating_beat](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L145) | REGRESSION for axis.h:539-541: the old limiter forced tlast but left tkeep untouched, so the beat that hit the limit still claimed all its bytes were real. Here keep must be a prefix of exactly the remaining length, and the dropped lanes' data must be zeroed. |
| [test_exact_multiple_limit](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L160) | Exact multiple limit. |
| [test_eod_never_forced_on_invalid_beat](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L167) | REGRESSION for axis.h:539-541, which forced tlast without checking validity, so tlast could sit high on an invalid beat. |
| [test_counter_resets_so_next_frame_is_limited_too](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L179) | REGRESSION for the framing half of the same bug: the counter must reset at the real end of a frame -- but NOT at the forced one, or the trailing padding re-arms the limiter and comes through as a second value. |
| [test_short_frame_passes_through_untouched](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L191) | A frame already under the limit must be unmodified -- same data, same keep, its own eod, no forced one. |
| [test_bad_max_bytes_rejected](../../../src/tests/pypeline_tests/inst/axis_max_len_limiter_test.py#L200) | Bad max bytes rejected. |

### inst/axis_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:axis_test`, `synth_device_models:axis_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_keep_count_and_count_to_keep](../../../src/tests/pypeline_tests/inst/axis_test.py#L55) | Keep count and count to keep. |

### inst/bit_manip_test.py

No direct Python entry registered; see caller/build registrations. Registration(s): `elab:bit_manip_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_bit_select](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L29) | HDL MAIN declaration, not a discovered Python assertion case. Bit select. |
| [test_bit_slice](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L34) | HDL MAIN declaration, not a discovered Python assertion case. Bit slice. |
| [test_bit_slice_assign](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L39) | HDL MAIN declaration, not a discovered Python assertion case. Bit slice assign. |
| [test_tuple_concat2](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L45) | HDL MAIN declaration, not a discovered Python assertion case. Tuple concat2. |
| [test_tuple_concat3](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L50) | HDL MAIN declaration, not a discovered Python assertion case. Tuple concat3. |
| [test_bit_dup](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L55) | HDL MAIN declaration, not a discovered Python assertion case. Bit dup. |
| [test_rotl](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L60) | HDL MAIN declaration, not a discovered Python assertion case. Rotl. |
| [test_rotr](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L65) | HDL MAIN declaration, not a discovered Python assertion case. Rotr. |
| [test_bswap](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L70) | HDL MAIN declaration, not a discovered Python assertion case. Bswap. |
| [test_bit_assign](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L75) | HDL MAIN declaration, not a discovered Python assertion case. Bit assign. |
| [test_array_to_uint_be](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L80) | HDL MAIN declaration, not a discovered Python assertion case. Array to uint be. |
| [test_array_to_uint_le](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L85) | HDL MAIN declaration, not a discovered Python assertion case. Array to uint le. |
| [test_uint_to_array_be](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L90) | HDL MAIN declaration, not a discovered Python assertion case. Uint to array be. |
| [test_uint_to_array_le](../../../src/tests/pypeline_tests/inst/bit_manip_test.py#L95) | HDL MAIN declaration, not a discovered Python assertion case. Uint to array le. |

### inst/bit_math_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:bit_math_test`, `synth_device_models:bit_math_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_truncate_then_square](../../../src/tests/pypeline_tests/inst/bit_math_test.py#L84) | 20000 + 20000 = 40000, truncated to int16_t = -25536; -25536^2 = 652086296. |
| [test_no_truncation_when_in_range](../../../src/tests/pypeline_tests/inst/bit_math_test.py#L96) | Typed annotation that does not overflow is a no-op — value is preserved. |
| [test_nested_truncate](../../../src/tests/pypeline_tests/inst/bit_math_test.py#L105) | Typed assignment inside an if-branch is rewritten by the transformer. |
| [test_counter_wraps_at_256](../../../src/tests/pypeline_tests/inst/bit_math_test.py#L116) | uint8_t typed annotation on the increment causes wrap-around at 256. |
| [test_cx_cy_hardware_arithmetic](../../../src/tests/pypeline_tests/inst/bit_math_test.py#L155) | cx and cy match hardware's unsigned intermediate arithmetic. |
| [test_plain_assign_inferred_truncation](../../../src/tests/pypeline_tests/inst/bit_math_test.py#L248) | Plain-Assign re-uses the declared type and truncates identically to AnnAssign. |

### inst/bottom_up_report_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:bottom_up_report_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_auto_pipeline_read_sites_and_pass_record](../../../src/tests/pypeline_tests/inst/bottom_up_report_test.py#L60) | Auto pipeline read sites and pass record. |
| [test_auto_multi_cycle_read_sites](../../../src/tests/pypeline_tests/inst/bottom_up_report_test.py#L100) | Auto multi cycle read sites. |
| [test_hardware_body_read_site](../../../src/tests/pypeline_tests/inst/bottom_up_report_test.py#L114) | Hardware body read site. |
| [test_documented_sizing_attributes](../../../src/tests/pypeline_tests/inst/bottom_up_report_test.py#L125) | Documented sizing attributes. |

### inst/c_structs_pkg_relayout_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:c_structs_pkg_relayout_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_relayout_between_passes_keeps_package_valid](../../../src/tests/pypeline_tests/inst/c_structs_pkg_relayout_test.py#L133) | Relayout between passes keeps package valid. |
| [test_resize_through_discovered_depths_in_one_out_dir](../../../src/tests/pypeline_tests/inst/c_structs_pkg_relayout_test.py#L163) | Harvested body depths 0, 1, 3, 6 (lanes 2, 3, 5, 8), then back to 1, all in one output directory. Each pass re-elaborates the outer design with that depth: powers_t and lane_sel_t (whose index width follows the lane count) keep one VHDL name, are declared once with the current layout, and the package plus the lane-select RTL analyze in GHDL. Only encrypt's cache entry changes; decrypt's types stay byte-identical. |
| [test_isolated_synthesis_reads_only_its_types](../../../src/tests/pypeline_tests/inst/c_structs_pkg_relayout_test.py#L264) | The WireGuard pass-2 cost: a lane-sized powers_t change invalidated every isolated synthesis, used or not. Each isolated synthesis now reads a c_structs_pkg holding only the types its files use. body (uint32_t only) keeps the same package bytes across the relayout; mac (acc_t, powers_t) gets a new one. Both analyze in GHDL. |
| [test_scoped_package_selection_rules](../../../src/tests/pypeline_tests/inst/c_structs_pkg_relayout_test.py#L304) | Synthetic chunk index: a use of only an enum literal or a conversion function pulls in its type; record fields pull in their element types; unused types stay out; an unreadable input falls back (None). |

### inst/cast_error_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:cast_error_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_unregistered_cast_pair_errors](../../../src/tests/pypeline_tests/inst/cast_error_test.py#L105) | Unregistered cast pair errors. |
| [test_wrong_arity_scalar_cast_errors_clearly](../../../src/tests/pypeline_tests/inst/cast_error_test.py#L116) | Wrong arity scalar cast errors clearly. |
| [test_array_ctype_cast_errors](../../../src/tests/pypeline_tests/inst/cast_error_test.py#L131) | Array ctype cast errors. |
| [test_bare_local_fwd_t_still_banned_via_cast_call](../../../src/tests/pypeline_tests/inst/cast_error_test.py#L140) | Bare local fwd t still banned via cast call. |
| [test_multi_field_interface_ctor_still_requires_keywords](../../../src/tests/pypeline_tests/inst/cast_error_test.py#L157) | Multi field interface ctor still requires keywords. |
| [test_multi_field_interface_ctor_with_keywords_is_clean](../../../src/tests/pypeline_tests/inst/cast_error_test.py#L179) | Multi field interface ctor with keywords is clean. |

### inst/cast_hw_func_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:cast_hw_func_test`, `elab:cast_hw_func_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_user_struct_cast_with_real_logic](../../../src/tests/pypeline_tests/inst/cast_hw_func_test.py#L55) | User struct cast with real logic. |
| [test_float32_to_float64_cast](../../../src/tests/pypeline_tests/inst/cast_hw_func_test.py#L87) | Float32 to float64 cast. |
| [test_float_to_int_cast](../../../src/tests/pypeline_tests/inst/cast_hw_func_test.py#L100) | Float to int cast. |
| [test_int_to_float_cast](../../../src/tests/pypeline_tests/inst/cast_hw_func_test.py#L109) | Int to float cast. |

### inst/cast_interface_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:cast_interface_test`, `elab:cast_interface_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_wrap_fwd](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L137) | Wrap fwd. |
| [test_wrap_fb](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L143) | Wrap fb. |
| [test_unwrap_fwd](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L149) | Unwrap fwd. |
| [test_unwrap_fb](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L158) | Unwrap fb. |
| [test_wide_feedback_wrap_unwrap](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L164) | Wide feedback wrap unwrap. |
| [test_aliased_call_form_wrap_fwd](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L191) | Aliased call form wrap fwd. |
| [test_aliased_call_form_wrap_fb](../../../src/tests/pypeline_tests/inst/cast_interface_test.py#L197) | Aliased call form wrap fb. |

### inst/cast_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:cast_test`, `elab:cast_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_cast_matches_assign_widen_unsigned](../../../src/tests/pypeline_tests/inst/cast_test.py#L112) | Cast matches assign widen unsigned. |
| [test_cast_matches_assign_narrow_unsigned](../../../src/tests/pypeline_tests/inst/cast_test.py#L116) | Cast matches assign narrow unsigned. |
| [test_cast_matches_assign_widen_signed](../../../src/tests/pypeline_tests/inst/cast_test.py#L122) | Cast matches assign widen signed. |
| [test_cast_matches_assign_narrow_signed](../../../src/tests/pypeline_tests/inst/cast_test.py#L126) | Cast matches assign narrow signed. |
| [test_cast_matches_assign_narrow_unsigned_from_signed](../../../src/tests/pypeline_tests/inst/cast_test.py#L136) | Cast matches assign narrow unsigned from signed. |
| [test_cast_matches_assign_widen_signed_from_unsigned](../../../src/tests/pypeline_tests/inst/cast_test.py#L144) | Cast matches assign widen signed from unsigned. |
| [test_identity_cast](../../../src/tests/pypeline_tests/inst/cast_test.py#L150) | Identity cast. |
| [test_cast_as_call_arg](../../../src/tests/pypeline_tests/inst/cast_test.py#L189) | Cast as call arg. |
| [test_cast_as_struct_field_init](../../../src/tests/pypeline_tests/inst/cast_test.py#L195) | Cast as struct field init. |
| [test_cast_in_expression](../../../src/tests/pypeline_tests/inst/cast_test.py#L201) | Cast in expression. |
| [test_cast_in_ternary](../../../src/tests/pypeline_tests/inst/cast_test.py#L207) | Cast in ternary. |
| [test_deepcopy_and_copy_not_reinterpreted_as_cast](../../../src/tests/pypeline_tests/inst/cast_test.py#L235) | Deepcopy and copy not reinterpreted as cast. |

### inst/char_array_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:char_array_test`, `synth_device_models:char_array_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_local_str_init](../../../src/tests/pypeline_tests/inst/char_array_test.py#L123) | Local str init. |
| [test_str_literal_exact_fit](../../../src/tests/pypeline_tests/inst/char_array_test.py#L131) | Str literal exact fit. |
| [test_passthrough](../../../src/tests/pypeline_tests/inst/char_array_test.py#L138) | Passthrough. |
| [test_increment_chars](../../../src/tests/pypeline_tests/inst/char_array_test.py#L145) | Increment chars. |
| [test_call_with_str_literal_arg](../../../src/tests/pypeline_tests/inst/char_array_test.py#L155) | Call with str literal arg. |
| [test_struct_field](../../../src/tests/pypeline_tests/inst/char_array_test.py#L162) | Struct field. |
| [test_strlen](../../../src/tests/pypeline_tests/inst/char_array_test.py#L170) | Strlen. |
| [test_strlen_not_char_gated](../../../src/tests/pypeline_tests/inst/char_array_test.py#L180) | Strlen not char gated. |
| [test_2d_grid](../../../src/tests/pypeline_tests/inst/char_array_test.py#L187) | 2d grid. |
| [test_mixed_arrays_struct](../../../src/tests/pypeline_tests/inst/char_array_test.py#L194) | Mixed arrays struct. |

### inst/clock_api_unit_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:clock_api_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_identity_and_port_names](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py#L58) | Identity and port names. |
| [test_argument_errors](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py#L73) | Argument errors. |
| [test_clock_conflicts](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py#L82) | Clock conflicts. |
| [test_main_clock_forms](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py#L93) | Main clock forms. |
| [test_markers](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py#L123) | Markers. |
| [test_fifo_initializers](../../../src/tests/pypeline_tests/inst/clock_api_unit_test.py#L142) | Fifo initializers. |

### inst/clock_domains_elab_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:clock_domains_elab_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_named_clocks_and_syn_mhz](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L76) | Named clocks and syn mhz. |
| [test_inference](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L113) | Inference. |
| [test_notes_printed_once](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L169) | Notes printed once. |
| [test_default_clock_warning](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L189) | Default clock warning. |
| [test_bare_main_two_clocks](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L210) | Bare main two clocks. |
| [test_crossing_error](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L239) | Crossing error. |
| [test_per_leaf_split_is_legal](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L270) | Per leaf split is legal. |
| [test_async_rows_and_warning](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L300) | Async rows and warning. |
| [test_stated_clocks](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L335) | Stated clocks. |
| [test_pins_on_two_clocks](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L370) | Pins on two clocks. |
| [test_board_clock_binding](../../../src/tests/pypeline_tests/inst/clock_domains_elab_test.py#L408) | Board clock binding. |

### inst/clock_mhz_pragma_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:clock_mhz_pragma_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_clk_mhz_populated_on_success](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py#L108) | Clk mhz populated on success. |
| [test_two_named_clocks_of_one_rate](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py#L115) | Two named clocks of one rate. |
| [test_non_uint1_t_rejected](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py#L133) | Non uint1 t rejected. |
| [test_output_rejected](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py#L138) | Output rejected. |
| [test_two_pins_for_one_clock_rejected](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py#L143) | Two pins for one clock rejected. |
| [test_clock_of_no_main_rejected](../../../src/tests/pypeline_tests/inst/clock_mhz_pragma_test.py#L148) | Clock of no main rejected. |

### inst/closure_local_nested_struct_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:closure_local_nested_struct_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_closure_local_nested_struct_registration](../../../src/tests/pypeline_tests/inst/closure_local_nested_struct_test.py#L74) | Closure local nested struct registration. |

### inst/conditional_import_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:conditional_import_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_minimal_conditional_import](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L136) | The handoff's minimal repro: a module-qualified wire write and function call through a module imported inside an `if`, plus its unconditional control. Both elaboration entry points and the pypelinec CLI. |
| [test_if_else_alias_picks_the_chosen_module](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L206) | `if: import A as impl / else: import B as impl` -- same wire and function names in both -- registers only the chosen module, under its own prefix. |
| [test_elif_try_and_from_imports](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L232) | elif chains, an except handler that ran, and conditional from-imports. |
| [test_selected_callable_passed_to_factory](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L264) | The WireGuard shape: the chosen module's function is passed into a factory in another module, and the closure calls it. The callee reads its own module's wire by bare name, which needs that module discovered. |
| [test_diamond_shared_resource_and_reparse](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L382) | One shared module reached from both directions is discovered once, under its own prefix, with one copy of its MAIN; unselected private modules stay out. A re-parse after the capacity changes (what the pin-and-confirm loop does when a latency changes a lane count) rediscovers the new sizes. |
| [test_untaken_branch_excluded_even_if_loaded](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L415) | Untaken imports of modules that ARE in sys.modules -- one loaded before any parse, one loaded by the design itself under another name -- are not discovered. Includes an untaken from-import that also names a shared object (uint8_t), which alone must not count as proof. |
| [test_main_in_undiscovered_module_fails_loud](../../../src/tests/pypeline_tests/inst/conditional_import_test.py#L450) | A module imported only inside a function body runs (its @MAIN registers, and native sim would run it) but is not discovered. PARSE_FILE must say so rather than leave that MAIN out of the hardware. |

### inst/cordic_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:cordic_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_matches_golden_model](../../../src/tests/pypeline_tests/inst/cordic_test.py#L86) | Hardware and the Python model must agree BIT for bit, not approximately. |
| [test_accuracy_all_quadrants](../../../src/tests/pypeline_tests/inst/cordic_test.py#L105) | Accuracy all quadrants. |
| [test_accuracy_is_scale_invariant](../../../src/tests/pypeline_tests/inst/cordic_test.py#L126) | The whole point of the input normalization: a weak phasor must be as accurately measured as a strong one. |
| [test_degenerate_zero_input](../../../src/tests/pypeline_tests/inst/cordic_test.py#L155) | Degenerate zero input. |
| [test_negative_x_axis](../../../src/tests/pypeline_tests/inst/cordic_test.py#L164) | atan2(y=0, x<0) is exactly +0.5 turns -- the one angle that sits on the int16 boundary, since +0.5 and -0.5 are the same direction. Either sign is correct; what must hold is that the result is within a LSB of the boundary rather than landing somewhere in the middle of the circle. |
| [test_pipeline_throughput_and_latency](../../../src/tests/pypeline_tests/inst/cordic_test.py#L179) | One result per cycle, in order, at the advertised latency. |
| [test_narrow_instance](../../../src/tests/pypeline_tests/inst/cordic_test.py#L199) | A second instantiation with different widths must also be exact. |

### inst/cross_file_helper_name_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:cross_file_helper_name_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sub_file_helper_is_not_the_top_file_helper](../../../src/tests/pypeline_tests/inst/cross_file_helper_name_test.py#L49) | Sub file helper is not the top file helper. |

### inst/dc_block_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:dc_block_test`, `synth_device_models:dc_block_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_random_stim_matches_golden](../../../src/tests/pypeline_tests/inst/dc_block_test.py#L117) | Random stim matches golden. |
| [test_resized_output_matches_golden](../../../src/tests/pypeline_tests/inst/dc_block_test.py#L125) | Resized output matches golden. |
| [test_valid_only_mode](../../../src/tests/pypeline_tests/inst/dc_block_test.py#L133) | Valid only mode. |
| [test_backpressure_stalls](../../../src/tests/pypeline_tests/inst/dc_block_test.py#L141) | Backpressure stalls. |
| [test_input_valid_gaps](../../../src/tests/pypeline_tests/inst/dc_block_test.py#L150) | Input valid gaps. |

### inst/design_params_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:design_params_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_precedence](../../../src/tests/pypeline_tests/inst/design_params_test.py#L48) | Precedence. |
| [test_types](../../../src/tests/pypeline_tests/inst/design_params_test.py#L69) | Types. |
| [test_choices_duplicates_bare](../../../src/tests/pypeline_tests/inst/design_params_test.py#L97) | Choices duplicates bare. |
| [test_names_and_parsing](../../../src/tests/pypeline_tests/inst/design_params_test.py#L113) | Names and parsing. |
| [test_once_per_process](../../../src/tests/pypeline_tests/inst/design_params_test.py#L125) | Once per process. |
| [test_injection](../../../src/tests/pypeline_tests/inst/design_params_test.py#L137) | Injection. |
| [test_injected_name_checks](../../../src/tests/pypeline_tests/inst/design_params_test.py#L166) | Injected name checks. |
| [test_parse_file_report_and_provenance](../../../src/tests/pypeline_tests/inst/design_params_test.py#L221) | Parse file report and provenance. |

### inst/device_models_sta_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:device_models_sta_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_register_path_components_and_arc_trace](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L63) | Register path components and arc trace. |
| [test_primary_input_to_output_has_explicit_zero_components](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L118) | Primary input to output has explicit zero components. |
| [test_zero_logic_path_has_explicit_empty_diagnostics](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L143) | Zero logic path has explicit empty diagnostics. |
| [test_fixed_recipe_commands_and_cache_identity](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L161) | Fixed recipe commands and cache identity. |
| [test_artifact_paths_fit_filename_limit](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L224) | Artifact paths fit filename limit. |
| [test_syn_disk_caches_are_recipe_scoped](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L273) | Syn disk caches are recipe scoped. |
| [test_mux_cache_keys_canonicalize_packed_types_by_width](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L314) | Mux cache keys canonicalize packed types by width. |
| [test_struct_mux_reads_plain_uint_cache_entry](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L374) | Struct mux reads plain uint cache entry. |
| [test_planner_component_weight_is_optional_and_deepcopied](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L399) | Planner component weight is optional and deepcopied. |
| [test_component_cache_sidecar_round_trip_and_validation](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L433) | Component cache sidecar round trip and validation. |
| [test_log_and_structured_report_round_trip](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L466) | Log and structured report round trip. |
| [test_cached_timing_requires_exact_inputs_model_and_mapped_json_hash](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L524) | Cached timing requires exact inputs model and mapped json hash. |
| [test_cached_timing_mismatch_reason_names_changed_input](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L567) | Cached timing mismatch reason names changed input. |
| [test_synthesis_identity_survives_copying_the_output_directory](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L631) | Synthesis identity survives copying the output directory. |
| [test_durable_qor_evidence_matrices_are_self_consistent](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L694) | Durable qor evidence matrices are self consistent. |
| [test_max_capacitance_violations_are_parsed](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L885) | Max capacitance violations are parsed. |
| [test_max_capacitance_violations_default_none_when_absent](../../../src/tests/pypeline_tests/inst/device_models_sta_test.py#L900) | Max capacitance violations default none when absent. |

### inst/divider_qor_bench_unit_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:divider_qor_bench_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_depth_and_timing_parsers_use_slice_stage_semantics](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L34) | Depth and timing parsers use slice stage semantics. |
| [test_forced_step_request_is_generic_and_bounded](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L56) | Forced step request is generic and bounded. |
| [test_stream_type_discovery_uses_payload_fields_not_hash_constants](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L94) | Stream type discovery uses payload fields not hash constants. |
| [test_exact_sim_workdir_is_recreated_between_toolchains](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L114) | Exact sim workdir is recreated between toolchains. |
| [test_fixture_sources_are_143_mhz_and_divide_by_zero_model_is_defined](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L141) | Fixture sources are 143 mhz and divide by zero model is defined. |
| [test_frozen_script_discovery_and_manifest_self_hash_exclusion](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L148) | Frozen script discovery and manifest self hash exclusion. |
| [test_vpi_abi_failure_is_narrowly_recognized](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L200) | Vpi abi failure is narrowly recognized. |
| [test_nonzero_simulator_return_cannot_be_overridden_by_result_json](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L207) | Nonzero simulator return cannot be overridden by result json. |
| [test_existing_runtime_requires_existing_build](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L222) | Existing runtime requires existing build. |
| [test_existing_manifest_derives_stages_from_known_slices](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L262) | Existing manifest derives stages from known slices. |
| [test_generated_python_and_delay_caches_do_not_enter_snapshot_hash](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L272) | Generated python and delay caches do not enter snapshot hash. |
| [test_model_record_rejects_external_liberty_override](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L287) | Model record rejects external liberty override. |
| [test_new_runs_reject_nonempty_evidence_and_generator_manifest_mismatch](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L308) | New runs reject nonempty evidence and generator manifest mismatch. |
| [test_continuity_source_derivation_changes_only_clock_assignment](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L356) | Continuity source derivation changes only clock assignment. |
| [test_continuity_acceptance_enforces_monotonic_depth_and_real_mid_gain](../../../src/tests/pypeline_tests/inst/divider_qor_bench_unit_test.py#L368) | Continuity acceptance enforces monotonic depth and real mid gain. |

### inst/doc_links_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:doc_links_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_no_broken_markdown_links](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L202) | No broken markdown links. |
| [test_guide_has_no_section_sign](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L213) | Guide has no section sign. |
| [test_guide_has_no_numbered_anchors](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L225) | Guide has no numbered anchors. |
| [test_docs_have_no_dated_headings](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L294) | Docs have no dated headings. |
| [test_docs_have_no_dated_body_text](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L324) | Docs have no dated body text. |
| [test_docs_have_convention_note](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L351) | Docs have convention note. |
| [test_design_docs_have_complete_toc](../../../src/tests/pypeline_tests/inst/doc_links_test.py#L403) | Every docs/*_DESIGN.md has a '## Table of Contents' (ended by the next '---' rule or heading) whose in-page links cover each '##' heading after it, in document order, and every TOC link resolves (checked here too: a heading like `Wire[T]` makes link text test_no_broken_markdown_links cannot parse). Deeper entries are optional. |

### inst/double_parse_file_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:double_parse_file_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_multi_file_design_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L76) | Multi file design reparses. |
| [test_stream_auto_pipeline_design_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L82) | Stream auto pipeline design reparses. |
| [test_fir_design_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L87) | Fir design reparses. |
| [test_auto_fsm_design_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L94) | Auto fsm design reparses. |
| [test_scheduled_auto_fsm_cache_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L103) | Scheduled auto fsm cache reparses. |
| [test_var_ref_naming_design_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L113) | Var ref naming design reparses. |
| [test_user_names_design_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L127) | User names design reparses. |
| [test_design_source_is_frozen_across_reparses](../../../src/tests/pypeline_tests/inst/double_parse_file_test.py#L143) | Design source is frozen across reparses. |

### inst/dwidth_converter_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:dwidth_converter_test`, `synth_device_models:dwidth_converter_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_split_assemble_round_trip](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py#L109) | Split assemble round trip. |
| [test_widen_full_beats](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py#L124) | 4 fully-kept narrow beats, eod[0] only on the 4th -> exactly one full wide beat. |
| [test_widen_partial_final_beat](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py#L154) | Only 2 narrow beats before eod[0], 2nd one partially kept -> realigned/right-justified wide output covering just those 2 beats worth of data. |
| [test_widen_back_to_back_packets](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py#L181) | 8 full narrow beats spanning 2 wide outputs, eod[0] only on the very last (8th) beat -> first wide beat eod[0]=0, second wide beat eod[0]=1. |
| [test_narrow_full_beat_drain](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py#L210) | One fully-kept wide beat with eod[0]=1 -> drains into 4 narrow beats, eod[0] only on the last (highest-address) one drained. |
| [test_widen_narrow_round_trip](../../../src/tests/pypeline_tests/inst/dwidth_converter_test.py#L245) | narrow -> dwidth_widen -> dwidth_narrow -> narrow reproduces the original stream. |

### inst/enum_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:enum_test`, `synth_device_models:enum_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_passthrough](../../../src/tests/pypeline_tests/inst/enum_test.py#L155) | Passthrough. |
| [test_is_idle](../../../src/tests/pypeline_tests/inst/enum_test.py#L163) | Is idle. |
| [test_simple_fsm](../../../src/tests/pypeline_tests/inst/enum_test.py#L171) | Simple fsm. |
| [test_packet_field](../../../src/tests/pypeline_tests/inst/enum_test.py#L184) | Packet field. |
| [test_factory_enum](../../../src/tests/pypeline_tests/inst/enum_test.py#L194) | Factory enum. |
| [test_plain_class_enum](../../../src/tests/pypeline_tests/inst/enum_test.py#L202) | Plain class enum. |
| [test_introspection](../../../src/tests/pypeline_tests/inst/enum_test.py#L210) | Introspection. |
| [test_parameterizable](../../../src/tests/pypeline_tests/inst/enum_test.py#L219) | Parameterizable. |
| [test_auto_plain_class_enum](../../../src/tests/pypeline_tests/inst/enum_test.py#L229) | auto() in a plain class assigns 0-based values (IDLE=0, RUNNING=1, DONE=2). |
| [test_pypeline_enum_base](../../../src/tests/pypeline_tests/inst/enum_test.py#L243) | PypelineEnum base class gives 0-based auto() for the IntEnum-subclass form. |
| [test_auto_introspection](../../../src/tests/pypeline_tests/inst/enum_test.py#L255) | Bit-width introspection is correct for auto() enums. |

### inst/factory_api_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:factory_api_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_return_type_survives_all_simulation_wrapper_variants](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L29) | Return type survives all simulation wrapper variants. |
| [test_void_and_unannotated_functions_expose_none](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L55) | Void and unannotated functions expose none. |
| [test_internal_pipeline_factory_returns_the_callable_and_tag_metadata](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L68) | Internal pipeline factory returns the callable and tag metadata. |
| [test_stacked_decorators_preserve_return_type](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L84) | Stacked decorators preserve return type. |
| [test_stream_result_contains_both_port_directions](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L94) | Stream result contains both port directions. |
| [test_width_converters_expose_directional_port_types](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L108) | Width converters expose directional port types. |
| [test_ram_cache_returns_the_complete_callable](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L123) | Ram cache returns the complete callable. |
| [test_generated_interface_cache_returns_the_complete_callable](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L135) | Generated interface cache returns the complete callable. |
| [test_fixed_operations_distinguish_operands_from_widened_results](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L151) | Fixed operations distinguish operands from widened results. |
| [test_unsigned_fixed_operations_expose_no_negate](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L167) | Unsigned fixed operations expose no negate. |
| [test_float_operations_bundle_contains_registered_callables](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L174) | Float operations bundle contains registered callables. |
| [test_undecorated_factory_callable_exposes_its_return_type](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L188) | Undecorated factory callable exposes its return type. |
| [test_factory_object_attributes_elaborate_as_hardware_types_and_calls](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L198) | Factory object attributes elaborate as hardware types and calls. |
| [test_hardware_local_cannot_resolve_a_shadowed_operation_bundle](../../../src/tests/pypeline_tests/inst/factory_api_test.py#L214) | Hardware local cannot resolve a shadowed operation bundle. |

### inst/factory_arg_port_annotation_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:factory_arg_port_annotation_test`, `native_vs_vhdl_sim:factory_arg_port_annotation_test_comb`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sim_call_through_rom](../../../src/tests/pypeline_tests/inst/factory_arg_port_annotation_test.py#L150) | Sim call through rom. |

### inst/factory_closure_naming_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:factory_closure_naming_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_nested_factory_instances_get_distinct_readable_names](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L105) | Nested factory instances get distinct readable names. |
| [test_top_level_callable_closure_param_is_readable](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L120) | Top level callable closure param is readable. |
| [test_nested_callable_closure_param_recurses_and_stays_unique](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L134) | Nested callable closure param recurses and stays unique. |
| [test_function_type_params_are_not_mistaken_for_hardware_annotations](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L158) | Function type params are not mistaken for hardware annotations. |
| [test_annotation_only_param_recovered_into_closure_ns](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L176) | Annotation only param recovered into closure ns. |
| [test_recursive_naming_uses_callables_own_globals_and_recovers_annotations](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L192) | Recursive naming uses callables own globals and recovers annotations. |
| [test_same_factory_same_args_dedups](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L217) | Same factory same args dedups. |
| [test_functools_partial_closure_param_no_crash](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L228) | Functools partial closure param no crash. |
| [test_lambda_closure_param_is_valid_identifier_with_hash](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L236) | Lambda closure param is valid identifier with hash. |
| [test_hw_func_wrapped_closure_param_unwraps_before_recursing](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L253) | Hw func wrapped closure param unwraps before recursing. |
| [test_builtin_closure_param_is_readable](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L268) | Builtin closure param is readable. |
| [test_cycle_guard_falls_back_to_hash_not_infinite_recursion](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L275) | Cycle guard falls back to hash not infinite recursion. |
| [test_overflow_collapse_keeps_readable_prefix](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L285) | Overflow collapse keeps readable prefix. |
| [test_negative_int_closure_param_has_no_bare_minus](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L297) | Negative int closure param has no bare minus. |
| [test_list_closure_param_is_readable_and_distinct](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L312) | List closure param is readable and distinct. |
| [test_list_closure_param_same_values_dedups](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L327) | List closure param same values dedups. |
| [test_nested_list_closure_param_is_valid_identifier](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L336) | Nested list closure param is valid identifier. |
| [test_empty_list_closure_param_no_crash](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L344) | Empty list closure param no crash. |
| [test_tuple_closure_param_encoded_same_as_list](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L351) | Tuple closure param encoded same as list. |
| [test_list_closure_param_float_element_is_readable](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L367) | List closure param float element is readable. |
| [test_unencodable_closure_param_gets_labeled_hash_not_error](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L380) | Unencodable closure param gets labeled hash not error. |
| [test_ast_meta_src_file_and_line_point_to_true_definition](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L402) | Ast meta src file and line point to true definition. |
| [test_struct_factory_param_suffix_disambiguates_colliding_field_types](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L461) | Struct factory param suffix disambiguates colliding field types. |
| [test_struct_factory_param_suffix_deterministic_regardless_of_order](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L477) | Struct factory param suffix deterministic regardless of order. |
| [test_struct_factory_param_suffix_same_args_same_name](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L497) | Struct factory param suffix same args same name. |
| [test_struct_bare_decorator_unaffected](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L504) | Struct bare decorator unaffected. |
| [test_struct_factory_param_suffix_scalar_ctype_value](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L524) | Struct factory param suffix scalar ctype value. |
| [test_struct_factory_param_suffix_negative_value_safe](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L546) | Struct factory param suffix negative value safe. |
| [test_struct_factory_param_suffix_overflow_collapses_safely](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L564) | Struct factory param suffix overflow collapses safely. |
| [test_hw_func_name_elides_redundant_module_prefix](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L580) | Hw func name elides redundant module prefix. |
| [test_enum_sequential_values_elided_sparse_kept](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L591) | Enum sequential values elided sparse kept. |
| [test_overflow_collapse_never_lands_mid_token](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L615) | Overflow collapse never lands mid token. |
| [test_generic_call_site_alias_labels_instance_with_callee_name](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L631) | Generic call site alias labels instance with callee name. |
| [test_loc_str_omits_el_for_single_line_keeps_for_multiline](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L662) | Loc str omits el for single line keeps for multiline. |
| [test_bin_func_name_sanitizes_array_brackets](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L700) | Bin func name sanitizes array brackets. |
| [test_unary_func_name_sanitizes_array_brackets](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L708) | Unary func name sanitizes array brackets. |
| [test_bin_func_name_scalar_types_unaffected](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L716) | Bin func name scalar types unaffected. |
| [test_bin_func_name_builtin_op_info_keeps_unsanitized_types](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L725) | Bin func name builtin op info keeps unsanitized types. |
| [test_factory_name_none_is_not_captured](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L746) | Factory name none is not captured. |
| [test_named_hw_func_key_is_name_plus_digest_of_unnamed_key](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L788) | Named hw func key is name plus digest of unnamed key. |
| [test_named_hw_func_errors](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L805) | Named hw func errors. |
| [test_named_struct_and_enum_type_names](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L828) | Named struct and enum type names. |
| [test_stream_factory_names_unchanged_and_forwarded](../../../src/tests/pypeline_tests/inst/factory_closure_naming_test.py#L858) | Stream factory names unchanged and forwarded. |

### inst/factory_main_api_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:factory_main_api_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_decorator_forms](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L74) | Decorator forms. |
| [test_call_form_registers_a_factory_function](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L119) | Call form registers a factory function. |
| [test_call_form_keeps_mhz](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L130) | Call form keeps mhz. |
| [test_call_form_takes_a_clock](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L139) | Call form takes a clock. |
| [test_name_must_be_a_vhdl_identifier](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L153) | Name must be a vhdl identifier. |
| [test_default_name_is_the_function_name](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L161) | Default name is the function name. |
| [test_default_name_has_the_module_prefix](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L169) | Default name has the module prefix. |
| [test_default_name_is_the_functions_own_name](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L189) | Default name is the functions own name. |
| [test_one_function_registered_twice_is_an_error](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L196) | One function registered twice is an error. |
| [test_main_during_a_simulation_run_is_an_error](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L209) | Main during a simulation run is an error. |
| [test_main_of_a_non_function_is_an_error](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L223) | Main of a non function is an error. |
| [test_duplicate_names_message](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L229) | Duplicate names message. |
| [test_name_helpers_are_shared_with_the_compiler](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L245) | Name helpers are shared with the compiler. |
| [test_build_results_find_mains_by_name](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L257) | Build results find mains by name. |
| [test_live_root_main_is_keyed_by_its_name](../../../src/tests/pypeline_tests/inst/factory_main_api_unit_test.py#L269) | Live root main is keyed by its name. |

### inst/factory_main_elab_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:factory_main_elab_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_lanes_made_in_a_loop](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L90) | Lanes made in a loop. |
| [test_bare_made_main_takes_rate_through_a_wire](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L107) | Bare made main takes rate through a wire. |
| [test_imported_factory_main_gets_the_module_prefix](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L114) | Imported factory main gets the module prefix. |
| [test_pure_factory_library_function_registered_by_the_design](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L144) | Pure factory library function registered by the design. |
| [test_renamed_top_level_main](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L165) | Renamed top level main. |
| [test_plain_def_passed_to_main](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L177) | Plain def passed to main. |
| [test_plain_def_passed_to_main_with_a_name](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L190) | Plain def passed to main with a name. |
| [test_factory_closure_wire_users_use_its_key](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L205) | Factory closure wire users use its key. |
| [test_reparse_gives_the_same_main_names](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L238) | Reparse gives the same main names. |
| [test_two_mains_with_one_name](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L250) | Two mains with one name. |
| [test_main_named_like_a_function](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L259) | Main named like a function. |
| [test_main_in_an_undiscovered_module_with_hardware](../../../src/tests/pypeline_tests/inst/factory_main_elab_test.py#L279) | Main in an undiscovered module with hardware. |

### inst/factory_main_pipeline_latency_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:factory_main_pipeline_latency_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_lanes_dispatch_to_their_own_timing](../../../src/tests/pypeline_tests/inst/factory_main_pipeline_latency_test.py#L92) | Lanes dispatch to their own timing. |

### inst/factory_main_sim_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:factory_main_sim_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_counter_lanes_keep_their_own_registers](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py#L176) | Counter lanes keep their own registers. |
| [test_lanes_keep_their_own_wire_elements](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py#L187) | Lanes keep their own wire elements. |
| [test_stateless_mains_keep_their_own_fifo_models](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py#L195) | Stateless mains keep their own fifo models. |
| [test_two_mains_with_one_name_stop_native_sim](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py#L204) | Two mains with one name stop native sim. |
| [test_multi_rate_refusal_names_made_mains](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py#L212) | Multi rate refusal names made mains. |
| [test_main_in_a_sim_hook_is_an_error](../../../src/tests/pypeline_tests/inst/factory_main_sim_test.py#L220) | Main in a sim hook is an error. |

### inst/feedback_reeval_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:feedback_reeval_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_feedback_from_stateful_child](../../../src/tests/pypeline_tests/inst/feedback_reeval_test.py#L95) | Bug #5 repro: fb_val must equal the previous cycle's x every cycle, including cycles where producer_child's old/new Reg value differs (the cycles that exposed the mixed-pass corruption: index 3 and 6 below). |
| [test_feedback_reg_same_body](../../../src/tests/pypeline_tests/inst/feedback_reeval_test.py#L115) | Feedback reg same body. |
| [test_feedback_stateful_child_pure_driver](../../../src/tests/pypeline_tests/inst/feedback_reeval_test.py#L128) | Feedback stateful child pure driver. |

### inst/fifo_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:fifo_test`, `synth_device_models:fifo_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_fifo_empty_behavior](../../../src/tests/pypeline_tests/inst/fifo_test.py#L37) | Fifo empty behavior. |
| [test_fifo_fwft_order](../../../src/tests/pypeline_tests/inst/fifo_test.py#L44) | Fifo fwft order. |
| [test_fifo_backpressure_at_capacity](../../../src/tests/pypeline_tests/inst/fifo_test.py#L57) | Fifo backpressure at capacity. |
| [test_fifo_simultaneous_push_pop](../../../src/tests/pypeline_tests/inst/fifo_test.py#L82) | Fifo simultaneous push pop. |
| [test_fifo_reference_model_soak](../../../src/tests/pypeline_tests/inst/fifo_test.py#L108) | Drive a scripted mix of idle/push/pop/simultaneous/full/empty phases, checking every cycle against an independent plain-Python reference model (not the implementation's own _FifoFwftModel). |

### inst/fir_decim_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:fir_decim_test`, `synth_device_models:fir_decim_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_decim3_matches_golden](../../../src/tests/pypeline_tests/inst/fir_decim_test.py#L126) | Decim3 matches golden. |
| [test_decim3_backpressure_phase_alignment](../../../src/tests/pypeline_tests/inst/fir_decim_test.py#L136) | Decim3 backpressure phase alignment. |
| [test_decim3_input_gaps](../../../src/tests/pypeline_tests/inst/fir_decim_test.py#L145) | Decim3 input gaps. |
| [test_decim2_valid_only](../../../src/tests/pypeline_tests/inst/fir_decim_test.py#L153) | Decim2 valid only. |
| [test_decim1_equals_plain_fir](../../../src/tests/pypeline_tests/inst/fir_decim_test.py#L172) | Decim1 equals plain fir. |

### inst/fir_interp_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:fir_interp_test`, `synth_device_models:fir_interp_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_zero_stuffer_beats](../../../src/tests/pypeline_tests/inst/fir_interp_test.py#L92) | Zero stuffer beats. |
| [test_interp3_matches_golden](../../../src/tests/pypeline_tests/inst/fir_interp_test.py#L120) | Interp3 matches golden. |
| [test_interp3_stall_recovery](../../../src/tests/pypeline_tests/inst/fir_interp_test.py#L130) | Interp3 stall recovery. |
| [test_interp3_input_gaps](../../../src/tests/pypeline_tests/inst/fir_interp_test.py#L139) | Interp3 input gaps. |

### inst/fir_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:fir_test`, `synth_device_models:fir_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_impulse_recovers_response](../../../src/tests/pypeline_tests/inst/fir_test.py#L179) | Impulse recovers response. |
| [test_random_stim_matches_golden](../../../src/tests/pypeline_tests/inst/fir_test.py#L187) | Random stim matches golden. |
| [test_symmetry_fold_bit_identical](../../../src/tests/pypeline_tests/inst/fir_test.py#L195) | Symmetry fold bit identical. |
| [test_halfband_zero_tap_skip](../../../src/tests/pypeline_tests/inst/fir_test.py#L207) | Halfband zero tap skip. |
| [test_antisymmetric_fold](../../../src/tests/pypeline_tests/inst/fir_test.py#L215) | Antisymmetric fold. |
| [test_full_precision](../../../src/tests/pypeline_tests/inst/fir_test.py#L223) | Full precision. |
| [test_backpressure_stalls](../../../src/tests/pypeline_tests/inst/fir_test.py#L231) | Backpressure stalls. |
| [test_input_valid_gaps](../../../src/tests/pypeline_tests/inst/fir_test.py#L241) | Input valid gaps. |
| [test_valid_only_mode](../../../src/tests/pypeline_tests/inst/fir_test.py#L250) | Valid only mode. |

### inst/fixed_point_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:fixed_point_test`, `synth_device_models:fixed_point_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_as_const_roundtrip](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L156) | As const roundtrip. |
| [test_arithmetic_vs_fraction_golden](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L175) | Arithmetic vs fraction golden. |
| [test_sign_mismatched_operand_pairs](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L201) | Sign mismatched operand pairs. |
| [test_mismatched_frac_bits_raises](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L235) | Mismatched frac bits raises. |
| [test_unary_negate](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L251) | Unary negate. |
| [test_resize_rounding_ties](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L285) | Resize rounding ties. |
| [test_resize_saturation](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L312) | Resize saturation. |
| [test_quantize_coeffs](../../../src/tests/pypeline_tests/inst/fixed_point_test.py#L346) | Quantize coeffs. |

### inst/float32_add_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:float32_add_test`, `synth_device_models:float32_add_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_float_add_32](../../../src/tests/pypeline_tests/inst/float32_add_test.py#L95) | Float add 32. |

### inst/float_ops_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:float_ops_test`, `synth_device_models:float_ops_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_bare_operators_native_sim](../../../src/tests/pypeline_tests/inst/float_ops_test.py#L70) | Bare +, -, *, / on float32_t/float64_t called directly as plain Python (no sim_call) -- exercises the struct-operator dispatch dunders (__add__/__sub__/__mul__/__truediv__) added to pypeline.py's struct() decorator, which is what makes `a + b` on registered float types work outside of hardware elaboration in the first place. |
| [test_conversions](../../../src/tests/pypeline_tests/inst/float_ops_test.py#L99) | Conversions. |
| [test_unregistered_operator_raises_clear_error](../../../src/tests/pypeline_tests/inst/float_ops_test.py#L117) | A struct type with no registered operator must raise a clear TypeError, not fall through to NamedTuple's default tuple concatenation/repeat behavior for +/-/*/ (the bug the struct-dispatch fix replaces). |
| [test_negate_primitive](../../../src/tests/pypeline_tests/inst/float_ops_test.py#L137) | _make_negate directly, at both width shapes make_float_adder actually instantiates -- widening (man_hidden_t uint24 -> signed_man_t int25) and narrowing (sum_man_t int26 -> abs_sum_t uint25). |

### inst/floor_and_bits_cap_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:floor_and_bits_cap_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_far_above_floor_is_not_at_floor](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L38) | Far above floor is not at floor. |
| [test_near_floor_from_above_is_at_floor](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L45) | Near floor from above is at floor. |
| [test_below_floor_is_not_at_floor](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L53) | Below floor is not at floor. |
| [test_floor_above_target_never_triggers](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L57) | Floor above target never triggers. |
| [test_none_floor_never_triggers](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L62) | None floor never triggers. |
| [test_at_predicted_floor_stress_symmetry](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L66) | At predicted floor stress symmetry. |
| [test_hard_floor_stop_needs_the_failing_path_to_reach_the_span](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L84) | Hard floor stop needs the failing path to reach the span. |
| [test_best_score_above_one_met_all_goals](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L123) | Best score above one met all goals. |
| [test_best_score_exactly_one_met_all_goals](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L129) | Best score exactly one met all goals. |
| [test_best_score_below_one_did_not_meet](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L133) | Best score below one did not meet. |
| [test_best_score_none_did_not_meet](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L137) | Best score none did not meet. |
| [test_get_leaf_bit_width_uses_widest_wire](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L152) | Get leaf bit width uses widest wire. |
| [test_get_leaf_bit_width_uses_binary_inputs_not_carry_output](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L162) | Get leaf bit width uses binary inputs not carry output. |
| [test_get_leaf_bit_width_none_when_no_types_resolve](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L172) | Get leaf bit width none when no types resolve. |
| [test_narrow_leaf_caps_internal_units_to_width_minus_one](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L188) | Narrow leaf caps internal units to width minus one. |
| [test_two_bit_leaf_keeps_one_internal_and_one_output_boundary](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L201) | Two bit leaf keeps one internal and one output boundary. |
| [test_wide_leaf_uncapped_when_width_exceeds_span](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L208) | Wide leaf uncapped when width exceeds span. |
| [test_unknown_width_exposes_only_truthful_output_boundary](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L216) | Unknown width exposes only truthful output boundary. |
| [test_bits_per_stage_dict_rejects_interior_zero_bit_stage](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L229) | Bits per stage dict rejects interior zero bit stage. |
| [test_bits_per_stage_dict_allows_leading_trailing_zero_bit_stage](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L244) | Bits per stage dict allows leading trailing zero bit stage. |
| [test_bits_per_stage_dict_within_cap_never_raises](../../../src/tests/pypeline_tests/inst/floor_and_bits_cap_unit_test.py#L256) | Bits per stage dict within cap never raises. |

### inst/func_wires_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:func_wires_test`, `elab:func_wires_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_wires_sim_call](../../../src/tests/pypeline_tests/inst/func_wires_test.py#L41) | @wires implies @hw_func: callable directly via sim_call(), no extra decorator. |
| [test_wires_main_sim_call](../../../src/tests/pypeline_tests/inst/func_wires_test.py#L49) | Wires main sim call. |

### inst/generated_naming_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:generated_naming_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_interface_specializations_have_distinct_keys_and_keep_pairing](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L26) | Interface specializations have distinct keys and keep pairing. |
| [test_record_names_describe_factory_and_interface_role](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L49) | Record names describe factory and interface role. |
| [test_typed_identity_survives_lossy_readable_encoding](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L62) | Typed identity survives lossy readable encoding. |
| [test_overflow_preserves_roles_and_is_fully_decodable](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L77) | Overflow preserves roles and is fully decodable. |
| [test_returned_factory_preserves_outer_closure_identity](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L102) | Returned factory preserves outer closure identity. |
| [test_interface_function_identity_survives_a_returned_factory](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L131) | Interface function identity survives a returned factory. |
| [test_presentation_collisions_are_deterministic_and_case_insensitive](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L144) | Presentation collisions are deterministic and case insensitive. |
| [test_vhdl_lexing_preserves_literals_comments_and_public_ports](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L157) | Vhdl lexing preserves literals comments and public ports. |
| [test_user_name_base_is_verbatim_and_keeps_the_automatic_description](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L175) | User name base is verbatim and keeps the automatic description. |
| [test_user_name_collisions_get_a_logical_key_digest](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L189) | User name collisions get a logical key digest. |
| [test_user_name_validation](../../../src/tests/pypeline_tests/inst/generated_naming_test.py#L205) | User name validation. |

### inst/generated_vhdl_stability_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:generated_vhdl_stability_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_first_write_matches_single_pass_layout](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L104) | First write matches single pass layout. |
| [test_later_pass_types_are_appended_and_kept](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L110) | Later pass types are appended and kept. |
| [test_pass_with_no_new_types_leaves_file_untouched](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L120) | Pass with no new types leaves file untouched. |
| [test_redefined_type_starts_over](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L130) | Redefined type starts over. |
| [test_changed_preamble_starts_over](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L137) | Changed preamble starts over. |
| [test_missing_package_file_ignores_stale_chunk_list](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L145) | Missing package file ignores stale chunk list. |
| [test_relayout_under_one_vhdl_name_starts_over](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L218) | Relayout under one vhdl name starts over. |
| [test_repeated_relayout_passes_settle](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L241) | Repeated relayout passes settle. |
| [test_same_declaration_from_another_logical_type_is_kept](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L256) | Same declaration from another logical type is kept. |
| [test_vhdl_type_names_are_case_insensitive](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L281) | Vhdl type names are case insensitive. |
| [test_pre_format_index_starts_over](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L289) | Pre format index starts over. |
| [test_one_pass_declaring_a_vhdl_name_twice_is_an_error](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L308) | One pass declaring a vhdl name twice is an error. |
| [test_identical_rerender_does_not_rewrite_the_file](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L318) | Identical rerender does not rewrite the file. |
| [test_builtin_operator_entities_have_no_call_site_comment](../../../src/tests/pypeline_tests/inst/generated_vhdl_stability_test.py#L334) | Builtin operator entities have no call site comment. |

### inst/global_fifo_api_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:global_fifo_api_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_fifo_type](../../../src/tests/pypeline_tests/inst/global_fifo_api_unit_test.py#L49) | Fifo type. |
| [test_fifo_type_errors](../../../src/tests/pypeline_tests/inst/global_fifo_api_unit_test.py#L73) | Fifo type errors. |
| [test_initializers](../../../src/tests/pypeline_tests/inst/global_fifo_api_unit_test.py#L83) | Initializers. |
| [test_port_helper](../../../src/tests/pypeline_tests/inst/global_fifo_api_unit_test.py#L100) | Port helper. |
| [test_fifo_main_generator](../../../src/tests/pypeline_tests/inst/global_fifo_api_unit_test.py#L153) | Fifo main generator. |

### inst/global_fifo_elab_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:global_fifo_elab_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_realization](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L81) | Realization. |
| [test_imported_module_fifo](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L141) | Imported module fifo. |
| [test_unused_end](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L164) | Unused end. |
| [test_two_users_of_one_end](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L169) | Two users of one end. |
| [test_user_with_two_instances](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L187) | User with two instances. |
| [test_driving_wr_ready](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L206) | Driving wr ready. |
| [test_driving_rd_stream](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L224) | Driving rd stream. |
| [test_missing_initializer](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L238) | Missing initializer. |
| [test_module_port_mismatch](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L243) | Module port mismatch. |
| [test_sync_fifo_ends_on_two_clocks](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L252) | Sync fifo ends on two clocks. |
| [test_fifo_inside_function](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L278) | Fifo inside function. |
| [test_auto_pipeline_of_handshake_user](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L292) | Auto pipeline of handshake user. |
| [test_fifo_main_name_collision](../../../src/tests/pypeline_tests/inst/global_fifo_elab_test.py#L319) | Fifo main name collision. |

### inst/global_fifo_pipeline_latency_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:global_fifo_pipeline_latency_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_late_fifo_main_leaves_trimmed_functions_alone](../../../src/tests/pypeline_tests/inst/global_fifo_pipeline_latency_test.py#L93) | Late fifo main leaves trimmed functions alone. |

### inst/global_inst_api_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:global_inst_api_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_plain_ports](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L97) | Plain ports. |
| [test_interface_ports](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L113) | Interface ports. |
| [test_auto_pipeline_tag](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L136) | Auto pipeline tag. |
| [test_errors](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L143) | Errors. |
| [test_main_generator](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L190) | Main generator. |
| [test_main_names](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L220) | Main names. |
| [test_name_checks](../../../src/tests/pypeline_tests/inst/global_inst_api_unit_test.py#L228) | Name checks. |

### inst/global_inst_elab_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:global_inst_elab_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_registration](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L82) | Registration. |
| [test_unused_instance_is_bare](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L105) | Unused instance is bare. |
| [test_handshake_user](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L118) | Handshake user. |
| [test_imported_module_instance](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L143) | Imported module instance. |
| [test_auto_pipeline_inside_instance_is_validated](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L164) | Auto pipeline inside instance is validated. |
| [test_driving_an_output](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L186) | Driving an output. |
| [test_users_on_two_rates](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L208) | Users on two rates. |
| [test_initializer](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L219) | Initializer. |
| [test_inst_inside_function](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L224) | Inst inside function. |
| [test_auto_pipeline_of_handshake_user](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L237) | Auto pipeline of handshake user. |
| [test_inst_main_name_collision](../../../src/tests/pypeline_tests/inst/global_inst_elab_test.py#L266) | Inst main name collision. |

### inst/global_wire_errors_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:global_wire_errors_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_overlapping_leaf_from_two_writers](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L61) | Overlapping leaf from two writers. |
| [test_whole_write_plus_field_write_conflict](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L80) | Whole write plus field write conflict. |
| [test_nested_leaf_overlap](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L99) | Nested leaf overlap. |
| [test_field_vs_enclosing_subtree_overlap](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L125) | Field vs enclosing subtree overlap. |
| [test_array_element_overlap](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L150) | Array element overlap. |
| [test_dynamic_index_write_rejected_with_multiple_writers](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L170) | Dynamic index write rejected with multiple writers. |
| [test_dynamic_index_write_global_wire_positive_case](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L205) | Dynamic index write global wire positive case. |
| [test_dynamic_index_write_local_var_positive_case](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L234) | Dynamic index write local var positive case. |
| [test_writing_input_still_errors](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L259) | Writing input still errors. |
| [test_unrolled_loop_precision_positive_case](../../../src/tests/pypeline_tests/inst/global_wire_errors_test.py#L274) | Unrolled loop precision positive case. |

### inst/hooks_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:hooks_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sim_finish](../../../src/tests/pypeline_tests/inst/hooks_test.py#L54) | Sim finish. |
| [test_run_n_cutoff](../../../src/tests/pypeline_tests/inst/hooks_test.py#L60) | Run n cutoff. |
| [test_error_still_runs_finals](../../../src/tests/pypeline_tests/inst/hooks_test.py#L66) | Error still runs finals. |
| [test_final_hook_error_raised_after_all_finals](../../../src/tests/pypeline_tests/inst/hooks_test.py#L73) | Final hook error raised after all finals. |
| [test_sim_finish_in_hook](../../../src/tests/pypeline_tests/inst/hooks_test.py#L80) | Sim finish in hook. |
| [test_decorator_errors](../../../src/tests/pypeline_tests/inst/hooks_test.py#L88) | Decorator errors. |

### inst/host_types_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:host_types_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_matches_pypeline_layout](../../../src/tests/pypeline_tests/inst/host_types_test.py#L251) | Decode and encode in a Pypeline-free process agree with pypeline itself, for every fixture, both endians, over random frames. |
| [test_struct_format_reproduces_handwritten_one](../../../src/tests/pypeline_tests/inst/host_types_test.py#L278) | The `struct` fast path is derived from the same leaf walk, never authored. |
| [test_generation_is_deterministic](../../../src/tests/pypeline_tests/inst/host_types_test.py#L294) | Generation is deterministic. |
| [test_auto_registration_from_make_type_to_bytes](../../../src/tests/pypeline_tests/inst/host_types_test.py#L303) | The whole point of hooking the choke point: no design edit required. |
| [test_auto_registration_through_axis_factory](../../../src/tests/pypeline_tests/inst/host_types_test.py#L315) | A design that only ever calls make_type_to_axis still registers -- that factory reaches make_type_to_bytes underneath, which is why PDW's three host-facing types would need no design change at all. |
| [test_both_endians_defaults_little_and_says_so](../../../src/tests/pypeline_tests/inst/host_types_test.py#L334) | Both endians defaults little and says so. |
| [test_host_export_values_and_alias](../../../src/tests/pypeline_tests/inst/host_types_test.py#L345) | Host export values and alias. |
| [test_enum_members_keep_int_to_bytes](../../../src/tests/pypeline_tests/inst/host_types_test.py#L360) | An @enum must NOT gain a to_bytes attribute: on an IntEnum that would shadow int.to_bytes for every member. Same call pypeline itself declines to make on @enum. |
| [test_char_array_behaves_like_a_string](../../../src/tests/pypeline_tests/inst/host_types_test.py#L377) | Char array behaves like a string. |
| [test_bad_field_names_rejected](../../../src/tests/pypeline_tests/inst/host_types_test.py#L391) | Bad field names rejected. |
| [test_write_host_types_places_and_skips](../../../src/tests/pypeline_tests/inst/host_types_test.py#L415) | Write host types places and skips. |

### inst/if_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:if_test`, `synth_device_models:if_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_if_num_cond](../../../src/tests/pypeline_tests/inst/if_test.py#L179) | If num cond. |

### inst/importfrom_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:importfrom_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_importfrom_transitive_struct_discovery](../../../src/tests/pypeline_tests/inst/importfrom_test.py#L42) | Importfrom transitive struct discovery. |

### inst/interface_array_port_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_array_port_test`, `synth_device_models:interface_array_port_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_array_port_is_introspected_as_one_port_of_n_elements](../../../src/tests/pypeline_tests/inst/interface_array_port_test.py#L52) | Array port is introspected as one port of n elements. |
| [test_array_fanout_matches_hand_written_twin](../../../src/tests/pypeline_tests/inst/interface_array_port_test.py#L180) | Array fanout matches hand written twin. |
| [test_each_lane_backpressures_independently](../../../src/tests/pypeline_tests/inst/interface_array_port_test.py#L184) | The interlock ands every lane's ready together, and each lane's ready reaches it through its own array element -- not a shared one. |

### inst/interface_boundary_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_boundary_test`, `synth_device_models:interface_boundary_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_generated_port_shape_is_the_documented_one](../../../src/tests/pypeline_tests/inst/interface_boundary_test.py#L109) | args = params (interface ones as their feedforward half) then one feedback arg per output port; return = feedforward per output port, then plain bundle fields, then feedback per input port. All named by port. |
| [test_both_crossings_match_hand_written_twin](../../../src/tests/pypeline_tests/inst/interface_boundary_test.py#L203) | Both crossings match hand written twin. |
| [test_plain_signals_cross_both_boundaries](../../../src/tests/pypeline_tests/inst/interface_boundary_test.py#L207) | `limit` goes down through the generated layer into two hand-written modules (a plain value may fan out; an interface may not), and `passed` comes back up through the mixed return bundle. |

### inst/interface_func_loop_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_func_loop_test`, `synth_device_models:interface_func_loop_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_generated_wiring_has_both_feedback_directions](../../../src/tests/pypeline_tests/inst/interface_func_loop_test.py#L152) | The loop needs two Feedbacks: one carrying the feedforward value backward (fsm's from_pipe_if) and one carrying the reverse value backward (to_pipe_if's). |
| [test_loop_matches_hand_written_twin](../../../src/tests/pypeline_tests/inst/interface_func_loop_test.py#L162) | Loop matches hand written twin. |

### inst/interface_func_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_func_test`, `synth_device_models:interface_func_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_ports_introspected_structurally](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L79) | Direction comes from which side holds the feedforward half -- no name convention is consulted, so port names are arbitrary. |
| [test_chain_matches_hand_written_twin](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L131) | Chain matches hand written twin. |
| [test_multi_in_out_bundle](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L167) | Multi in out bundle. |
| [test_multi_field_non_bit_reverse](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L223) | Multi field non bit reverse. |
| [test_plain_values_pass_through](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L263) | Plain values pass through. |
| [test_composition_and_memoization](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L294) | Composition and memoization. |
| [test_rejections](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L313) | Rejections. |
| [test_all_keyword_matches_positional_twin](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L418) | An all-keyword call site wires identically to the hand-written twin the positional `series` was checked against. |
| [test_mixed_positional_and_keyword](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L430) | Mixed positional and keyword. |
| [test_keyword_rejections](../../../src/tests/pypeline_tests/inst/interface_func_test.py#L437) | Keyword rejections. |

### inst/interface_hw_func_pairing_error_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_hw_func_pairing_error_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_lone_feedforward_half_errors](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L73) | An input port's feedforward half in the args, but no reverse half in the return -- the exact 'forgot the other half' shape. (The plain `uint8_t` output is not an interface, so `stream_in` is the only port here.) |
| [test_lone_reverse_half_errors](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L90) | A bare reverse half with no forward -- backpressure for a stream that isn't there. Almost always a real bug, so it errors too. |
| [test_first_lone_half_errors](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L110) | A function that leaves *both* an input and an output port half-declared raises on the first one found -- confirming the check runs, not that both are enumerated (a hard error stops at the first problem). |
| [test_complete_port_is_silent](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L130) | Both halves present (input port: fwd arg + fb return) -- no error. |
| [test_one_directional_interface_is_silent](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L146) | A feedforward-only interface has no reverse half to pair, so a lone forward half is complete and must not error. |
| [test_plain_signals_are_silent](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L155) | A hw_func with no interface types at all never errors. |
| [test_valid_only_stream_is_silent](../../../src/tests/pypeline_tests/inst/interface_hw_func_pairing_error_test.py#L163) | The structural escape hatch: a lone port typed as a genuinely one-directional valid-only stream (`make_stream_t`, no reverse half at all) never errors, in place of the old suppressible warning. |

### inst/interface_mixing_rules_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_mixing_rules_test`, `synth_device_models:interface_mixing_rules_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_legacy_scalar_ready_ports_are_rejected_by_name](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L92) | Legacy scalar ready ports are rejected by name. |
| [test_half_migrated_module_cannot_be_instantiated](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L99) | Half migrated module cannot be instantiated. |
| [test_array_input_port_is_rejected_clearly](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L123) | Array input port is rejected clearly. |
| [test_unassigned_plain_bundle_field_is_rejected](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L150) | Unassigned plain bundle field is rejected. |
| [test_plain_statement_may_read_non_interface_fields](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L176) | Plain statement may read non interface fields. |
| [test_plain_statement_may_not_touch_an_interface](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L183) | Plain statement may not touch an interface. |
| [test_factory_instances_are_named_apart](../../../src/tests/pypeline_tests/inst/interface_mixing_rules_test.py#L237) | Factory instances are named apart. |

### inst/interface_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:interface_test`, `synth_device_models:interface_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_derived_types_split_by_direction](../../../src/tests/pypeline_tests/inst/interface_test.py#L62) | Derived types split by direction. |
| [test_derivation_is_memoized_and_deterministic](../../../src/tests/pypeline_tests/inst/interface_test.py#L77) | Derivation is memoized and deterministic. |
| [test_nested_and_mixed_bundle](../../../src/tests/pypeline_tests/inst/interface_test.py#L96) | Nested and mixed bundle. |
| [test_one_directional_interfaces](../../../src/tests/pypeline_tests/inst/interface_test.py#L116) | One directional interfaces. |
| [test_explicit_split_struct_hw_func_simulates](../../../src/tests/pypeline_tests/inst/interface_test.py#L147) | Explicit split struct hw func simulates. |
| [test_plain_struct_rejects_directional_fields](../../../src/tests/pypeline_tests/inst/interface_test.py#L176) | A plain @struct has one direction, so a reverse field or a whole interface inside it is meaningless -- caught at declaration, not later. |
| [test_interface_declaration_errors](../../../src/tests/pypeline_tests/inst/interface_test.py#L195) | Interface declaration errors. |

### inst/interface_type_error_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:interface_type_error_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_reg_fwd_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L115) | Reg fwd t errors. |
| [test_reg_fb_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L124) | Reg fb t errors. |
| [test_reg_fwd_t_array_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L133) | Reg fwd t array errors. |
| [test_reg_stream_t_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L143) | Reg stream t is clean. |
| [test_feedback_fwd_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L154) | Feedback fwd t errors. |
| [test_feedback_stream_t_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L168) | Feedback stream t is clean. |
| [test_local_fwd_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L191) | Local fwd t errors. |
| [test_local_fb_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L201) | Local fb t errors. |
| [test_local_stream_t_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L211) | Local stream t is clean. |
| [test_feedback_fb_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L223) | Feedback fb t errors. |
| [test_feedback_stream_t_is_clean_via_port_crossing](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L234) | Feedback stream t is clean via port crossing. |
| [test_unannotated_local_fwd_t_assign_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L252) | Unannotated local fwd t assign errors. |
| [test_inline_ctor_call_argument_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L266) | Inline ctor call argument is clean. |
| [test_global_wire_fwd_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L287) | Global wire fwd t errors. |
| [test_global_wire_fb_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L299) | Global wire fb t errors. |
| [test_global_input_fwd_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L311) | Global input fwd t errors. |
| [test_global_output_fb_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L323) | Global output fb t errors. |
| [test_global_wire_stream_t_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L335) | Global wire stream t is clean. |
| [test_bare_interface_wire_is_clean_and_multi_writer](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L350) | Bare interface wire is clean and multi writer. |
| [test_bare_interface_wire_fwd_t_still_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L375) | Bare interface wire fwd t still errors. |
| [test_function_returning_fwd_t_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L398) | Function returning fwd t errors. |
| [test_function_returning_stream_t_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L408) | Function returning stream t is clean. |
| [test_bare_assign_of_direct_ctor_call_still_errors](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L418) | Bare assign of direct ctor call still errors. |
| [test_inline_ctor_call_argument_from_helper_is_clean](../../../src/tests/pypeline_tests/inst/interface_type_error_test.py#L436) | Inline ctor call argument from helper is clean. |

### inst/keyword_call_test.py

No direct Python entry registered; see caller/build registrations. Registration(s): `elab:keyword_call_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_keyword_calls_sim](../../../src/tests/pypeline_tests/inst/keyword_call_test.py#L49) | Keyword calls sim. |

### inst/latency_memory_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:latency_memory_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_read_latency_table_formats](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L41) | Read latency table formats. |
| [test_build_latency_profile_verdicts_and_seeds](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L94) | Build latency profile verdicts and seeds. |
| [test_seeded_tags_are_start_only_regions](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L174) | A seeded tag's sweep starts at its seed (a start-only region), except a callee holding another AUTO_PIPELINE, which stays as unconstrained as its source; unseeded unconstrained tags are never regions. |
| [test_selection_and_store](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L202) | Selection and store. |
| [test_digest_changes_only_ancestors](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L236) | Digest changes only ancestors. |
| [test_recording_per_piece_and_lock_roundtrip](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L267) | Recording per piece and lock roundtrip. |
| [test_replay_bounds_and_lower_goal_floor](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L327) | A changed cap rejects replay; a floor survives a smaller planned count. |
| [test_lower_goal_floor_only_for_regions](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L421) | A lower-goal depth floors only a region: a seeded tag whose callee holds another AUTO_PIPELINE is planned as if unseeded, so a floor there could never be enforced. The final-table check never reports floors. |
| [test_dependent_piece_resolution](../../../src/tests/pypeline_tests/inst/latency_memory_unit_test.py#L470) | Dependent piece resolution. |

### inst/leaf_split_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:leaf_split_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_split_kind_classification](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L66) | Split kind classification. |
| [test_leaf_max_split_slices](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L100) | Leaf max split slices. |
| [test_equal_width_split_ignores_requested_fraction](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L118) | Equal width split ignores requested fraction. |
| [test_equal_width_split_balances_multiple_chunks](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L131) | Equal width split balances multiple chunks. |
| [test_exact_bit_boundaries_emit_requested_uneven_chunks](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L138) | Exact bit boundaries emit requested uneven chunks. |
| [test_integer_mux_exact_boundary_renders_stage_local_bit_chunks](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L145) | Integer mux exact boundary renders stage local bit chunks. |
| [test_aggregate_mux_width_and_slv_chunks](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L174) | Aggregate mux width and slv chunks. |
| [test_two_stage_two_bit_plus_uses_carry_prefix_split](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L202) | Two stage two bit plus uses carry prefix split. |
| [test_bits_per_stage_dict_sum_and_balance_invariant_stress](../../../src/tests/pypeline_tests/inst/leaf_split_unit_test.py#L236) | Bits per stage dict sum and balance invariant stress. |

### inst/live_root_default_ops_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:live_root_default_ops_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_process_state_unchanged](../../../src/tests/pypeline_tests/inst/live_root_default_ops_test.py#L153) | Process state unchanged. |
| [test_stateful_rom_caller_with_signed_compare](../../../src/tests/pypeline_tests/inst/live_root_default_ops_test.py#L174) | Stateful rom caller with signed compare. |
| [test_pure_rom_caller_with_signed_compare](../../../src/tests/pypeline_tests/inst/live_root_default_ops_test.py#L184) | Pure rom caller with signed compare. |
| [test_design_registration_outranks_default](../../../src/tests/pypeline_tests/inst/live_root_default_ops_test.py#L193) | Under PARSE_FILE the defaults are registered before the design file is imported, so the design's own registrations win. They must here too. |
| [test_guard_armed_during_elaboration](../../../src/tests/pypeline_tests/inst/live_root_default_ops_test.py#L216) | An op pinned back to the built-in path gets the guard's explicit error, not a crash deep inside the C-generation path. |

### inst/loc_str_multiline_binop_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:loc_str_multiline_binop_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_multiline_binop_chain_elaborates_without_duplicate_instance_error](../../../src/tests/pypeline_tests/inst/loc_str_multiline_binop_test.py#L30) | Multiline binop chain elaborates without duplicate instance error. |

### inst/local_binds_global_wire_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:local_binds_global_wire_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sim_rejects_local_binding_of_wire_name](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L132) | Sim rejects local binding of wire name. |
| [test_elab_rejects_local_binding_of_wire_name](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L147) | Elab rejects local binding of wire name. |
| [test_elab_rejects_through_parse_file](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L163) | The PARSE_FILE (pypelinec) path, which elaborates every top-level hw_func. |
| [test_module_alias_binding_rejected](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L187) | A local named like an imported module that declares wires (file_a) would otherwise make `file_a.o` mean the module's wire in one layer only. |
| [test_sub_file_prefix_binding_rejected](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L218) | In an imported sub-file the wire is registered as '<module>_arr'; its bare name 'arr' must still count as the wire there. |
| [test_other_module_local_is_not_the_wire](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L263) | A local in a module that does NOT declare the wire stays a local, even when the top design file declares a same-named wire -- or a sub-file wire whose registered key is spelled the same ('file_a_o'). |
| [test_same_module_write_still_drives_wire](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L340) | Positive control: the ordinary no-`global` write is unchanged. |
| [test_unpack_into_wire_writes_it_in_sim](../../../src/tests/pypeline_tests/inst/local_binds_global_wire_test.py#L367) | Unpack into wire writes it in sim. |

### inst/local_shadows_global_const_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:local_shadows_global_const_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_compound_global_shadowed_by_local](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L168) | The original crash: KeyError: 'uint8_t' out of _ref_toks_to_ctype. |
| [test_str_global_shadowed_by_local](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L179) | A str-valued global would be emitted as a string-literal CONST wire. |
| [test_int_global_shadowed_by_local](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L190) | Sanity: an int-valued global already lost to the local; keep it that way. |
| [test_index_shadowed_by_local_is_not_const_folded](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L201) | arr[IDX] with a hardware IDX must stay a variable read, not fold to arr[2]. |
| [test_const_env_value_not_reused_after_name_becomes_hardware](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L213) | b = 0; b = x; b + 1 -- the stale const_env b == 0 must not fold to 1. |
| [test_aug_assign_after_name_becomes_hardware](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L223) | b += 1 must update the hardware b, not the stale const_env entry. |
| [test_comprehension_bound_name_still_folds](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L233) | A name bound INSIDE the expression is not the hardware local. |
| [test_annotation_still_sees_the_global](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L242) | Annotations are never evaluated by Python, so the global must win there. |
| [test_sim_call_prepare_path](../../../src/tests/pypeline_tests/inst/local_shadows_global_const_test.py#L254) | sim_call of a function reaching a @pipeline_latency child elaborates too. |

### inst/log2_db_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:log2_db_test`, `synth_device_models:log2_db_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_matches_golden_model](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L103) | Matches golden model. |
| [test_accuracy_vs_log10](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L118) | The hardware on 600 inputs, then its bit-exact model on 300k -- the number the module docstring quotes for each method. |
| [test_methods_agree](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L142) | The two methods are independent constructions of the same function, so each checks the other: they must agree to within their combined budget. |
| [test_fractional_bits_are_subtracted](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L156) | The headline correctness trap: dB must be of the VALUE, not of the raw integer. power_t carries 12 fractional bits, so raw == 4096 is 1.0 -> 0 dB. Taking dB of the raw integer would report +36.1 dB here, and would overflow Q8.8 at the top of the range. |
| [test_decade_and_octave_steps](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L177) | A factor of 10 is 10 dB and a factor of 2 is 3.0103 dB, within the approximation's error budget. |
| [test_nonpositive_is_floored_and_flagged](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L202) | A DC-blocked power estimate legitimately goes negative between pulses; dB of it does not exist, so it must be flagged rather than wrapped. |
| [test_different_binary_point_instance](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L221) | mean_t has 10 fractional bits, not 12. The dB of the same VALUE must match across the two instances even though the raw integers differ. |
| [test_monotonic](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L237) | dB must be non-decreasing in the input -- a segment-boundary mistake in the piecewise-linear table shows up here and almost nowhere else. |
| [test_pipeline_latency](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L261) | Pipeline latency. |
| [test_independent_rom_latencies](../../../src/tests/pypeline_tests/inst/log2_db_test.py#L277) | Floors, bubbles and data must agree when either table is the slow one. |

### inst/long_file_list_arg_len_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:long_file_list_arg_len_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_cocotb_makefile_recipe_under_max_arg_strlen](../../../src/tests/pypeline_tests/inst/long_file_list_arg_len_test.py#L67) | Cocotb makefile recipe under max arg strlen. |
| [test_yosys_script_argv_under_max_arg_strlen](../../../src/tests/pypeline_tests/inst/long_file_list_arg_len_test.py#L108) | Yosys script argv under max arg strlen. |

### inst/loop_iter_naming_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:loop_iter_naming_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_tuple_iteration_and_ordinal_naming](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L73) | Tuple iteration and ordinal naming. |
| [test_tuple_target_unpack_in_for](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L99) | Tuple target unpack in for. |
| [test_enumerate_zip_dict_str_iteration](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L120) | Enumerate zip dict str iteration. |
| [test_duplicate_iter_values_stay_distinct](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L146) | Duplicate iter values stay distinct. |
| [test_negative_and_nested_values_legal_vhdl](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L170) | Negative and nested values legal vhdl. |
| [test_swap_unpack_assign](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L195) | Swap unpack assign. |
| [test_const_unpack_assign](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L210) | Const unpack assign. |
| [test_indexed_call_target](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L229) | Indexed call target. |
| [test_determinism_across_two_parses](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L255) | Determinism across two parses. |
| [test_set_iteration_rejected](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L303) | Set iteration rejected. |
| [test_starred_target_rejected](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L318) | Starred target rejected. |
| [test_unpack_arity_mismatch_rejected](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L341) | Unpack arity mismatch rejected. |
| [test_for_iter_non_iterable_rejected](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L352) | For iter non iterable rejected. |
| [test_non_callable_expression_call_target_rejected](../../../src/tests/pypeline_tests/inst/loop_iter_naming_test.py#L364) | Non callable expression call target rejected. |

### inst/lut_atan2_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:lut_atan2_test`, `native_vs_vhdl_sim:lut_atan2_test_comb`, `native_vs_vhdl_sim:lut_atan2_pdw_width`, `native_vs_vhdl_sim:lut_atan2_recip_slow`, `native_vs_vhdl_sim:lut_atan2_angle_slow`.

| Declaration | Purpose / execution note |
|---|---|
| [test_numeric_accuracy](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py#L107) | Numeric accuracy. |
| [test_scale_and_corner_pipeline](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py#L157) | Scale and corner pipeline. |
| [test_pipeline_and_selected_plans](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py#L172) | Pipeline and selected plans. |
| [test_table_boundaries_pipeline](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py#L194) | Table boundaries pipeline. |
| [test_pdw_width_pipeline](../../../src/tests/pypeline_tests/inst/lut_atan2_test.py#L204) | Pdw width pipeline. |

### inst/lut_nco_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:lut_nco_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_automatic_and_manual_latency](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L78) | Automatic and manual latency. |
| [test_table_contents](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L101) | Table contents. |
| [test_matches_golden_model](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L110) | Matches golden model. |
| [test_golden_accuracy_vs_math](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L126) | Every phase bin, both instances, against amplitude*cos/sin evaluated at the ACTUAL phase (not the bin centre). The error allowed is half a bin of phase plus one LSB of rounding -- a wrong quadrant sign or a mirror that is off by one bin misses this by orders of magnitude. |
| [test_quadrant_axes](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L154) | The four axis crossings, from just either side. The sign of each rail is unambiguous there, so a swapped sign table cannot hide. |
| [test_constant_envelope_and_zero_mean](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L178) | Over every bin: \|z\| stays at the amplitude, and the rails average to zero. A per-quadrant rounding asymmetry shows up as a DC term here, which a phasor frequency estimator reads as a signal at 0 Hz. |
| [test_saturation_not_wrap](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L201) | amplitude = -32768 at the positive peak is the one product that does not fit int16. It must clamp to +32767, not wrap to -32768. |
| [test_spur_level](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L212) | Measured spur-free dynamic range for a tone whose frequency is not a multiple of the bin size, so phase truncation error is as bad as it gets. The docstring's ~6 dB-per-index-bit claim is what this pins. |
| [test_frequency_estimate_unbiased](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L243) | The PDW measures frequency as the angle of sum(z[n] * conj(z[n-1])). Phase truncation must not bias that: over a 32-product block its share of the error telescopes to at most one bin / 32 = 2^-17 turn. Output rounding adds the same order again, so the bound is 2^-15 -- under half the CORDIC atan2's own worst case (3.4e-5 turn) that measures it. |
| [test_pipeline_latency](../../../src/tests/pypeline_tests/inst/lut_nco_test.py#L271) | Pipeline latency. |

### inst/magnitude_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:magnitude_test`, `synth_device_models:magnitude_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_random_stim_matches_golden](../../../src/tests/pypeline_tests/inst/magnitude_test.py#L125) | Random stim matches golden. |
| [test_resized_output_matches_golden](../../../src/tests/pypeline_tests/inst/magnitude_test.py#L133) | Resized output matches golden. |
| [test_valid_only_mode](../../../src/tests/pypeline_tests/inst/magnitude_test.py#L141) | Valid only mode. |
| [test_backpressure_stalls](../../../src/tests/pypeline_tests/inst/magnitude_test.py#L149) | Backpressure stalls. |
| [test_input_valid_gaps](../../../src/tests/pypeline_tests/inst/magnitude_test.py#L158) | Input valid gaps. |

### inst/mixed_granularity_reassign_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:mixed_granularity_reassign_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_mixed_granularity_reassign_uses_fresh_value](../../../src/tests/pypeline_tests/inst/mixed_granularity_reassign_test.py#L62) | Mixed granularity reassign uses fresh value. |

### inst/moving_avg_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:moving_avg_test`, `synth_device_models:moving_avg_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_random_stim_matches_golden](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L127) | Random stim matches golden. |
| [test_resized_output_matches_golden](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L135) | Resized output matches golden. |
| [test_non_power_of_two_rawsum](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L143) | Non power of two rawsum. |
| [test_valid_only_mode](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L151) | Valid only mode. |
| [test_backpressure_stalls](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L159) | Backpressure stalls. |
| [test_input_valid_gaps](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L168) | Input valid gaps. |
| [test_non_power_of_two_normalize_raises](../../../src/tests/pypeline_tests/inst/moving_avg_test.py#L176) | Non power of two normalize raises. |

### inst/mux_fanout_planning_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:mux_fanout_planning_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_non_deepening_cut_is_dropped](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L116) | Non deepening cut is dropped. |
| [test_deepening_cut_is_kept](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L144) | Deepening cut is kept. |
| [test_locked_region_slices_are_not_counted_as_unplanned](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L168) | Locked region slices are not counted as unplanned. |
| [test_placement_inside_an_auto_pipeline_region_is_not_dropped](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L189) | Placement inside an auto pipeline region is not dropped. |
| [test_selected_mux_output_banks_are_chunked_by_default](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L279) | Selected mux output banks are chunked by default. |
| [test_narrow_bank_is_not_chunked_by_default](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L296) | Narrow bank is not chunked by default. |
| [test_terminal_mux_split_still_requires_the_measured_escalation](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L306) | Terminal mux split still requires the measured escalation. |
| [test_chunked_mux_refinement_is_none_when_nothing_selected](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L329) | Chunked mux refinement is none when nothing selected. |
| [test_mux_packed_bank_floor_is_soft_with_a_real_reason](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L337) | Mux packed bank floor is soft with a real reason. |
| [test_1ll_atomic_floor_stays_hard](../../../src/tests/pypeline_tests/inst/mux_fanout_planning_test.py#L347) | 1ll atomic floor stays hard. |

### inst/name_index_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:name_index_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_overflowing_struct_gets_full_name_recorded](../../../src/tests/pypeline_tests/inst/name_index_test.py#L71) | Overflowing struct gets full name recorded. |
| [test_overflowing_func_name_gets_full_name_recorded](../../../src/tests/pypeline_tests/inst/name_index_test.py#L115) | Overflowing func name gets full name recorded. |
| [test_same_named_closures_in_different_factories_are_distinct](../../../src/tests/pypeline_tests/inst/name_index_test.py#L162) | Same named closures in different factories are distinct. |
| [test_forced_canonical_collision_raises_naming_both_sources](../../../src/tests/pypeline_tests/inst/name_index_test.py#L172) | Forced canonical collision raises naming both sources. |
| [test_user_names_section_and_named_groups](../../../src/tests/pypeline_tests/inst/name_index_test.py#L239) | User names section and named groups. |
| [test_conflicting_auto_pipeline_name_names_both_sites](../../../src/tests/pypeline_tests/inst/name_index_test.py#L279) | Conflicting auto pipeline name names both sites. |
| [test_auto_tag_names_preserve_instance_hierarchy](../../../src/tests/pypeline_tests/inst/name_index_test.py#L295) | Names on a direct tag and a stream factory preserve emitted labels. |

### inst/openxc7_unit_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:openxc7_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_xc7_part_and_chipdb_name](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L70) | Xc7 part and chipdb name. |
| [test_xc7_chipdb_lookup_needs_the_parts_package](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L77) | Xc7 chipdb lookup needs the parts package. |
| [test_openxc7_root_locates_tools_chipdb_and_family_database](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L101) | Openxc7 root locates tools chipdb and family database. |
| [test_xc7_database_family_is_not_hardcoded_to_artix7](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L126) | Xc7 database family is not hardcoded to artix7. |
| [test_openxc7_characterization_avoids_physical_iopads](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L134) | Openxc7 characterization avoids physical iopads. |
| [test_openxc7_timing_parser_accepts_colons_in_synthesized_clock_names](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L152) | Openxc7 timing parser accepts colons in synthesized clock names. |
| [test_openxc7_timing_parser_reads_nextpnr_xilinx_report](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L170) | Openxc7 timing parser reads nextpnr xilinx report. |
| [test_openxc7_clock_alias_needs_one_constrained_clock_at_that_frequency](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L184) | Openxc7 clock alias needs one constrained clock at that frequency. |
| [test_openxc7_bitstream_conversion_is_an_explicit_backend_operation](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L196) | Openxc7 bitstream conversion is an explicit backend operation. |
| [test_openxc7_uses_existing_open_tools_backend_selection](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L216) | Openxc7 uses existing open tools backend selection. |
| [test_openxc7_bitstream_preflight_checks_conversion_tools_and_part_database](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L225) | Openxc7 bitstream preflight checks conversion tools and part database. |
| [test_openxc7_bitstream_runs_final_implementation_before_conversion](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L265) | Openxc7 bitstream runs final implementation before conversion. |
| [test_openxc7_install_check_requires_xc7_specific_payload](../../../src/tests/pypeline_tests/inst/openxc7_unit_test.py#L347) | Openxc7 install check requires xc7 specific payload. |

### inst/operator_scope_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:operator_scope_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_generic_operator_registry](../../../src/tests/pypeline_tests/inst/operator_scope_test.py#L125) | Generic operator registry. |
| [test_array_equality_operator_names_are_bracket_free](../../../src/tests/pypeline_tests/inst/operator_scope_test.py#L196) | Array equality operator names are bracket free. |

### inst/ord_char_literal_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:ord_char_literal_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_constant_builtin_calls_fold](../../../src/tests/pypeline_tests/inst/ord_char_literal_test.py#L96) | Constant builtin calls fold. |
| [test_builtin_on_hardware_value_is_clear_error](../../../src/tests/pypeline_tests/inst/ord_char_literal_test.py#L144) | Builtin on hardware value is clear error. |
| [test_str_into_scalar_same_error_both_sides](../../../src/tests/pypeline_tests/inst/ord_char_literal_test.py#L156) | Str into scalar same error both sides. |
| [test_str_into_char_array_still_works](../../../src/tests/pypeline_tests/inst/ord_char_literal_test.py#L200) | Str into char array still works. |

### inst/path_attribution_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:path_attribution_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_wireguard_decrypt_blames_chacha_not_the_interface_wrapper](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L196) | Wireguard decrypt blames chacha not the interface wrapper. |
| [test_post_rename_shapes_still_blame_chacha_not_the_interface_wrapper](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L265) | Post rename shapes still blame chacha not the interface wrapper. |
| [test_netlist_resources_cannot_outvote_a_deeper_endpoint_match](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L277) | Netlist resources cannot outvote a deeper endpoint match. |
| [test_missing_end_reg_name_falls_back_to_the_single_endpoint](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L289) | Missing end reg name falls back to the single endpoint. |
| [test_sky130_divider_attribution_is_unchanged](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L316) | Sky130 divider attribution is unchanged. |
| [test_no_endpoint_match_falls_back_to_resource_scoring](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L327) | No endpoint match falls back to resource scoring. |
| [test_ranking_is_deterministic_under_hash_salt](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L357) | Ranking is deterministic under hash salt. |
| [test_unsliceable_wrapper_defers_to_a_deeper_sliceable_func](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L389) | Unsliceable wrapper defers to a deeper sliceable func. |
| [test_stops_when_nothing_on_the_path_is_sliceable](../../../src/tests/pypeline_tests/inst/path_attribution_test.py#L429) | Stops when nothing on the path is sliceable. |

### inst/path_portability_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:path_portability_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_repo_paths_windows_portable](../../../src/tests/pypeline_tests/inst/path_portability_test.py#L86) | Repo paths windows portable. |
| [test_repo_paths_no_case_collisions](../../../src/tests/pypeline_tests/inst/path_portability_test.py#L103) | Repo paths no case collisions. |
| [test_part_cache_dir_name](../../../src/tests/pypeline_tests/inst/path_portability_test.py#L119) | Part cache dir name. |
| [test_gowin_cache_dir_is_safe_and_committed](../../../src/tests/pypeline_tests/inst/path_portability_test.py#L129) | Gowin cache dir is safe and committed. |

### inst/pipeline_latency_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:pipeline_latency_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_alternating_live_roots](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L140) | Alternating live roots. |
| [test_standalone_alignment](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L154) | Standalone alignment. |
| [test_direct_registers](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L169) | Direct registers. |
| [test_aliases_and_instances](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L175) | Aliases and instances. |
| [test_serial_and_parallel](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L186) | Serial and parallel. |
| [test_conditional_enable](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L193) | Conditional enable. |
| [test_dynamic_array_alignment](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L200) | Dynamic array alignment. |
| [test_unaffected_gate](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L210) | Unaffected gate. |
| [test_untagged_sim_skips_pipeline_model](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L225) | Untagged sim skips pipeline model. |
| [test_decorator_validation](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L285) | Decorator validation. |
| [test_decorator_stacking](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L308) | Decorator stacking. |
| [test_tagged_sim_model](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L335) | Tagged sim model. |
| [test_file_parse_metadata](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L363) | File parse metadata. |
| [test_convergence_and_reset](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L397) | Convergence and reset. |
| [test_conflicting_auto_pipeline](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L415) | Conflicting auto pipeline. |
| [test_elaboration_metadata](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L449) | Elaboration metadata. |
| [test_fixed_vhdl_has_no_added_registers](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L479) | Fixed vhdl has no added registers. |
| [test_placement_respects_entire_fixed_boundary](../../../src/tests/pypeline_tests/inst/pipeline_latency_test.py#L503) | Placement respects entire fixed boundary. |

### inst/pipeline_map_scheduler_scalability_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:pipeline_map_scheduler_scalability_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_zero_latency_chain_scheduling_work_is_linear](../../../src/tests/pypeline_tests/inst/pipeline_map_scheduler_scalability_test.py#L103) | Zero latency chain scheduling work is linear. |
| [test_latency_chain_scheduling_work_is_linear](../../../src/tests/pypeline_tests/inst/pipeline_map_scheduler_scalability_test.py#L119) | Latency chain scheduling work is linear. |
| [test_stuck_graph_reports_waiting_submodule](../../../src/tests/pypeline_tests/inst/pipeline_map_scheduler_scalability_test.py#L137) | Stuck graph reports waiting submodule. |

### inst/plan_cuts_boundary_snap_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:plan_cuts_boundary_snap_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_low_cut_density_never_merges_two_full_steps](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L97) | Low cut density never merges two full steps. |
| [test_cuts_land_at_end_of_run_not_mid_run](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L115) | Cuts land at end of run not mid run. |
| [test_plan_cuts_boundary_snap_invariants_stress](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L137) | Plan cuts boundary snap invariants stress. |
| [test_discarded_tail_boundary_never_hides_useful_legal_cuts](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L149) | Discarded tail boundary never hides useful legal cuts. |
| [test_stage_never_exceeds_budget_unless_physically_forced](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L242) | Stage never exceeds budget unless physically forced. |
| [test_no_plan_spends_registers_it_does_not_earn](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L268) | No plan spends registers it does not earn. |
| [test_cut_count_is_minimal_for_the_budget](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L299) | Cut count is minimal for the budget. |
| [test_budget_just_above_one_iteration_cuts_on_the_boundary](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L314) | Budget just above one iteration cuts on the boundary. |
| [test_parallel_branch_output_is_not_a_stage_boundary](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L367) | Parallel branch output is not a stage boundary. |
| [test_bit_splitting_is_dropped_when_it_does_not_pay_once_realized](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L394) | Bit splitting is dropped when it does not pay once realized. |
| [test_fmax_goal_can_ask_for_depths_between_the_structural_levels](../../../src/tests/pypeline_tests/inst/plan_cuts_boundary_snap_test.py#L424) | Fmax goal can ask for depths between the structural levels. |

### inst/pylist_value_context_error_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:pylist_value_context_error_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_undefined_ref_raises_clean_elaboration_error](../../../src/tests/pypeline_tests/inst/pylist_value_context_error_test.py#L25) | Undefined ref raises clean elaboration error. |

### inst/pylist_value_context_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:pylist_value_context_test`, `elab:pylist_value_context_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_module_global_list_value_context](../../../src/tests/pypeline_tests/inst/pylist_value_context_test.py#L51) | Module global list value context. |
| [test_closure_list_value_context](../../../src/tests/pypeline_tests/inst/pylist_value_context_test.py#L60) | Closure list value context. |

### inst/pypeline_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:pypeline_test`, `synth_device_models:pypeline_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_regs_multi_inst](../../../src/tests/pypeline_tests/inst/pypeline_test.py#L39) | Regs multi inst. |
| [test_point_u8_t](../../../src/tests/pypeline_tests/inst/pypeline_test.py#L143) | HDL MAIN declaration, not a discovered Python assertion case. Point u8 t. |
| [test_point_max](../../../src/tests/pypeline_tests/inst/pypeline_test.py#L312) | Point max. |

### inst/ram_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:ram_test`, `synth_device_models:ram_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_attributes](../../../src/tests/pypeline_tests/inst/ram_test.py#L240) | Attributes. |
| [test_distinct_contents_distinct_functions](../../../src/tests/pypeline_tests/inst/ram_test.py#L262) | Distinct contents distinct functions. |
| [test_sp_bram_read_first_and_passthrough](../../../src/tests/pypeline_tests/inst/ram_test.py#L276) | Sp bram read first and passthrough. |
| [test_valid_gates_writes](../../../src/tests/pypeline_tests/inst/ram_test.py#L292) | Valid gates writes. |
| [test_comb_read_struct_elements_and_wrap](../../../src/tests/pypeline_tests/inst/ram_test.py#L300) | Comb read struct elements and wrap. |
| [test_latency3_ports_and_write_collision](../../../src/tests/pypeline_tests/inst/ram_test.py#L321) | Latency3 ports and write collision. |
| [test_regfile_array_elements](../../../src/tests/pypeline_tests/inst/ram_test.py#L351) | Regfile array elements. |
| [test_byte_write_enables](../../../src/tests/pypeline_tests/inst/ram_test.py#L368) | Byte write enables. |
| [test_rom_of_strings](../../../src/tests/pypeline_tests/inst/ram_test.py#L384) | Rom of strings. |
| [test_init_forms](../../../src/tests/pypeline_tests/inst/ram_test.py#L393) | Init forms. |
| [test_factory_validation](../../../src/tests/pypeline_tests/inst/ram_test.py#L411) | Factory validation. |
| [test_two_call_sites_are_two_rams_and_reset_restores_init](../../../src/tests/pypeline_tests/inst/ram_test.py#L429) | Two call sites are two rams and reset restores init. |
| [test_reevaluation_commits_only_the_final_writes](../../../src/tests/pypeline_tests/inst/ram_test.py#L442) | pypeline_sim.py re-evaluates a model several times per cycle while wires converge. Only the last evaluation's writes may land, exactly once. |
| [test_stateful_caller_uses_physical_output](../../../src/tests/pypeline_tests/inst/ram_test.py#L464) | Stateful caller uses physical output. |
| [test_pure_caller_is_aligned](../../../src/tests/pypeline_tests/inst/ram_test.py#L470) | Pure caller is aligned. |
| [test_reference_soak_latency3_signed](../../../src/tests/pypeline_tests/inst/ram_test.py#L523) | Reference soak latency3 signed. |
| [test_reference_soak_byte_enables](../../../src/tests/pypeline_tests/inst/ram_test.py#L539) | Reference soak byte enables. |
| [test_reference_soak_comb_arrays_and_structs](../../../src/tests/pypeline_tests/inst/ram_test.py#L557) | Reference soak comb arrays and structs. |
| [test_file_parse_metadata](../../../src/tests/pypeline_tests/inst/ram_test.py#L582) | Elaborating this file records every generated RAM with its latency. |

### inst/reg_aug_assign_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:reg_aug_assign_test`, `native_sim:reg_aug_assign_convergence_test`, `native_vs_vhdl_sim:reg_aug_assign_test_comb`.

| Declaration | Purpose / execution note |
|---|---|
| [test_handoff_repro_matches_plain_assignment](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L160) | Handoff repro matches plain assignment. |
| [test_power_on_value_survives_sim_reset](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L167) | Power on value survives sim reset. |
| [test_scalar_targets_wrap_at_declared_width](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L208) | Scalar targets wrap at declared width. |
| [test_compound_leaves_wrap_at_declared_width](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L213) | Compound leaves wrap at declared width. |
| [test_struct_field_and_variable_index_nested_path](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L248) | Struct field and variable index nested path. |
| [test_sequential_read_after_write](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L258) | Sequential read after write. |
| [test_all_operators_match_plain_assignment](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L327) | All operators match plain assignment. |
| [test_feedback_convergence_advances_once_per_clock](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L354) | Feedback convergence advances once per clock. |
| [test_two_instances_do_not_share_state](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L381) | Two instances do not share state. |
| [test_typed_local_copy_does_not_alias_register](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L436) | Typed local copy does not alias register. |
| [test_parameter_writes_do_not_reach_the_caller](../../../src/tests/pypeline_tests/inst/reg_aug_assign_test.py#L440) | Parameter writes do not reach the caller. |

### inst/reg_bitwise_mask_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:reg_bitwise_mask_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_bitwise_mask_across_cycles](../../../src/tests/pypeline_tests/inst/reg_bitwise_mask_test.py#L43) | Cycle-by-cycle repro from the bug report: a/b must stay in {0, 1}. |
| [test_reg_literal_init_bitwise](../../../src/tests/pypeline_tests/inst/reg_bitwise_mask_test.py#L66) | Reg[uint1_t] = 1 literal init must be typed/masked from cycle 0. |
| [test_or_masks_raw_negative_operand](../../../src/tests/pypeline_tests/inst/reg_bitwise_mask_test.py#L74) | Bitwise dunders in isolation: OR-ing an out-of-range-but-typed SimVal against another typed SimVal must mask to the ctype's width, not leak the raw value through _bitwise_ctype's ctype-adoption. |

### inst/reg_init_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:reg_init_test`, `synth_device_models:reg_init_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_scalar_init](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L119) | First call returns init+1 (10+1=11), not 0+1=1. |
| [test_default_init_unchanged](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L129) | No initializer: first call still returns 0+1=1. |
| [test_signed_init](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L137) | Signed register init -5: first call returns -5+1=-4. |
| [test_array_init](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L147) | Array register init [10,20,30,40]: first read of buf[0] is 10. |
| [test_struct_init_dict](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L155) | Struct register dict style {x:3, y:7}: first return is 3+7=10. |
| [test_struct_init_ctor](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L163) | Struct register constructor style reg_point_t(x=5, y=2): first return is 5+2=7. |
| [test_sim_reset_restores_init](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L171) | After sim_reset(), register returns to init value, not accumulated state. |
| [test_reg_scalar_field_write](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L182) | Scalar field write through a Reg[struct] local, 1 level deep. |
| [test_reg_array_field_write](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L190) | Whole-array-literal field write through a Reg[struct] local, 1 level deep. |
| [test_reg_nested_array_field_write](../../../src/tests/pypeline_tests/inst/reg_init_test.py#L198) | Whole-array-literal field write through a Reg[struct] local, 2 levels deep. |

### inst/reg_undefined_width_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:reg_undefined_width_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_uint25_reg_persists](../../../src/tests/pypeline_tests/inst/reg_undefined_width_test.py#L31) | Previously-undefined width 25: register state must persist across calls. |
| [test_uint8_reg_persists](../../../src/tests/pypeline_tests/inst/reg_undefined_width_test.py#L41) | Already-defined width 8: unaffected by the constant-block edit. |
| [test_bogus_reg_type_raises](../../../src/tests/pypeline_tests/inst/reg_undefined_width_test.py#L50) | Reg[T] annotation whose T can't be resolved must fail loudly (NotImplementedError) at MAIN-registration time, not silently run with wrong (unregistered) state. |

### inst/registration_audit_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:registration_audit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_every_test_file_is_registered_somewhere](../../../src/tests/pypeline_tests/inst/registration_audit_test.py#L73) | Every test file is registered somewhere. |
| [test_registered_filenames_actually_exist](../../../src/tests/pypeline_tests/inst/registration_audit_test.py#L90) | Registered filenames actually exist. |

### inst/self_timed_factory_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:self_timed_factory_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_factories_do_not_query_latency](../../../src/tests/pypeline_tests/inst/self_timed_factory_test.py#L47) | Factories do not query latency. |

### inst/serdes_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:serdes_test`, `synth_device_models:serdes_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_serialize_non_divisible_partial_final_beat](../../../src/tests/pypeline_tests/inst/serdes_test.py#L229) | 13 elements on a 4-lane bus. The old serializer_in_to_out deadlocked outright here (serializer.h:42's `out_counter==IN_SIZE` never fires when IN_SIZE % OUT_SIZE != 0); the final beat must instead carry keep == 1. |
| [test_serialize_zeroes_unkept_lanes](../../../src/tests/pypeline_tests/inst/serdes_test.py#L243) | Unkept lanes carry 0, not stale buffer contents -- an unwritten register reads 'U' in GHDL but 0 in native sim, so stale data would show up as a spurious mismatch in a native-vs-VHDL cycle diff. |
| [test_deserialize_non_divisible](../../../src/tests/pypeline_tests/inst/serdes_test.py#L255) | The mirror: gather 13 elements from 4-lane beats. Old deserializer.h:41 (`out_counter==OUT_SIZE`) stepped over the target and wedged forever. |
| [test_deserialize_widening](../../../src/tests/pypeline_tests/inst/serdes_test.py#L266) | 2 lanes in, 8-element value out. |
| [test_deserialize_equal_width](../../../src/tests/pypeline_tests/inst/serdes_test.py#L274) | 1 beat per value, the case the old registered-ready deserializer halved the throughput of. |
| [test_deserializer_is_bubble_free](../../../src/tests/pypeline_tests/inst/serdes_test.py#L283) | THE regression for changing the old macro's handshake. |
| [test_serializer_is_bubble_free](../../../src/tests/pypeline_tests/inst/serdes_test.py#L312) | The serializer's combinational ready path (kept from serializer.h:32) means back-to-back values stream with no gap: N values of 2 beats each take 2N beats in 2N+1 cycles. |
| [test_backpressure_stall_and_resume](../../../src/tests/pypeline_tests/inst/serdes_test.py#L334) | With the sink not ready, nothing is emitted and no state is lost; once ready returns the whole value comes out intact. |
| [test_padding_exact_raises_at_factory_time](../../../src/tests/pypeline_tests/inst/serdes_test.py#L355) | The replacement for the old silent deadlock: a design that asks for exact sizing and does not have it fails while the module is being imported, with both sizes in the message. |
| [test_bad_options_rejected](../../../src/tests/pypeline_tests/inst/serdes_test.py#L376) | Bad options rejected. |
| [test_on_eod_discard_resyncs_after_runt](../../../src/tests/pypeline_tests/inst/serdes_test.py#L390) | Default policy. A packet that ends mid-value drops the residue and pulses .runt, so the NEXT packet decodes correctly -- the fix for axis.h:561-595, where the deserializer was never flushed on tlast and one runt permanently desynced every value after it. |
| [test_on_eod_zero_pad_emits_padded_value](../../../src/tests/pypeline_tests/inst/serdes_test.py#L404) | The alternative policy: emit the partial value zero-filled, still pulsing .runt so a consumer can tell. |
| [test_on_eod_ignore_reproduces_old_desync](../../../src/tests/pypeline_tests/inst/serdes_test.py#L415) | Documents the behaviour this library deliberately no longer defaults to. |
| [test_packed_carries_residue_across_values](../../../src/tests/pypeline_tests/inst/serdes_test.py#L433) | align="packed": two 6-element values arriving as 4-lane beats straddle beat boundaries and both come out whole. |
| [test_packed_serializer_concatenates_into_one_packet](../../../src/tests/pypeline_tests/inst/serdes_test.py#L443) | The send-side mirror: two 6-element values become one packet whose eod lands only on the caller-flagged final value. |
| [test_serializer_eod_never_on_invalid_beat](../../../src/tests/pypeline_tests/inst/serdes_test.py#L457) | serializer.h:29 computed out_last from the counter alone, so tlast could sit high while tvalid was low (and axis.h:653 copied it straight through). Here eod is only ever observable on a valid beat. |
| [test_round_trip_through_both](../../../src/tests/pypeline_tests/inst/serdes_test.py#L474) | serializer -> deserializer recovers the original 13 elements. |

### inst/sim_assert_finish_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:sim_assert_finish_test`, `synth_device_models:sim_assert_finish_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sim_assert_passes_silently](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py#L71) | Sim assert passes silently. |
| [test_sim_assert_fails_with_message](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py#L80) | Sim assert fails with message. |
| [test_sim_assert_default_message](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py#L93) | Sim assert default message. |
| [test_sim_finish_stops_native_sim](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py#L120) | Sim finish stops native sim. |
| [test_bare_call_asserts_elaborate](../../../src/tests/pypeline_tests/inst/sim_assert_finish_test.py#L133) | Bare call asserts elaborate. |

### inst/sim_elab_operator_parity_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:sim_elab_operator_parity_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_builtin_negate_widens_and_signs_like_elaboration](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L132) | The built-in path -- what runs when nothing is registered for NEGATE. |
| [test_soft_negate_return_type_matches_the_builtin_rule](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L147) | The library implementation and the built-in must agree, or registering the default soft ops would silently change every negate in a design. |
| [test_registered_negate_and_builtin_negate_agree](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L161) | Same value and same type whether or not the soft impl is the thing that runs -- this is the property that makes the SIM_SOFT_OPS default a performance choice rather than a correctness one. |
| [test_matcher_registration_dispatches_when_enabled](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L202) | Matcher registration dispatches when enabled. |
| [test_matcher_registration_is_bypassed_when_disabled](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L218) | Matcher registration is bypassed when disabled. |
| [test_concrete_registration_dispatches_regardless_of_policy](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L232) | A concrete-type registration is a deliberate, narrow override, so the SIM_SOFT_OPS policy (which is about the process-wide matcher defaults) does not switch it off. |
| [test_constant_shift_amount_does_not_dispatch](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L265) | Elaboration sends a constant amount to CONST_SL/CONST_SR and never consults the registry (PY_TO_LOGIC._elab_binop). Sim has to make the same split: the registered barrel shifter's own body shifts by a constant, so dispatching here recurses forever. |
| [test_variable_shift_amount_does_dispatch](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L284) | Variable shift amount does dispatch. |
| [test_default_soft_families_run_without_recursing](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L373) | The RecursionError guard. With every default matcher registration dispatchable, each family must terminate and return the built-in's value and type. DIV/MOD go through the barrel shifter internally, so a regression in the constant-shift split takes these down too. |
| [test_default_soft_families_agree_with_builtins](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L396) | Default soft families agree with builtins. |
| [test_scoped_generic_registration_does_not_leak_globally](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L416) | _resolve_generic_* memoizes a resolved implementation into the global concrete registry. Doing that for an entry that came from a scope= registration leaked it past scope exit, so every other function in the design silently picked up one function's scoped implementation -- wrong hardware, not just wrong sim. |
| [test_global_generic_registration_is_still_memoized](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L446) | The scoped-leak fix must not cost the memoization for ordinary global matcher registrations -- that is what keeps repeated resolutions cheap. |
| [test_literal_ctype_rules_agree_between_sim_and_elaboration](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L462) | pypeline._infer_literal_ctype and PY_TO_LOGIC._infer_const_ctype are duplicate implementations of one rule. They agree today only because LOGIC.BOOL_C_TYPE happens to be "uint1_t"; nothing asserted it. |
| [test_arith_promote_rules](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L473) | Arith promote rules. |
| [test_arith_output_ctype_widths](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L483) | Arith output ctype widths. |
| [test_sim_soft_ops_policy_spellings](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L495) | Sim soft ops policy spellings. |
| [test_sim_soft_ops_policy_switches_the_gate_set](../../../src/tests/pypeline_tests/inst/sim_elab_operator_parity_test.py#L514) | Toggling the policy has to rebuild the gate sets SimVal's dunders read, not just record a preference. |

### inst/sim_input_local_error_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:sim_input_local_error_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sim_rejects_misuse](../../../src/tests/pypeline_tests/inst/sim_input_local_error_test.py#L236) | Sim rejects misuse. |
| [test_elab_rejects_misuse_without_running_it](../../../src/tests/pypeline_tests/inst/sim_input_local_error_test.py#L254) | Elab rejects misuse without running it. |
| [test_parse_file_rejects_handoff_repro](../../../src/tests/pypeline_tests/inst/sim_input_local_error_test.py#L272) | The pypelinec path: PARSE_FILE elaborates the testbench top. |
| [test_sanctioned_forms_still_work](../../../src/tests/pypeline_tests/inst/sim_input_local_error_test.py#L294) | Sanctioned forms still work. |

### inst/sim_loop_reg_state_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:sim_loop_reg_state_test`, `native_sim:sim_loop_reg_state_loose_test`, `native_sim:sim_loop_reg_state_raw_test`, `native_vs_vhdl_sim:sim_loop_reg_state_test_comb`.

| Declaration | Purpose / execution note |
|---|---|
| [test_for_and_while_loop_instances_are_independent](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py#L130) | For and while loop instances are independent. |
| [test_nested_and_pure_helper_loop_instances_are_independent](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py#L140) | Nested and pure helper loop instances are independent. |
| [test_runtime_gated_iterations_keep_their_own_state](../../../src/tests/pypeline_tests/inst/sim_loop_reg_state_test.py#L150) | Runtime gated iterations keep their own state. |

### inst/sim_model_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:sim_model_test`, `native_sim:sim_model_convergence_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_delegate_model_two_instances](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L156) | Delegate model two instances. |
| [test_class_model_matches_delegate](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L163) | Class model matches delegate. |
| [test_return_cast_wraps](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L169) | Return cast wraps. |
| [test_sim_reset_recreates_model_instances](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L176) | Sim reset recreates model instances. |
| [test_copy_state_false_inplace](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L184) | Copy state false inplace. |
| [test_model_overrides_normal_hw_func](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L192) | Model overrides normal hw func. |
| [test_no_model_still_raises](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L197) | No model still raises. |
| [test_errors](../../../src/tests/pypeline_tests/inst/sim_model_test.py#L205) | Errors. |

### inst/sim_print_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:sim_print_test`, `synth_device_models:sim_print_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_counter_prints](../../../src/tests/pypeline_tests/inst/sim_print_test.py#L70) | Counter prints. |
| [test_print_name](../../../src/tests/pypeline_tests/inst/sim_print_test.py#L86) | Print name. |
| [test_sim_call_always_fires](../../../src/tests/pypeline_tests/inst/sim_print_test.py#L97) | Sim call always fires. |
| [test_extra_positional_arg_rejected_in_sim](../../../src/tests/pypeline_tests/inst/sim_print_test.py#L110) | sim_print("n", n) is an elaboration error (exactly one positional argument). Native sim used to accept it by binding n to debug=, printing just "n" and, once n went nonzero, a [SIM DEBUG PRINT ...] tag. It must fail the same way elaboration does. |
| [test_bare_char_array_elaborates](../../../src/tests/pypeline_tests/inst/sim_print_test.py#L127) | A bare {expr} for a char_t[N] array now auto-infers %s at elaboration time, and matches it in simulation via CharArray's NUL-stopped __str__ -- no wrapper call needed. print_name/test_print_name above already exercises this end to end; this test just pins down that elaboration itself succeeds (doesn't raise) for the bare form, on an isolated temp file (not this file itself, since this file is also fed wholesale to pypelinec by elab_tests.py/synth_tests.py and must elaborate cleanly end to end). |
| [test_bare_char_scalar_rejected_at_elaboration](../../../src/tests/pypeline_tests/inst/sim_print_test.py#L156) | A bare {expr} for a single char_t value is ambiguous (%c vs %d) and would print correctly in hardware but WRONG in simulation (Python's default int formatting of a SimVal) -- this must still be a hard elaboration error; unaffected by the char_array_to_str removal, since it's a distinct ambiguity requiring chr(expr). |

### inst/skid_buffer_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:skid_buffer_test`, `synth_device_models:skid_buffer_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_order_preserved_under_random_handshake](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L105) | No beat lost, duplicated or reordered, for any mode, under pseudo-random valid gaps and pseudo-random backpressure. |
| [test_output_held_stable_while_consumer_stalled](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L134) | AXI stability rule: once a beat is presented it must not change while ready is low. Input is held constant so the combinational-bypass modes are being asked a fair question. |
| [test_backpressure_propagates_after_exactly_n_slots](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L159) | With the consumer stalled forever and the producer always offering, a slice absorbs exactly `n_slots` beats and then holds ready low. This is the property that says how much storage each mode really has. |
| [test_full_throughput_and_fill_latency](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L176) | One beat per cycle sustained once filled -- the reason a skid buffer exists rather than a plain register -- and the exact advertised latency. |
| [test_modes_cut_the_paths_they_claim](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L254) | Modes cut the paths they claim. |
| [test_axis_frame_passes_through_byte_identical](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L284) | data/keep/eod are carried opaquely: a partial-keep eod beat comes out exactly as it went in. |
| [test_bad_mode_rejected_at_factory_call_time](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L332) | Bad mode rejected at factory call time. |
| [test_advertised_slots_and_latency](../../../src/tests/pypeline_tests/inst/skid_buffer_test.py#L344) | Advertised slots and latency. |

### inst/soft_mult_karatsuba_leaves_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:soft_mult_karatsuba_leaves_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_hybrid_registered_globally](../../../src/tests/pypeline_tests/inst/soft_mult_karatsuba_leaves_test.py#L160) | Hybrid registered globally. |
| [test_direct_calls_and_distinct_configurations](../../../src/tests/pypeline_tests/inst/soft_mult_karatsuba_leaves_test.py#L164) | Direct calls and distinct configurations. |
| [test_leaves_ignore_exact_soft_registration](../../../src/tests/pypeline_tests/inst/soft_mult_karatsuba_leaves_test.py#L168) | Leaves ignore exact soft registration. |
| [test_default_soft_karatsuba_unchanged](../../../src/tests/pypeline_tests/inst/soft_mult_karatsuba_leaves_test.py#L172) | Default soft karatsuba unchanged. |

### inst/soft_ops_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:soft_ops_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_soft_add](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L101) | Soft add. |
| [test_soft_add_carry_select](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L110) | Soft add carry select. |
| [test_soft_sub](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L119) | Soft sub. |
| [test_soft_add_sub_split](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L129) | AUTO_FSM's forced-descent adder/subtractor: two half-width built-in adds joined through a carry-in bit. Exhaustive over equal and unequal operand widths, including the odd result widths where the halves differ and a 1-bit operand. |
| [test_soft_mult_split](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L148) | AUTO_FSM's forced-descent multiplier: split the WIDER operand, two pinned inferred products, one add of the upper bits. Exhaustive, both operand orders (so both the split-left and split-right bodies run). |
| [test_soft_negate](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L161) | Signed AND unsigned operands. The unsigned case is the one that matters: negating an unsigned value is exactly where a same-width two's-complement negate silently returns the unsigned wrap instead of a negative number, so it is the case an `x * -1` workaround was papering over. make_soft_negate widens to int(width+1) FIRST, which is what makes the cheap ~x+1 form correct. |
| [test_soft_mult](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L181) | Soft mult. |
| [test_soft_mult_asymmetric](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L190) | Non-square operand widths, both orders -- make_soft_mult_shift_add's tree is sized by r_bits with eff_l_t-wide leaves, so unequal left/right widths are the case most likely to expose a tree sizing mistake. |
| [test_soft_carry_save_mult](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L207) | make_soft_mult_carry_save against the same golden sweep as test_soft_mult, across several max_width values -- including max_width >= the operand width, which degenerates toward a small number of wide adds and is the closest thing this shape has to a built-in control (though not byte-identical to make_soft_mult_shift_add's own tree, unlike Karatsuba's T>=n_bits case -- see docs/SYN_DESIGN.md section 11). |
| [test_soft_carry_save_mult_asymmetric](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L224) | Non-square operand widths, both orders -- same rationale as test_soft_mult_asymmetric. |
| [test_soft_carry_save_mult_degenerate](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L241) | Regression test for a real non-termination bug found while building this multiplier: when EVERY remaining summand in the carry-save reduction is simultaneously non-overlapping with its neighbors (only possible when the left operand is 1 bit wide, so every partial product is a single disjoint bit), the naive pairing scan marks everything 'pass' and the element count never shrinks -- uint1 x uint5 hung indefinitely before _plan_carry_save_levels merged shift-contiguous 'pass' runs. |
| [test_tree_add_shifted](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L263) | make_soft_add_tree_shifted directly, against the Python reference sum(t << i for i, t in enumerate(terms)). Exercised independently of the multiplier because its per-level shift/width/leftover bookkeeping is where a mistake would hide: odd leaf counts take the leftover path, and levels whose node width saturates at out_t exercise the width cap. Leaf counts include non-powers-of-two on purpose. |
| [test_soft_karatsuba_mult](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L290) | Regression test for a bug caught by manual audit: odd-bit-width splits in the recursion (e.g. the 16-bit case recurses into a 9-bit middle-term multiply) undersized mid_t by one bit, truncating a_lo+a_hi and corrupting the result -- e.g. uint16_t 65535*1 elaborated to 67043327 instead of 65535. threshold=4 forces recursion (and odd splits) even for the smaller 8-bit sweep below. |
| [test_soft_div_mod](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L320) | Soft div mod. |
| [test_soft_signed_div_mod](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L333) | make_soft_signed_div/make_soft_signed_mod: C-style truncating signed division (abs operands through the unsigned restoring divider, then fix the sign -- same structure C_TO_LOGIC.GET_BIN_OP_DIV_INT_N_C_CODE / GET_BIN_OP_MOD_INT_N_C_CODE used to generate as C). |
| [test_soft_radix4_div_mod](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L365) | make_soft_div_radix4/mod: 2-quotient-bits-per-step restoring divider, against the same golden a//b, a%b as test_soft_div_mod. Even width (6, exercises only 2-bit steps) and odd width (7, exercises the leading 1-bit step) both covered -- the odd-width path is the one most likely to have an off-by-one in the elaboration-time step-list construction. |
| [test_soft_signed_radix4_div_mod](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L385) | Signed radix-4 divider: same C-style truncating convention as test_soft_signed_div_mod, same abs-then-fix-sign wrapper, radix-4 unsigned core instead of the plain restoring one. |
| [test_soft_radix_div_mod_generalized](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L410) | make_soft_div_radix/mod(bits_per_step): the generalized factory make_soft_div_radix4/mod are built from (bits_per_step=2). |
| [test_soft_signed_radix_div_mod_generalized](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L434) | Signed generalized radix divider: same abs-then-fix-sign wrapper and C-style truncating convention as test_soft_signed_radix4_div_mod, swept across bits_per_step. |
| [test_soft_div_mod_registration](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L459) | register_soft_div/register_soft_mod split unsigned (any_uint_t -> make_soft_div/make_soft_mod) from signed (any_int_t -> make_soft_signed_div/make_soft_signed_mod). Mixed signedness (int/uint) is deliberately left unregistered, falling through to the built-in inferred path and from there to the PYPELINE_NO_SW_LIB_GUARD guard (raises loudly) rather than silently matching a factory never verified for that case. |
| [test_soft_mult_registration_unsigned_only](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L489) | register_soft_mult/register_soft_mult_karatsuba must register for any_uint_t x any_uint_t ONLY. |
| [test_soft_mult_karatsuba_threshold_override](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L524) | register_soft_mult_karatsuba(threshold=...) must actually thread the override into the registered factory (not silently fall back to make_soft_mult_karatsuba's own default), and the default (threshold=None) must resolve to a working multiplier at all. Regression test for the functools.partial-based override added alongside the threshold=16 default (docs/SYN_DESIGN.md#karatsuba-base-case-threshold). |
| [test_soft_mult_carry_save_max_width_override](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L548) | Same regression shape as test_soft_mult_karatsuba_threshold_override, for register_soft_mult_carry_save(max_width=...). |
| [test_soft_mult_default_is_carry_save](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L568) | register_soft_mult() must resolve to make_soft_mult_carry_save, not make_soft_mult_shift_add -- regression test for the default switch (docs/SYN_DESIGN.md#carry-save-multiplier-default-and-why-it-replaced-shift-and-add: the port of solution.vhd's sky130 reference design is now the default; the old tree stays reachable via register_soft_mult_shift_add()). |
| [test_karatsuba_leaf_policies](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L623) | Both Karatsuba leaf policies, called directly: exhaustive small and unequal widths deep enough to recurse, both sides of a threshold, and zero/maximal/random wide operands. |
| [test_karatsuba_defaults_unchanged](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L660) | The leaf option is opt-in: the soft registrations keep their factories and defaults (shift-and-add leaves at threshold 16, carry-save with max_width=2). |
| [test_karatsuba_inferred_leaves_registered](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L684) | register_mult_karatsuba_inferred_leaves() resolves to the threshold-34 hybrid, and the resolved hybrid -- run with that registration active -- still multiplies correctly. Native sim never dispatches a registered INFERRED_MULT for a plain `*` (SimVal.__mul__ is a Python product), so leaf pinning against this and other registrations is checked on the elaborated hierarchy in soft_mult_karatsuba_leaves_test.py instead. |
| [test_soft_cmp](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L725) | All six comparator flavors x all four ops x unsigned and signed. |
| [test_soft_cmp_mixed_width](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L754) | Mismatched operand widths and mixed signedness -- the paths where each flavor has to resize to a common width before comparing (the resize bug make_soft_cmp_bitwise's own docstring documents). |
| [test_soft_eq](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L773) | Soft eq. |
| [test_soft_shift](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L783) | Exhaustive over uint8_t (every value x every amount, both directions), plus a signed sweep of make_soft_shift_barrel_sr against Python's arithmetic >> -- each CONST_SR stage lowers via VHDL's numeric_std shift_right, which is arithmetic (sign-extending) for a signed operand type, so a signed value_t should already match Python's sign-extending >> with no separate signed implementation needed. |
| [test_soft_rotate](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L830) | make_soft_rot_barrel_l/rotr: exhaustive over uint8_t, both directions, including amount == 0 (identity) and amount == n_bits-1. |
| [test_soft_shift_rot](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L846) | make_soft_shift_rot: the unified 4-mode (direction x rotate) funnel barrel, exhaustive over uint8_t against the same shift/rotate goldens test_soft_shift/test_soft_rotate use -- this is the primitive that answers the pasted latchup_rotate C with one barrel instead of four. |
| [test_generic_registry_end_to_end](../../../src/tests/pypeline_tests/inst/soft_ops_test.py#L871) | Register a soft adder for any_integer_t globally, then verify plain `a + b` on a fresh, never-before-seen concrete width dispatches to it (proving the matcher -> factory -> memoize path, not just the factories in isolation). |

### inst/src_module_import_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:src_module_import_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_every_src_module_imports_first](../../../src/tests/pypeline_tests/inst/src_module_import_test.py#L49) | Every src module imports first. |
| [test_python_build_without_cpp](../../../src/tests/pypeline_tests/inst/src_module_import_test.py#L65) | Python build without cpp. |
| [test_c_build_without_cpp_names_cpp](../../../src/tests/pypeline_tests/inst/src_module_import_test.py#L81) | C build without cpp names cpp. |
| [test_no_syn_tool_falls_back_to_comb_no_synth](../../../src/tests/pypeline_tests/inst/src_module_import_test.py#L118) | No syn tool falls back to comb no synth. |
| [test_no_syn_tool_fallback_re_elaborates_start_latency](../../../src/tests/pypeline_tests/inst/src_module_import_test.py#L126) | No syn tool fallback re elaborates start latency. |

### inst/stream_auto_fsm_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:stream_auto_fsm_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_latency_and_ii_no_backpressure](../../../src/tests/pypeline_tests/inst/stream_auto_fsm_test.py#L115) | With the consumer always ready, latency and initiation interval both equal ADD_FSM.latency (== fsm.latency + 1 == 1 in plain native sim): each result is consumed the same cycle it first appears (no stalls), so the consumed-cycle IS the first-valid cycle here. |
| [test_backpressure_no_loss_no_reorder](../../../src/tests/pypeline_tests/inst/stream_auto_fsm_test.py#L134) | A pseudo-random ready pattern (including long stalls) must still deliver every result, in order, with no drops/duplicates/reordering, and (checked inside _drive) a held result's data must never change while stalled. |
| [test_ready_deasserts_while_busy](../../../src/tests/pypeline_tests/inst/stream_auto_fsm_test.py#L153) | stream_in_if.ready must be low on every cycle the wrapper is busy with no result ready yet (single item in flight). Ready may legitimately be high again on the very same cycle a result first goes valid -- the slot frees combinationally within that cycle (the make_stream_multi_cycle-style same-cycle out->in trick), so that cycle is exempt from the check. |

### inst/stream_auto_multi_cycle_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:stream_auto_multi_cycle_test`, `synth_vivado:stream_auto_multi_cycle_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_start_latency_handshake](../../../src/tests/pypeline_tests/inst/stream_auto_multi_cycle_test.py#L133) | Start latency handshake. |
| [test_fixed_latency_handshake](../../../src/tests/pypeline_tests/inst/stream_auto_multi_cycle_test.py#L139) | Fixed latency handshake. |

### inst/stream_auto_pipeline_latency_args_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:stream_auto_pipeline_latency_args_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_forwarding_and_build_modes](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py#L110) | Forwarding and build modes. |
| [test_stable_identity](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py#L134) | Stable identity. |
| [test_pinned_latency_metadata](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py#L146) | A pin-and-confirm pass re-executes the factory with the harvested core depth cached; the exported .auto_pipeline / .max_in_flight follow it. |
| [test_bad_arguments](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py#L163) | Bad arguments. |
| [test_native_sim_latency](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py#L206) | Native sim latency. |
| [test_dsp_factories_forward](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_latency_args_test.py#L229) | Dsp factories forward. |

### inst/stream_auto_pipeline_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:stream_auto_pipeline_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_stream_auto_pipeline_steady_drain](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_test.py#L82) | Stream auto pipeline steady drain. |
| [test_stream_auto_pipeline_stall_and_resume](../../../src/tests/pypeline_tests/inst/stream_auto_pipeline_test.py#L92) | Stream auto pipeline stall and resume. |

### inst/stream_fifo_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:stream_fifo_test`, `synth_device_models:stream_fifo_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_stream_fifo_order_and_backpressure](../../../src/tests/pypeline_tests/inst/stream_fifo_test.py#L37) | Light coverage of the stream_t field plumbing (.data/.valid <-> .out_stream_if/.in_stream_if) -- FIFO push/pop/backpressure correctness itself is exhaustively covered by fifo_test.py against the shared _FifoFwftModel. |

### inst/stream_ii1_throughput_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:stream_ii1_throughput_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_stream_auto_pipeline_sizing_metadata](../../../src/tests/pypeline_tests/inst/stream_ii1_throughput_test.py#L69) | Stream auto pipeline sizing metadata. |
| [test_stream_auto_pipeline_one_word_per_cycle](../../../src/tests/pypeline_tests/inst/stream_ii1_throughput_test.py#L77) | Stream auto pipeline one word per cycle. |
| [test_stream_auto_pipeline_stall_admits_round_trip](../../../src/tests/pypeline_tests/inst/stream_ii1_throughput_test.py#L102) | Stream auto pipeline stall admits round trip. |
| [test_elastic_dsp_blocks_full_rate](../../../src/tests/pypeline_tests/inst/stream_ii1_throughput_test.py#L153) | in_every: cycles between accepted inputs (fir_interp emits `interp` beats per input); out_every: cycles between results (fir_decim emits one per `decim` inputs). |

### inst/stream_multi_cycle_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:stream_multi_cycle_test`, `synth_vivado:stream_multi_cycle_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_divider_mcp_handshake](../../../src/tests/pypeline_tests/inst/stream_multi_cycle_test.py#L102) | Divider mcp handshake. |

### inst/stream_perf_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:stream_perf_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_meter_hand_worked_trace](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L66) | Meter hand worked trace. |
| [test_meter_steady_rates](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L107) | Meter steady rates. |
| [test_handshake_tap](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L134) | Handshake tap. |
| [test_epoch_keeps_last_converged_sample](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L160) | Epoch keeps last converged sample. |
| [test_buffer_tap](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L176) | Buffer tap. |
| [test_state_and_arb_taps](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L198) | State and arb taps. |
| [test_registry_enablement](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L225) | Registry enablement. |
| [test_packet_size_phases](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L240) | Packet size phases. |
| [test_rollup_and_verdict](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L294) | Rollup and verdict. |
| [test_check_taps_spread](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L331) | Check taps spread. |
| [test_headline_and_best_ceiling](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L338) | Headline and best ceiling. |
| [test_markdown_and_csv](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L356) | Markdown and csv. |
| [test_buffer_tap_errors](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L398) | Buffer tap errors. |
| [test_report](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L420) | Report. |
| [test_probed_fifo_sim_call](../../../src/tests/pypeline_tests/inst/stream_perf_test.py#L456) | Probed fifo sim call. |

### inst/stream_ram_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:stream_ram_test`, `synth_device_models:stream_ram_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_attributes](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L108) | Attributes. |
| [test_steady_flow_one_response_per_cycle](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L118) | Steady flow one response per cycle. |
| [test_stall_freezes_pipeline_and_holds_response](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L134) | Stall freezes pipeline and holds response. |
| [test_last_stage_bubble_is_filled](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L148) | Last stage bubble is filled. |
| [test_write_executes_once_per_accepted_request](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L160) | A write request held in the RAM stage by a stall writes once, when it finally advances; a request refused while stalled never writes at all. |
| [test_combinational_stream_ram](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L206) | Combinational stream ram. |
| [test_random_backpressure_soak](../../../src/tests/pypeline_tests/inst/stream_ram_test.py#L242) | Random valid/ready on a single rw port: the accepted responses, in order, must equal an independent replay of the accepted requests. |

### inst/struct_ctor_narrow_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:struct_ctor_narrow_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_struct_ctor_narrows_unsigned_overflow](../../../src/tests/pypeline_tests/inst/struct_ctor_narrow_test.py#L51) | p_t(c=a.c+1) at uint4_t max (15) must wrap to 0, matching o.c = a.c+1. |
| [test_struct_ctor_narrows_signed_overflow](../../../src/tests/pypeline_tests/inst/struct_ctor_narrow_test.py#L64) | q_t(c=a.c+1) at int4_t max (7) must wrap to -8 (sign-extend), not 8. |
| [test_struct_ctor_narrows_byte_boundary](../../../src/tests/pypeline_tests/inst/struct_ctor_narrow_test.py#L73) | r_t(c=a.c+1) at uint8_t max (255) must wrap to 0. |

### inst/sweep_comb_test.py

No direct Python entry registered; see caller/build registrations. Registration(s): `synth_device_models:sweep_comb_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_comb_sim](../../../src/tests/pypeline_tests/inst/sweep_comb_test.py#L34) | Sweep comb sim. |

### inst/sweep_cross_main_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:sweep_cross_main_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_real_fixture_path_roles](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L181) | Real fixture path roles. |
| [test_unrecognized_hierarchy_counts_as_reachable](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L210) | Unrecognized hierarchy counts as reachable. |
| [test_no_hierarchy_evidence_keeps_old_behavior](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L227) | No hierarchy evidence keeps old behavior. |
| [test_no_goal_owner_means_crossing_mains_still_own_it](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L243) | No goal owner means crossing mains still own it. |
| [test_scoped_attribution_ignores_other_mains_instances](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L253) | The encrypt plan's candidates include prep_auth_data_fsm and its interface wrapper. Unscoped, Tier-C substring scoring matched prep_auth_data_fsm against a cell of the DECRYPT instance (what the real sweep printed); scoped to encrypt's own cells nothing matches. |
| [test_attribution_basis_labels](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L284) | Attribution basis labels. |
| [test_snapshot_tie_rule_with_the_real_numbers](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L302) | Snapshot tie rule with the real numbers. |
| [test_crossing_path_never_drives_the_plans_it_crosses](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L422) | 'core' fails its own path until its helper is locked; 'flow' always meets its own. A planless fixture's path crossing both fails throughout (93.5 MHz). Each plan follows only its own paths; the fixture alone fails the build, naming what it crosses. |
| [test_old_rule_would_drive_crossed_plans](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L460) | Control: without hierarchy evidence (names a tool could not place) the same scenario keeps the old behavior -- every implicated MAIN owns the path, so 'flow' is re-pipelined by a path it cannot change. |
| [test_best_result_ties_prefer_met_own_paths](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L480) | 'a' fails its own path (95.2 MHz) until locked; 'b' is stuck on an unpipelinable own path (97.1 MHz); a crossing fixture path fails at 93.46 MHz unlocked / 93.28 MHz locked -- the same result within 1%. The old highest-ratio restore kept the unlocked implementation; ties now go to the one whose own paths are met. |
| [test_unattributed_endpoint_path_in_stateful_logic_names_the_blocker](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L508) | 'a' owns the end of a failing path whose every cell in 'a' sits in its stateful wrapper, and nothing in a's landscapes matches. Before, that was "no attribution" and rescaled the whole plan every iteration; now the blocker is named (by hierarchy) and the plan stops as unpipelinable. |
| [test_confirmation_keeps_crossed_mains_and_skips_unhelpful_fallback](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L534) | Confirmation keeps crossed mains and skips unhelpful fallback. |
| [test_lock_rules_for_regions](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L620) | Lock rules for regions. |
| [test_try_minisweep_streak_and_budget](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L643) | Try minisweep streak and budget. |
| [test_region_bootstrap_and_calibration_after_lock](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L659) | Region bootstrap and calibration after lock. |
| [test_start_latency_region_hotspot_takes_the_minisweep](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L736) | Start latency region hotspot takes the minisweep. |
| [test_capped_region_never_locks_inside](../../../src/tests/pypeline_tests/inst/sweep_cross_main_test.py#L746) | Capped region never locks inside. |

### inst/sweep_evidence_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:sweep_evidence_test`, `unit:sweep_evidence_test_seed777`.

| Declaration | Purpose / execution note |
|---|---|
| [test_concrete_lock_replays_identical_descendants_after_model_refresh](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L19) | Concrete lock replays identical descendants after model refresh. |
| [test_input_identity_follows_tool_inputs_not_location_or_provenance](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L74) | Input identity follows tool inputs not location or provenance. |
| [test_requested_overflow_survives_final_table_at_capacity](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L97) | Requested overflow survives final table at capacity. |
| [test_utilization_tables_are_read_by_header_columns](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L129) | Utilization tables are read by header columns. |
| [test_bank_dedup_keeps_fields_and_pipeline_stage](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L142) | Bank dedup keeps fields and pipeline stage. |
| [test_incomplete_and_errored_logs_are_not_accepted](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L166) | Incomplete and errored logs are not accepted. |
| [test_optional_compact_paths_preserve_mcp_normalization_and_coverage](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L193) | Optional compact paths preserve mcp normalization and coverage. |
| [test_mcp_seed_uses_raw_endpoint_evidence_and_honors_caps](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L206) | Mcp seed uses raw endpoint evidence and honors caps. |
| [test_fit_stop_records_evidence_before_any_timing_feedback](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L244) | Fit stop records evidence before any timing feedback. |
| [test_region_latency_changes_survive_renamed_wrappers](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L277) | The 40 MHz fit-stop record showed previous: null for the Poly1305 bodies because re-elaboration renamed their lane wrappers. Region depths are keyed by owning MAIN and canonical key; physical paths are evidence. |
| [test_scripted_shared_clock_freezes_unimplicated_and_skips_noops](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L307) | Scripted shared clock freezes unimplicated and skips noops. |
| [test_mcp_only_confirmation_repairs_all_groups_in_one_feedback_round](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L497) | Mcp only confirmation repairs all groups in one feedback round. |
| [test_locked_internal_endpoints_skip_boundary_policies](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L585) | Locked internal endpoints skip boundary policies. |
| [test_mcp_shape_ignores_reelaborated_handshake_but_tracks_arithmetic](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L605) | Mcp shape ignores reelaborated handshake but tracks arithmetic. |
| [test_mcp_provisional_confirm_down_once_restores_failed_trial](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L632) | Mcp provisional confirm down once restores failed trial. |
| [test_optional_report_errors_do_not_block_the_log](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L676) | Optional report errors do not block the log. |
| [test_optional_tcl_is_caught_and_mcp_pairs_use_constraint_pins](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L703) | Optional tcl is caught and mcp pairs use constraint pins. |
| [test_failing_evidence_sorts_first_and_planless_keeps_worst](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L725) | Failing evidence sorts first and planless keeps worst. |
| [test_passing_optional_path_never_erases_a_capped_mcp_failure](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L792) | Passing optional path never erases a capped mcp failure. |
| [test_carried_locks_belong_to_their_main_and_obey_lock_rules](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L837) | Carried locks belong to their main and obey lock rules. |
| [test_locked_interior_match_uses_marker_prefix_and_hotspot](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L888) | Locked interior match uses marker prefix and hotspot. |
| [test_mcp_confirmation_repair_is_bounded](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L907) | Mcp confirmation repair is bounded. |
| [test_confirm_down_reuses_an_observed_candidate](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L958) | Confirm down reuses an observed candidate. |
| [test_isolated_mcp_evidence_keeps_the_worst_replica](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L984) | Isolated mcp evidence keeps the worst replica. |
| [test_lock_survives_real_reelaboration_with_resized_lanes](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1013) | A real two-pass parse (like pin-and-confirm): pass 2 resizes the latency-sized lanes and adds helper instances. The owning MAIN reuses the concrete interior on every instance; the other MAIN inherits nothing. |
| [test_seed_replays_entity_hash_after_real_reelaboration](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1069) | A resized lane wrapper and renamed call sites preserve heterogeneous placements in repeated helpers, including the deliberately empty calls. |
| [test_confirmation_prints_one_worst_value_per_main](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1129) | Confirmation prints one worst value per main. |
| [test_estimated_unsliceable_span_is_not_an_impossibility_verdict](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1148) | Estimated unsliceable span is not an impossibility verdict. |
| [test_pipelined_confirmation_failure_preserves_unaffected_mains](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1164) | Pipelined confirmation failure preserves unaffected mains. |
| [test_confirmation_skipped_when_mcp_seed_changes_consumed_count](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1218) | A consumed AUTO_MULTI_CYCLE count sets the handshake's compare constant, so a changed seed means re-elaboration is certain. Only a count that matches the consumed hardware is worth a confirmation. |
| [test_trim_probes_uneven_stages_despite_small_timing_margin](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1359) | Trim probes uneven stages despite small timing margin. |
| [test_trim_probes_when_worst_path_is_in_an_uncut_subtree](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1366) | Trim probes when worst path is in an uncut subtree. |
| [test_trim_failed_probe_restores_passing_implementation](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1373) | Trim failed probe restores passing implementation. |
| [test_trim_zero_effort_accepts_first_passing_implementation](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1378) | Trim zero effort accepts first passing implementation. |
| [test_trim_probes_removing_the_last_optional_cut](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1382) | Trim probes removing the last optional cut. |
| [test_trim_failed_zero_cut_probe_restores_the_passing_registers](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1387) | Trim failed zero cut probe restores the passing registers. |
| [test_infinite_budget_needs_no_optional_cut_before_an_atomic_tail](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1392) | Infinite budget needs no optional cut before an atomic tail. |
| [test_infinite_budget_retains_required_placement_units](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1402) | Infinite budget retains required placement units. |
| [test_zero_density_trim_preserves_fixed_latency_region_count](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1413) | Zero density trim preserves fixed latency region count. |
| [test_zero_density_trim_removes_optional_region_cuts](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1418) | Zero density trim removes optional region cuts. |
| [test_unresolved_region_keeps_zero_cut_probe_during_mcp_repair](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1429) | Unresolved region keeps zero cut probe during mcp repair. |
| [test_replayed_plan_keeps_the_landscape_its_cuts_came_from](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1456) | A met MAIN replays its snapshot while a delay-model refresh shrinks the landscape (the measured fallback). Its cut offsets must not be evaluated against the rebuilt axis (the 40 MHz WireGuard run's IndexError). |
| [test_fresh_concrete_candidate_is_tried_before_measured_fallback](../../../src/tests/pypeline_tests/inst/sweep_evidence_test.py#L1505) | A stagnant MAIN that just received a new concrete lock is not yet stagnant: the lock is synthesized first, and the broad measured fallback runs only if stagnation persists (the 40 MHz run measured 25 functions before trying two fresh locks that then met). |

### inst/sweep_floor_detect_design.py

No direct Python entry registered; see caller/build registrations. Registration(s): indirect/manual.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_floor_sim](../../../src/tests/pypeline_tests/inst/sweep_floor_detect_design.py#L55) | Sweep floor sim. |

### inst/sweep_fsm_auto_pipeline_test.py

No direct Python entry registered; see caller/build registrations. Registration(s): `synth_device_models:sweep_fsm_auto_pipeline_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_fsm_auto_pipeline_sim](../../../src/tests/pypeline_tests/inst/sweep_fsm_auto_pipeline_test.py#L82) | Sweep fsm auto pipeline sim. |

### inst/sweep_history_record_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:sweep_history_record_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_assumed_met_is_lower_bound_not_fmax](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L40) | Assumed met is lower bound not fmax. |
| [test_measured_met_is_not_lower_bound](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L61) | Measured met is not lower bound. |
| [test_timing_failure_overrides_outcome](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L75) | Timing failure overrides outcome. |
| [test_confirmation_supersedes_sweep_and_iterations_accumulate](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L93) | Confirmation supersedes sweep and iterations accumulate. |
| [test_restored_snapshot_keeps_its_iteration](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L118) | Restored snapshot keeps its iteration. |
| [test_unverified_and_goalless_have_no_verdict](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L136) | Unverified and goalless have no verdict. |
| [test_writer_schema_and_planless_entry](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L150) | Writer schema and planless entry. |
| [test_retained_observation_matches_winner_and_constraints](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L201) | A restored winner's retained observation is the newest one with its exact implementation signature: entity hash, clocks AND multi-cycle counts. A newer log of another implementation -- same HDL with different MCP constraints, or an over-capacity netlist -- never supplies it. |
| [test_over_capacity_record_is_never_a_pass](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L294) | Default mode (no --stop_on_over_capacity) keeps sweeping an over-capacity netlist; meeting timing there is still not a pass. |
| [test_over_capacity_final_netlist_fails_the_build](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L324) | The retained (built) implementation is over capacity but met timing: final.met is False and sweep_timing_failures -- the exit code's list -- gets a device_over_capacity entry. A goal-less MAIN is not blamed. |
| [test_writer_skips_when_nothing_recorded](../../../src/tests/pypeline_tests/inst/sweep_history_record_unit_test.py#L396) | Writer skips when nothing recorded. |

### inst/sweep_planless_design.py

No direct Python entry registered; see caller/build registrations. Registration(s): indirect/manual.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_planless_sim](../../../src/tests/pypeline_tests/inst/sweep_planless_design.py#L32) | Sweep planless sim. |

### inst/sweep_plateau_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:sweep_plateau_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_handoff_trace_stops_at_iter_6](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L38) | Handoff trace stops at iter 6. |
| [test_still_improving_does_not_stop](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L45) | Still improving does not stop. |
| [test_flat_without_cut_growth_does_not_stop](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L53) | Flat without cut growth does not stop. |
| [test_short_window_does_not_stop](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L59) | Short window does not stop. |
| [test_met_or_incomplete_record_does_not_stop](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L64) | Met or incomplete record does not stop. |
| [test_only_tail_counts](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L74) | Only tail counts. |
| [test_window_start_slice_respected](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L80) | Window start slice respected. |
| [test_streak_parameter](../../../src/tests/pypeline_tests/inst/sweep_plateau_unit_test.py#L89) | Streak parameter. |

### inst/sweep_refinement_recovery_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:sweep_refinement_recovery_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_flattened_device_model_paths_still_check_every_main](../../../src/tests/pypeline_tests/inst/sweep_refinement_recovery_test.py#L27) | Flattened device model paths still check every main. |
| [test_failed_zero_cut_probe_recovers_after_mcp_count_repair](../../../src/tests/pypeline_tests/inst/sweep_refinement_recovery_test.py#L46) | Failed zero cut probe recovers after mcp count repair. |
| [test_failed_trim_tests_a_new_helper_lock_before_restoring_the_met_snapshot](../../../src/tests/pypeline_tests/inst/sweep_refinement_recovery_test.py#L77) | Failed trim tests a new helper lock before restoring the met snapshot. |
| [test_opaque_path_is_refined_after_combinational_fallback_before_floor_stop](../../../src/tests/pypeline_tests/inst/sweep_refinement_recovery_test.py#L105) | Opaque path is refined after combinational fallback before floor stop. |

### inst/sweep_stateful_boundary_test.py

No direct Python entry registered; see caller/build registrations. Registration(s): `synth_device_models:sweep_stateful_boundary_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_boundary_sim](../../../src/tests/pypeline_tests/inst/sweep_stateful_boundary_test.py#L43) | Sweep boundary sim. |

### inst/sweep_two_mains_test.py

No direct Python entry registered; see caller/build registrations. Registration(s): `synth_device_models:sweep_two_mains_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_two_mains_sim](../../../src/tests/pypeline_tests/inst/sweep_two_mains_test.py#L38) | Sweep two mains sim. |

### inst/sweep_unpipelinable_design.py

No direct Python entry registered; see caller/build registrations. Registration(s): indirect/manual.

| Declaration | Purpose / execution note |
|---|---|
| [test_sweep_unpipelinable_sim](../../../src/tests/pypeline_tests/inst/sweep_unpipelinable_design.py#L32) | Sweep unpipelinable sim. |

### inst/syn_cache_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `build_report_pyrtl:syn_cache_test`, `build_report_open_tools:syn_cache_netlist_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_manifest_identity](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L133) | Manifest identity. |
| [test_reuse_log](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L165) | Reuse log. |
| [test_store](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L192) | Store. |
| [test_reuse_only](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L234) | Reuse only. |
| [test_stale_inputs_rebuild](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L289) | Stale inputs rebuild. |
| [test_final_vhdl_follows_edit](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L306) | Final vhdl follows edit. |
| [test_shared_store](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L324) | Shared store. |
| [test_stored_measurements](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L341) | Stored measurements. |
| [test_sim_only_param_reuses](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L368) | Sim only param reuses. |
| [test_yosys_json_never_cached](../../../src/tests/pypeline_tests/inst/syn_cache_test.py#L377) | Yosys json never cached. |

### inst/synthesis_scope_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:synthesis_scope_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_bank_helpers_are_estimated_from_primitive_dependencies](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L68) | Bank helpers are estimated from primitive dependencies. |
| [test_shared_pipeline_helper_is_measured_without_authorizing_blocked_calls](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L82) | Shared pipeline helper is measured without authorizing blocked calls. |
| [test_stateful_surroundings_have_no_standalone_hierarchy_measurements](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L91) | Stateful surroundings have no standalone hierarchy measurements. |
| [test_opaque_text_starts_at_zero_without_standalone_measurement](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L112) | Opaque text starts at zero without standalone measurement. |
| [test_opaque_text_does_not_consult_cached_scalar_delays_in_any_mode](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L125) | Opaque text does not consult cached scalar delays in any mode. |
| [test_unrelated_controller_has_no_geometry_jobs](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L141) | Unrelated controller has no geometry jobs. |
| [test_scheduled_fsm_is_one_measured_atomic_span](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L157) | Scheduled fsm is one measured atomic span. |
| [test_unmarked_stateful_function_without_consumer_has_no_jobs](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L172) | Unmarked stateful function without consumer has no jobs. |
| [test_opaque_fallback_requires_failing_path_evidence_in_the_plan](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L178) | Opaque fallback requires failing path evidence in the plan. |
| [test_mcp_endpoint_evidence_is_separate_from_geometry_and_reused_by_shape](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L202) | Mcp endpoint evidence is separate from geometry and reused by shape. |
| [test_opaque_fallback_refreshes_zero_only_ancestor_geometry](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L225) | Opaque fallback refreshes zero only ancestor geometry. |
| [test_fallback_ignores_estimated_surroundings_and_returns_no_change](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L238) | Fallback ignores estimated surroundings and returns no change. |
| [test_fallback_measures_only_eligible_combinational_estimates](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L251) | Fallback measures only eligible combinational estimates. |
| [test_fully_combinational_main_retains_frontier_measurement](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L267) | Fully combinational main retains frontier measurement. |
| [test_goal_less_combinational_main_has_no_geometry_jobs](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L273) | Goal less combinational main has no geometry jobs. |
| [test_goal_less_fixed_latency_region_remains_a_geometry_consumer](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L281) | Goal less fixed latency region remains a geometry consumer. |
| [test_delay_scope_is_declared_before_characterization](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L289) | Delay scope is declared before characterization. |
| [test_delay_measurement_requires_explicit_scope_initialization](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L296) | Delay measurement requires explicit scope initialization. |
| [test_rooted_characterization_preserves_the_full_parse_scope](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L308) | Rooted characterization preserves the full parse scope. |
| [test_parser_state_copy_preserves_independent_delay_scope_collections](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L319) | Parser state copy preserves independent delay scope collections. |
| [test_unseeded_goal_having_tag_has_its_own_placement_region](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L330) | Unseeded goal having tag has its own placement region. |
| [test_goal_less_unconstrained_tag_has_no_geometry_jobs](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L340) | Goal less unconstrained tag has no geometry jobs. |
| [test_tag_placements_do_not_depend_on_surrounding_stateful_delays](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L349) | Tag placements do not depend on surrounding stateful delays. |
| [test_estimated_blocked_spans_cannot_establish_a_hard_floor](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L370) | Estimated blocked spans cannot establish a hard floor. |
| [test_primitive_only_mode_keeps_mcp_evidence_but_skips_comb_frontier](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L383) | Primitive only mode keeps mcp evidence but skips comb frontier. |
| [test_explicit_full_hierarchy_mode_retains_unrelated_diagnostics](../../../src/tests/pypeline_tests/inst/synthesis_scope_test.py#L389) | Explicit full hierarchy mode retains unrelated diagnostics. |

### inst/two_factory_wrappers_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:two_factory_wrappers_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_two_factory_wrappers_distinct_logic](../../../src/tests/pypeline_tests/inst/two_factory_wrappers_test.py#L87) | Two factory wrappers distinct logic. |
| [test_two_list_parameterized_instances_get_distinct_logic](../../../src/tests/pypeline_tests/inst/two_factory_wrappers_test.py#L146) | Two list parameterized instances get distinct logic. |
| [test_list_parameterized_factory_matches_golden_in_sim](../../../src/tests/pypeline_tests/inst/two_factory_wrappers_test.py#L186) | List parameterized factory matches golden in sim. |

### inst/type_axis_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:type_axis_test`, `synth_device_models:type_axis_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_one_per_packet_exact_frame](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L207) | One per packet exact frame. |
| [test_one_per_packet_drops_ethernet_style_padding](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L214) | THE reason the limiter exists, and a REGRESSION for axis.h:527's underflow. A 7-byte struct arriving in a 16-byte padded frame must decode to exactly one value -- the padding dropped, not decoded as a second. |
| [test_one_per_packet_back_to_back_frames_stay_aligned](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L224) | Two padded frames in a row: the limiter must re-arm per frame, so both decode identically and nothing drifts. |
| [test_tx_one_per_packet_tlast_and_partial_keep](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L233) | REGRESSION for axis.h:650 (tkeep hardcoded all-ones) and axis.h:653 (tlast unqualified). Each value gets its own frame, ending in a beat whose keep is the real remaining byte count. |
| [test_tx_one_per_packet_frames_each_value](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L245) | Tx one per packet frames each value. |
| [test_axis_round_trip_one_per_packet](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L252) | Axis round trip one per packet. |
| [test_many_per_packet_tx_one_frame](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L262) | The mode old axis_to_type was meant to be, shipped `#if 0`'d (axis.h:598) because of a stale signature. Three 3-byte values -> one 9-byte frame, boundaries straddling beats, tlast only at the end. |
| [test_many_per_packet_rx_splits_frame](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L273) | Many per packet rx splits frame. |
| [test_many_per_packet_round_trip](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L281) | Many per packet round trip. |
| [test_structs_per_packet_counter_frames_every_k](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L288) | structs_per_packet=3: two frames' worth of values must produce exactly two tlasts, without the caller driving eod at all. |
| [test_runt_then_good_frame_resyncs](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L300) | REGRESSION for axis.h:561-595: old axis_packet_to_type never flushed the deserializer on tlast, so one short frame permanently desynced the value boundary. The good frame after a runt must decode correctly, and .runt must pulse exactly once. |
| [test_runt_zero_pad_emits_padded_value](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L313) | Runt zero pad emits padded value. |
| [test_runt_ignore_reproduces_old_desync](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L321) | Documents what this library deliberately no longer does by default. |
| [test_rx_consumes_partial_keep_beat](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L335) | REGRESSION for axis.h:587, which ignored tkeep for data and shifted all bus bytes in regardless. A frame whose last beat is partial must contribute only its kept bytes. |
| [test_tx_produces_contiguous_prefix_keep](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L347) | Every emitted beat must be Xilinx-style: full keep unless it carries eod, and a contiguous prefix even then. |
| [test_bad_options_rejected](../../../src/tests/pypeline_tests/inst/type_axis_test.py#L361) | Bad options rejected. |

### inst/type_byte_stream_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:type_byte_stream_test`, `synth_device_models:type_byte_stream_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_wire_bytes_match_software_layout](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L247) | THE contract. Whatever the hardware puts on the wire is exactly what a software author gets from pypeline.type_to_bytes for the same value. |
| [test_partial_final_beat_keep](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L265) | A 7-byte struct on a 4-byte bus: 2 beats, the last carrying 3 bytes. Old type_to_axis hardcoded tkeep all-ones (axis.h:650), making this inexpressible -- and the underlying serializer deadlocked outright. |
| [test_aligned_type_has_no_partial_beat](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L277) | Aligned type has no partial beat. |
| [test_eod_exactly_once_per_value](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L285) | Eod exactly once per value. |
| [test_loopback_all_shapes](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L297) | tx -> rx recovers each value, including the enum-bearing nested struct and a bare array type. |
| [test_software_built_frame_decodes_in_hardware](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L312) | The direction a software author actually cares about: build the bytes in Python with type_to_bytes, feed them in as beats, get the struct out. |
| [test_padding_exact_propagates_type_level_message](../../../src/tests/pypeline_tests/inst/type_byte_stream_test.py#L333) | A non-divisible struct with padding='exact' must name the byte length, the bus width and the way out -- not deadlock like the old macros. |

### inst/type_bytes_sw_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:type_bytes_sw_test`, `elab:type_bytes_sw_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_scalar_endianness](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L136) | Scalar endianness. |
| [test_length_always_byte_length](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L144) | Length always byte length. |
| [test_roundtrip_all_fixtures](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L151) | Roundtrip all fixtures. |
| [test_struct_layout_explicit](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L162) | Spell the packed/unpadded layout out byte by byte, so a change in field order, leaf rounding, or ragged-width handling fails loudly rather than staying self-consistent. |
| [test_signed_leaves_come_back_negative](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L187) | Signed leaves come back negative. |
| [test_enum_leaf](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L196) | Enum leaf. |
| [test_ragged_leaf_masks_high_bits](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L206) | A uint12_t leaf occupies 2 bytes but only 12 bits are significant -- packing must zero the top nibble and unpacking must ignore it, matching the hardware's tmp[hi:lo] slicing. |
| [test_accepted_input_shapes](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L216) | Every value shape native sim produces or accepts must pack identically. |
| [test_bytes_like_and_iterable_input](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L230) | Bytes like and iterable input. |
| [test_char_array_returns_charray](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L241) | Char array returns charray. |
| [test_classmethods_agree_with_module_functions](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L248) | Classmethods agree with module functions. |
| [test_struct_field_named_to_bytes_rejected](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L257) | Struct field named to bytes rejected. |
| [test_errors](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L270) | Errors. |
| [test_sw_matches_hw](../../../src/tests/pypeline_tests/inst/type_bytes_sw_test.py#L297) | The contract: software and hardware are one layout, not two. |

### inst/type_bytes_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:type_bytes_test`, `elab:type_bytes_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_byte_length](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L287) | Byte length. |
| [test_byte_length_enum](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L300) | Byte length enum. |
| [test_enum_array_not_expressible](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L310) | `some_enum_t[N]` is not a pypeline type at all: @struct installs __class_getitem__ but @enum does not, so the subscript hits EnumMeta.__getitem__ (member lookup by name). An enum inside a struct inside an array -- has_enum_t[3] above -- is the supported spelling. |
| [test_enum_struct_roundtrip](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L323) | Enum struct roundtrip. |
| [test_nested_enum_roundtrip](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L334) | Nested enum roundtrip. |
| [test_array_of_enum_bearing_struct_roundtrip](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L350) | Array of enum bearing struct roundtrip. |
| [test_enum_ragged_width_masking](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L362) | A wide_state_t leaf is 4 bits in a 1-byte slot. Hardware truncates the upper nibble; native sim must agree (this is what the generated uintN_t temp buys -- a direct `rv.w = src[i]` would keep all 8 bits in sim only). |
| [test_wires_tagged](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L371) | Wires tagged. |
| [test_scalar_roundtrip_le](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L379) | Scalar roundtrip le. |
| [test_scalar_roundtrip_be](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L389) | Scalar roundtrip be. |
| [test_array_of_scalar_roundtrip](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L399) | Array of scalar roundtrip. |
| [test_struct_roundtrip_byte_rounding](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L408) | Struct roundtrip byte rounding. |
| [test_nested_struct_roundtrip](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L418) | Nested struct roundtrip. |
| [test_array_of_struct_roundtrip](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L426) | Array of struct roundtrip. |
| [test_chacha20_state_regression](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L435) | Regression proof for the wireguard-fpga migration this feature enables: byte_length() replaces the hand-maintained CHACHA20_BLOCK_SIZE constant, and the generated from_bytes function reproduces the same little-endian per-word byte layout chacha20_init() currently builds manually via nested concat() calls. |
| [test_u320_regression](../../../src/tests/pypeline_tests/inst/type_bytes_test.py#L452) | U320 regression. |

### inst/typed_pipeline_placement_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:typed_pipeline_placement_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_landscape_exposes_typed_candidates](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L68) | Landscape exposes typed candidates. |
| [test_coherent_boundary_wins_same_position](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L84) | Coherent boundary wins same position. |
| [test_fixed_position_partitions_budget](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L94) | Fixed position partitions budget. |
| [test_slightly_sub_budget_helpers_cut_at_previous_boundary](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L104) | Slightly sub budget helpers cut at previous boundary. |
| [test_setup_op_and_repeated_helpers_do_not_merge_or_leave_empty_tail](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L136) | Setup op and repeated helpers do not merge or leave empty tail. |
| [test_planner_component_weights_change_geometry_not_total_budget](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L195) | Planner component weights change geometry not total budget. |
| [test_typed_lowering_is_local_not_recursive](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L216) | Typed lowering is local not recursive. |
| [test_input_boundary_is_a_typed_local_placement](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L242) | Input boundary is a typed local placement. |
| [test_minisweep_serial_topology_shares_one_boundary_per_edge](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L285) | Minisweep serial topology shares one boundary per edge. |
| [test_minisweep_topology_does_not_cross_an_operation](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L306) | Minisweep topology does not cross an operation. |
| [test_minisweep_boundary_cover_respects_no_io_pragma_and_fingerprint](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L317) | Minisweep boundary cover respects no io pragma and fingerprint. |
| [test_minisweep_boundary_cover_shares_fanout_and_fanin_banks](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L332) | Minisweep boundary cover shares fanout and fanin banks. |
| [test_minisweep_zero_cut_pass_never_locks_io_only_latency](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L346) | An isolated helper that already meets timing needs no IO-only lock. |
| [test_bit_requests_materialize_to_raw_equal_width_boundaries](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L385) | Bit requests materialize to raw equal width boundaries. |
| [test_exact_typed_bit_boundaries_lower_and_hash_distinctly](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L454) | Exact typed bit boundaries lower and hash distinctly. |
| [test_internal_exact_bit_boundary_group_resolves_without_raster_aliasing](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L486) | Internal exact bit boundary group resolves without raster aliasing. |
| [test_chunked_mux_refinement_replaces_outputs_and_covers_terminal_tail](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L517) | Chunked mux refinement replaces outputs and covers terminal tail. |
| [test_chunked_mux_lowering_preserves_group_identity](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L626) | Chunked mux lowering preserves group identity. |
| [test_chunked_mux_skips_partially_qualifying_group](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L686) | Chunked mux skips partially qualifying group. |
| [test_parallel_output_frontier_grouping_and_serial_rejection](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L785) | Parallel output frontier grouping and serial rejection. |
| [test_component_stage_budget_and_legacy_fallback](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L842) | Component stage budget and legacy fallback. |
| [test_parallel_bit_frontier_is_one_logical_cut](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L913) | Parallel bit frontier is one logical cut. |
| [test_parallel_bit_frontier_can_move_as_one_physical_group](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L935) | Parallel bit frontier can move as one physical group. |
| [test_common_coherent_boundary_beats_parallel_leaf_group](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L967) | Common coherent boundary beats parallel leaf group. |
| [test_two_cuts_per_leaf_move_the_whole_bit_frontier](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L979) | Two cuts per leaf move the whole bit frontier. |
| [test_moved_bit_frontier_group_is_accepted](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L1050) | Moved bit frontier group is accepted. |
| [test_split_bit_frontier_group_is_rejected](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L1092) | Split bit frontier group is rejected. |
| [test_incomplete_group_is_rejected](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L1128) | Incomplete group is rejected. |
| [test_internal_selector_is_deterministic_and_strict](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L1150) | Internal selector is deterministic and strict. |
| [test_internal_placement_file_rejects_empty_request](../../../src/tests/pypeline_tests/inst/typed_pipeline_placement_test.py#L1174) | Internal placement file rejects empty request. |

### inst/valid_join_test.py

Python entry registered; module auto-discovery. Registration(s): `native_sim:valid_join_test`, `native_vs_vhdl_sim:valid_join_test_comb`.

| Declaration | Purpose / execution note |
|---|---|
| [test_independent_arrivals](../../../src/tests/pypeline_tests/inst/valid_join_test.py#L64) | Independent arrivals. |
| [test_one_result_per_clock](../../../src/tests/pypeline_tests/inst/valid_join_test.py#L95) | One result per clock. |
| [test_overflow_is_detected](../../../src/tests/pypeline_tests/inst/valid_join_test.py#L116) | Overflow is detected. |

### inst/vhdl_submodule_port_map_test.py

Python entry registered; module auto-discovery. Registration(s): `unit:vhdl_submodule_port_map_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_every_submodule_port_map_is_exact](../../../src/tests/pypeline_tests/inst/vhdl_submodule_port_map_test.py#L67) | Every submodule port map is exact. |

### inst/vhdl_text_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `native_sim:vhdl_text_test`, `synth_device_models:vhdl_text_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_vhdl_text_sim_raises](../../../src/tests/pypeline_tests/inst/vhdl_text_test.py#L27) | Vhdl text sim raises. |

### inst/vivado_version_unit_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `unit:vivado_version_unit_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_parses_two_and_three_part_versions](../../../src/tests/pypeline_tests/inst/vivado_version_unit_test.py#L32) | Parses two and three part versions. |
| [test_fixed_pkg_cutoff_compares_as_a_version_not_a_float](../../../src/tests/pypeline_tests/inst/vivado_version_unit_test.py#L43) | Fixed pkg cutoff compares as a version not a float. |

### inst/wires_contract_test.py

Python entry registered; custom entrypoint/manual calls. Registration(s): `elab_introspect:wires_contract_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_stateful_testbench_main_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L67) | Stateful testbench main is not wires. |
| [test_logic_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L89) | Logic is not wires. |
| [test_stateful_callee_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L104) | Stateful callee is not wires. |
| [test_variable_index_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L128) | Variable index is not wires. |
| [test_logic_feeding_an_output_and_a_sim_builtin_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L141) | Logic feeding an output and a sim builtin is not wires. |
| [test_auto_wrapped_cast_with_logic_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L155) | Auto wrapped cast with logic is not wires. |
| [test_untagged_raw_vhdl_callee_is_not_wires](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L173) | Untagged raw vhdl callee is not wires. |
| [test_genuine_wires_are_accepted](../../../src/tests/pypeline_tests/inst/wires_contract_test.py#L197) | Genuine wires are accepted. |

### inst/wiring_only_leaf_zero_delay_test.py

Python entry registered; module auto-discovery. Registration(s): `elab_introspect:wiring_only_leaf_zero_delay_test`.

| Declaration | Purpose / execution note |
|---|---|
| [test_stateless_function_without_submodules_is_zero_delay](../../../src/tests/pypeline_tests/inst/wiring_only_leaf_zero_delay_test.py#L78) | Stateless function without submodules is zero delay. |
| [test_constant_only_function_is_zero_delay](../../../src/tests/pypeline_tests/inst/wiring_only_leaf_zero_delay_test.py#L84) | Constant only function is zero delay. |
| [test_stateful_function_without_submodules_is_timed](../../../src/tests/pypeline_tests/inst/wiring_only_leaf_zero_delay_test.py#L90) | Stateful function without submodules is timed. |
| [test_function_with_an_operator_is_timed](../../../src/tests/pypeline_tests/inst/wiring_only_leaf_zero_delay_test.py#L97) | Function with an operator is timed. |


## History

### Review provenance

The source review was completed on 2026-10-25 at commit `ddd87701a255e8e9de9383f94cf7814e4b0055b7`. Timings come from the 2026-10-22 partial run and are summed per-test elapsed time under concurrency, not CPU time or suite wall time. Worker count and full cache provenance were not retained. Exact commands, source hashes, timings and snapshot validation are preserved in [REVIEW_MANIFEST.json](REVIEW_MANIFEST.json). Moving these documents into the repository does not refresh the source review or establish current test status.
