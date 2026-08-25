# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test reproducing two data-corruption bugs in the
elaboration of dynamic-indexed (runtime-index) array WRITES, both found via
wireguard-fpga's append_auth_tag.py (issue #44 tkeep work): a dynamic write
produced correct results in native sim but wrong data under real GHDL sim.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim
--comb) and cocotb+GHDL (--cocotb --ghdl) sims and diffs their
sim_print(debug=True) output cycle by cycle -- the only mechanism that
catches this class of bug (the sim_assert checks below pass in native sim
either way; only real VHDL elaboration was wrong).

Bug 1 -- stale self.env scalar readback (PY_TO_LOGIC._emit_var_ref_assign
never invalidates self.env, unlike _write_ref): a constant-index write seeds
self.env["buf[k]"]; a later dynamic-index write to the same array does not
touch self.env at all; a subsequent CONSTANT-index scalar read of that same
slot hits _read_ref's env fast path and returns the pre-dynamic-write wire,
bypassing the alias-chain resolution (_find_covering_wire) that would
otherwise see the dynamic write. `readback_main` below is the minimal
isolation of the original append_auth_tag symptom (top of array retained an
earlier value instead of the dynamically-written one).

Bug 2 -- oldest-covering-port selection (_build_var_ref_assign_logic /
_build_var_ref_rd_logic pick the FIRST match out of a dict that
_temporal_sort_covering_wires deliberately orders oldest-first, instead of
the newest/most-specific match): once a whole-array alias and a more recent
single-element alias both cover the same position, a subsequent dynamic
write/read at that position silently resolves through the STALE whole-array
alias instead of the newer single-element one. `covering_main` below
reproduces both the WRITE-side (VAR_REF_ASSIGN) and READ-side (VAR_REF_RD)
form of this in one design.

See also var_ref_assign_cond_loop_test.py for a third, crash-mode bug
(_assemble_var_ref_coverage dropping branch_tag) found in the same
investigation -- kept in a separate design file since, pre-fix, it fails to
elaborate at all and would otherwise prevent this file's designs from being
observed independently.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, sim_print, uint8_t

NUM_CHECKS = 20


@MAIN
def readback_main():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    buf: uint8_t[4]
    for i in range(4):
        buf[i] = 0
    buf[idx] = n + 200
    readback0: uint8_t = buf[0]
    expected0: uint8_t = 0
    if idx == 0:
        expected0 = n + 200
    sim_assert(
        readback0 == expected0,
        f"cycle {n}: buf[0] readback expected {expected0} got {readback0}",
    )

    # No debug print on the sim_finish() cycle -- see self_check_counter_test.py.
    if n < NUM_CHECKS - 1:
        sim_print(
            f"var_ref_assign_readback n={n} idx={idx} readback0={readback0}",
            debug=True,
        )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1


@MAIN
def covering_main():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3

    # Whole-array alias (single covering entry for all 4 positions), then a
    # concrete write to position 0 (a newer, more specific covering entry
    # for JUST position 0), then a dynamic write spanning all positions.
    whole: uint8_t[4]
    for i in range(4):
        whole[i] = n + i
    buf: uint8_t[4] = whole
    buf[0] = 111
    buf[idx] = n + 200

    for k in range(4):
        expected_k: uint8_t = 0
        if k == 0:
            expected_k = 111
        if k != 0:
            expected_k = n + k
        if k == idx:
            expected_k = n + 200
        sim_assert(
            buf[k] == expected_k,
            f"cycle {n}: buf[{k}] expected {expected_k} got {buf[k]}",
        )

    # Same shape, READ side (VAR_REF_RD instead of VAR_REF_ASSIGN).
    whole2: uint8_t[4]
    for i in range(4):
        whole2[i] = n + 50 + i
    buf2: uint8_t[4] = whole2
    buf2[0] = 222
    read_dyn: uint8_t = buf2[idx]
    expected_dyn: uint8_t = n + 50 + idx
    if idx == 0:
        expected_dyn = 222
    sim_assert(
        read_dyn == expected_dyn,
        f"cycle {n}: buf2[idx={idx}] expected {expected_dyn} got {read_dyn}",
    )

    # No debug print on the sim_finish() cycle.
    if n < NUM_CHECKS - 1:
        sim_print(
            f"var_ref_assign_covering n={n} idx={idx} "
            f"buf={buf[0]},{buf[1]},{buf[2]},{buf[3]} read_dyn={read_dyn}",
            debug=True,
        )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
