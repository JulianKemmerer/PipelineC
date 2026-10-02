#!/usr/bin/env python3
# pyright: reportInvalidTypeForm=none
"""AUTO_MULTI_CYCLE unit tests -- no synthesis tool involved:
  - AUTO_MULTI_CYCLE constructor validation and .latency resolution (default/start/
    fixed/cache), construction-site keys, the inline-construction guard,
    design-read tracking (served / unread);
  - pypeline_names identity follows the resolved cycle count;
  - SYN: MCP_EFFECTIVE_NCYCLES, ELABORATED/HARVEST_AUTO_MULTI_CYCLE_NCYCLES, the
    MultiMainTimingParams hash (unchanged unless a count was overridden);
  - SWEEP: timing-report register matching, needed-cycle math, feedback with
    and without a cap, on a synthetic Vivado multi-cycle path report;
  - elaboration: stream_auto_multi_cycle_test.py's AUTO_MULTI_CYCLE paths land in
    Logic.auto_multi_cycle_tuples, a cache re-parse changes the count AND renames the
    holding entity, and an unread tag fails AUTO_MULTI_CYCLE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ;
  - endpoint selection on that design's elaborated wrappers (controller
    counter, look-alike names and CE pins excluded) and isolated-seed rounding.
"""
import os
import sys
import types

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(THIS_DIR, "..", "..", "..")
sys.path.insert(0, SRC_DIR)
sys.path.insert(0, os.path.join(SRC_DIR, "..", "include", "pypeline"))

import pypeline
from pypeline import AUTO_MULTI_CYCLE, Reg, uint32_t
import pypeline_names
import C_TO_LOGIC
import PY_TO_LOGIC
import AUTO_PIPELINE
import AUTO_MULTI_CYCLE as AUTO_MULTI_CYCLE_MODULE  # aliased: the pypeline tag has the same name
import VHDL
import VIVADO


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} from {fn}")


def make_tag(**kwargs):
    return AUTO_MULTI_CYCLE(**kwargs)  # one construction site for key tests


def test_constructor_validation():
    expect_raises(ValueError, AUTO_MULTI_CYCLE, latency=0)
    expect_raises(ValueError, AUTO_MULTI_CYCLE, start_latency=-1)
    expect_raises(TypeError, AUTO_MULTI_CYCLE, max_latency=True)
    expect_raises(TypeError, AUTO_MULTI_CYCLE, start_latency=2.0)
    expect_raises(ValueError, AUTO_MULTI_CYCLE, latency=2, start_latency=2)
    expect_raises(ValueError, AUTO_MULTI_CYCLE, latency=2, max_latency=3)
    expect_raises(ValueError, AUTO_MULTI_CYCLE, start_latency=4, max_latency=3)
    expect_raises(TypeError, AUTO_MULTI_CYCLE, 3)  # keyword-only
    print("test_constructor_validation PASS")


def test_latency_resolution():
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    assert AUTO_MULTI_CYCLE()._ncycles_for_compiler() == 1
    assert AUTO_MULTI_CYCLE(start_latency=3)._ncycles_for_compiler() == 3
    assert AUTO_MULTI_CYCLE(start_latency=3, max_latency=5)._ncycles_for_compiler() == 3
    tag = AUTO_MULTI_CYCLE(latency=4)
    assert tag.latency == 4 and tag.ncycles == 4
    print("test_latency_resolution PASS")


def test_keys_and_cache():
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    k0 = make_tag(start_latency=2).canonical_key
    k1 = make_tag(start_latency=2).canonical_key
    assert k0 != k1, (k0, k1)
    assert k0.endswith("_0_start_latency_2") and k1.endswith("_1_start_latency_2"), (
        k0,
        k1,
    )
    # Deterministic across a re-execution (tracking reset between them)
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    assert make_tag(start_latency=2).canonical_key == k0
    # Cache resolves the count; mismatches with fixed/max are errors
    try:
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({k0: 5})
        assert make_tag(start_latency=2)._ncycles_for_compiler() == 5
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        k_max = make_tag(start_latency=2, max_latency=4).canonical_key
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({k_max: 5})
        expect_raises(ValueError, make_tag, start_latency=2, max_latency=4)
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        k_fixed = make_tag(latency=2).canonical_key
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({k_fixed: 3})
        expect_raises(ValueError, make_tag, latency=2)
    finally:
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({})
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    print("test_keys_and_cache PASS")


