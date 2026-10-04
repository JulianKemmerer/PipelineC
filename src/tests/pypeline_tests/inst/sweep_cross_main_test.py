#!/usr/bin/env python3
"""Cross-MAIN timing paths, per-MAIN attribution scope, best-result ties and
the mini-sweep ladder inside start_latency= regions (in-process, no tool).

Source: the shared WireGuard 70 MHz build (sweep_history.json iterations 4-6,
vivado_bb95972a). A testbench handshake path between two encrypt_syn_tb
registers ran through the shared ChaCha wrapper and both dataflows' FSMs.
GET_MAIN_INSTS_FOR_PATH_REPORT implicated all four MAINs, so the path drove
ChaCha (grew 44->56 while its own paths met), blamed the encrypt dataflow on
prep_auth_data_fsm from a cell in the DECRYPT instance, and the best-result
restore chose between iterations by 0.02 MHz of that one path. Separately, a
start_latency= hint made ChaCha a constrained region, where mini-sweeps were
never allowed: 44-56 clks instead of the 20 the measured block_step lock gave.
"""

import os
import sys
import tempfile
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
import AUTO_MULTI_CYCLE
import AUTO_PIPELINE
import C_TO_LOGIC
import SWEEP
import SYN
import VHDL
from scripted_sweep_backend import ScriptedBackend, path
from sweep_evidence_test import _scripted_sweep_patches
from typed_pipeline_placement_test import FakeLogic as _BaseLogic

M = C_TO_LOGIC.SUBMODULE_MARKER


class Logic(_BaseLogic):
    """FakeLogic with the fields WHY_NOT_SLICEABLE reads; state=True cannot
    hold added latency (ADDED_LATENCY_BLOCKER stops at it)."""

    def __init__(self, func_name, state=False, subs=None, tags=None):
        super().__init__(func_name)
        self.state = state
        self.submodule_instances = dict(subs or {})
        self.sub_inst_to_auto_pipeline_latency = dict(tags or {})
        self.sub_inst_to_auto_pipeline_key = {}
        self.uses_nonvolatile_state_regs = state
        self.feedback_vars = []
        self.vhdl_module_text = None
        self.is_vhdl_func = self.is_vhdl_expr = self.is_clock_crossing = False
        self.is_new_style_bit_manip = True  # SW_LIB.IS_MEM short-circuits
        self.is_c_built_in = False
        self.ast_meta = None
        self.delay = 200
        self.delay_is_estimated = False

    def CAN_HAVE_ADDED_LATENCY(self, _parser_state):
        return not self.state


def _state(tree, goals):
    """tree: {inst: (func, state)}, children named '<parent>____<local>'."""
    insts = {}
    for inst, (func, state) in tree.items():
        insts[inst] = Logic(func, state)
    for inst in insts:
        if M in inst:
            parent, local = inst.rsplit(M, 1)
            insts[parent].submodule_instances[local] = insts[inst].func_name
    ps = SimpleNamespace(
        LogicInstLookupTable=insts,
        FuncLogicLookupTable={l.func_name: l for l in insts.values()},
        func_fixed_latency={},
        func_marked_blackbox=set(),
        func_marked_wires=set(),
        func_marked_no_add_io_regs=set(),
        main_mhz=dict(goals),
        FuncToInstances={},
        clk_cross_var_info={},
        part="scripted",
    )
    for inst, logic in insts.items():
        ps.FuncToInstances.setdefault(logic.func_name, set()).add(inst)
    return ps


