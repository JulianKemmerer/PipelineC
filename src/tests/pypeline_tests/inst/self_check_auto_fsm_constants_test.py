"""Typed constant cleanup and scoped constant arithmetic through real GHDL.

The same eight boundary cases run in passthrough and scheduled modes. Expected
values are computed in Python before elaboration, independently of the kernel.
"""

from pypeline import (
    AUTO_FSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    int8_t,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
)

# Boundary values include sign extension and unsigned wrap.
CASES = (0, 1, 15, 127, 128, 251, 254, 255)
EXPECTED = tuple(
    (((v * 5) & 0xFF) + (v if v < 128 else v - 256)) & 0xFFFF for v in CASES
)


@struct
class input_t(NamedTuple):
    x: uint8_t


@hw_func
def constant_work(x: input_t) -> uint16_t:
    product: uint8_t = x.x * 5
    signed: int8_t = x.x
    extended: uint16_t = signed
    zero: uint8_t = x.x * 0
    result: uint16_t = product + extended
    result = result + zero
    if x.x >= 256:
        result = 99
    return result


# Construct once so both simulators use the installed schedule latency.
FSM = AUTO_FSM(constant_work)


@MAIN(5.0)
def self_check_auto_fsm_constants() -> uint16_t:
    idx: Reg[uint4_t]
    busy: Reg[uint1_t]
    last: Reg[uint16_t]
    inputs: uint8_t[len(CASES)] = CASES
    expected: uint16_t[len(CASES)] = EXPECTED
    request: FSM.in_stream_t
    request.data.x = inputs[idx]
    request.valid = ~busy
    if request.valid:
        busy = 1
    response = FSM(request)
    if response.valid:
        sim_assert(response.data == expected[idx], "typed constant arithmetic")
        last = response.data
        busy = 0
        if idx == len(CASES) - 1:
            sim_finish()
        else:
            sim_print(f"constants case={idx} data={response.data}", debug=True)
        idx += 1
    return last
