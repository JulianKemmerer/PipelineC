#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native-sim handshake test for make_stream_autofsm
(include/pypeline/stream/stream_autofsm.py). Plain native sim never installs
an AUTOFSM schedule (pypeline_sim.py run directly), so ADD_FSM.fsm.latency
stays 0 throughout and the wrapper's own latency/II are both 1 -- this test
exercises the wrapper's HANDSHAKE PROTOCOL, not any particular schedule.

Companion coverage: self_check_stream_autofsm_test.py drives the same shape
through a real non---comb build (a real schedule installed, latency > 1) and
through native-vs-VHDL cycle diffing.
"""
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

import random
from typing import NamedTuple
from pypeline import (
    struct,
    hw_func,
    sim_call,
    sim_reset,
    uint8_t,
)

from stream.stream_autofsm import make_stream_autofsm


@struct
class in_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@hw_func
def add_ab(x: in_t) -> uint8_t:
    return x.a + x.b


def _model(a, b):
    return (a + b) & 0xFF


ADD_FSM, ADD_FSM_T = make_stream_autofsm(add_ab)


def _drive(inputs, ready_pattern, ncycles):
    """Runs the wrapper for ncycles, holding stream_in valid until each input
    is accepted (one at a time -- the wrapper only ever has one item in
    flight) and driving stream_out ready from ready_pattern[cycle]. Returns
    (results, accepted_cycles, consumed_cycles) -- results[i] is the i'th
    consumed output value; accepted_cycles[i]/consumed_cycles[i] are the cycle
    each input was accepted / its result was consumed (valid & ready together
    -- when the consumer is never backpressured this is also the cycle the
    result first went valid, since it is retired the same cycle it appears)."""
    sim_reset()
    results = []
    accepted_cycles = []
    consumed_cycles = []
    next_idx = 0
    held_data_prev = None
    was_held = False
    for cycle in range(ncycles):
        in_valid = 1 if next_idx < len(inputs) else 0
        data = in_t(*inputs[next_idx]) if in_valid else in_t(a=0, b=0)
        out_ready = ready_pattern[cycle % len(ready_pattern)]

        out = sim_call(
            ADD_FSM,
            ADD_FSM.in_fwd_t(stream=ADD_FSM.in_intrf.stream_t(data=data, valid=in_valid)),
            ADD_FSM.out_fb_t(ready=out_ready),
        )

        if in_valid and out.stream_in_if.ready:
            accepted_cycles.append(cycle)
            next_idx += 1

        v = out.stream_out_if.stream.valid
        d = int(out.stream_out_if.stream.data)
        if v:
            if was_held:
                # Held across a stalled cycle: must be the SAME result, never
                # dropped or replaced while the consumer wasn't ready.
                assert d == held_data_prev, (
                    f"cycle {cycle}: held result changed from "
                    f"{held_data_prev} to {d} while stalled"
                )
            if out_ready:
                results.append(d)
                consumed_cycles.append(cycle)
                was_held = False
            else:
                held_data_prev = d
                was_held = True
        else:
            was_held = False
    return results, accepted_cycles, consumed_cycles


def test_latency_and_ii_no_backpressure():
    """With the consumer always ready, latency and initiation interval both
    equal ADD_FSM.latency (== fsm.latency + 1 == 1 in plain native sim): each
    result is consumed the same cycle it first appears (no stalls), so the
    consumed-cycle IS the first-valid cycle here."""
    inputs = [(i, i + 1) for i in range(6)]
    results, accepted, consumed = _drive(inputs, [1], ncycles=40)
    assert results == [_model(a, b) for a, b in inputs], results
    assert len(accepted) == len(inputs) == len(consumed)
    for acc, cons in zip(accepted, consumed):
        assert cons - acc == ADD_FSM.latency, (acc, cons, ADD_FSM.latency)
    for i in range(1, len(accepted)):
        assert accepted[i] - accepted[i - 1] == ADD_FSM.latency, (
            "expected back-to-back requests spaced exactly .latency cycles "
            f"apart (no bubble, no overlap): {accepted}"
        )
    print(f"test_latency_and_ii_no_backpressure PASS  latency={ADD_FSM.latency}")


def test_backpressure_no_loss_no_reorder():
    """A pseudo-random ready pattern (including long stalls) must still
    deliver every result, in order, with no drops/duplicates/reordering, and
    (checked inside _drive) a held result's data must never change while
    stalled."""
    rng = random.Random(1234)
    inputs = [(i % 251, (2 * i + 3) % 251) for i in range(25)]
    ready_pattern = [1 if rng.random() > 0.4 else 0 for _ in range(97)]
    results, accepted, consumed = _drive(inputs, ready_pattern, ncycles=2000)
    assert len(accepted) == len(inputs), (
        f"expected all {len(inputs)} inputs accepted, got {len(accepted)}"
    )
    assert results == [_model(a, b) for a, b in inputs], (
        f"output sequence mismatch:\n got={results}\nwant="
        f"{[_model(a, b) for a, b in inputs]}"
    )
    print(f"test_backpressure_no_loss_no_reorder PASS  n={len(inputs)}")


def test_ready_deasserts_while_busy():
    """stream_in_if.ready must be low on every cycle the wrapper is busy with
    no result ready yet (single item in flight). Ready may legitimately be
    high again on the very same cycle a result first goes valid -- the slot
    frees combinationally within that cycle (the make_valid_ready_mcp-style
    same-cycle out->in trick), so that cycle is exempt from the check."""
    sim_reset()
    inputs = [(3, 4), (5, 6)]
    next_idx = 0
    busy = False
    for cycle in range(30):
        in_valid = 1 if next_idx < len(inputs) else 0
        data = in_t(*inputs[next_idx]) if in_valid else in_t(a=0, b=0)
        out = sim_call(
            ADD_FSM,
            ADD_FSM.in_fwd_t(stream=ADD_FSM.in_intrf.stream_t(data=data, valid=in_valid)),
            ADD_FSM.out_fb_t(ready=1),
        )
        if busy and not out.stream_out_if.stream.valid:
            assert not out.stream_in_if.ready, (
                f"cycle {cycle}: ready asserted while busy with no result yet"
            )
        if in_valid and out.stream_in_if.ready:
            next_idx += 1
            busy = True
        if out.stream_out_if.stream.valid:
            busy = False
        if next_idx >= len(inputs) and not busy:
            break
    print("test_ready_deasserts_while_busy PASS")


if __name__ == "__main__":
    test_latency_and_ii_no_backpressure()
    test_backpressure_no_loss_no_reorder()
    test_ready_deasserts_while_busy()
    print("All stream_autofsm tests passed.")