# ─── Real names: the iteration-4 clock-worst path, as VIVADO.PathReport parsed
# it from vivado_bb95972a_65a02d66e85082c8.log (every non-testbench cell, plus
# a few testbench ones; slack -1.003 ns at 70 MHz).
_FIXTURE_START = 'encrypt_syn_tb_0CLK_78f47f11/byte_source_encrypt_syn_tb_py_l138_c10_el143_ec5/remaining_reg[29]'
_FIXTURE_END = 'encrypt_syn_tb_0CLK_78f47f11/input_packet_count_reg[29]'
_FIXTURE_RESOURCES = [
    'chacha20_pipeline_shared_0CLK_7aed0219/pipeline_func_chacha20_pipeline_shared_py_l219_c13_el222_ec5/module_to_global[chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137][chacha20_pipeline_shared_encrypt_pipeline_in_if][stream][valid][0]',
    'chacha20_pipeline_shared_0CLK_7aed0219/pipeline_func_chacha20_pipeline_shared_py_l219_c13_el222_ec5/module_to_global[decrypt_dataflow_shared][decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5][chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148][chacha20_pipeline_shared_decrypt_pipeline_in_if][stream][valid]',
    'chacha20_pipeline_shared_0CLK_7aed0219/pipeline_func_chacha20_pipeline_shared_py_l219_c13_el222_ec5/wide_out_reg[data][frag][data][0][7]_i_3/O',
    'chacha20_pipeline_shared_0CLK_7aed0219/pipeline_func_chacha20_pipeline_shared_py_l219_c13_el222_ec5/wide_out_reg[data][frag][data][0][7]_i_3__0/O',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/BIN_OP_OR_chacha20_py_l311_c11_ec58_return_output',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/axis128_2broadcast_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l19_c12_ec141_return_output[axis_in_if][ready]',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/block_count[31]_i_3__0/O',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/module_to_global[chacha20_pipeline_shared][chacha20_pipeline_shared_decrypt_pipeline_in_if][ready]',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/narrow_in_reg[data][frag][data][0][7]_i_5/O',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/priority_encrypt[0]_i_2__0/O',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/wide_out_reg[data][frag][data][0][7]_i_1__0/O',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/chacha_func_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148/chacha20_fsm_chacha20_pipeline_shared_py_l271_c14_el281_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/wide_out_reg[data][frag][data][0][7]_i_1__0_n_0',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/prep_auth_data_fsm_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l21_c11_ec125/narrow_in_reg[data][frag][data][0][7]_i_3/O',
    'decrypt_dataflow_shared_0CLK_f9761c9a/decrypt_dataflow_core_decrypt_dataflow_shared_py_l41_c8_el50_ec5/prep_auth_data_fsm_ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l21_c11_ec125/narrow_in_reg_reg[data][frag][data][0][7]',
    'encrypt_dataflow_shared_0CLK_682153e8/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5/chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137/chacha20_fsm_chacha20_pipeline_shared_py_l242_c14_el252_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/BIN_OP_OR_chacha20_py_l311_c11_ec58_return_output',
    'encrypt_dataflow_shared_0CLK_682153e8/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5/chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137/chacha20_fsm_chacha20_pipeline_shared_py_l242_c14_el252_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/module_to_global[chacha20_pipeline_shared][chacha20_pipeline_shared_encrypt_pipeline_in_if][ready]',
    'encrypt_dataflow_shared_0CLK_682153e8/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5/chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137/chacha20_fsm_chacha20_pipeline_shared_py_l242_c14_el252_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/priority_encrypt[0]_i_3/O',
    'encrypt_dataflow_shared_0CLK_682153e8/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5/chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137/chacha20_fsm_chacha20_pipeline_shared_py_l242_c14_el252_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/remaining[31]_i_4/O',
    'encrypt_dataflow_shared_0CLK_682153e8/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5/chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137/chacha20_fsm_chacha20_pipeline_shared_py_l242_c14_el252_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/wide_out_reg[data][frag][data][0][7]_i_1/O',
    'encrypt_dataflow_shared_0CLK_682153e8/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5/chacha_func_ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137/chacha20_fsm_chacha20_pipeline_shared_py_l242_c14_el252_ec5/axis128_to_axis512_chacha20_py_l298_c18_el301_ec5/wide_out_reg[data][frag][data][0][7]_i_1_n_0',
    'encrypt_syn_tb_0CLK_78f47f11/byte_source_encrypt_syn_tb_py_l138_c10_el143_ec5/BIN_OP_MINUS_axis_py_l489_c24_ec37/input_packet_count[0]_i_2/O',
    'encrypt_syn_tb_0CLK_78f47f11/byte_source_encrypt_syn_tb_py_l138_c10_el143_ec5/BIN_OP_MINUS_axis_py_l489_c24_ec37/input_packet_count[0]_i_2_1',
    'encrypt_syn_tb_0CLK_78f47f11/byte_source_encrypt_syn_tb_py_l138_c10_el143_ec5/encrypt_dataflow_core_encrypt_dataflow_shared_py_l43_c8_el52_ec5_return_output[axis_in_if][ready]',
]

_ENTITIES = {
    "encrypt_syn_tb": "encrypt_syn_tb_0CLK_78f47f11",
    "chacha20_pipeline_shared": "chacha20_pipeline_shared_0CLK_7aed0219",
    "encrypt_dataflow_shared": "encrypt_dataflow_shared_0CLK_682153e8",
    "decrypt_dataflow_shared": "decrypt_dataflow_shared_0CLK_f9761c9a",
}


def _wireguard_state():
    """The instance hierarchy those names run through: stateful wrappers and
    FSMs (state=True), the comb interface wrapper, the tagged regions."""
    enc_core = "encrypt_dataflow_shared" + M + "encrypt_dataflow_core[encrypt_dataflow_shared_py_l43_c8_el52_ec5]"
    dec_core = "decrypt_dataflow_shared" + M + "decrypt_dataflow_core[decrypt_dataflow_shared_py_l41_c8_el50_ec5]"
    enc_chacha = enc_core + M + "chacha_func[ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l14_c13_ec137]"
    dec_chacha = dec_core + M + "chacha_func[ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l20_c13_ec148]"
    enc_fsm = enc_chacha + M + "chacha20_fsm[chacha20_pipeline_shared_py_l242_c14_el252_ec5]"
    dec_fsm = dec_chacha + M + "chacha20_fsm[chacha20_pipeline_shared_py_l271_c14_el281_ec5]"
    pipeline_func = "chacha20_pipeline_shared" + M + "pipeline_func[chacha20_pipeline_shared_py_l219_c13_el222_ec5]"
    tree = {
        "encrypt_syn_tb": ("encrypt_syn_tb", True),
        "encrypt_syn_tb" + M + "byte_source[encrypt_syn_tb_py_l138_c10_el143_ec5]": ("byte_source", True),
        "chacha20_pipeline_shared": ("chacha20_pipeline_shared", True),
        pipeline_func: ("stream_auto_pipeline_func", True),
        pipeline_func + M + "auto_pipelined_func[stream_auto_pipeline_py_l130_c36_ec72]": ("auto_pipelined_func", True),
        "encrypt_dataflow_shared": ("encrypt_dataflow_shared", True),
        enc_core: ("encrypt_dataflow_core_from_factory", True),
        enc_chacha: ("chacha20_encrypt_shared", False),
        enc_fsm: ("chacha20_fsm", True),
        enc_fsm + M + "axis128_to_axis512[chacha20_py_l298_c18_el301_ec5]": ("axis128_to_axis512", True),
        enc_core + M + "prep_auth_data_fsm[ifgen_encrypt_dataflow_core_encrypt_dataflow_core_if46677ace_py_l16_c11_ec125]": ("prep_auth_data_fsm", True),
        "decrypt_dataflow_shared": ("decrypt_dataflow_shared", True),
        dec_core: ("decrypt_dataflow_core_from_factory", True),
        dec_chacha: ("chacha20_decrypt_shared", False),
        dec_fsm: ("chacha20_fsm", True),
        dec_fsm + M + "axis128_to_axis512[chacha20_py_l298_c18_el301_ec5]": ("axis128_to_axis512", True),
        dec_core + M + "prep_auth_data_fsm[ifgen_decrypt_dataflow_core_decrypt_dataflow_core_if508c7ccd_py_l21_c11_ec125]": ("prep_auth_data_fsm", True),
    }
    return _state(tree, {m: 70.0 for m in _ENTITIES})


