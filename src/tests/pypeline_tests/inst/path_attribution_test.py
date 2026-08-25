#!/usr/bin/env python3
# In-process unit tests for SWEEP.RANK_PATH_FUNC_CANDIDATES /
# WHY_HOTSPOT_NOT_PIPELINABLE / RESOLVE_PIPELINABLE_HOTSPOT.
#
# Real bug (wireguard-fpga `./build.py --dec --sim --native`, 80 MHz goal):
# the sweep stopped after 2 iterations blaming
# `if8040c842_decrypt_dataflow_core_077e07da383ed36e_inst18` (an
# auto-generated interface-func wrapper) for a critical path that Vivado's
# own timing report shows runs entirely between two registers inside
# `chacha20_chacha20_block_step`, many levels deeper.
#
# Root cause: the old scorer summed `len(candidate_name)` once per matching
# endpoint/resource string. Every ancestor's name is a substring of a
# descendant register's fully-qualified name (each hierarchy level just
# prepends its own instance name), so the score carried no depth signal at
# all - it just picked whichever candidate name happened to be longest.
# Confirmed by replaying the real Vivado report through the real scorer:
# the 58-char wrapper scored 14112 and beat the 29-char
# `chacha20_chacha20_block_step` at 7056, even though all four matched
# candidates matched every endpoint and every one of 250 netlist resources
# (see test_wireguard_decrypt_blames_chacha_not_the_interface_wrapper).
#
# Fix: rank by the deepest (rightmost) substring match position shared by
# every available endpoint name first - the two endpoint names share their
# textual prefix down to the lowest common ancestor of the two registers,
# so this finds the true LCA without ever needing exact hierarchical
# matching (still substring-based; post-synthesis names below the MAIN
# stay mangled tool-dependently). Falls back to the old summed-length
# score only when no candidate matches any endpoint name at all.
#
# A second, independent defect this uncovered: even with the true LCA
# correctly attributed, that LCA can legitimately be unsliceable itself
# (state/feedback at its own level) while wrapping other, unrelated
# sliceable logic - the sweep must not treat that as "nothing here can be
# autopipelined" without checking whether a different candidate on the
# same path can still be densified. RESOLVE_PIPELINABLE_HOTSPOT covers
# that scan.
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import SWEEP


class FakePathReport:
    def __init__(self, start_reg_name=None, end_reg_name=None, netlist_resources=()):
        self.start_reg_name = start_reg_name
        self.end_reg_name = end_reg_name
        self.netlist_resources = set(netlist_resources)


class FakeLogic:
    def __init__(
        self,
        func_name,
        can_have_added_latency=True,
        feedback_vars=(),
        uses_nonvolatile_state_regs=False,
        submodule_instances=None,
        is_new_style_bit_manip=False,
    ):
        self.func_name = func_name
        self._can_have_added_latency = can_have_added_latency
        self.feedback_vars = list(feedback_vars)
        self.uses_nonvolatile_state_regs = uses_nonvolatile_state_regs
        self.submodule_instances = dict(submodule_instances or {})
        # WHY_NOT_SLICEABLE / LOGIC_IS_ZERO_DELAY mirror fields
        self.is_new_style_bit_manip = is_new_style_bit_manip
        self.is_c_built_in = False
        self.is_clock_crossing = False
        self.is_vhdl_func = False
        self.is_vhdl_expr = False
        self.vhdl_module_text = None

    def CAN_HAVE_ADDED_LATENCY(self, _parser_state):
        return self._can_have_added_latency

    def CAN_USE_AUTOPIPELINING(self, parser_state):
        return self._can_have_added_latency


class FakeParserState:
    def __init__(self, inst_to_logic, extra_func_logics=()):
        self.LogicInstLookupTable = dict(inst_to_logic)
        self.FuncLogicLookupTable = {
            logic.func_name: logic for logic in inst_to_logic.values()
        }
        for logic in extra_func_logics:
            self.FuncLogicLookupTable[logic.func_name] = logic
        self.func_fixed_latency = {}
        self.func_marked_blackbox = set()
        self.func_marked_wires = set()


