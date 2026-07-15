import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    Reg,
    SimFinish,
    hw_func,
    sim_assert,
    sim_call,
    sim_finish,
    sim_reset,
    uint8_t,
)


# ── hardware functions ───────────────────────────────────────────────────────


@MAIN
def counter_with_assert(en: uint8_t) -> uint8_t:
    """Real per-cycle state (not just constant wiring) alongside the assert, so
    synthesis has actual timing paths to measure -- mirrors sim_print_test.py's
    counter_with_print in spirit."""
    n: Reg[uint8_t]
    sim_assert(n < 5, f"n too big: {n}")
    if en:
        n = n + 1
    return n


@MAIN
def counter_with_finish(en: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    if n >= 3:
        sim_finish()
    if en:
        n = n + 1
    return n


def check_a(i: uint8_t):
    sim_assert(i < 200, "i too big (check_a)")


def check_b(i: uint8_t):
    sim_assert(i < 200, f"i too big {i}")


@MAIN
def main_a_b():
    i: Reg[uint8_t]
    if i < 10:
        check_a(i)
        check_b(i)
        i += 1
    else:
        i = 0


# ── simulation tests ─────────────────────────────────────────────────────────


def test_sim_assert_passes_silently():
    sim_reset()
    r0 = sim_call(counter_with_assert, en=1)
    r1 = sim_call(counter_with_assert, en=1)
    assert int(r0) == 1, int(r0)
    assert int(r1) == 2, int(r1)
    print("test_sim_assert_passes_silently PASS")


def test_sim_assert_fails_with_message():
    sim_reset()
    for _ in range(5):
        sim_call(counter_with_assert, en=1)
    try:
        sim_call(counter_with_assert, en=1)
    except AssertionError as e:
        assert "n too big: 5" in str(e), str(e)
    else:
        raise AssertionError("expected AssertionError from sim_assert")
    print("test_sim_assert_fails_with_message PASS")


def test_sim_assert_default_message():
    # No comparison operators here -- x is already uint1_t, so PARSE_FILE only needs
    # to elaborate sim_assert's own raw-HDL submodule, not a synthesized BIN_OP_LT
    # comparator (which requires the full CLI-driven SYN_OUTPUT_DIRECTORY context that
    # a standalone PARSE_FILE() call, outside pipelinec's driver, doesn't set up).
    sim_reset()
    fd, path = tempfile.mkstemp(
        suffix=".py", dir=os.path.dirname(os.path.abspath(__file__))
    )
    src = (
        "from pypeline import MAIN, sim_assert, uint1_t, uint8_t\n\n"
        "@MAIN\n"
        "def bad(x: uint1_t) -> uint1_t:\n"
        "    sim_assert(x)\n"
        "    return x\n"
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(src)
        import PY_TO_LOGIC

        PY_TO_LOGIC.PARSE_FILE(path)  # elaboration must not raise (no message given)
    finally:
        os.remove(path)
    print("test_sim_assert_default_message PASS")


def test_sim_finish_stops_native_sim():
    sim_reset()
    for i in range(3):
        sim_call(counter_with_finish, en=1)
    try:
        sim_call(counter_with_finish, en=1)
    except SimFinish:
        pass
    else:
        raise AssertionError("expected SimFinish from sim_finish")
    print("test_sim_finish_stops_native_sim PASS")


def test_bare_call_asserts_elaborate():
    sim_reset()
    sim_call(main_a_b)  # must not raise -- sim_assert calls nested in helper funcs
    print("test_bare_call_asserts_elaborate PASS")


if __name__ == "__main__":
    test_sim_assert_passes_silently()
    test_sim_assert_fails_with_message()
    test_sim_assert_default_message()
    test_sim_finish_stops_native_sim()
    test_bare_call_asserts_elaborate()
    print("All sim_assert/sim_finish tests passed.")
