# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test: real end-to-end (GHDL-analyzed) coverage for
the iteration-ordinal loop-naming scheme (_elab_for/_bind_const_target/
_elab_unpack_assign, plus _elab_call's expression-callee branch) --
loop_iter_naming_test.py already checks the elaborator's internal
name/error-path contract in-process; this file proves the resulting VHDL
actually builds and simulates correctly through real GHDL, not just that
PARSE_FILE accepts it.

Every value below is a compile-time constant (or derived from the
free-running counter `n` in a way that cancels out), so the expected
accumulator total is the same fixed number every cycle -- computed
independently in plain Python alongside each block below; EXPECTED_ACC is
their sum. Exercises, in one accumulation chain:
  - tuple iteration (`for op in OPS:`) -- illegal to name under the old
    repr()-based scheme (parens/commas/spaces in a tuple's repr).
  - tuple-target unpack in a for loop (`for kind, a, b, c in OPS:`).
  - enumerate/zip/dict/str iteration -- all previously rejected outright
    (isinstance(iter_val, (range, tuple, list)) only).
  - a negative loop value under a nested loop (old scheme: "FOR_i_-2_" ->
    WIRE_TO_VHDL_NAME's '-'->'_' collapse gives the illegal "FOR_i__2_").
  - tuple-unpacking assignment, both the constant-RHS case
    (`p, q, r = PLAN[m]`, the soft_div.py shape this change was written to
    unblock) and the hardware-RHS swap case (`sx, sy = sy, sx`).
  - an indexed/expression call target (`ADDERS[j](acc)`), previously
    "'Subscript' object has no attribute 'id'".
  - make_soft_mult_carry_save (include/pypeline/operators/soft_mult.py):
    previously exercised only via sim_call (soft_ops_test.py, native_sim
    category), which never runs the elaborator at all -- this closes that
    gap for the OPS[i][k]-loop rewrite in soft_mult.py.

Registered in native_vs_vhdl_sim_tests.py (--comb: native vs. real
cocotb+GHDL, diffed cycle by cycle) and native_sim_tests.py (native only).
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

from pypeline import MAIN, Reg, hw_func, sim_assert, sim_finish, sim_print, uint8_t, uint32_t
from operators.soft_mult import make_soft_mult_carry_save

NUM_COUNTS = 4

OPS = [(0, 4, 2, 6), (1, 5, 3, 7), (2, 6, 4, 8)]
XS = [10, 20, 30]
YS = [1, 2, 3]
D = {"a": 1, "b": 2, "c": 3}
PLAN = {2: (10, 20, 30), 3: (40, 50, 60)}


def make_adder(k: int):
    @hw_func
    def add_k(v: uint32_t) -> uint32_t:
        return v + k

    return add_k


ADDERS = [make_adder(1), make_adder(2), make_adder(3)]

mult4 = make_soft_mult_carry_save(uint8_t, uint8_t, max_width=4)

# Sum of every constant contribution below, verified independently in plain
# Python (not re-derived here, so a copy/paste slip in either place shows up
# as a mismatch, not a tautology):
#   tuple iter (48) + tuple-target unpack (48) + enumerate (63) + zip (66)
#   + dict (6) + str (2) + negative-nested (54) + swap (4) + const-unpack
#   (210) + indexed-call (6) + carry-save mult 6*7 (42) = 549
EXPECTED_ACC = 549


@MAIN
def self_check_loop_unpack():
    n: Reg[uint8_t]

    acc: uint32_t = 0
    for op in OPS:
        acc = acc + op[0] + op[1] + op[2] + op[3]
    for kind, a, b, c in OPS:
        acc = acc + kind + a + b + c
    for i, v in enumerate(XS):
        acc = acc + i + v
    for a, b in zip(XS, YS):
        acc = acc + a + b
    for k in D:
        acc = acc + D[k]
    for ch in "ab":
        acc = acc + 1
    for i in range(-1, 2):
        for j in [(3, 4), (5, 6)]:
            acc = acc + j[0] + j[1]

    # Hardware-valued swap (Case B of _elab_unpack_assign): sx/sy both
    # depend on the register n, so neither const-folds -- (n+9)-(n+5) == 4
    # regardless of n, keeping the total cycle-invariant while still
    # forcing the real temp-lowering path (not the constant fast path).
    sx: uint32_t = n + 5
    sy: uint32_t = n + 9
    sx, sy = sy, sx
    acc = acc + sx - sy

    for m in range(2, 4):
        p, q, r = PLAN[m]
        acc = acc + p + q + r

    for j in range(3):
        acc = ADDERS[j](acc)

    ma: uint8_t = 6
    mb: uint8_t = 7
    acc = acc + mult4(ma, mb)

    sim_assert(
        acc == EXPECTED_ACC,
        f"loop/unpack accumulator mismatch: got {acc}, want {EXPECTED_ACC}",
    )
    # No debug print on the sim_finish() cycle -- whether a same-cycle VHDL
    # write flushes before std.env.finish kills GHDL is a process-ordering
    # race the cycle diff must not depend on.
    if n < NUM_COUNTS - 1:
        sim_print(f"self_check_loop_unpack acc={acc}", debug=True)
    if n == NUM_COUNTS - 1:
        sim_finish()
    n += 1