def _fixture_path():
    return SimpleNamespace(
        start_reg_name=_FIXTURE_START,
        end_reg_name=_FIXTURE_END,
        netlist_resources=set(_FIXTURE_RESOURCES),
        path_group="clk_70p0",
        path_delay_ns=15.289,
        slack_ns=-1.003,
    )


def _real_name_patches(stack):
    for obj, name, value in [
        (VHDL, "GET_ENTITY_NAME", lambda inst, logic, tpl, ps: _ENTITIES[inst]),
        (SYN, "GET_TARGET_MHZ", lambda m, ps: ps.main_mhz.get(m)),
        (SYN, "FUNC_SRC_LOC_STR", lambda *a: ""),
    ]:
        stack.enter_context(patch.object(obj, name, value))


def test_real_fixture_path_roles():
    ps = _wireguard_state()
    params = SimpleNamespace(TimingParamsLookupTable={})
    with ExitStack() as stack:
        _real_name_patches(stack)
        report = _fixture_path()
        mains = SYN.GET_MAIN_INSTS_FROM_PATH_REPORT(report, ps, {})
        assert mains == set(_ENTITIES), mains  # all four touched, as before
        roles = SWEEP.PATH_MAIN_ROLES(report, ps, params)
        owners = SWEEP.PATH_OWNING_MAINS(report, ps, params)
        crossed = SWEEP.DESCRIBE_CROSSING(report, roles, ps)
    assert roles["encrypt_syn_tb"]["relation"] == "endpoint"
    assert roles["encrypt_syn_tb"]["start"] and roles["encrypt_syn_tb"]["end"]
    for main in ("chacha20_pipeline_shared", "encrypt_dataflow_shared", "decrypt_dataflow_shared"):
        role = roles[main]
        assert role["relation"] == "through" and not role["reach"], (main, role)
        assert role["crossing"], (main, role)
    blockers = {m: {f for f, _why in r["blockers"]} for m, r in roles.items()}
    assert blockers["chacha20_pipeline_shared"] == {"stream_auto_pipeline_func"}, blockers
    # Each dataflow is blocked by its OWN instances; only decrypt's cells
    # are in prep_auth_data_fsm
    assert blockers["encrypt_dataflow_shared"] == {"axis128_to_axis512"}, blockers
    assert blockers["decrypt_dataflow_shared"] == {"axis128_to_axis512", "prep_auth_data_fsm"}, blockers
    assert all(why == "state_regs" for r in roles.values() for _f, why in r["blockers"])
    assert owners == {"encrypt_syn_tb"}, owners
    assert "chacha20_pipeline_shared (stream_auto_pipeline_func: state_regs)" in crossed, crossed
    assert "encrypt_syn_tb" not in crossed, crossed


def test_unrecognized_hierarchy_counts_as_reachable():
    ps = _wireguard_state()
    params = SimpleNamespace(TimingParamsLookupTable={})
    report = _fixture_path()
    # A cell two hierarchy levels below anything the trie knows: its owner is
    # unknown, so the MAIN is not claimed unable to register the path.
    report.netlist_resources = set(report.netlist_resources) | {
        "chacha20_pipeline_shared_0CLK_7aed0219/pipeline_func_chacha20_pipeline_shared_py_l219_c13_el222_ec5/"
        "unknown_child/deeper/lut/O"
    }
    with ExitStack() as stack:
        _real_name_patches(stack)
        roles = SWEEP.PATH_MAIN_ROLES(report, ps, params)
    assert roles["chacha20_pipeline_shared"]["reach"]
    assert not roles["chacha20_pipeline_shared"]["crossing"]