def _plan(main_func, ancestor_func_sets, extra_func_logics=(), target_mhz=100.0):
    """One-subtree plan whose landscape carries one ATOMIC Segment per given
    ancestor_funcs set. RANK_PATH_FUNC_CANDIDATES only reads plan.main_inst,
    plan.subtrees, and landscape.segments[*].ancestor_funcs."""
    main_inst = "main"
    plan = SWEEP.MainSweepPlan(main_inst, target_mhz)
    plan.subtrees = [main_inst]
    landscape = SWEEP.SliceLandscape(main_inst, 100, 1.0)
    for i, ancestor_funcs in enumerate(ancestor_func_sets):
        seg = SWEEP.Segment(
            f"{main_inst}__seg{i}",
            f"seg{i}_func",
            float(i),
            float(i + 1),
            SWEEP.Segment.ATOMIC,
            "not_sliceable",
        )
        seg.ancestor_funcs = set(ancestor_funcs)
        landscape.segments.append(seg)
    plan.landscapes = {main_inst: landscape}
    ps = FakeParserState({main_inst: FakeLogic(main_func)}, extra_func_logics)
    return plan, ps


# ─── Real wireguard-fpga decrypt path (source data for the bug report) ───
#
# PRE-RENAME HISTORICAL FIXTURE: these strings are a byte-for-byte capture
# from one specific past build, predating the generated-name readability
# work (see docs/PY_TO_LOGIC_DESIGN.md). Left exactly as recorded -- do NOT
# "modernize" these to the current naming scheme -- they still exercise
# RANK_PATH_FUNC_CANDIDATES's substring-depth-matching ranking exactly as
# intended, which is name-shape-agnostic by construction. See the separate
# post-rename-shape fixture below (_PR_START_REG etc.) for coverage of the
# CURRENT naming scheme's shapes (no if########_ prefix, readable-leading
# interface-func names, no module-prefix stutter, no redundant single-line
# "_el").

