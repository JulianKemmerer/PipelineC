# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for CONDITIONALLY driven fields of a split
compound Wire[T] -- the clock-enable idiom. main_cond drives w.en and w.x
only on odd cycles, inside a bare `if` with no else; on even cycles those
leaves must read ZERO everywhere (the implicit zero-init default is the
else-value of the write mux). main_always drives w.y every cycle. checker
uses w.en as a clock enable gating a counting Reg.

This is also the regression test for a first-touch-inside-a-branch write:
main_cond's FIRST (and only) textual writes to w sit inside the if body --
pre-fix, the lazy write-declare ran mid-branch and elaboration crashed with
"No covering wire found" at _connect_final_state_wires; the fix hoists
write-declaration of every pre-scanned written wire to elaborate() start so
the branch merge always has the implicit zero-init base to mux against.

Registered in native_sim_tests.py (--sim --run all) and vhdl_sim_tests.py
(--sim --comb --cocotb --ghdl --run all).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    sim_assert,
    sim_finish,
    struct,
    uint1_t,
    uint8_t,
)


@struct
class ctrl_t(NamedTuple):
    en: uint1_t
    x: uint8_t
    y: uint8_t


w: Wire[ctrl_t]  # .en/.x driven by main_cond (odd cycles only), .y by main_always

NUM_CHECKS = 10


@MAIN
def main_cond():
    n: Reg[uint8_t]
    if (n & 1) == 1:
        w.en = 1
        w.x = n
    n += 1


@MAIN
def main_always():
    n: Reg[uint8_t]
    w.y = n + 50
    n += 1


@MAIN
def checker():
    n: Reg[uint8_t]
    enables_seen: Reg[uint8_t]
    if (n & 1) == 1:
        sim_assert(w.en == 1, f"cycle {n}: w.en expected 1 got {w.en}")
        sim_assert(w.x == n, f"cycle {n}: w.x expected {n} got {w.x}")
    else:
        sim_assert(w.en == 0, f"cycle {n}: w.en expected 0 got {w.en}")
        sim_assert(w.x == 0, f"cycle {n}: undriven w.x expected 0 got {w.x}")
    sim_assert(w.y == n + 50, f"cycle {n}: w.y expected {n + 50} got {w.y}")
    # Clock-enable use: count the cycles where w.en was asserted.
    if w.en == 1:
        enables_seen += 1
    if n == NUM_CHECKS - 1:
        # en asserted on odd cycles 1,3,5,7,9; the increment above runs before
        # this check in program order, so cycle 9's own enable is included: 5.
        sim_assert(enables_seen == 5, f"enables_seen expected 5 got {enables_seen}")
        sim_finish()
    n += 1
