#!/usr/bin/env python3
"""In-process unit tests for the AUTOFSM scheduler and code generator.

These run the real elaborator (PY_TO_LOGIC.PARSE_FILE) but no synthesis, so
they are fast and can assert on things a build log cannot show: the exact
schedule, the generated source text, and the invariants that keep the driver's
schedule-and-confirm loop sound.

What is covered, and why each matters:
  - binding: several operations of one kind bind to ONE unit (the feature)
  - one operation per unit per state (what makes a unit shareable at all)
  - dependencies: an operation is never scheduled before its inputs
  - registers: any value crossing a state boundary gets one (otherwise the FSM
    silently reads whatever the shared unit happens to be computing)
  - budget: a tighter per-state budget produces more/smaller states
  - floors: an indivisible operation bigger than a state is reported, not
    looped on forever
  - determinism: the same design schedules identically and generates
    byte-identical source, which is what keeps entity names stable across the
    driver's repeated re-elaborations
  - the schedule is plain picklable data (it is carried across design re-execs)
"""
import copy
import json
import os
import pickle
import re
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import AUTOFSM
import C_TO_LOGIC
import DEVICE_MODELS
import PY_TO_LOGIC
import SYN
import pypeline

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


DESIGN_SRC = textwrap.dedent(
    """
    # pyright: reportInvalidTypeForm=none
    import os, sys
    sys.path.insert(0, {repo!r})
    from pypeline import (AUTOFSM, MAIN, NamedTuple, Reg, hw_func, int16_t,
                          struct, uint1_t)

    @struct
    class in_t(NamedTuple):
        a: int16_t
        b: int16_t
        c: int16_t
        d: int16_t

    @hw_func
    def chain(x: in_t) -> int16_t:
        t0: int16_t = x.a + x.b
        t1: int16_t = t0 + x.c
        t2: int16_t = t1 + x.d
        return t2

    FSM = AUTOFSM(chain)

    @MAIN({mhz})
    def top(start: uint1_t, x: in_t) -> int16_t:
        s: FSM.in_stream_t
        s.data = x
        s.valid = start
        o = FSM(s)
        r: Reg[int16_t]
        if o.valid:
            r = o.data
        return r
    """
)

CROSS_FU_SRC = (
    DESIGN_SRC.replace("x.a + x.b", "x.a ^ x.b")
    .replace("t0 + x.c", "t0 & x.c")
    .replace("t1 + x.d", "t1 | x.d")
)

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))


def parse_design(tmpdir, mhz=25.0, name="af_unit_design", source=DESIGN_SRC):
    """Elaborate a fresh copy of the design and hand back the parser state plus
    its AUTOFSM tag. A distinct file name per call keeps Python's import
    machinery from returning a stale module."""
    path = os.path.join(tmpdir, name + ".py")
    with open(path, "w") as f:
        f.write(source.format(repo=REPO, mhz=mhz))
    parser_state = PY_TO_LOGIC.PARSE_FILE(path)
    tags = AUTOFSM.GET_TAGS(parser_state)
    assert len(tags) == 1, f"expected one AUTOFSM tag, got {list(tags)}"
    (key,) = list(tags)
    return parser_state, key, tags[key]


def fake_delays(parser_state, key, tag, adder_du=115):
    """Delays as a real build would have measured them, without running one:
    every adder costs adder_du, all rewiring is free."""
    func_entity = AUTOFSM._entity_key_for_callable(parser_state, tag.func)
    logic = parser_state.FuncLogicLookupTable[func_entity]
    for entity in set(logic.submodule_instances.values()):
        sub = parser_state.FuncLogicLookupTable[entity]
        sub.delay = adder_du if entity.startswith("BIN_OP_") else 0
    parser_state.FuncLogicLookupTable[func_entity].delay = adder_du * 3
    return func_entity