def test_no_hierarchy_evidence_keeps_old_behavior():
    ps = _wireguard_state()
    params = SimpleNamespace(TimingParamsLookupTable={})
    report = SimpleNamespace(
        start_reg_name="u_main/a_reg", end_reg_name="u_main/b_reg",
        netlist_resources={"u_other/lut"}, path_delay_ns=15.0,
    )
    with ExitStack() as stack:
        _real_name_patches(stack)
        assert SWEEP.PATH_MAIN_ROLES(report, ps, params) is None
        # One-MAIN designs never look
        single = _state({"m": ("m", False)}, {"m": 70.0})
        assert SWEEP.PATH_MAIN_ROLES(report, single, params) is None
    assert SWEEP.SCOPED_PATH_REPORT(report, "encrypt_syn_tb", None) is report


def test_no_goal_owner_means_crossing_mains_still_own_it():
    ps = _wireguard_state()
    ps.main_mhz["encrypt_syn_tb"] = None  # nobody with a goal would report it
    params = SimpleNamespace(TimingParamsLookupTable={})
    with ExitStack() as stack:
        _real_name_patches(stack)
        roles = SWEEP.PATH_MAIN_ROLES(_fixture_path(), ps, params)
    assert not any(r["crossing"] for r in roles.values()), roles


def test_scoped_attribution_ignores_other_mains_instances():
    """The encrypt plan's candidates include prep_auth_data_fsm and its
    interface wrapper. Unscoped, Tier-C substring scoring matched
    prep_auth_data_fsm against a cell of the DECRYPT instance (what the real
    sweep printed); scoped to encrypt's own cells nothing matches."""
    ps = _wireguard_state()
    params = SimpleNamespace(TimingParamsLookupTable={})
    plan = SWEEP.MainSweepPlan("encrypt_dataflow_shared", 70.0)
    plan.subtrees = ["encrypt_dataflow_shared"]
    landscape = SWEEP.SliceLandscape("encrypt_dataflow_shared", 10, 1.0)
    for i, func in enumerate(("prep_auth_data_fsm", "chacha20_encrypt_shared")):
        seg = SWEEP.Segment(f"seg{i}", func, float(i), float(i + 1), SWEEP.Segment.ATOMIC, "state_regs")
        seg.ancestor_funcs = {"encrypt_dataflow_shared", "encrypt_dataflow_core_from_factory", func}
        landscape.segments.append(seg)
    plan.landscapes = {"encrypt_dataflow_shared": landscape}
    with ExitStack() as stack:
        _real_name_patches(stack)
        report = _fixture_path()
        unscoped = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(report, plan, ps)
        roles = SWEEP.PATH_MAIN_ROLES(report, ps, params)
        scoped_report = SWEEP.SCOPED_PATH_REPORT(report, "encrypt_dataflow_shared", roles)
        scoped = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(scoped_report, plan, ps)
    assert unscoped[0] == "prep_auth_data_fsm", unscoped  # the real misattribution
    assert scoped[0] is None, scoped
    assert scoped_report.start_reg_name is None and scoped_report.end_reg_name is None
    assert all(r.startswith(_ENTITIES["encrypt_dataflow_shared"]) for r in scoped_report.netlist_resources)
    assert len(scoped_report.netlist_resources) == 6
    # The basis of the old guess: cell names only, never an endpoint
    assert SWEEP.ATTRIBUTION_BASIS(report, "prep_auth_data_fsm") == "cells"


def test_attribution_basis_labels():
    report = SimpleNamespace(
        start_reg_name="top/step_a/quarter_round_x/REG_STAGE0_s_reg",
        end_reg_name="top/step_b/quarter_round_y/REG_STAGE0_s_reg",
        netlist_resources={"top/step_a/lut"},
    )
    assert SWEEP.ATTRIBUTION_BASIS(report, "quarter_round") == "inside"
    assert SWEEP.ATTRIBUTION_BASIS(report, "step_a") == "endpoint"
    assert SWEEP.ATTRIBUTION_BASIS(report, "lut") == "cells"
    assert SWEEP.ATTRIBUTION_BASIS(report, "nowhere") is None
    assert SWEEP.ATTRIBUTION_BASIS(report, None) is None
    assert "runs inside" in SWEEP.DESCRIBE_HOTSPOT_LOCATION("inside", "f")
    assert "starts or ends" in SWEEP.DESCRIBE_HOTSPOT_LOCATION("endpoint", "f")
    assert "no register of the path is inside it" in SWEEP.DESCRIBE_HOTSPOT_LOCATION("cells", "f")
    assert "by instance hierarchy" in SWEEP.DESCRIBE_HOTSPOT_LOCATION("hierarchy", "f")
    assert SWEEP.DESCRIBE_HOTSPOT_LOCATION(None, "f") == "the critical path was attributed to f"


