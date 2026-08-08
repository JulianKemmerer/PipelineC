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
    char_t,
    hw_func,
    sim_call,
    sim_reset,
    sim_print,
    strlen,
    uint8_t,
)


# ── hardware functions ───────────────────────────────────────────────────────


@MAIN
def counter_with_print(en: uint8_t) -> uint8_t:
    """Real per-cycle state (not just constant wiring) alongside the print, so
    synthesis has actual timing paths to measure -- mirrors char_array_test.py's
    increment_chars in spirit."""
    n: Reg[uint8_t]
    sim_print(f"n={n} hex={hex(n)} ch={chr(n)}")
    if en:
        n = n + 1
    return n


@MAIN
def print_name(name: char_t[8]) -> uint8_t:
    """%s auto-inferred from the bare char_t[8] value, sized to 8 (not PipelineC C's
    historical 256) -- proves the real-array-size fix, not just that %s elaborates
    at all."""
    sim_print(f"name={name} len={strlen(name)}")
    return strlen(name)


def print_a():
    sim_print("Prints same thing every cycle")


def print_b(i: uint8_t):
    sim_print(f"Prints different thing every cycle {i}")


@MAIN
def main_a_b():
    i: Reg[uint8_t]
    if i < 10:
        print_a()
        print_b(i)
        i += 1
    else:
        i = 0


# ── simulation tests ─────────────────────────────────────────────────────────


def test_counter_prints():
    sim_reset()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # sim_print(...) reads n *before* the conditional increment, so the printed
        # values are the pre-increment 0/1 -- but `return n` reads n *after* the
        # increment, so the returned values are post-increment 1/2.
        r0 = sim_call(counter_with_print, en=1)
        r1 = sim_call(counter_with_print, en=1)
    assert int(r0) == 1, int(r0)
    assert int(r1) == 2, int(r1)
    expected = "n=0 hex=0x0 ch=\x00\n" "n=1 hex=0x1 ch=\x01\n"
    assert buf.getvalue() == expected, repr(buf.getvalue())
    print("test_counter_prints PASS")


def test_print_name():
    sim_reset()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = sim_call(print_name, name="hi")
    # strlen() returns declared capacity (8), not content length -- see char_array_test.py.
    assert int(r) == 8, int(r)
    assert buf.getvalue() == "name=hi len=8\n", repr(buf.getvalue())
    print("test_print_name PASS")


def test_sim_call_always_fires():
    # sim_call() never sets _sim_converging, so sim_print always fires -- deterministic,
    # unlike pypeline_sim.py's multi-MAIN convergence loop (see global_wires_sim_test.py).
    sim_reset()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sim_call(counter_with_print, en=0)
        sim_call(counter_with_print, en=0)
        sim_call(counter_with_print, en=0)
    assert buf.getvalue().count("\n") == 3, repr(buf.getvalue())
    print("test_sim_call_always_fires PASS")


def test_bare_char_array_elaborates():
    """A bare {expr} for a char_t[N] array now auto-infers %s at elaboration time, and
    matches it in simulation via CharArray's NUL-stopped __str__ -- no wrapper call
    needed. print_name/test_print_name above already exercises this end to end; this
    test just pins down that elaboration itself succeeds (doesn't raise) for the bare
    form, on an isolated temp file (not this file itself, since this file is also fed
    wholesale to pypelinec by elab_tests.py/synth_tests.py and must elaborate cleanly
    end to end)."""
    import PY_TO_LOGIC

    src = (
        "from pypeline import MAIN, char_t, sim_print, uint8_t\n\n"
        "@MAIN\n"
        "def good(name: char_t[8]) -> uint8_t:\n"
        '    sim_print(f"name={name}")\n'
        "    return 0\n"
    )
    fd, path = tempfile.mkstemp(
        suffix=".py", dir=os.path.dirname(os.path.abspath(__file__))
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(src)
        PY_TO_LOGIC.PARSE_FILE(path)  # must not raise
    finally:
        os.remove(path)
    print("test_bare_char_array_elaborates PASS")


def test_bare_char_scalar_rejected_at_elaboration():
    """A bare {expr} for a single char_t value is ambiguous (%c vs %d) and would print
    correctly in hardware but WRONG in simulation (Python's default int formatting of a
    SimVal) -- this must still be a hard elaboration error; unaffected by the
    char_array_to_str removal, since it's a distinct ambiguity requiring chr(expr)."""
    import PY_TO_LOGIC

    src = (
        "from pypeline import MAIN, char_t, sim_print\n\n"
        "@MAIN\n"
        "def bad(ch: char_t) -> char_t:\n"
        '    sim_print(f"ch={ch}")\n'
        "    return ch\n"
    )
    fd, path = tempfile.mkstemp(
        suffix=".py", dir=os.path.dirname(os.path.abspath(__file__))
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(src)
        try:
            PY_TO_LOGIC.PARSE_FILE(path)
        except PY_TO_LOGIC.ElaborationError as e:
            assert "chr(expr)" in str(e), str(e)
        else:
            raise AssertionError(
                "expected ElaborationError for bare {ch} single-char interpolation"
            )
    finally:
        os.remove(path)
    print("test_bare_char_scalar_rejected_at_elaboration PASS")


if __name__ == "__main__":
    test_counter_prints()
    test_print_name()
    test_sim_call_always_fires()
    test_bare_char_array_elaborates()
    test_bare_char_scalar_rejected_at_elaboration()
    print("All sim_print tests passed.")
