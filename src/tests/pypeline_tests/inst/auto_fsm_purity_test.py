#!/usr/bin/env python3
"""AUTO_FSM requires a pure function in its whole subtree (AUTO.FIND_EFFECTS),
not just in the levels the scheduler opens.

An impure callee kept as one shared unit would be time-multiplexed across the
FSM's states: its Reg state stepped once per use, its global wires sampled
at whichever state uses it. The scheduler used to keep such a callee as an
opaque operation. This test checks that BUILD_SCHEDULE now rejects:
  - a callee that reads a global wire,
  - a callee that holds Reg state,
  - the FSM'd function reading a global wire directly,
and still schedules the same design with a pure callee.

Run standalone: python3 auto_fsm_purity_test.py
"""
import os
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import AUTO
import AUTO_FSM
import PY_TO_LOGIC

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../..")
)

FAILURES = []


def check(cond, msg):
    print(("  ok: " if cond else "  FAIL: ") + msg)
    if not cond:
        FAILURES.append(msg)


DESIGN = textwrap.dedent(
    """
    # pyright: reportInvalidTypeForm=none
    import sys
    sys.path.insert(0, {repo!r})
    from pypeline import (AUTO_FSM, MAIN, Input, Reg, hw_func, uint1_t, uint16_t)

    g: Input[uint16_t]

    @hw_func
    def child(x: uint16_t) -> uint16_t:
        {child_body}

    @hw_func
    def core(x: uint16_t) -> uint16_t:
        {core_body}

    FSM = AUTO_FSM(core)

    @MAIN(10.0)
    def top(start: uint1_t, x: uint16_t) -> uint16_t:
        s: FSM.in_stream_t
        s.data = x
        s.valid = start
        o = FSM(s)
        return o.data
    """
)

PURE_CHILD = "return x * 3"
GLOBAL_CHILD = "return x + g"
STATEFUL_CHILD = "prev: Reg[uint16_t]\n    r: uint16_t = prev\n    prev = x\n    return r"
CALLS_CHILD = "return child(x) + 1"
READS_GLOBAL = "return child(x) + g"


def schedule(tmp, name, child_body, core_body):
    path = os.path.join(tmp, name + ".py")
    with open(path, "w") as f:
        f.write(DESIGN.format(repo=REPO, child_body=child_body, core_body=core_body))
    parser_state = PY_TO_LOGIC.PARSE_FILE(path)
    tags = AUTO_FSM.GET_TAGS(parser_state)
    (key,) = list(tags)
    try:
        AUTO_FSM.BUILD_SCHEDULE(parser_state, key, tags[key], 1.0)
    except AUTO.AutoError as e:
        return str(e)
    return None


def main():
    with tempfile.TemporaryDirectory() as tmp:
        err = schedule(tmp, "fsm_pure", PURE_CHILD, CALLS_CHILD)
        check(err is None, f"pure callee schedules (error: {err})")
        err = schedule(tmp, "fsm_global_child", GLOBAL_CHILD, CALLS_CHILD)
        check(
            err is not None and "its callee" in err and "reads or writes global wires" in err,
            f"global-reading callee rejected: {err}",
        )
        err = schedule(tmp, "fsm_state_child", STATEFUL_CHILD, CALLS_CHILD)
        check(
            err is not None and "its callee" in err and "holds Reg state" in err,
            f"stateful callee rejected: {err}",
        )
        err = schedule(tmp, "fsm_global_root", PURE_CHILD, READS_GLOBAL)
        check(
            err is not None and "reads or writes global wires" in err,
            f"direct global read rejected: {err}",
        )
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