def test_inline_construction_rejected():
    for pseudo_file in ("<local_const>", "<const_eval>"):
        expect_raises(
            TypeError,
            eval,
            compile("AUTO_MULTI_CYCLE(start_latency=2)", pseudo_file, "eval"),
            {"AUTO_MULTI_CYCLE": AUTO_MULTI_CYCLE},
        )
    print("test_inline_construction_rejected PASS")


def test_read_tracking():
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    tag = make_tag(start_latency=2)
    fixed = AUTO_MULTI_CYCLE(latency=3)
    assert pypeline.AUTO_MULTI_CYCLE_UNREAD_KEYS() == [tag.canonical_key]
    tag._ncycles_for_compiler()  # the compiler's read does not count
    assert pypeline.AUTO_MULTI_CYCLE_UNREAD_KEYS() == [tag.canonical_key]
    assert tag.latency == 2
    assert pypeline.AUTO_MULTI_CYCLE_UNREAD_KEYS() == []
    assert pypeline.AUTO_MULTI_CYCLE_SERVED_LATENCIES() == {tag.canonical_key: {2}}
    assert fixed.canonical_key not in pypeline.AUTO_MULTI_CYCLE_UNREAD_KEYS()
    # PARSE_FILE's per-execution reset also clears AUTO_MULTI_CYCLE tracking
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
    assert pypeline.AUTO_MULTI_CYCLE_SERVED_LATENCIES() == {}
    assert pypeline.AUTO_MULTI_CYCLE_CONSTRUCTED() == {}
    print("test_read_tracking PASS")


def test_identity_follows_count_and_reg_tag():
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    tag = make_tag(start_latency=2)

    def holder():
        return tag

    id_tag = pypeline_names.identity(tag)
    id_holder = pypeline_names.identity(holder)
    tag._ncycles = 6
    assert pypeline_names.identity(tag) != id_tag
    assert pypeline_names.identity(holder) != id_holder
    tag._ncycles = 2
    assert pypeline_names.identity(tag) == id_tag
    reg_t = Reg[uint32_t, tag.start]
    assert reg_t.multi_cycle_role.tag is tag and reg_t.multi_cycle_role.is_start
    assert "start_latency=2" in repr(tag)
    print("test_identity_follows_count_and_reg_tag PASS")


def _fake_parser_state(ncycles="3"):
    constraint = C_TO_LOGIC.AutoMultiCycleConstraint("k", None, 3, None)
    logic = types.SimpleNamespace(
        mcp_tuples={(ncycles, "launch", "capture")},
        auto_multi_cycle_tuples={("launch", "capture"): constraint},
    )
    return (
        types.SimpleNamespace(main_mhz={}, FuncLogicLookupTable={"f": logic}),
        constraint,
    )


