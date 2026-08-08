# pyright: reportInvalidTypeForm=none
"""KNOWN ISSUE (reproducer, not a fix): int16_t squaring-then-truncating a
value that overflows int16_t range computes a DIFFERENT result in real GHDL
hardware than in native sim.

    a = 200 (int16_t)
    big: int16_t = a * a     # 40000, truncated to int16_t -> -25536 (native, correct)
    out = big + 1            # -25535 (native)

Native sim: r3 == -25535 (matches the plain-Python model: ((200*200) & 0xFFFF
as signed 16-bit) + 1). Real GHDL hardware for the exact same source computes
r3 == 7233 instead -- a genuine native-vs-hardware divergence in the
int16_t*int16_t -> truncate-to-int16_t codegen path, not a native-sim-only
bug (see docs/pypeline_sim_DESIGN.md's Limitations -- this is not one of the
documented/expected native-vs-VHDL differences).

Discovered while building native_vs_vhdl_sim_tests.py's cycle-diff coverage:
self_check_bit_math_test.py (native_sim_tests.py, synth_tests.py) exercises
this same nested_truncate(200) call and has silently carried a failing
sim_assert through GHDL the whole time -- masked because its GHDL run always
also raced the unrelated "Simulator shutdown prematurely" cocotb/GHDL
same-cycle-sim_finish() harness quirk (see the sim_finish() delay comment
below and known_issues_tests.py's own module docstring), so nobody looking at
a green run ever saw this assertion actually execute and fail.

sim_finish() is deliberately delayed by one cycle from the check via the
`finishing` Reg: calling it the SAME cycle as the sim_assert races GHDL's
write-flush vs std.env.finish ordering and produces the same premature-
shutdown false read this file is trying to avoid -- see
sim_finish_debug_print_race_test.py in this directory for a direct
reproduction of THAT (separate, non-compiler) issue.

Repro: pypelinec <this file> --sim --comb --cocotb --ghdl --run all
  -> assertion failure: "nested_truncate(200) expected -25535 got 7233"
Native: pypelinec <this file> --sim --comb --run all
  -> passes clean (no assertion fires).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, hw_func, int16_t, sim_assert, sim_finish, uint1_t


@hw_func
def nested_truncate(a: int16_t) -> int16_t:
    out: int16_t = 0
    if a > 0:
        big: int16_t = a * a  # int32_t product truncated to int16_t
        out = big + 1
    return out


@MAIN
def nested_truncate_vhdl_mismatch():
    n3: int16_t = 200
    r3: int16_t = nested_truncate(n3)
    finishing: Reg[uint1_t]
    if finishing:
        sim_finish()
    else:
        sim_assert(r3 == -25535, f"nested_truncate(200) expected -25535 got {r3}")
        finishing = 1