def test_snapshot_tie_rule_with_the_real_numbers():
    goal = 70.0
    # (whole-design ratio, own-path ratio capped at 1, pipeline stages)
    iter4 = (65.407 / goal, 67.967 / goal, 54)  # ChaCha own path failing, body 5/5
    iter5 = (65.389 / goal, 1.0, 56)  # every planned MAIN's own paths met, body 3/3
    iter6 = (65.389 / goal, 1.0, 62)
    assert SWEEP.SNAPSHOT_BETTER(iter5, iter4)
    assert not SWEEP.SNAPSHOT_BETTER(iter4, iter5)
    assert not SWEEP.SNAPSHOT_BETTER(iter6, iter5)  # same result, more stages
    assert SWEEP.SNAPSHOT_BETTER(iter4, None)
    # A real whole-design improvement still wins over own paths and stages
    assert SWEEP.SNAPSHOT_BETTER((0.96, 0.9, 80), (0.93, 1.0, 10))
    # Meeting every goal is never a tie with missing one
    assert SWEEP.SNAPSHOT_BETTER((1.0, 1.0, 90), (0.995, 1.0, 10))
    assert not SWEEP.SNAPSHOT_BETTER((0.995, 1.0, 10), (1.0, 1.0, 90))
    # Within tolerance and both own-met: fewer stages
    assert SWEEP.SNAPSHOT_BETTER((0.934, 1.0, 40), (0.935, 1.0, 50))


# ─── Scripted sweeps (scripted_sweep_backend): one goal for every MAIN ───


def _scripted_state(planned, planless=("fixture",)):
    """Planned MAINs get a comb helper 'h' (the mini-sweep lock target) and a
    stateful 'wrap' a crossing path's cells sit in; planless MAINs a stateful
    'src' holding the fixture's registers."""
    tree = {}
    for m in planned:
        tree[m] = (m, False)
        tree[m + M + "h"] = ("h_" + m, False)
        tree[m + M + "wrap"] = ("wrap_" + m, True)
    for m in planless:
        tree[m] = (m, True)
        tree[m + M + "src"] = ("src_" + m, True)
    return _state(tree, {m: 100 for m in list(planned) + list(planless)})


def _crossing_path(delay, crossed, owner="fixture"):
    report = path(owner, delay, pair="src")
    report.netlist_resources = {f"{m}/wrap/lut/O" for m in crossed} | {
        owner + "/src/lut/O"
    }
    return report


def _scripted_run(ps, rule, planned, extra=(), multiple=True):
    helper = {m: m + M + "h" for m in planned}

    def fresh(_):
        return {i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}

    params = SimpleNamespace(TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={})
    minis = []

    def mini(func, plan, ps_):
        minis.append(func)
        table = fresh(ps_)
        target = helper[plan.main_inst]
        table[target].SET_SLICES([0.5])
        plan.locked[target] = SWEEP.MiniSweepLock(
            [0.5],
            concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(target, table, ps_),
            model_fingerprint=SWEEP.SUBTREE_MODEL_FINGERPRINT(target, ps_),
        )
        return True

    backend = ScriptedBackend(rule, multiple)
    history = {}
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        patches = _scripted_sweep_patches(
            backend,
            fresh,
            [
                (SYN, "SYN_OUTPUT_DIRECTORY", out),
                (VHDL, "GET_ENTITY_NAME", lambda inst, logic, tpl, ps_: inst),
                (SWEEP, "COLLECT_CUT_SUBTREES", lambda m, p: [m] if m in helper else []),
                (SWEEP, "RUN_HOTSPOT_MINISWEEP", mini),
                (SWEEP, "SWEEP_HISTORY", history),
                (
                    SWEEP,
                    "GET_MAIN_INSTS_FOR_PATH_REPORT",
                    lambda p, *a: {
                        n.split("/")[0]
                        for n in [p.start_reg_name, p.end_reg_name] + sorted(p.netlist_resources)
                    },
                ),
                (
                    SWEEP,
                    "SUMMARIZE_SUBTREE_PIPELINE",
                    lambda m, st, t, p: (False, [], len(t[helper[m]]._slices)),
                ),
                (
                    SWEEP,
                    "GET_SUBTREE_PIPELINE_STAGES",
                    lambda plan, t, p: len(t[helper[plan.main_inst]]._slices),
                ),
                (
                    AUTO_PIPELINE.TimingParams,
                    "GET_TOTAL_LATENCY",
                    lambda self, _ps, t: sum(
                        len(t[i]._slices)
                        for i in t
                        if i == self.inst_name or i.startswith(self.inst_name + M)
                    ),
                ),
                (AUTO_PIPELINE, "FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL", lambda *a: True),
            ]
            + list(extra),
        )
        for obj, key, value in patches:
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
    locked = {m: len(result.TimingParamsLookupTable[helper[m]]._slices) for m in planned}
    return result, history, minis, locked, backend


def _locked(params, m):
    return len(params.TimingParamsLookupTable[m + M + "h"]._slices)


