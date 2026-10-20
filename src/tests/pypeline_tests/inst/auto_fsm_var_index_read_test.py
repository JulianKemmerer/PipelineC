#!/usr/bin/env python3
"""Regression for #377: direct and nested variable-index array reads.

Both designs elaborate and schedule with the indexed read as an operation of
its own. The nested case also exercises AUTO_COMB_OPT's timing-model path.
Uses stand-in delays and no synthesis; registered in elab_introspect_tests.py.
"""
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

import AUTO  # noqa: E402
import AUTO_FSM  # noqa: E402
import PY_TO_LOGIC  # noqa: E402

DESIGN_SRC = textwrap.dedent(
    """
    # pyright: reportInvalidTypeForm=none
    import sys
    sys.path.insert(0, {repo!r})
    from pypeline import (AUTO_FSM, MAIN, NamedTuple, Reg, hw_func, make_uint_t,
                          struct, uint1_t, uint16_t)

    uint2_t = make_uint_t(2)

    @struct
    class in_t(NamedTuple):
        vals: uint16_t[4]
        idx: uint2_t

    @hw_func
    def pick(x: in_t) -> uint16_t:
        v: uint16_t = x.vals[x.idx]
        return v + x.vals[0]

    @hw_func
    def nested(x: in_t) -> uint16_t:
        return pick(x) + x.vals[1]

    @hw_func
    def direct(x: in_t) -> uint16_t:
        v: uint16_t = x.vals[x.idx]
        return v + x.vals[1]

    FSM = AUTO_FSM({func})

    @MAIN(25.0)
    def top(start: uint1_t, x: in_t) -> uint16_t:
        s: FSM.in_stream_t
        s.data = x
        s.valid = start
        o = FSM(s)
        r: Reg[uint16_t]
        if o.valid:
            r = o.data
        return r
    """
)


def parse_and_schedule(func):
    """Parse the design tagging `func`, give `pick` more delay than one state
    at 25 MHz and every operator and array read a delay that fits one, and
    schedule it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"af_var_index_{func}.py")
        with open(path, "w") as f:
            f.write(DESIGN_SRC.format(repo=REPO, func=func))
        ps = PY_TO_LOGIC.PARSE_FILE(path)
    callables = AUTO._entity_callables(ps)
    for entity, logic in ps.FuncLogicLookupTable.items():
        if getattr(callables.get(entity), "__name__", None) == "pick":
            logic.delay = 1000
        elif entity.startswith(("BIN_OP_", "VAR_REF_RD_")):
            logic.delay = 100
    ((key, tag),) = AUTO_FSM.GET_TAGS(ps).items()
    return ps, key, tag, AUTO_FSM.BUILD_SCHEDULE(ps, key, tag, 0.9)


def test_nested_variable_index_read_opens():
    ps, key, _tag, sched = parse_and_schedule("nested")
    report = AUTO_FSM.DESCRIBE_SCHEDULE(ps, key, sched)
    assert not sched["descend_blocked"] and not sched["at_floor"], report


def test_direct_variable_index_read_schedules():
    ps, _key, tag, sched = parse_and_schedule("direct")
    AUTO_FSM.GENERATE_FSM_SOURCE(tag, sched, ps)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
