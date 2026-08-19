# pyright: reportInvalidTypeForm=none
"""Was nested_truncate_vhdl_mismatch_known_issue.py: int16_t squaring-then-
truncating a value that overflows int16_t range used to compute a DIFFERENT
result in real GHDL hardware than in native sim, because
VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS's signed->signed NARROWING case emitted a
plain numeric_std.resize(SIGNED, N) -- which is sign-preserving (copies the
sign bit into the new MSB, keeps the low N-1 bits) -- instead of C's actual
truncation rule (take the low N bits of the two's-complement representation
regardless of sign). Fixed as part of adding T(x) casting (see docs:
Casting's "Make integer conversion match C" section): the narrowing case now
routes through unsigned first, matching the shape already used one branch
over for signed->unsigned narrowing, and matching native sim's _sim_cast
(which was always C-correct -- this was purely a VHDL-emission bug).

    a = 200 (int16_t)
    big: int16_t = a * a     # 40000, truncated to int16_t -> -25536
    out = big + 1            # -25535, both native sim AND real GHDL now

Promoted out of known_issues_tests.py: this is now a real (non-XFAIL)
native_vs_vhdl_sim_tests.py entry -- see this repo's docs/pypeline_TESTS.md
for why an XPASS here would otherwise report as a failure.

Discovered while building native_vs_vhdl_sim_tests.py's cycle-diff coverage:
self_check_bit_math_test.py (native_sim_tests.py, synth_tests.py) exercises
this same nested_truncate(200) call and had silently carried this exact
check through GHDL the whole time -- masked because its GHDL registration is
excluded from native_vs_vhdl_sim_tests.py for an unrelated structural reason
(its whole body is one combinational block calling sim_finish() the same
cycle it computes everything -- see that file's own registration comment),
so nobody looking at a green run ever saw this assertion actually execute
against real hardware.

sim_finish() is deliberately delayed by one cycle from the check via the
`finishing` Reg: calling it the SAME cycle as the sim_assert races GHDL's
write-flush vs std.env.finish ordering and produces a premature-shutdown
false read -- see sim_finish_debug_print_race_test.py in this directory for
a direct reproduction of THAT (separate, non-compiler) issue.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, hw_func, int16_t, sim_assert, sim_finish, sim_print, uint1_t


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
        sim_print(f"nested_truncate r3={r3}", debug=True)
        sim_assert(r3 == -25535, f"nested_truncate(200) expected -25535 got {r3}")
        finishing = 1
