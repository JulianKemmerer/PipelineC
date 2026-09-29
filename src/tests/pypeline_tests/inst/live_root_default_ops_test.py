# pyright: reportInvalidTypeForm=none
"""Plain sim_call of a function that reaches a @pipeline_latency callee and
contains an integer compare.

Reaching a @pipeline_latency callee (here a make_ram ROM) makes sim_call
elaborate the caller with PY_TO_LOGIC.ELABORATE_LIVE_ROOTS, to align its paths.
That elaboration used to lack the default soft-operator lowerings PARSE_FILE
registers (operators.soft.register_sw_lib_replacements), so `s > lim` fell
through to the SW_LIB C-generation path and crashed on the unset
SYN.SYN_OUTPUT_DIRECTORY (`TypeError: ... 'NoneType' and 'str'`). pypelinec
and pypeline_sim.py register the lowerings before the design loads, so only a
plain Python process like this one hit it.

ELABORATE_LIVE_ROOTS now installs the lowerings, and arms
C_TO_LOGIC.PYPELINE_NO_SW_LIB_GUARD, for its own duration only. The
lowerings go in as lowest-priority fallbacks, so the process is left exactly
as before: a global registration would also switch native sim to the soft
implementations (pypeline.SIM_SOFT_OPS) for every later sim_call.

Registered in native_sim.
"""
import os
import sys

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
import copy

import C_TO_LOGIC
import PY_TO_LOGIC
import pypeline as PL
from pypeline import (
    INFERRED,
    Reg,
    any_int_t,
    hw_func,
    int8_t,
    register_operator,
    sim_call,
    sim_reset,
    uint4_t,
    uint8_t,
)
from ram import make_ram


def make_rom_caller(signed):
    s_t = int8_t if signed else uint8_t
    rom, _rom_t = make_ram(
        uint8_t, 16, ports=("r",), read_latency=1, init=list(range(16))
    )

    @hw_func
    def rom_caller(x: uint4_t, s: s_t) -> uint8_t:
        # Stateful: held is the ROM's physical output, the data for the
        # address two calls back (one cycle in the ROM, one in held).
        held: Reg[uint8_t]
        lim: s_t = 3
        big: uint8_t = 100
        res: uint8_t = held
        r = rom(rom.p0_in_t(addr=x, valid=1))
        held = r.p0.rd_data
        if s > lim:
            res = big
        return res

    return rom_caller


def make_pure_rom_caller():
    rom, _rom_t = make_ram(
        uint8_t, 16, ports=("r",), read_latency=1, init=list(range(16))
    )

    @hw_func
    def pure_rom_caller(x: uint4_t, s: int8_t) -> uint8_t:
        # Pure: native sim aligns s with the ROM's one cycle, so the compare
        # runs inside the aligned graph as a soft-compare entity.
        lim: int8_t = 3
        big: uint8_t = 100
        r = rom(rom.p0_in_t(addr=x, valid=1))
        res: uint8_t = r.p0.rd_data
        if s > lim:
            res = big
        return res

    return pure_rom_caller


signed_rom_caller = make_rom_caller(signed=True)
unsigned_rom_caller = make_rom_caller(signed=False)
pure_rom_caller = make_pure_rom_caller()

ADDRS = (5, 6, 7, 8, 9, 10)

# Every piece of live operator-registry state that elaboration resolves through
# or native-sim dispatch reads. The per-scope stores are left out: they keep
# the default lowerings' entries for reuse, by design.
_LIVE_REGISTRY_NAMES = (
    "_operator_registry",
    "_left_operator_registry",
    "_unary_operator_registry",
    "_mux_registry",
    "_generic_operator_registry",
    "_generic_left_operator_registry",
    "_generic_unary_operator_registry",
    "_generic_mux_registry",
    "_registered_binary_op_names",
    "_registered_unary_op_names",
    "_registered_mux_type_names",
    "_concrete_binary_op_names",
    "_concrete_unary_op_names",
    "_concrete_mux_type_names",
    "_matcher_binary_op_names",
    "_matcher_unary_op_names",
    "_matcher_mux_type_names",
    "_fallback_generic_head",
    "_scoped_generic_tail",
)