# Verbatim from generated-files-sim-pipe-dec-native/top/vivado_443bba56.log,
# the worst "Slack (VIOLATED)" path's Source:/Destination:, with the
# trailing /C and /D pin components stripped - exactly what
# VIVADO.PathReport.start_reg_name/end_reg_name hold.
_WG_START_REG = (
    "decrypt_dataflow_decrypt_dataflow_0CLK_6f395802/"
    "decrypt_dataflow_core_decrypt_dataflow_py_l27_c8_el36_ec5/"
    "chacha_func_pypeline_interface_func_gen_if8040c842_decrypt_dataflow_core_077e07da383ed36e_inst18_py_l20_c13_el20_ec148/"
    "pipeline_func_pypeline_interface_func_gen_ifbf63ab38_chacha20_instance_wiring_inst10_py_l12_c11_el12_ec74/"
    "autopipelined_func_stream_pipeline_py_l112_c36_el112_ec71/"
    "func_stream_pypeline_py_l1559_c14_el1559_ec24/"
    "func_stream_pipeline_py_l72_c14_el72_ec26/"
    "chacha20_chacha20_block_chacha20_py_l205_c12_el205_ec33/"
    "chacha20_chacha20_block_step_chacha20_py_l128_c12_el128_ec38/"
    "quarter_round_2_6_10_14_chacha20_py_l108_c13_el108_ec44/"
    "io_registers_r_reg[output_regs][return_output][state][3][1]"
)
_WG_END_REG = (
    "decrypt_dataflow_decrypt_dataflow_0CLK_6f395802/"
    "decrypt_dataflow_core_decrypt_dataflow_py_l27_c8_el36_ec5/"
    "chacha_func_pypeline_interface_func_gen_if8040c842_decrypt_dataflow_core_077e07da383ed36e_inst18_py_l20_c13_el20_ec148/"
    "pipeline_func_pypeline_interface_func_gen_ifbf63ab38_chacha20_instance_wiring_inst10_py_l12_c11_el12_ec74/"
    "autopipelined_func_stream_pipeline_py_l112_c36_el112_ec71/"
    "func_stream_pypeline_py_l1559_c14_el1559_ec24/"
    "func_stream_pipeline_py_l72_c14_el72_ec26/"
    "chacha20_chacha20_block_chacha20_py_l205_c12_el205_ec33/"
    "chacha20_chacha20_block_step_chacha20_py_l129_c12_el129_ec38/"
    "quarter_round_3_4_9_14_chacha20_py_l113_c13_el113_ec43/"
    "REG_STAGE0_s_reg[state][7][6]"
)
# The real 21-name ancestor_functions list recorded in this run's
# placement_trace.json for decrypt_dataflow_decrypt_dataflow (minus the
# MAIN's own name, which the real code excludes too).
_WG_ANCESTOR_FUNCS = {
    "BIN_OP_PLUS_uint32_t_uint32_t",
    "BIN_OP_XOR_uint32_t_uint32_t",
    "BIN_OP_XOR_uint8_t_uint8_t",
    "MUX_uint8_t",
    "autopipelined_func_has_input_reg_has_output_reg_d077aabe",
    "chacha20_chacha20_block",
    "chacha20_chacha20_block_step",
    "chacha20_chacha20_loop_body",
    "func_stream_func_chacha20_chacha20_loop_body_in_plain_t_stream_t_d2e83538_out_plain_t_e9e6dc91",
    "if8040c842_decrypt_dataflow_core_077e07da383ed36e_inst18",
    "ifbf63ab38_chacha20_instance_wiring_inst10",
    "quarter_round_a_0_b_4_c_8_d_12",
    "quarter_round_a_0_b_5_c_10_d_15",
    "quarter_round_a_1_b_5_c_9_d_13",
    "quarter_round_a_1_b_6_c_11_d_12",
    "quarter_round_a_2_b_6_c_10_d_14",
    "quarter_round_a_2_b_7_c_8_d_13",
    "quarter_round_a_3_b_4_c_9_d_14",
    "quarter_round_a_3_b_7_c_11_d_15",
    "stream_pipeline_func_8e3e72e6",
}
_WG_WRAPPER = "if8040c842_decrypt_dataflow_core_077e07da383ed36e_inst18"
_WG_HOTSPOT = "chacha20_chacha20_block_step"


def test_wireguard_decrypt_blames_chacha_not_the_interface_wrapper():
    path_report = FakePathReport(_WG_START_REG, _WG_END_REG)
    plan, ps = _plan("decrypt_dataflow_decrypt_dataflow", [_WG_ANCESTOR_FUNCS])
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert len(ranked) > 0, "expected at least one attribution candidate"
    assert ranked[0] == _WG_HOTSPOT, (
        f"expected the deepest common ancestor {_WG_HOTSPOT!r} to win, got "
        f"{ranked[0]!r} (full ranking: {ranked})"
    )
    assert _WG_WRAPPER != ranked[0]
    func, stage_info = SWEEP.ATTRIBUTE_PATH_TO_FUNC(path_report, plan, ps)
    assert func == _WG_HOTSPOT


