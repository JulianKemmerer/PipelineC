"""Shared pipelined arithmetic, exact latency and stream stalls through GHDL.

Three dependent seven-add helpers must fit a six-cycle cap. A scheduled build
must select a pipelined implementation, so passing cannot exercise only
combinational units. A second raw call site asserts valid continuously with
changing inputs: only idle requests count, and each result matches its launch.
"""

from pypeline import (
    INFERRED,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    register_operator,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint3_t,
    uint4_t,
    uint16_t,
    uint32_t,
)
from stream.stream_auto_fsm import make_stream_auto_fsm


@struct
class input_t(NamedTuple):
    a: uint32_t
    b: uint32_t
    c: uint32_t
    d: uint32_t


@hw_func
def seven_adds(a: uint32_t, b: uint32_t, c: uint32_t, d: uint32_t) -> uint32_t:
    r0: uint32_t = a + b
    r1: uint32_t = r0 + c
    r2: uint32_t = r1 + d
    r3: uint32_t = r2 + a
    r4: uint32_t = r3 + b
    r5: uint32_t = r4 + c
    r6: uint32_t = r5 + d
    return r6


# Retain the written chain and its exact primitive dispatch during exploration.
register_operator("PLUS", uint32_t, uint32_t, INFERRED, scope=seven_adds)


@hw_func
def kernel(x: input_t) -> uint32_t:
    a: uint32_t = seven_adds(x.a, x.b, x.c, x.d)
    b: uint32_t = seven_adds(a, x.c, x.d, x.a)
    return seven_adds(b, x.d, x.a, x.b)


# Host arithmetic supplies overflow and boundary vectors independently of HDL.
INPUTS = tuple(
    input_t(*v)
    for v in (
        (0, 0, 0, 0),
        (1, 2, 3, 4),
        (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
        (0xFFFFFFFF, 1, 2, 0x80000000),
        (0x80000000, 0x7FFFFFFF, 255, 256),
        (17, 65534, 511, 7),
        (9, 13, 29, 71),
        (0xFFFFFFFF, 0, 0xFFFFFFFF, 0),
    )
)
EXPECTED = tuple(
    (14 * x.a + 10 * x.b + 12 * x.c + 14 * x.d) & 0xFFFFFFFF for x in INPUTS
)
# Both instances share a generated entity and own independent transaction state.
SERVICE = make_stream_auto_fsm(kernel, max_latency=6)
RAW = SERVICE.fsm
if RAW.schedule is not None:
    assert RAW.schedule.get(
        "implementations"
    ), "fixture must exercise a pipelined functional unit"


@MAIN(60.0)
def self_check_auto_fsm_pipelined_unit() -> uint32_t:
    index: Reg[uint4_t]
    sent: Reg[uint1_t]
    ready: Reg[uint1_t]
    raw_index: Reg[uint3_t]
    raw_busy: Reg[uint1_t]
    raw_age: Reg[uint16_t]
    raw_expected: Reg[uint32_t]
    raw_checked: Reg[uint16_t]
    last: Reg[uint32_t]
    inputs: input_t[8] = INPUTS
    expected: uint32_t[8] = EXPECTED

    raw_request: RAW.in_stream_t
    raw_request.data = inputs[raw_index]
    raw_request.valid = 1
    expected_now: uint32_t = raw_expected
    age_now: uint16_t = raw_age + 1
    if raw_busy == 0:
        expected_now = expected[raw_index]
        raw_expected = expected_now
        age_now = 0
        raw_busy = 1
    raw_age = age_now
    raw_response = RAW(raw_request)
    if raw_response.valid:
        sim_assert(
            raw_response.data == expected_now,
            "raw busy requests changed the in-flight result",
        )
        sim_assert(age_now == RAW.latency, "raw pipeline completion latency")
        raw_busy = 0
        raw_checked += 1
    raw_index += 1

    request: SERVICE.in_intrf.stream_t
    request.data = inputs[index]
    request.valid = ~sent
    ready_now: uint1_t = ready
    ready = ~ready
    response = SERVICE(
        SERVICE.in_fwd_t(stream=request), SERVICE.out_fb_t(ready=ready_now)
    )
    if request.valid & response.stream_in_if.ready:
        sent = 1
    if response.stream_out_if.stream.valid & ready_now:
        value: uint32_t = response.stream_out_if.stream.data
        sim_assert(
            value == expected[index], "pipelined stream result under backpressure"
        )
        last = value
        sent = 0
        if index == 7:
            sim_assert(
                raw_checked >= 2, "raw call site did not complete enough transactions"
            )
            sim_finish()
        else:
            low: uint16_t = value
            high: uint16_t = value >> 16
            sim_print(f"pipelined unit case={index} high={high} low={low}", debug=True)
        index += 1
    return last