def _snapshot():
    return {name: copy.copy(getattr(PL, name)) for name in _LIVE_REGISTRY_NAMES}


def _restore(saved):
    """Undo a test's global registrations (there is no unregister API)."""
    for name, value in saved.items():
        live = getattr(PL, name)
        live.clear()
        if isinstance(live, list):
            live.extend(value)
        else:
            live.update(value)
    for cache in (
        PL._generic_operator_cache,
        PL._generic_left_operator_cache,
        PL._generic_unary_operator_cache,
        PL._generic_mux_cache,
    ):
        cache.clear()


def test_process_state_unchanged():
    # First, so no earlier elaboration can already have changed the state it
    # checks.
    before = _snapshot()
    guard = C_TO_LOGIC.PYPELINE_NO_SW_LIB_GUARD
    sim_reset()
    got = [
        int(sim_call(unsigned_rom_caller, x, s))
        for x, s in zip(ADDRS, (0, 0, 0, 0, 9, 200))
    ]
    assert got == [0, 0, 5, 6, 100, 100], got
    after = _snapshot()
    changed = [name for name in _LIVE_REGISTRY_NAMES if after[name] != before[name]]
    assert not changed, f"registry state changed: {changed}"
    assert C_TO_LOGIC.PYPELINE_NO_SW_LIB_GUARD == guard
    # Nothing resolves to a default lowering outside the elaboration.
    assert PL._resolve_generic_operator("GT", "int8_t", "int8_t") is None
    assert PL._resolve_generic_unary_operator("NEGATE", "int8_t") is None
    assert PL._resolve_generic_left_operator("SR", "uint8_t") is None


def test_stateful_rom_caller_with_signed_compare():
    sim_reset()
    # -9 is only below the limit as a signed int8_t (0xF7 unsigned is not).
    got = [
        int(sim_call(signed_rom_caller, x, s))
        for x, s in zip(ADDRS, (0, 0, 0, 0, 9, -9))
    ]
    assert got == [0, 0, 5, 6, 100, 8], got


def test_pure_rom_caller_with_signed_compare():
    sim_reset()
    got = [
        int(sim_call(pure_rom_caller, x, s))
        for x, s in zip(ADDRS, (0, 0, 0, 9, -9, 0))
    ]
    assert got == [0, 5, 6, 7, 100, 9], got


def test_design_registration_outranks_default():
    """Under PARSE_FILE the defaults are registered before the design file is
    imported, so the design's own registrations win. They must here too."""
    from operators.soft_cmp import make_soft_cmp_bitwise

    bitwise_gt = make_soft_cmp_bitwise("GT")
    asked = []

    def design_gt(l_t, r_t):
        asked.append((PL._ctype_str(l_t), PL._ctype_str(r_t)))
        return bitwise_gt(l_t, r_t)

    saved = _snapshot()
    try:
        register_operator("GT", any_int_t, any_int_t, design_gt)
        state = PY_TO_LOGIC.ELABORATE_LIVE_ROOTS([signed_rom_caller])
    finally:
        _restore(saved)
    assert asked == [("int8_t", "int8_t")], asked
    prefix = [name for name in state.FuncLogicLookupTable if "soft_cmp_prefix" in name]
    assert not prefix, f"default compare used instead of the design's: {prefix}"


def test_guard_armed_during_elaboration():
    """An op pinned back to the built-in path gets the guard's explicit error,
    not a crash deep inside the C-generation path."""
    saved = _snapshot()
    try:
        register_operator("GT", int8_t, int8_t, INFERRED)
        try:
            PY_TO_LOGIC.ELABORATE_LIVE_ROOTS([signed_rom_caller])
        except Exception as e:  # the guard raises a plain Exception
            assert "SW_LIB/cpp/pycparser" in str(e), repr(e)
        else:
            raise AssertionError("GT pinned to INFERRED elaborated without the guard")
    finally:
        _restore(saved)
    assert C_TO_LOGIC.PYPELINE_NO_SW_LIB_GUARD is False


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