# ─── Same scenario, current (post-rename) naming shapes ───────────────────
# Not a literal re-encoding of the wireguard build above -- a representative
# path built from the CURRENT naming conventions this work introduced, so the
# ranking algorithm (which is name-shape-agnostic: it works on shared
# substring depth, not length or a specific format) is exercised against
# them too, not only the pre-rename fixture's shapes.
_PR_START_REG = (
    "decrypt_dataflow_0CLK_6f395802/"
    "decrypt_dataflow_core_decrypt_dataflow_py_l27_c8_ec5/"
    "chacha_func_decrypt_dataflow_core_if8040c842_py_l20_c13_ec148/"
    "pipeline_func_chacha20_instance_wiring_ifbf63ab38_py_l12_c11_ec74/"
    "autopipelined_func_chacha20_chacha20_loop_body_has_input_reg_True_"
    "has_output_reg_True_chacha20_py_l112_c36_ec71/"
    "chacha20_block_chacha20_py_l205_c12_ec33/"
    "chacha20_block_step_chacha20_py_l128_c12_ec38/"
    "quarter_round_a_2_b_6_c_10_d_14_chacha20_py_l108_c13_ec44/"
    "io_registers_r_reg[output_regs][return_output][state][3][1]"
)
_PR_END_REG = (
    "decrypt_dataflow_0CLK_6f395802/"
    "decrypt_dataflow_core_decrypt_dataflow_py_l27_c8_ec5/"
    "chacha_func_decrypt_dataflow_core_if8040c842_py_l20_c13_ec148/"
    "pipeline_func_chacha20_instance_wiring_ifbf63ab38_py_l12_c11_ec74/"
    "autopipelined_func_chacha20_chacha20_loop_body_has_input_reg_True_"
    "has_output_reg_True_chacha20_py_l112_c36_ec71/"
    "chacha20_block_chacha20_py_l205_c12_ec33/"
    "chacha20_block_step_chacha20_py_l129_c12_ec38/"
    "quarter_round_a_3_b_4_c_9_d_14_chacha20_py_l113_c13_ec43/"
    "REG_STAGE0_s_reg[state][7][6]"
)
_PR_ANCESTOR_FUNCS = {
    "BIN_OP_PLUS_uint32_t_uint32_t",
    "BIN_OP_XOR_uint32_t_uint32_t",
    "BIN_OP_XOR_uint8_t_uint8_t",
    "MUX_uint8_t",
    "autopipelined_func_chacha20_chacha20_loop_body_has_input_reg_True_"
    "has_output_reg_True",
    "chacha20_block",
    "chacha20_block_step",
    "chacha20_loop_body",
    "decrypt_dataflow_core_if8040c842",
    "chacha20_instance_wiring_ifbf63ab38",
    "quarter_round_a_0_b_4_c_8_d_12",
    "quarter_round_a_0_b_5_c_10_d_15",
    "quarter_round_a_1_b_5_c_9_d_13",
    "quarter_round_a_1_b_6_c_11_d_12",
    "quarter_round_a_2_b_6_c_10_d_14",
    "quarter_round_a_2_b_7_c_8_d_13",
    "quarter_round_a_3_b_4_c_9_d_14",
    "quarter_round_a_3_b_7_c_11_d_15",
}
_PR_WRAPPER = "decrypt_dataflow_core_if8040c842"
_PR_HOTSPOT = "chacha20_block_step"


def test_post_rename_shapes_still_blame_chacha_not_the_interface_wrapper():
    path_report = FakePathReport(_PR_START_REG, _PR_END_REG)
    plan, ps = _plan("decrypt_dataflow", [_PR_ANCESTOR_FUNCS])
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert len(ranked) > 0, "expected at least one attribution candidate"
    assert ranked[0] == _PR_HOTSPOT, (
        f"expected the deepest common ancestor {_PR_HOTSPOT!r} to win, got "
        f"{ranked[0]!r} (full ranking: {ranked})"
    )
    assert _PR_WRAPPER != ranked[0]


def test_netlist_resources_cannot_outvote_a_deeper_endpoint_match():
    # Pad netlist_resources with many repeats of the wrapper's name - under
    # the old summed-length scoring this alone could tip a close score;
    # Tier A (true common ancestors from the endpoint names) must never
    # even consult resources when it already found a match.
    resources = {f"{_WG_WRAPPER}_net_{i}" for i in range(50)}
    path_report = FakePathReport(_WG_START_REG, _WG_END_REG, resources)
    plan, ps = _plan("decrypt_dataflow_decrypt_dataflow", [_WG_ANCESTOR_FUNCS])
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert ranked[0] == _WG_HOTSPOT