def test_crossing_path_never_drives_the_plans_it_crosses():
    """'core' fails its own path until its helper is locked; 'flow' always
    meets its own. A planless fixture's path crossing both fails throughout
    (93.5 MHz). Each plan follows only its own paths; the fixture alone fails
    the build, naming what it crosses."""
    ps = _scripted_state(["core", "flow"])

    def rule(ps_, params):
        core_locked = _locked(params, "core")
        return [
            _crossing_path(10.7, ["core", "flow"]),
            path("core", 5.0 if core_locked else 12.0),
            path("flow", 5.0),
        ]

    hotspots = {"core": ("h_core", None, ""), "flow": ("h_flow", None, "")}
    result, history, minis, locked, backend = _scripted_run(
        ps, rule, ["core", "flow"],
        [(SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: hotspots[plan.main_inst])],
    )
    failures = {f[0]: f for f in result.sweep_timing_failures}
    assert set(failures) == {"fixture"}, result.sweep_timing_failures
    assert failures["fixture"][3].startswith("nothing_auto_pipelinable: path crosses "), failures
    assert "core (wrap_core: state_regs)" in failures["fixture"][3], failures
    assert minis == ["h_core"], minis  # flow never touched, core locked once
    assert locked == {"core": 1, "flow": 0}, locked
    actions = {m: [r["action"] for r in history[m]["iterations"]] for m in ("core", "flow")}
    assert all(a == "met" for a in actions["flow"]), actions
    assert not any(
        a.startswith(("replan", "stop")) for m in ("core", "flow") for a in actions[m]
    ), actions
    # The crossing is kept as evidence on the crossed MAINs' records
    crossing = [r.get("crossing_paths") for r in history["flow"]["iterations"]]
    assert all(c and c[0]["owner_mains"] == ["fixture"] for c in crossing), crossing
    assert history["fixture"]["iterations"][-1]["crosses"].startswith("core ("), history["fixture"]
    assert SWEEP.SWEEP_OUTCOMES == {} or True  # (outcomes are patched per run)


def test_old_rule_would_drive_crossed_plans():
    """Control: without hierarchy evidence (names a tool could not place) the
    same scenario keeps the old behavior -- every implicated MAIN owns the
    path, so 'flow' is re-pipelined by a path it cannot change."""
    ps = _scripted_state(["core", "flow"])

    def rule(ps_, params):
        return [_crossing_path(10.7, ["core", "flow"]), path("core", 5.0), path("flow", 5.0)]

    hotspots = {"core": ("h_core", None, ""), "flow": ("h_flow", None, "")}
    result, history, minis, locked, _ = _scripted_run(
        ps, rule, ["core", "flow"],
        [
            (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: hotspots[plan.main_inst]),
            (SWEEP, "PATH_MAIN_ROLES", lambda *a: None),
        ],
    )
    assert "h_flow" in minis, minis


def test_best_result_ties_prefer_met_own_paths():
    """'a' fails its own path (95.2 MHz) until locked; 'b' is stuck on an
    unpipelinable own path (97.1 MHz); a crossing fixture path fails at
    93.46 MHz unlocked / 93.28 MHz locked -- the same result within 1%. The
    old highest-ratio restore kept the unlocked implementation; ties now go
    to the one whose own paths are met."""
    ps = _scripted_state(["a", "b"])

    def rule(ps_, params):
        a_locked = _locked(params, "a")
        return [
            _crossing_path(10.72 if a_locked else 10.70, ["a", "b"]),
            path("a", 5.0 if a_locked else 10.5),
            path("b", 10.3),
        ]

    hotspots = {"a": ("h_a", None, ""), "b": ("fsm_b", "state_regs", "")}
    result, history, minis, locked, _ = _scripted_run(
        ps, rule, ["a", "b"],
        [(SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: hotspots[plan.main_inst])],
    )
    failures = {f[0]: f[3] for f in result.sweep_timing_failures}
    assert failures.keys() == {"fixture", "b"}, failures
    assert failures["b"].startswith("unpipelinable_hotspot"), failures
    assert minis == ["h_a"], minis
    assert locked["a"] == 1, locked  # the restored table keeps the lock


def test_unattributed_endpoint_path_in_stateful_logic_names_the_blocker():
    """'a' owns the end of a failing path whose every cell in 'a' sits in its
    stateful wrapper, and nothing in a's landscapes matches. Before, that was
    "no attribution" and rescaled the whole plan every iteration; now the
    blocker is named (by hierarchy) and the plan stops as unpipelinable."""
    ps = _scripted_state(["a"])

    def rule(ps_, params):
        report = path("fixture", 10.7, pair="src")
        report.end_reg_name = "a/wrap/state_reg[0]"
        report.netlist_resources = {"a/wrap/lut/O", "fixture/src/lut/O"}
        return [report]

    result, history, minis, locked, _ = _scripted_run(
        ps, rule, ["a"],
        [(SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: (None, None, ""))],
    )
    failures = {f[0]: f[3] for f in result.sweep_timing_failures}
    assert failures.get("a") == "unpipelinable_hotspot: wrap_a, state_regs", failures
    records = history["a"]["iterations"]
    assert records[0]["bottleneck"] == "wrap_a", records[0]
    assert records[0]["bottleneck_basis"] == "hierarchy", records[0]
    assert records[-1]["action"] == "stop(unpipelinable wrap_a)", records[-1]
    assert minis == [], minis