def test_syn_counts_and_hash():
    parser_state, constraint = _fake_parser_state()
    assert AUTO_MULTI_CYCLE_MODULE.ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state) == {"k": 3}
    mtp = AUTO_PIPELINE.MultiMainTimingParams()
    tup = ("3", "launch", "capture")
    assert AUTO_MULTI_CYCLE_MODULE.MCP_EFFECTIVE_NCYCLES(tup, constraint, mtp) == "3"
    assert AUTO_MULTI_CYCLE_MODULE.MCP_EFFECTIVE_NCYCLES(tup, None, mtp) == "3"
    h_plain = mtp.GET_HASH_EXT(parser_state)
    mtp.auto_multi_cycle_ncycles = {"k": 3}  # equal to elaborated: hash unchanged
    assert mtp.GET_HASH_EXT(parser_state) == h_plain
    assert AUTO_MULTI_CYCLE_MODULE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES(parser_state, mtp) == {"k": 3}
    mtp.auto_multi_cycle_ncycles = {"k": 5}
    assert AUTO_MULTI_CYCLE_MODULE.MCP_EFFECTIVE_NCYCLES(tup, constraint, mtp) == "5"
    assert AUTO_MULTI_CYCLE_MODULE.MCP_EFFECTIVE_NCYCLES(tup, None, mtp) == "3"
    assert mtp.GET_HASH_EXT(parser_state) != h_plain
    assert AUTO_MULTI_CYCLE_MODULE.HARVEST_AUTO_MULTI_CYCLE_NCYCLES(parser_state, mtp) == {"k": 5}
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    assert AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED(parser_state, {"k": 3})
    assert not AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_BUILT_MATCHES_ELABORATED(parser_state, {"k": 5})
    print("test_syn_counts_and_hash PASS")


# Shaped like a Vivado report_timing_summary max-delay path of a 3-cycle MCP
# at a 10 ns clock, failing by 3 ns: 33 ns launch->capture.
_REPORT = """Max Delay Paths
--------------------------------------------------------------------------------------
Slack (VIOLATED) :        -3.000ns  (required time - arrival time)
  Source:                 main_top/func_mcp_inst/launch_reg[3]/C
                            (rising edge-triggered cell FDRE clocked by clk  {rise@0.000ns fall@5.000ns period=10.000ns})
  Destination:            main_top/func_mcp_inst/capture_reg[7]/D
                            (rising edge-triggered cell FDRE clocked by clk  {rise@0.000ns fall@5.000ns period=10.000ns})
  Path Group:             clk
  Path Type:              Setup (Max at Slow Process Corner)
  Requirement:            30.000ns  (clk rise@30.000ns - clk rise@0.000ns)
  Data Path Delay:        32.500ns  (logic 10.000ns (30.769%)  route 22.500ns (69.231%))
  Logic Levels:           20  (CARRY4=10 LUT2=10)
"""


def test_report_matching_and_feedback():
    report = VIVADO.PathReport(_REPORT)
    assert (report.start_pin_name, report.end_pin_name) == ("C", "D")
    assert (report.start_cell_type, report.end_cell_type) == ("FDRE", "FDRE")
    dsp_report = VIVADO.PathReport(_REPORT.replace("launch_reg[3]/C", "mul/dsp/CLK").replace("cell FDRE", "cell DSP48E1", 1))
    assert (dsp_report.start_pin_name, dsp_report.start_cell_type) == ("CLK", "DSP48E1")
    assert report.start_reg_name == "main_top/func_mcp_inst/launch_reg[3]", (
        report.start_reg_name
    )
    assert report.end_reg_name == "main_top/func_mcp_inst/capture_reg[7]"
    assert abs(report.requirement_ns - 30.0) < 1e-9
    assert abs(report.path_delay_ns - 11.0) < 1e-9, report.path_delay_ns

    regex = AUTO_MULTI_CYCLE_MODULE._MCP_CELL_GLOB_REGEX("main_top/func_mcp_inst/launch_reg[*]")
    assert regex.search(report.start_reg_name)
    assert regex.search("outer/main_top/func_mcp_inst/launch_reg[12]")
    # Struct registers are named per field (Vivado: launch_reg[a][limbs][0][5])
    assert regex.search("main_top/func_mcp_inst/launch_reg[a][limbs][0][5]")
    assert not regex.search("main_top/func_mcp_inst/launch_reg[a]/sub_reg[1]")
    assert not regex.search("main_top/func_mcp_inst/launch_regx[3]")
    assert not regex.search("main_top/func_mcp_inst2/launch_reg[3]")
    assert not regex.search("main_top/func_mcp_inst/launch_reg[3]_rep")

    assert AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_NEEDED_NCYCLES(11.0, 3, 10.0) == 4
    assert AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_NEEDED_NCYCLES(9.0, 3, 10.0) == 4  # always grows
    assert AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_NEEDED_NCYCLES(40.0, 2, 10.0) == 8
    assert AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_NEEDED_NCYCLES(10.0, 4, 10.0) == 5

    def run(constraint, current):
        group = AUTO_MULTI_CYCLE_MODULE.AutoMultiCycleGroup("k", constraint)
        mtp = AUTO_PIPELINE.MultiMainTimingParams()
        mtp.auto_multi_cycle_ncycles = {"k": current}
        action, changed, blame = AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_FEEDBACK(group, report, 100.0, mtp)
        return mtp.auto_multi_cycle_ncycles["k"], action, changed, blame

    n, action, changed, blame = run(C_TO_LOGIC.AutoMultiCycleConstraint("k", None, 3), 3)
    assert changed and n == 4 and blame is None and "3->4" in action, action
    n, action, changed, blame = run(C_TO_LOGIC.AutoMultiCycleConstraint("k", None, 3, 3), 3)
    assert not changed and n == 3 and "max_latency=3" in blame, blame
    n, action, changed, blame = run(C_TO_LOGIC.AutoMultiCycleConstraint("k", 3), 3)
    assert not changed and n == 3 and "latency=3" in blame, blame
    print("test_report_matching_and_feedback PASS")