def test_missing_end_reg_name_falls_back_to_the_single_endpoint():
    # DEVICE_MODELS' primary-output endpoint case: end_reg_name is None.
    path_report = FakePathReport(_WG_START_REG, None)
    plan, ps = _plan("decrypt_dataflow_decrypt_dataflow", [_WG_ANCESTOR_FUNCS])
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert ranked[0] == _WG_HOTSPOT


# ─── Real sky130/yosys divider path (regression: must be unchanged) ──────

_DIV_START_REG = (
    r"$flatten\solution_64clk_17c0b934.\radix2_div_solution_py_l45_c18_el45_ec69."
    r"\for_i_10_bin_op_minus_solution_py_l33_c26_el33_ec38.$auto$ff.cc:266:slice$8526"
)
_DIV_END_REG = (
    r"$flatten\solution_64clk_17c0b934.\radix2_div_solution_py_l45_c18_el45_ec69."
    r"\for_i_10_mux_uint32_t_if_remainder_solution_py_l35_c8_el38_ec35.$auto$ff.cc:266:slice$7930"
)
_DIV_ANCESTOR_FUNCS = {
    "radix2_div",
    "MUX_uint32_t",
    "BIN_OP_MINUS_uint34_t_uint34_t",
    "UNARY_OP_NOT_uint34_t",
    "BIN_OP_GT_uint34_t_uint34_t",
}


def test_sky130_divider_attribution_is_unchanged():
    # DEVICE_MODELS.PathReport never populates netlist_resources, so this
    # design's attribution rests entirely on the endpoint names - and
    # "solution" (the MAIN) must be excluded even though it's a substring
    # of both endpoints too.
    path_report = FakePathReport(_DIV_START_REG, _DIV_END_REG)
    plan, ps = _plan("solution", [_DIV_ANCESTOR_FUNCS])
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert ranked[0] == "radix2_div"


def test_no_endpoint_match_falls_back_to_resource_scoring():
    # Neither endpoint name matches anything - Tier C (the pre-existing
    # summed substring-length score) must still pick a winner from
    # netlist_resources, unchanged from before this fix.
    resources = {
        f"path/through/{_WG_WRAPPER}/net",
        f"path/through/{_WG_HOTSPOT}/net",
    }
    path_report = FakePathReport("totally_unrelated_mangled_name", None, resources)
    plan, ps = _plan("decrypt_dataflow_decrypt_dataflow", [_WG_ANCESTOR_FUNCS])
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert len(ranked) > 0
    # Longer name wins under the unchanged Tier C formula.
    assert ranked[0] == _WG_WRAPPER


def _tie_scenario():
    # Six same-length candidate names, each occurring only in ONE of the
    # two endpoints at the identical text offset (a genuine Tier B tie:
    # same (position, len) key, distinguished only by name). Enough
    # candidates that a hash-seed-dependent set iteration order would very
    # likely have shuffled the pre-fix result across at least one pair.
    names = ["bbbb", "cccc", "dddd", "eeee", "ffff", "gggg"]
    start = "top_prefix_" + names[0] + "_middle"
    end = "top_prefix_" + names[1] + "_middle"
    path_report = FakePathReport(start, end)
    plan, ps = _plan("top", [set(names)])
    return path_report, plan, ps


def test_ranking_is_deterministic_under_hash_salt():
    # Re-invoke this module as a subprocess under two different
    # PYTHONHASHSEED values (the mechanism real string-set iteration order
    # is randomized by) and confirm the ranked output is byte-identical -
    # same technique as duplicate_collapse_naming_test.py, scoped to this
    # pure function instead of a full VHDL build.
    import subprocess

    results = []
    for seed in ("0", "1911"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--print-tie-ranking"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"child run failed under PYTHONHASHSEED={seed}:\n{result.stdout}"
        )
        results.append(result.stdout.strip())
    assert results[0] == results[1], (
        f"ranking differs across PYTHONHASHSEED values: {results[0]!r} vs "
        f"{results[1]!r}"
    )