def schedule_with(parser_state, key, tag, budget_scale):
    return AUTOFSM.BUILD_SCHEDULE(parser_state, key, tag, budget_scale)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("[binding and scheduling]")
        ps, key, tag = parse_design(tmp, mhz=25.0, name="d1")
        fake_delays(ps, key, tag)
        # 40 ns period; 3 adds at 11.5 ns each could all fit one state by delay
        # alone, so anything beyond one state per add comes from the
        # one-operation-per-unit-per-state rule, which is the point.
        sched = schedule_with(ps, key, tag, 0.9)

        scheduled = {n: v for n, v in sched["nodes"].items() if v.get("fu")}
        check(len(scheduled) == 3, f"3 adds scheduled (got {len(scheduled)})")
        check(
            len(sched["fus"]) == 1,
            f"3 adds bound to 1 shared unit (got {len(sched['fus'])})",
        )
        check(sched["n_states"] == 3, f"3 states (got {sched['n_states']})")
        check(
            sched["latency"] == sched["n_states"] + 1,
            "latency == states + 1 accept cycle",
        )

        per_state = {}
        for nid, node in scheduled.items():
            per_state.setdefault((node["state"], node["fu"]), []).append(nid)
        check(
            all(len(v) == 1 for v in per_state.values()),
            "at most one operation per unit per state",
        )

        # Dependencies: an operand may only come from an earlier-or-equal state.
        sched_ids = set(scheduled)
        ok_deps = True
        for nid, node in scheduled.items():
            deps = set()
            for operand in node["operands"]:
                AUTOFSM._scheduled_deps(
                    {"nodes": sched["nodes"]}, operand, sched_ids, deps
                )
            for dep in deps - {nid}:
                if scheduled[dep]["state"] > node["state"]:
                    ok_deps = False
        check(ok_deps, "no operation is scheduled before its inputs")

        print("[registers for values crossing states]")
        cg = AUTOFSM._Codegen(tag, sched, ps)
        cross = cg._cross_state_nodes()
        # In a 3-add chain each intermediate is produced in one state and
        # consumed in the next, so both must be registered.
        check(len(cross) == 2, f"2 intermediates registered (got {len(cross)})")
        ok_reg = True
        for nid in scheduled:
            producer_state = scheduled[nid]["state"]
            for other, onode in scheduled.items():
                deps = set()
                for operand in onode["operands"]:
                    AUTOFSM._scheduled_deps(
                        {"nodes": sched["nodes"]}, operand, sched_ids, deps
                    )
                if nid in deps and onode["state"] > producer_state:
                    if nid not in cross:
                        ok_reg = False
        check(ok_reg, "every value read in a later state has a register")

        print("[generated source]")
        name, src, _globals = AUTOFSM.GENERATE_FSM_SOURCE(tag, sched, ps)
        check(name == sched["entity"], "generated function name is the schedule entity")
        check(src.count("+") == 1, f"exactly one '+' in the generated FSM (got {src.count('+')})")
        check("if (st == 0) & s.valid:" in src, "accepts input only while idle")
        # v3 drives valid straight from the last-state pulse bit rather than
        # defaulting it to 0 and setting 1 inside a state comparison.
        check("out_valid_r = ow" in src, "pulses valid when the result is ready")
        check(
            src.index("st: ") < src.index("st_r = "),
            "state is snapshotted before it is written",
        )

        print("[v3 control path]")
        # The whole point of ctl v3: state is compared ONCE per FSM, in the
        # accept. Everything else -- unit selects, register write enables, the
        # next state -- reads a constant table indexed by the state instead.
        check(
            src.count("st == ") == 1,
            f"exactly one state comparator in the whole FSM "
            f"(got {src.count('st == ')})",
        )
        check("ns_lut: " in src, "next state comes from a constant table")
        check(
            src.index("st_r = ns_lut[st]") < src.index("if (st == 0) & s.valid:"),
            "the next-state table is written BEFORE the accept, so accepting "
            "an input overrides it (pypeline assignment is sequential)",
        )
        # 3 adds on one unit over 3 states: one select table, and the only
        # value crossing a state boundary is the running sum.
        check(
            "u0_sel0_lut: " in src,
            "the shared unit's select comes from a table",
        )
        check(
            src.count("_wel: ") == 1,
            f"one write-enable table per cross-state register "
            f"(got {src.count('_wel: ')})",
        )
        check(
            "if v0_we:" in src,
            "the register write is a plain one-bit enable, which PY_TO_LOGIC "
            "turns into a clock enable rather than a comparator",
        )
        # State 1 runs fold 0, state 2 fold 1, state 3 fold 2; state 0 is idle
        # and reads 0, which is harmless because nothing is enabled there.
        check("[0, 0, 1, 2]" in src, "select table maps state -> fold index")
        check("[0, 2, 3, 0]" in src, "next-state table advances then wraps to idle")

        print("[v2 control path is still available for A/B]")
        ps_v2, key_v2, tag_v2 = parse_design(tmp, mhz=25.0, name="d1b")
        fake_delays(ps_v2, key_v2, tag_v2)
        sched_v2 = AUTOFSM.BUILD_SCHEDULE(ps_v2, key_v2, tag_v2, 0.9, ctl="v2")
        _n2, src_v2, _g2 = AUTOFSM.GENERATE_FSM_SOURCE(tag_v2, sched_v2, ps_v2)
        check("elif st == " in src_v2, "ctl v2 still emits comparator chains")
        check(
            src_v2.count("st == ") > 1,
            "ctl v2 compares the state many times (what v3 removes)",
        )
        check(
            sched_v2["entity"] != sched["entity"],
            "the control path is part of the schedule identity, so measured "
            "delays cached for one are never reused for the other",
        )
        check(
            AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps_v2, sched_v2)
            > AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps, sched),
            "the area model prices v3's control path below v2's (which is what "
            "lets the sweep share further before muxes overtake the saving)",
        )

        print("[one-hot control path]")
        ps_oh, key_oh, tag_oh = parse_design(tmp, mhz=25.0, name="d1c")
        fake_delays(ps_oh, key_oh, tag_oh)
        sched_oh = AUTOFSM.BUILD_SCHEDULE(ps_oh, key_oh, tag_oh, 0.9, ctl="onehot")
        _n3, src_oh, _g3 = AUTOFSM.GENERATE_FSM_SOURCE(tag_oh, sched_oh, ps_oh)
        check(
            "st1h_r: " in src_oh and "= 1" in src_oh,
            "one-hot state register resets to the idle bit",
        )
        check(
            "st == " not in src_oh,
            "one-hot compares the state ZERO times -- even the accept is a bit "
            "read",
        )
        check(
            "u0_sel0[0:0] = " in src_oh,
            "the operand mux select is encoded back to binary from hot bits "
            "(the mux is a measured balanced tree and needs a binary select)",
        )
        check(
            "v0_we: _af_t5 = st1h[1:1] | st1h[2:2]" in src_oh,
            "a write enable is a plain OR of the writing states' hot bits",
        )
        check(
            "(s.valid ^ 1)" in src_oh,
            "the idle-hold term complements one bit with ^ 1, not ~ (which "
            "would invert the whole promoted width)",
        )
        # One flip-flop per state plus idle, where binary needs only log2. The
        # complete one-hot design can still win by eliminating enough decode,
        # so pin the register term itself rather than assuming the total.
        check(
            AUTOFSM._register_bit_count(sched_oh)
            > AUTOFSM._register_bit_count(sched),
            "the area model charges one-hot for its extra flip-flops",
        )

        print("[automatic control encoding]")
        auto = AUTOFSM.HARVEST_AUTOFSM_SCHEDULES(
            ps, area_sweep=False, ctl="auto"
        )[key]
        auto_scores = auto.get("ctl_auto_candidates", {})
        check(
            auto["ctl"] in ("v3", "onehot") and len(auto_scores) == 2,
            "auto evaluates both supported area-oriented encodings",
        )
        check(
            abs(AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps, auto) - min(auto_scores.values()))
            < 0.01,
            "auto returns the lowest-area feasible encoding",
        )

        print("[budget controls state count]")
        ps2, key2, tag2 = parse_design(tmp, mhz=25.0, name="d2")
        fake_delays(ps2, key2, tag2)
        loose = schedule_with(ps2, key2, tag2, 4.0)
        tight = schedule_with(ps2, key2, tag2, 0.05)
        check(
            tight["n_states"] >= loose["n_states"],
            f"a tighter budget never reduces states ({loose['n_states']} -> "
            f"{tight['n_states']})",
        )
        check(
            tight["at_floor"],
            "a budget smaller than one indivisible operation reports at_floor "
            "(so the driver stops tightening instead of looping)",
        )
        check(
            not loose["at_floor"],
            "a comfortable budget does not report at_floor",
        )

        print("[determinism]")
        # Re-parse the SAME file, exactly as the driver's schedule-and-confirm
        # loop does between passes. Node ids are derived from source
        # coordinates (file basename, line, column), so this must reproduce the
        # identical schedule and identical generated source -- if it did not,
        # entity names would churn between passes and cross-pass matching would
        # break. (Parsing a copy under a different FILE NAME legitimately gives
        # different ids, which is why this re-parses in place.)
        ps3, key3, tag3 = parse_design(tmp, mhz=25.0, name="d1")
        fake_delays(ps3, key3, tag3)
        sched3 = schedule_with(ps3, key3, tag3, 0.9)
        check(key3 == key, "the tag's canonical key is stable across passes")
        check(
            AUTOFSM.SCHEDULES_EQUAL({key: sched}, {key3: sched3}),
            "the same design schedules identically on re-elaboration",
        )
        name3, src3, _g3 = AUTOFSM.GENERATE_FSM_SOURCE(tag3, sched3, ps3)
        check(name3 == name, f"entity name is stable across passes ({name} vs {name3})")
        check(src3 == src, "generated source is byte-identical across passes")

        print("[schedule is plain carryable data]")
        try:
            pickle.loads(pickle.dumps(sched))
            json.dumps(sched, sort_keys=True, default=str)
            ok_data = True
        except Exception as e:  # noqa: BLE001
            print("   ", e)
            ok_data = False
        check(ok_data, "schedule survives pickle/json round-trip")
        check(
            AUTOFSM.SCHEDULES_EQUAL({key: sched}, {key: copy.deepcopy(sched)}),
            "SCHEDULES_EQUAL matches a deep copy",
        )
        check(
            not AUTOFSM.SCHEDULES_EQUAL({key: sched}, {key: tight}),
            "SCHEDULES_EQUAL distinguishes different schedules",
        )
        check(
            bool(sched["entity_delays_snapshot"]),
            "the delay snapshot is carried (later passes reschedule from it)",
        )

        print("[tag API]")
        check(tag.latency == 0, "an unscheduled tag reports latency 0")
        check(
            tag.in_stream_t._fields == ("data", "valid")
            and tag.out_stream_t._fields == ("data", "valid"),
            "in/out stream types are {data, valid}",
        )
        check(
            pypeline.AUTOFSM(tag.func, max_latency=5).max_latency == 5,
            "max_latency is accepted and stored",
        )
        bad = 0
        for value in (1, 0, -3):
            try:
                pypeline.AUTOFSM(tag.func, max_latency=value)
            except ValueError:
                bad += 1
        try:
            pypeline.AUTOFSM(tag.func, max_latency="8")
        except TypeError:
            bad += 1
        check(bad == 4, "max_latency below 2, or non-int, is rejected at construction")
        check(
            repr(pypeline.AUTOFSM(tag.func, max_latency=5))
            != repr(pypeline.AUTOFSM(tag.func)),
            "the cap is part of the tag's repr (it feeds canonical entity names)",
        )
        unregistered_tag = pypeline.AUTOFSM(
            tag.func, max_latency=1, register_output=False
        )
        check(
            unregistered_tag.canonical_key != tag.canonical_key,
            "output-register policy is part of the canonical schedule key",
        )

        print("[optional output register]")
        unregistered = AUTOFSM.BUILD_SCHEDULE(
            ps, unregistered_tag.canonical_key, unregistered_tag, 0.9, ctl="v3"
        )
        _nu, src_u, _gu = AUTOFSM.GENERATE_FSM_SOURCE(
            unregistered_tag, unregistered, ps
        )
        check(
            unregistered["latency"] == unregistered["n_states"],
            "unregistered output removes the output cycle from latency",
        )
        check(
            "out_data_r" not in src_u and "out_valid_r" not in src_u,
            "unregistered output emits no redundant result register bank",
        )
        check(
            "o.valid = ow" in src_u,
            "unregistered output is valid directly in the final execution state",
        )

        print("[max_latency caps the schedule]")
        # The cap is a HARD constraint. Sharing everything onto one adder needs
        # one state per add; meeting a tighter cap therefore requires giving
        # back some sharing, which is exactly the trade the user asked for by
        # setting a cap at all.
        ps4, key4, tag4 = parse_design(tmp, mhz=25.0, name="d4")
        fake_delays(ps4, key4, tag4)
        uncapped = schedule_with(ps4, key4, tag4, 0.9)
        tag4.max_latency = 3
        capped = schedule_with(ps4, key4, tag4, 0.9)
        check(
            uncapped["latency"] > capped["latency"] <= 3,
            f"a max_latency=3 cap is met ({uncapped['latency']} -> "
            f"{capped['latency']} clks)",
        )
        check(
            not capped["latency_infeasible"],
            "meeting the cap is not reported as infeasible",
        )
        check(
            len(capped["fus"]) > len(uncapped["fus"]),
            f"the cap was met by unsharing ({len(uncapped['fus'])} -> "
            f"{len(capped['fus'])} units), the only thing that can buy latency",
        )
        check(
            all(fu == entity or fu.startswith(entity + "#")
                for fu, entity in capped["fus"].items()),
            "every extra unit id maps back to the entity it is a copy of",
        )
        check(
            capped["max_latency"] == 3 and uncapped["max_latency"] is None,
            "the cap is recorded in the schedule (a cached schedule built under "
            "a different cap must not be reused)",
        )

        print("[operand multiplexers are array reads, not if/elif chains]")
        name4, src4, _g4 = AUTOFSM.GENERATE_FSM_SOURCE(tag, sched, ps)
        check(
            "_af_mux" in src4,
            "a shared unit's operands go through a generated mux entity",
        )
        check(
            len(re.findall(r"u0_c0\[\d+\] =", src4)) == 2
            and len(re.findall(r"u0_c1\[\d+\] =", src4)) == 3,
            "each operand mux contains only distinct values (the two running "
            "sum operands share one register row; b/c/d remain distinct)",
        )

        repeated_src = DESIGN_SRC.replace("t1 + x.d", "t1 + x.b").replace(
            "t0 + x.c", "t0 + x.b"
        )
        ps_same, key_same, tag_same = parse_design(
            tmp, mhz=25.0, name="d_same_operand", source=repeated_src
        )
        fake_delays(ps_same, key_same, tag_same)
        sched_same = schedule_with(ps_same, key_same, tag_same, 0.9)
        _ns, src_same, _gs = AUTOFSM.GENERATE_FSM_SOURCE(
            tag_same, sched_same, ps_same
        )
        check(
            "u0_c1:" not in src_same and "u0_a1:" in src_same,
            "identical operands across states bypass the operand mux entirely",
        )

        print("[cross-functional-unit register reuse]")
        bind_nodes = {
            "a": {
                "delay_du": 1, "state": 1, "out_type": "uint8_t",
                "fu": "add", "operands": [("in", "x")],
            },
            "b": {
                "delay_du": 1, "state": 2, "out_type": "uint8_t",
                "fu": "xor", "operands": [("node", "a")],
            },
            "c": {
                "delay_du": 1, "state": 3, "out_type": "uint8_t",
                "fu": "sub", "operands": [("node", "b")],
            },
        }
        plain_regs, _ = AUTOFSM.ALLOCATE_REGISTERS(
            bind_nodes, ("node", "c"), 3
        )
        shared_regs, _ = AUTOFSM.ALLOCATE_REGISTERS(
            bind_nodes, ("node", "c"), 3, ("uint8_t",)
        )
        check(
            len(set(plain_regs.values())) == 2
            and len(set(shared_regs.values())) == 1,
            "non-overlapping values from different units can share one register",
        )
        ps_cross, key_cross, tag_cross = parse_design(
            tmp, mhz=25.0, name="d_cross_fu", source=CROSS_FU_SRC
        )
        fake_delays(ps_cross, key_cross, tag_cross)
        sched_cross = schedule_with(ps_cross, key_cross, tag_cross, 0.35)
        sched_cross["cross_fu_register_types"] = ["int16_t"]
        _nc, src_cross, _gc = AUTOFSM.GENERATE_FSM_SOURCE(
            tag_cross, sched_cross, ps_cross
        )
        cross_value_regs = re.findall(r"v\d+_r:", src_cross)
        check(
            "v0_wchoices:" in src_cross and "v1_r:" not in src_cross,
            "codegen emits one measured writeback mux for a cross-unit register "
            f"(write choices={src_cross.count('_wchoices:')}, "
            f"value regs={cross_value_regs})",
        )
        # Forcing latency 2 unshares completely: three adders, one use each.
        # A unit with a single user needs no selection at all, and paying for a
        # multiplexer there would be pure loss.
        tag4.max_latency = 2
        unshared = schedule_with(ps4, key4, tag4, 0.9)
        _n5, src5, _g5 = AUTOFSM.GENERATE_FSM_SOURCE(tag4, unshared, ps4)
        check(
            len(unshared["fus"]) == 3 and "_af_mux" not in src5,
            "a unit with a single user gets no multiplexer at all",
        )

        print("[area model and the minimum-area sweep]")
        ps6, key6, tag6 = parse_design(tmp, mhz=25.0, name="d6")
        fake_delays(ps6, key6, tag6)
        base = schedule_with(ps6, key6, tag6, 0.9)
        base_area = AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps6, base)
        check(base_area > 0, f"a schedule has a positive estimated area ({base_area:.0f})")
        # Opening a 16-bit adder into gates: three shared gates instead of one
        # shared adder, but 150-odd states' worth of registers and multiplexers
        # to pay for them. The model has to see that as WORSE, or the search
        # would decompose everything down to NAND.
        adder = "BIN_OP_PLUS_int16_t_int16_t"
        check(
            adder in getattr(ps6, "pypeline_autofsm_soft_equiv", {}),
            "a soft-operator equivalent was prepared for the built-in adder "
            "(this is what lets descent go below the operator level at all)",
        )
        gates = AUTOFSM.BUILD_SCHEDULE(ps6, key6, tag6, 0.9, None, (adder,))
        check(
            len(gates["nodes"]) > 10 * len(base["nodes"]),
            f"opening the adder really decomposes it ({len(base['nodes'])} -> "
            f"{len(gates['nodes'])} operations)",
        )
        check(
            all(not e.startswith("BIN_OP_PLUS") for e in gates["fus"].values()),
            f"the adder is gone, replaced by its gates: "
            f"{sorted(set(gates['fus'].values()))}",
        )
        check(
            AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps6, gates) > base_area,
            "sharing gates instead of adders is estimated as BIGGER, not "
            "smaller -- the multiplexers and registers outweigh the units",
        )
        gate_required_win = AUTOFSM._sweep_required_improvement(base, gates)
        check(
            gate_required_win > AUTOFSM.SWEEP_MIN_IMPROVEMENT,
            "opening into a much larger scheduled shape raises the confidence "
            f"threshold ({gate_required_win * 100.0:.1f}% required win)",
        )
        swept = AUTOFSM.SWEEP_MIN_AREA_SCHEDULE(ps6, key6, tag6, 0.9)
        check(
            swept["est_area"] <= swept["est_area_anchor"],
            "the sweep never returns something its own model calls worse than "
            "the plain schedule it started from",
        )
        check(
            swept["opened"] == [],
            "the sweep declines to open the adder into gates (its own model "
            "says that costs more than it saves)",
        )
        check(
            swept["est_area"] <= swept["est_area_anchor"],
            "the sweep's answer is never estimated worse than sharing "
            "everything at the written grain",
        )
        # THE calibration invariant, and the one the search gets wrong most
        # expensively if the AREA_* constants drift: an adder bit costs several
        # times what a multiplexer bit or a flip-flop does, so three adds
        # sharing one adder is smaller than three adders -- even counting the
        # multiplexers, the registers and the extra states. Confirmed against
        # real yosys cell counts by autofsm_area_sweep_compare_test.py; asserted
        # here because that test needs a full synthesis run and this does not.
        all_unshared = AUTOFSM.BUILD_SCHEDULE(
            ps6, key6, tag6, 0.9, None, (), None, ((adder, 3),)
        )
        check(
            len(all_unshared["fus"]) == 3
            and AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps6, all_unshared)
            > AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps6, base),
            f"building three adders is estimated as BIGGER than sharing one "
            f"({AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps6, base):.0f} shared vs "
            f"{AUTOFSM.ESTIMATE_SCHEDULE_AREA(ps6, all_unshared):.0f} unshared)",
        )
        check(
            swept["unshared"] == [],
            "...so the sweep leaves them shared",
        )
        ps7, key7, tag7 = parse_design(tmp, mhz=25.0, name="d6")
        fake_delays(ps7, key7, tag7)
        swept7 = AUTOFSM.SWEEP_MIN_AREA_SCHEDULE(ps7, key7, tag7, 0.9)
        check(
            AUTOFSM.SCHEDULES_EQUAL({key7: swept7}, {key6: swept}),
            "the sweep is deterministic across re-elaborations (its result "
            "names the generated entity, so it has to be)",
        )

    # ── soft-operator equivalents: which built-ins can be opened, and into
    #    WHAT. Signedness is the sharp edge -- substituting an unsigned
    #    algorithm for a signed operator does not make a slower design, it makes
    #    a wrong one, and _open_target's return-type/arity check cannot see the
    #    difference (same widths, different answers).
    print("\n[soft-operator equivalents]")

    class _FakeParserState:
        pass

    ps_soft = _FakeParserState()
    ps_soft.pypeline_builtin_op_info = {
        "u_mult": ("INFERRED_MULT", ("uint16_t", "uint16_t")),
        "s_mult": ("INFERRED_MULT", ("int16_t", "int16_t")),
        "u_div": ("DIV", ("uint16_t", "uint16_t")),
        "s_div": ("DIV", ("int16_t", "int16_t")),
        "u_mod": ("MOD", ("uint16_t", "uint16_t")),
        "shift": ("SR", ("uint32_t", "uint8_t")),
        "f_add": ("PLUS", ("float32_t", "float32_t")),
    }

    def soft_name(entity):
        fn = AUTOFSM._soft_equivalent_callable(ps_soft, entity)
        return getattr(fn, "__name__", None)

    check(
        soft_name("u_div") == "soft_div_radix",
        "an unsigned divide opens into the radix restoring divider (the one "
        "operation expensive enough that opening it buys real area)",
    )
    check(
        soft_name("s_div") == "soft_div_signed_radix",
        "a SIGNED divide opens into the signed divider, not the unsigned one",
    )
    # Modulo shares the divider's structure and, in the library, its function
    # NAME too (one factory, `want_remainder` picking which value comes out).
    # So the check that matters is not the name but that the two are different
    # functions computing different things -- a collision here would silently
    # turn `a % b` into `a / b`.
    div_fn = AUTOFSM._soft_equivalent_callable(ps_soft, "u_div")
    mod_fn = AUTOFSM._soft_equivalent_callable(ps_soft, "u_mod")
    check(
        mod_fn is not None and mod_fn is not div_fn,
        "unsigned modulo opens into its own function, not the divider's",
    )
    if mod_fn is not None and div_fn is not None:
        wrong = [
            (a, b)
            for a, b in ((100, 7), (255, 16), (9, 3), (1, 1))
            if pypeline.sim_call(div_fn, a, b) != a // b
            or pypeline.sim_call(mod_fn, a, b) != a % b
        ]
        check(
            not wrong,
            "the divide/modulo soft equivalents compute divide and remainder"
            + (f" -- wrong for {wrong[:2]}" if wrong else ""),
        )
    check(
        soft_name("u_mult") == "soft_mult_shift_add",
        "an unsigned multiply opens into the shift-and-add multiplier",
    )
    check(
        soft_name("s_mult") is None,
        "a SIGNED multiply is NOT openable: both soft multipliers treat the "
        "second operand as unsigned, so substituting one computes the wrong "
        "product (int16 -3 * 4 comes out as 1048564)",
    )
    check(
        soft_name("shift") is None,
        "shifts are not openable: the barrel shifter takes log2(width) amount "
        "bits where the built-in takes the operand's own width, so the two "
        "disagree for out-of-range shift amounts",
    )
    check(
        soft_name("f_add") is None,
        "floating-point operands have no soft equivalent",
    )

    # The soft adders have to widen their operands to the result type
    # themselves, bit by bit. Above an operand's own width a SIGNED value
    # continues with its sign bit, not with zero -- get that wrong and the
    # adder is right for every non-negative input and quietly wrong for the
    # rest, which is exactly what descending into a signed add used to build.
    print("\n[soft adder sign extension]")
    try:
        from operators.soft_add import make_soft_add_ripple, make_soft_add_carry_select

        # Compared against the BUILT-IN adder rather than Python's `+`: that is
        # the actual contract ("computes what + computes"), and it sidesteps
        # how a simulated value of a signed type prints.
        @pypeline.hw_func
        def _builtin_add(a: pypeline.int16_t, b: pypeline.int16_t) -> pypeline.int17_t:
            r: pypeline.int17_t = a + b
            return r

        cases = ((-3, 4), (-3, -4), (-1, 1), (-32768, 5), (-32768, -32768), (7, 9))
        for factory in (make_soft_add_ripple, make_soft_add_carry_select):
            f = factory(pypeline.int16_t, pypeline.int16_t)
            bad = [
                (a, b)
                for a, b in cases
                if (pypeline.sim_call(f, a, b) & 0x1FFFF)
                != (pypeline.sim_call(_builtin_add, a, b) & 0x1FFFF)
            ]
            check(
                not bad,
                f"{factory.__name__} sign-extends signed operands"
                + (f" -- wrong for {bad[:2]}" if bad else ""),
            )
    except ImportError:
        print("  skip: operators.soft_add not importable")

    # _TypeResolver.resolve rebuilds a live type from the C type name string a
    # Logic graph carries. Scalars always worked; an ARRAY of a reconstructible
    # type should too -- 'uint16_t[16]' is just 'uint16_t' plus a dimension,
    # regardless of whether anything in the design ever carried that exact
    # array type standalone. This is what a descended soft multiplier's local
    # partial-products array needs (see docs/AUTOFSM_DESIGN.md and
    # soft_mult.py's make_soft_mult_shift_add) -- entities fully consumed by
    # descent contribute nothing to the usual fus/node seeding, so the type
    # must be reconstructible from its name alone, not merely seeded.
    print("\n[type resolver: array reconstruction]")
    import typing

    @pypeline.struct
    class _seeded_leaf_t(typing.NamedTuple):
        a: pypeline.uint8_t
        b: pypeline.uint8_t

    resolver = AUTOFSM._TypeResolver()
    t1 = resolver.resolve("uint16_t[16]")
    check(
        t1 is not None and pypeline.ctype_name(t1) == "uint16_t[16]",
        "an array of a scalar (uint16_t[16]) resolves from its name alone, unseeded",
    )
    # Dimension order must match _CTypeMeta.__getitem__ (outer/first bracket
    # applied first, C-declaration order) -- get it backwards and this
    # round-trip silently produces the wrong shape instead of raising.
    t2 = resolver.resolve("uint2_t[4][16]")
    check(
        t2 is not None
        and pypeline.ctype_name(t2) == "uint2_t[4][16]"
        and pypeline._array_len(t2) == 4
        and pypeline.ctype_name(pypeline._array_elem_ctype(t2)) == "uint2_t[16]",
        "a 2-D array (uint2_t[4][16]) round-trips with the outer dimension "
        "(4) first, matching C's T x[A][B]",
    )
    resolver.seed(_seeded_leaf_t)
    struct_arr_name = f"{pypeline.ctype_name(_seeded_leaf_t)}[8]"
    t3 = resolver.resolve(struct_arr_name)
    check(
        t3 is not None and pypeline.ctype_name(t3) == struct_arr_name,
        "an array of a SEEDED struct resolves",
    )
    raised_name = None
    try:
        resolver.resolve("some_unseeded_struct_t[8]")
    except AUTOFSM.AutofsmError as e:
        raised_name = str(e)
    check(
        raised_name is not None and "some_unseeded_struct_t" in raised_name,
        "an array of an UNSEEDED struct still raises, naming the base type "
        "(not the whole array name) -- a struct genuinely cannot be rebuilt "
        "from its name alone",
    )

    # Real sky130 area (docs/AUTOFSM_DESIGN.md section 3.8): ESTIMATE_SCHEDULE_AREA's
    # unit/mux/register terms consult SYN.GET_CACHED_LEAF_AREA under
    # DEVICE_MODELS instead of the abstract AREA_* constants. A synthetic
    # SYN_TOOL/cache-dir override here, no real synthesis -- same shape as
    # area_model_test.py's own fixtures, just exercised through AUTOFSM's own
    # entry points rather than SYN's directly.
    print("\n[area model: real sky130 um2]")
    with tempfile.TemporaryDirectory() as design_tmp, tempfile.TemporaryDirectory() as area_tmp:
        ps2, key2, tag2 = parse_design(design_tmp, mhz=25.0, name="af_unit_area_design")
        func_entity2 = AUTOFSM._entity_key_for_callable(ps2, tag2.func)
        add_logic = None
        for entity in set(
            ps2.FuncLogicLookupTable[func_entity2].submodule_instances.values()
        ):
            if entity.startswith("BIN_OP_PLUS_") or entity.startswith("BIN_OP_"):
                add_logic = (entity, ps2.FuncLogicLookupTable[entity])
                break
        assert add_logic is not None, "expected chain() to contain a BIN_OP entity"
        add_entity, add_logic = add_logic

        old_tool = SYN.SYN_TOOL
        old_env = os.environ.get("PYPELINEC_AREA_CACHE_DIR")
        old_force = AUTOFSM.FORCE_ABSTRACT_AREA
        try:
            # Not DEVICE_MODELS: unchanged from every tool's existing
            # abstract-units-only behavior, regardless of cache contents.
            SYN.SYN_TOOL = SYN.PYRTL
            check(
                AUTOFSM._area_unit_scale(ps2) == 1.0,
                "non-DEVICE_MODELS tools stay in abstract units (scale 1.0)",
            )

            SYN.SYN_TOOL = DEVICE_MODELS
            os.environ["PYPELINEC_AREA_CACHE_DIR"] = area_tmp + "/"
            check(
                AUTOFSM._area_unit_scale(ps2) == AUTOFSM.UM2_PER_ABSTRACT_AREA_UNIT,
                "DEVICE_MODELS scales into real um2",
            )

            # Cold cache: falls back to the abstract estimate scaled into
            # um2, NOT to zero -- a zero-area leaf would read as free wiring
            # and never get shared (the same failure mode _resolve_delay_du's
            # own tiering exists to avoid for delay).
            cold_tally = {}
            cold_val = AUTOFSM._leaf_area_um2(ps2, add_entity, add_logic, cold_tally)
            expected_cold = (
                AUTOFSM._leaf_area(add_entity, add_logic)
                * AUTOFSM.UM2_PER_ABSTRACT_AREA_UNIT
            )
            check(
                cold_val > 0.0 and abs(cold_val - expected_cold) < 1e-6,
                "a leaf with no cached area falls back to the scaled abstract "
                "estimate, not zero",
            )
            check(cold_tally == {"estimated": 1}, "cold leaf tallies as estimated")

            # Warm cache: a real measurement wins outright, however far it
            # sits from the abstract guess -- ground truth here is always
            # synthesis, never the fallback model.
            SYN.WRITE_CACHED_LEAF_AREA(add_logic, ps2, 999.5, "um2")
            warm_tally = {}
            warm_val = AUTOFSM._leaf_area_um2(ps2, add_entity, add_logic, warm_tally)
            check(warm_val == 999.5, "a cached real area is used as-is")
            check(warm_tally == {"measured": 1}, "warm leaf tallies as measured")

            # --autofsm_abstract_area (FORCE_ABSTRACT_AREA): reproduces the
            # non-DEVICE_MODELS numbers exactly, even with a warm cache --
            # the escape hatch this session's own A/B measurement needs.
            AUTOFSM.FORCE_ABSTRACT_AREA = True
            check(
                AUTOFSM._area_unit_scale(ps2) == 1.0,
                "--autofsm_abstract_area forces scale back to 1.0",
            )
            forced_val = AUTOFSM._leaf_area_um2(ps2, add_entity, add_logic)
            check(
                forced_val == AUTOFSM._leaf_area(add_entity, add_logic),
                "--autofsm_abstract_area ignores a warm cache entirely",
            )
            AUTOFSM.FORCE_ABSTRACT_AREA = False

            # Flip-flop area needs no cache at all -- a closed-form liberty
            # lookup, not a per-shape measurement.
            ff_val = AUTOFSM._ff_area_um2(ps2)
            expected_ff, _unit = DEVICE_MODELS.GET_SEQUENTIAL_CELL_AREA()
            check(
                ff_val == expected_ff,
                f"_ff_area_um2 returns the real sequential cell area "
                f"({expected_ff} um2), no cache needed",
            )
        finally:
            SYN.SYN_TOOL = old_tool
            AUTOFSM.FORCE_ABSTRACT_AREA = old_force
            if old_env is None:
                os.environ.pop("PYPELINEC_AREA_CACHE_DIR", None)
            else:
                os.environ["PYPELINEC_AREA_CACHE_DIR"] = old_env

    if FAILURES:
        print(f"\n{len(FAILURES)} AUTOFSM unit check(s) FAILED")
        sys.exit(1)
    print("\nAll AUTOFSM unit tests passed.")


if __name__ == "__main__":
    main()