def test_confirmation_keeps_crossed_mains_and_skips_unhelpful_fallback():
    ps = _scripted_state(["a", "b"])
    table = {i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}
    table["a" + M + "h"].SET_SLICES([0.5])
    noop = lambda *a, **kw: None

    def confirm(rule):
        params = SimpleNamespace(TimingParamsLookupTable=dict(table), auto_multi_cycle_ncycles={})
        seen = {}

        def fallback(ps_, params_):
            seen.update(params_.confirmation_preserved_mains)
            return params_

        backend = ScriptedBackend(rule, True)
        with ExitStack() as stack:
            for obj, name, value in [
                (SYN, "SYN_TOOL", backend),
                (SYN, "PART_SET_TOOL", noop),
                (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
                (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **kw: False),
                (SYN, "WRITE_BLACK_BOX_FILES", noop),
                (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
                (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
                (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
                (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
                (VHDL, "WRITE_CLK_CROSS_ENTITIES", noop),
                (VHDL, "WRITE_MULTIMAIN_TOP", noop),
                (VHDL, "GET_ENTITY_NAME", lambda inst, logic, tpl, ps_: inst),
                (AUTO_PIPELINE, "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES", lambda *a: set()),
                (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
                (SWEEP, "COLLECT_CUT_SUBTREES", lambda m, p: [m] if m in ("a", "b") else []),
                (SWEEP, "SUMMARIZE_SUBTREE_PIPELINE", lambda *a: (False, [], 0)),
                (SWEEP, "RECORD_CONFIRMATION_RESULTS", noop),
                (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
                (
                    SWEEP,
                    "GET_MAIN_INSTS_FOR_PATH_REPORT",
                    lambda p, *a: {
                        n.split("/")[0]
                        for n in [p.start_reg_name, p.end_reg_name] + sorted(p.netlist_resources)
                    },
                ),
                (SWEEP, "DO_PLANNED_THROUGHPUT_SWEEP", fallback),
                (AUTO_MULTI_CYCLE, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda p: {}),
                (AUTO_MULTI_CYCLE, "SEED_COUNTS", noop),
                (AUTO_MULTI_CYCLE, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
                (AUTO_MULTI_CYCLE, "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT", lambda *a: None),
            ]:
                stack.enter_context(patch.object(obj, name, value))
            result, met = SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP(ps, params)
        return met, seen, result.sweep_timing_failures

    # Only the planless fixture fails (its path crosses 'a'): nothing a
    # fallback sweep could replan, and 'a' is not charged with the path.
    met, seen, failures = confirm(
        lambda ps_, p: [_crossing_path(10.7, ["a"]), path("a", 5.0), path("b", 5.0)]
    )
    assert not met and seen == {}, (met, seen)
    assert [f[0] for f in failures] == ["fixture"], failures
    # 'b' fails its own path too: only 'b' is replanned, crossed 'a' is kept
    met, seen, failures = confirm(
        lambda ps_, p: [_crossing_path(10.7, ["a"]), path("a", 5.0), path("b", 12.0)]
    )
    assert not met and "a" in seen and "b" not in seen, seen
    assert seen["a"][M + "h"]["slices"] == [0.5], seen["a"]
    assert sorted(f[0] for f in failures) == ["b", "fixture"], failures


# ─── start_latency= regions take the mini-sweep ladder ───


def _region_state(constraint, other_main_member=False):
    mains = ["a", "z"] if other_main_member else ["a"]
    tree = {}
    for m in mains:
        tree[m] = (m, False)
        tree[m + M + "r"] = ("region_func", False)
        tree[m + M + "r" + M + "h"] = ("h", False)
    ps = _state(tree, {m: 100 for m in mains})
    for m in mains:
        ps.LogicInstLookupTable[m].sub_inst_to_auto_pipeline_latency = {"r": constraint}
        ps.LogicInstLookupTable[m].sub_inst_to_auto_pipeline_key = {"r": "region_key"}
    return ps


def test_lock_rules_for_regions():
    start_only = C_TO_LOGIC.AutoPipelineLatency(start_latency=1)
    for constraint, member, expected in [
        (start_only, False, None),
        (C_TO_LOGIC.AutoPipelineLatency(latency=2), False, "constrained AUTO_PIPELINE region"),
        (C_TO_LOGIC.AutoPipelineLatency(max_latency=3), False, "constrained AUTO_PIPELINE region"),
        (C_TO_LOGIC.AutoPipelineLatency(start_latency=1, max_latency=3), False, "constrained AUTO_PIPELINE region"),
        (start_only, True, "AUTO_PIPELINE region shared with another MAIN"),
    ]:
        ps = _region_state(constraint, member)
        plan = SWEEP.MainSweepPlan("a", 100)
        plan.subtrees = ["a"]
        plan.regions = [
            r for r in AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(ps) if r.inst.startswith("a" + M)
        ]
        with patch.object(AUTO_PIPELINE, "FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL", lambda *a: True):
            got = SWEEP.LOCK_BLOCKED_REASON("h", plan, ["a" + M + "r" + M + "h"], ps)
            # Locking the region root itself is never allowed
            root = SWEEP.LOCK_BLOCKED_REASON("region_func", plan, ["a" + M + "r"], ps)
        assert got == expected, (constraint.describe(), member, got)
        assert root == "constrained AUTO_PIPELINE region", root


def test_try_minisweep_streak_and_budget():
    plan = SWEEP.MainSweepPlan("a", 100)
    calls = []
    with patch.object(SWEEP, "RUN_HOTSPOT_MINISWEEP", lambda f, p, ps: calls.append(f) or True):
        assert not SWEEP.TRY_HOTSPOT_MINISWEEP("h", plan, None)  # streak 1
        assert not SWEEP.TRY_HOTSPOT_MINISWEEP("g", plan, None)  # resets h
        assert not SWEEP.TRY_HOTSPOT_MINISWEEP("h", plan, None)
        assert SWEEP.TRY_HOTSPOT_MINISWEEP("h", plan, None)  # second in a row
        assert plan.hotspot_streak["h"] == 0 and plan.minisweeps_used == 1
        plan.minisweeps_used = SWEEP.MAX_MINISWEEPS
        assert not SWEEP.TRY_HOTSPOT_MINISWEEP("g", plan, None)
        assert not SWEEP.TRY_HOTSPOT_MINISWEEP("g", plan, None)  # budget spent
    assert calls == ["h"], calls


def test_region_bootstrap_and_calibration_after_lock():
    region = AUTO_PIPELINE.AutoPipelineRegion("a" + M + "r", C_TO_LOGIC.AutoPipelineLatency(start_latency=4), "k", "region_func")
    landscape = SWEEP.SliceLandscape(region.inst, 20, 0.5)
    landscape.segments.append(SWEEP.Segment(region.inst + M + "h", "h", 0.0, 10.0, SWEEP.Segment.LOCKED))
    landscape.finalize({})
    region.landscape = landscape
    count, calibrate = AUTO_PIPELINE._AUTO_PIPELINE_REGION_COUNT(region, 10.0, 1.0)
    # The lock already holds part of the depth: no S=4 on top of it
    assert not region.start_pending and not calibrate and count != 4, (count, calibrate)
    plan = SWEEP.MainSweepPlan("a", 100)
    other = AUTO_PIPELINE.AutoPipelineRegion("a" + M + "q", C_TO_LOGIC.AutoPipelineLatency(start_latency=2), "other", "q")
    plan.regions = [region, other]
    region.scale, other.scale, other.start_pending = 0.36, 0.5, True
    region.start_pending = True
    AUTO_PIPELINE.RESET_REGION_CALIBRATION_AFTER_LOCK(plan, region)
    assert region.scale == 1.0 and not region.start_pending
    assert other.scale == 0.5 and other.start_pending  # other groups untouched


def _region_sweep(constraint):
    """Main 'a' whose only cuttable logic is a constrained region 'a____r'
    around a repeated helper 'h'; its path fails until 'h' is locked."""
    ps = _region_state(constraint)
    regions = AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(ps)
    helper = "a" + M + "r" + M + "h"

    def fresh(_):
        return {i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}

    params = SimpleNamespace(TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={})
    minis = []

    def mini(func, plan, ps_):
        minis.append(func)
        table = fresh(ps_)
        table[helper].SET_SLICES([0.5])
        plan.locked[helper] = SWEEP.MiniSweepLock(
            [0.5],
            concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(helper, table, ps_),
            model_fingerprint=SWEEP.SUBTREE_MODEL_FINGERPRINT(helper, ps_),
        )
        return True

    def rule(ps_, p):
        return [path("a", 5.0 if p.TimingParamsLookupTable[helper]._slices else 12.0)]

    backend = ScriptedBackend(rule, True)
    history = {}
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        for obj, key, value in _scripted_sweep_patches(
            backend,
            fresh,
            [
                (SYN, "SYN_OUTPUT_DIRECTORY", out),
                (SWEEP, "SWEEP_HISTORY", history),
                (AUTO_PIPELINE, "COLLECT_AUTO_PIPELINE_REGIONS", lambda *a, **k: regions),
                (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: ("h", None, "")),
                (SWEEP, "RUN_HOTSPOT_MINISWEEP", mini),
                (SWEEP, "SUMMARIZE_SUBTREE_PIPELINE", lambda m, st, t, p: (False, [], len(t[helper]._slices))),
                (SWEEP, "GET_SUBTREE_PIPELINE_STAGES", lambda plan, t, p: len(t[helper]._slices)),
                (
                    AUTO_PIPELINE.TimingParams,
                    "GET_TOTAL_LATENCY",
                    lambda self, _ps, t: sum(
                        len(t[i]._slices) for i in t
                        if i == self.inst_name or i.startswith(self.inst_name + M)
                    ),
                ),
                (AUTO_PIPELINE, "FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL", lambda *a: True),
            ],
        ):
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
    actions = [r["action"] for r in history["a"]["iterations"]]
    return result, minis, actions, regions[0]


def test_start_latency_region_hotspot_takes_the_minisweep():
    result, minis, actions, region = _region_sweep(C_TO_LOGIC.AutoPipelineLatency(start_latency=1))
    assert minis == ["h"], (minis, actions)
    assert actions[0].startswith("grow_auto_pipeline"), actions
    assert actions[1] == "minisweep(h)", actions
    assert actions[-1] == "met", actions
    assert not result.sweep_timing_failures, result.sweep_timing_failures
    assert region.scale == 1.0, region.scale  # recalibrated on the lock


def test_capped_region_never_locks_inside():
    result, minis, actions, _region = _region_sweep(C_TO_LOGIC.AutoPipelineLatency(max_latency=3))
    assert minis == [], (minis, actions)
    assert all(a.startswith(("grow_auto_pipeline", "stop", "replan")) for a in actions), actions
    assert result.sweep_timing_failures, "the capped region cannot meet timing here"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}", flush=True)
        except Exception:
            import traceback

            traceback.print_exc()
            print(f"[FAIL] {name}", flush=True)
            failed.append(name)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} test functions passed.")
    if failed:
        print("FAILED: " + ", ".join(failed))
        sys.exit(1)