# ─── RESOLVE_PIPELINABLE_HOTSPOT: defer past an unsliceable LCA ──────────


def test_unsliceable_wrapper_defers_to_a_deeper_sliceable_func():
    # wrapper_deep is the deepest (best-ranked) common ancestor but has its
    # own feedback_vars (mirrors if8040...'s real early_out_ready case);
    # helper_shared is a shallower common ancestor that is fully sliceable.
    # The guard must fall back to helper_shared rather than declaring the
    # whole path unpipelinable.
    start = "top__helper_shared__wrapper_deep__leaf_a"
    end = "top__helper_shared__wrapper_deep__leaf_b"
    path_report = FakePathReport(start, end)
    plan, ps = _plan(
        "top",
        [{"top", "helper_shared", "wrapper_deep"}],
        extra_func_logics=[
            FakeLogic(
                "wrapper_deep",
                can_have_added_latency=False,
                feedback_vars=["early_out_ready"],
                is_new_style_bit_manip=True,
            ),
            FakeLogic(
                "helper_shared",
                can_have_added_latency=True,
                submodule_instances={},
            ),
        ],
    )
    ranked = SWEEP.RANK_PATH_FUNC_CANDIDATES(path_report, plan, ps)
    assert ranked[0] == "wrapper_deep", f"test setup assumption broken: {ranked}"
    assert SWEEP.WHY_HOTSPOT_NOT_PIPELINABLE("wrapper_deep", ps) == "feedback_vars"
    assert SWEEP.WHY_HOTSPOT_NOT_PIPELINABLE("helper_shared", ps) is None

    hotspot_func, reason, _stage_info = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(
        path_report, plan, ps
    )
    assert hotspot_func == "helper_shared"
    assert reason is None


def test_stops_when_nothing_on_the_path_is_sliceable():
    # Same shape, but every candidate is genuinely unsliceable - the guard
    # must not loop forever or invent a func; it reports the deepest
    # candidate and its own reason, same as a direct, honest stop.
    start = "top__helper_shared__wrapper_deep__leaf_a"
    end = "top__helper_shared__wrapper_deep__leaf_b"
    path_report = FakePathReport(start, end)
    plan, ps = _plan(
        "top",
        [{"top", "helper_shared", "wrapper_deep"}],
        extra_func_logics=[
            FakeLogic(
                "wrapper_deep",
                can_have_added_latency=False,
                feedback_vars=["early_out_ready"],
                is_new_style_bit_manip=True,
            ),
            FakeLogic(
                "helper_shared",
                can_have_added_latency=False,
                uses_nonvolatile_state_regs=True,
                is_new_style_bit_manip=True,
            ),
        ],
    )
    hotspot_func, reason, _stage_info = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(
        path_report, plan, ps
    )
    assert hotspot_func == "wrapper_deep"
    assert reason == "feedback_vars"


if __name__ == "__main__":
    if "--print-tie-ranking" in sys.argv:
        _pr, _plan_obj, _ps = _tie_scenario()
        print(",".join(SWEEP.RANK_PATH_FUNC_CANDIDATES(_pr, _plan_obj, _ps)))
        sys.exit(0)
    test_wireguard_decrypt_blames_chacha_not_the_interface_wrapper()
    test_post_rename_shapes_still_blame_chacha_not_the_interface_wrapper()
    test_netlist_resources_cannot_outvote_a_deeper_endpoint_match()
    test_missing_end_reg_name_falls_back_to_the_single_endpoint()
    test_sky130_divider_attribution_is_unchanged()
    test_no_endpoint_match_falls_back_to_resource_scoring()
    test_ranking_is_deterministic_under_hash_salt()
    test_unsliceable_wrapper_defers_to_a_deeper_sliceable_func()
    test_stops_when_nothing_on_the_path_is_sliceable()
    print("All path attribution unit tests passed.")