def _auto_multi_cycle_paths(parser_state):
    """func name -> [(ncycles, constraint)] for Logic carrying AUTO_MULTI_CYCLE paths."""
    rv = {}
    for func_name, logic in parser_state.FuncLogicLookupTable.items():
        for tup in logic.mcp_tuples:
            constraint = logic.auto_multi_cycle_tuples.get((tup[1], tup[2]))
            if constraint is not None:
                rv.setdefault(func_name, []).append((int(tup[0]), constraint))
    return rv


def test_elaboration_and_cache_reparse():
    design = os.path.join(THIS_DIR, "stream_auto_multi_cycle_test.py")
    parser_state = PY_TO_LOGIC.PARSE_FILE(design)
    paths = _auto_multi_cycle_paths(parser_state)
    counts = sorted(n for entries in paths.values() for n, _c in entries)
    assert counts == [2, 3], paths
    start_key = next(
        c.key for entries in paths.values() for n, c in entries if n == 3
    )
    assert start_key.endswith("_start_latency_3_max_latency_8"), start_key
    AUTO_MULTI_CYCLE_MODULE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ(parser_state)  # the library reads .latency
    try:
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({start_key: 5})
        reparsed = PY_TO_LOGIC.PARSE_FILE(design)
    finally:
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({})
    new_paths = _auto_multi_cycle_paths(reparsed)
    new_counts = sorted(n for entries in new_paths.values() for n, _c in entries)
    assert new_counts == [2, 5], new_paths
    renamed_old = {f for f, entries in paths.items() if any(n == 3 for n, _ in entries)}
    renamed_new = {
        f for f, entries in new_paths.items() if any(n == 5 for n, _ in entries)
    }
    assert renamed_old and renamed_new and not (renamed_old & renamed_new), (
        renamed_old,
        renamed_new,
    )
    # The fixed latency=2 path's holder keeps its name
    fixed_old = {f for f, entries in paths.items() if any(n == 2 for n, _ in entries)}
    fixed_new = {
        f for f, entries in new_paths.items() if any(n == 2 for n, _ in entries)
    }
    assert fixed_old == fixed_new, (fixed_old, fixed_new)
    print("test_elaboration_and_cache_reparse PASS")


