# pyright: reportInvalidTypeForm=none
"""Known issue #378: library factories that make "n values of the caller's type"
write `elem_t[n]`, which is the wrong shape when elem_t is itself an array.

Pypeline keeps C array order, so `uint2_t[4][3]` is four `uint2_t[3]` values,
not three `uint2_t[4]` ones. make_shift_into_top(uint2_t[4], 3) (axi/axis.py)
therefore declares `uint2_t[4][3]` arrays, and so do make_kept_data_bus_t
(kept_data_bus.py) and the serializer/deserializer fragment and buffer types.
`make_array_t(elem_t, n)` builds the intended `uint2_t[3][4]`; AUTO_FSM's
operand mux had the same bug and now uses it.

The window below is declared the way a user would write three uint2_t[4]
lanes, `uint2_t[3][4]`. Elaboration accepts passing it to the factory's
`uint2_t[4][3]` port (#359 does not compare array lengths).

Native sim passes: its values are plain lists, so the declared shapes never
matter. The --cocotb --ghdl build stops in VHDL emission ("Unhandled array
assignment vhdl type resolve: uint2_t drives uint2_t"). Registered in
known_issues_tests.py (expect_fail); with both factories changed to
make_array_t the same build passes in GHDL.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]

from axi.axis import make_shift_into_top
from kept_data_bus import make_kept_data_bus_t
from pypeline import MAIN, Reg, sim_assert, sim_finish, uint2_t, uint4_t

N = 3
lanes_t = uint2_t[4]
window_t = uint2_t[N][4]  # three uint2_t[4] values

SHIFT = make_shift_into_top(lanes_t, N)
BUS_T = make_kept_data_bus_t(lanes_t, N)


@MAIN
def library_factory_array_elem_top() -> uint2_t:
    window: Reg[window_t]
    count: Reg[uint4_t]

    top_lanes: lanes_t
    for lane in range(4):
        top_lanes[lane] = count + lane
    window = SHIFT(window, top_lanes)

    kept: BUS_T
    for k in range(N):
        kept.data[k] = window[k]
        kept.keep[k] = 1

    if count == N + 1:
        # window[k] now holds the input of count N + 1 - (N - 1) + k = 2 + k.
        for k in range(N):
            for lane in range(4):
                want: uint2_t = k + 2 + lane
                sim_assert(window[k][lane] == want, "shift window lane mismatch")
                sim_assert(kept.data[k][lane] == want, "kept data bus lane mismatch")
        sim_finish()
    count += 1
    return kept.data[N - 1][3]
