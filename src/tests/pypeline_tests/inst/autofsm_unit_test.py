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
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import AUTOFSM
import C_TO_LOGIC
import PY_TO_LOGIC
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

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))


def parse_design(tmpdir, mhz=25.0, name="af_unit_design"):
    """Elaborate a fresh copy of the design and hand back the parser state plus
    its AUTOFSM tag. A distinct file name per call keeps Python's import
    machinery from returning a stale module."""
    path = os.path.join(tmpdir, name + ".py")
    with open(path, "w") as f:
        f.write(DESIGN_SRC.format(repo=REPO, mhz=mhz))
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
        check("out_valid_r = 1" in src, "pulses valid when the result is ready")
        check(
            src.index("st: ") < src.index("st_r = "),
            "state is snapshotted before it is written",
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
        try:
            pypeline.AUTOFSM(tag.func, max_latency=5)
            capped = False
        except NotImplementedError:
            capped = True
        check(capped, "max_latency is rejected rather than silently ignored")

    if FAILURES:
        print(f"\n{len(FAILURES)} AUTOFSM unit check(s) FAILED")
        sys.exit(1)
    print("\nAll AUTOFSM unit tests passed.")


if __name__ == "__main__":
    main()