def test_endpoint_selection_on_elaborated_wrapper():
    """The real stream wrapper's launch/capture registers, and nothing else:
    its cycles_since_launch controller, look-alike names and a CE pin are
    neither constrained nor attributed to the group. Also checks the isolated
    seed's delay-to-cycles rounding against the same elaborated groups."""
    from types import SimpleNamespace
    from unittest.mock import patch
    import SYN

    parser_state = PY_TO_LOGIC.PARSE_FILE(
        os.path.join(THIS_DIR, "stream_auto_multi_cycle_test.py")
    )
    tpl = {
        inst: AUTO_PIPELINE.TimingParams(inst, logic)
        for inst, logic in parser_state.LogicInstLookupTable.items()
    }
    mtp = AUTO_PIPELINE.MultiMainTimingParams()
    mtp.TimingParamsLookupTable = tpl
    mtp.auto_multi_cycle_ncycles = AUTO_MULTI_CYCLE_MODULE.ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state)
    groups = AUTO_MULTI_CYCLE_MODULE.COLLECT_AUTO_MULTI_CYCLE_GROUPS(parser_state)
    holders = {
        inst: logic
        for inst, logic in parser_state.LogicInstLookupTable.items()
        if logic.mcp_tuples
    }
    assert len(holders) == 2, sorted(holders)  # fixed latency=2 and start_latency=3
    period = 10.0
    for inst, logic in sorted(holders.items()):
        main = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(inst, parser_state)
        top = VHDL.GET_ENTITY_NAME(main, parser_state.LogicInstLookupTable[main], tpl, parser_state)
        paths = AUTO_MULTI_CYCLE_MODULE.GET_MCP_CELL_PATHS(inst, main, top, parser_state)
        assert len(paths) == 1, paths
        tup, start, end, auto = paths[0]
        assert (tup[1], tup[2]) == ("launch", "capture"), tup
        assert start.endswith("/launch_reg[*]") and end.endswith("/capture_reg[*]")
        prefix = start[: -len("launch_reg[*]")]
        start_re = AUTO_MULTI_CYCLE_MODULE._MCP_CELL_GLOB_REGEX(start)
        end_re = AUTO_MULTI_CYCLE_MODULE._MCP_CELL_GLOB_REGEX(end)
        # Every other register of the holder is controller state, never an endpoint.
        controller = set(logic.state_regs) - {"launch", "capture"}
        assert "cycles_since_launch" in controller, sorted(logic.state_regs)
        decoys = [prefix + reg + "_reg[2]" for reg in sorted(controller)] + [
            prefix + "not_launch_reg[0]",
            prefix + "not_capture_reg[0]",
            prefix + "cycles_since_launch_reg[7]",
            prefix + "launch_reg[0]_i_1",
        ]
        for name in decoys:
            assert not start_re.search(name) and not end_re.search(name), name
        ncycles = int(tup[0])
        with patch.object(SYN, "SYN_TOOL", VIVADO):
            xdc = AUTO_MULTI_CYCLE_MODULE.GET_MCP_PATH_CONSTRAINTS(inst, main, top, mtp, parser_state)
        assert not any("cycles_since_launch" in line for line in xdc), xdc
        assert sum("-setup" in line for line in xdc) == sum("-hold" in line for line in xdc) == 1
        assert f"set_multicycle_path {ncycles - 1} -hold" in "\n".join(xdc)

        def report(source, dest, pin="D"):
            return SimpleNamespace(
                start_reg_name=source, end_reg_name=dest, end_pin_name=pin,
                start_pin_name="C", start_cell_type="FDRE",
                source_ns_per_clock=period, requirement_ns=ncycles * period,
                slack_ns=-1.0, path_delay_ns=ncycles * period + 1.0,
            )

        real = report(prefix + "launch_reg[3]", prefix + "capture_reg[5]")
        wrong = [
            report(prefix + "cycles_since_launch_reg[1]", prefix + "capture_reg[5]"),
            report(prefix + "not_launch_reg[3]", prefix + "capture_reg[5]"),
            report(prefix + "launch_reg[3]", prefix + "capture_reg[5]", pin="CE"),
            report(prefix + "launch_reg[3]", prefix + "cycles_since_launch_reg[0]"),
        ]
        group = AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT(real, groups, parser_state, mtp)
        if auto is None:
            assert group is None  # a fixed MULTI_CYCLE path has no group to grow
            continue
        assert group is not None and group.key == auto.key
        for path in wrong:
            assert AUTO_MULTI_CYCLE_MODULE.AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT(path, groups, parser_state, mtp) is None, path
        # Isolated characterization keeps only the real launch->capture D path.
        timing = SimpleNamespace(path_reports={"clk": real}, extra_paths=wrong)
        with patch.object(AUTO_MULTI_CYCLE_MODULE, "ISOLATED_MCP_EVIDENCE", {}) as evidence:
            AUTO_MULTI_CYCLE_MODULE.REMEMBER_ISOLATED_REPORTS(timing, parser_state, mtp, main)
            shape = AUTO_MULTI_CYCLE_MODULE.MCP_SHAPE(group, parser_state)
            assert evidence == {(auto.key, shape): ncycles * period + 1.0}, evidence
            timing.path_reports = {}
            evidence.clear()
            AUTO_MULTI_CYCLE_MODULE.REMEMBER_ISOLATED_REPORTS(timing, parser_state, mtp, main)
            assert evidence == {}, evidence

    # Seed rounding: ceil(raw delay / period), at least 1, capped, grow-only,
    # and only for start_latency= tags (latency= is fixed).
    (auto_key,) = [k for k, g in groups.items() if not g.constraint.is_fixed()]
    shape = AUTO_MULTI_CYCLE_MODULE.MCP_SHAPE(groups[auto_key], parser_state)
    start = AUTO_MULTI_CYCLE_MODULE.ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(parser_state)[auto_key]
    assert start == 3
    for raw, expected in ((0.1, 3), (30.0, 3), (30.0 + 1e-12, 3), (30.5, 4), (61.0, 7), (1000.0, 8)):
        with patch.object(AUTO_MULTI_CYCLE_MODULE, "ISOLATED_MCP_EVIDENCE", {(auto_key, shape): raw}), \
                patch.object(AUTO_MULTI_CYCLE_MODULE, "PROVISIONAL_MCP_SEEDS", {}) as seeds, \
                patch.object(SYN, "GET_TARGET_MHZ", lambda inst, ps: 1000.0 / period):
            params = SimpleNamespace(auto_multi_cycle_ncycles={})
            counts = AUTO_MULTI_CYCLE_MODULE.SEED_COUNTS(parser_state, params)
            assert counts[auto_key] == expected, (raw, counts)
            assert all(n >= 1 for n in counts.values())
            assert bool(seeds) == (expected > start), (raw, seeds)
            fixed = [k for k, g in groups.items() if g.constraint.is_fixed()]
            assert all(counts[k] == 2 for k in fixed), counts
    print("test_endpoint_selection_on_elaborated_wrapper PASS")


def test_unread_tag_fails_build_check():
    parser_state = PY_TO_LOGIC.PARSE_FILE(
        os.path.join(THIS_DIR, "auto_multi_cycle_unread_design.py")
    )
    assert _auto_multi_cycle_paths(parser_state)
    try:
        AUTO_MULTI_CYCLE_MODULE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ(parser_state)
    except SystemExit as err:
        assert ".latency was never read" in str(err), err
    else:
        raise AssertionError("unread AUTO_MULTI_CYCLE was not refused")
    print("test_unread_tag_fails_build_check PASS")


if __name__ == "__main__":
    test_constructor_validation()
    test_latency_resolution()
    test_keys_and_cache()
    test_inline_construction_rejected()
    test_read_tracking()
    test_identity_follows_count_and_reg_tag()
    test_syn_counts_and_hash()
    test_report_matching_and_feedback()
    test_elaboration_and_cache_reparse()
    test_endpoint_selection_on_elaborated_wrapper()
    test_unread_tag_fails_build_check()
    print("All AUTO_MULTI_CYCLE unit tests passed.")
