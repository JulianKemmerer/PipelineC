import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import MAIN, Reg, sim_call, sim_reset, uint8_t, uint25_t, uint32_t


@MAIN
def counter_uint25() -> uint32_t:
    """Reg[uint25_t]: width 25 used to be missing from pypeline.py's predefined
    uintN_t constants, causing the annotation eval to raise NameError, silently
    swallowed by native sim -- the variable then behaved as an unregistered
    Python local that reset to its init value every call instead of persisting."""
    cnt: Reg[uint25_t] = 0
    cnt = cnt + 1
    return cnt


@MAIN
def counter_uint8() -> uint32_t:
    """Sanity check: an already-defined width still works after extending the
    uintN_t/intN_t constant blocks to cover 1-64."""
    cnt: Reg[uint8_t] = 0
    cnt = cnt + 1
    return cnt


def test_uint25_reg_persists():
    """Previously-undefined width 25: register state must persist across calls."""
    sim_reset()
    a = sim_call(counter_uint25)
    b = sim_call(counter_uint25)
    c = sim_call(counter_uint25)
    assert [int(a), int(b), int(c)] == [1, 2, 3], f"got {[int(a), int(b), int(c)]}"
    print(f"test_uint25_reg_persists PASS  {[int(a), int(b), int(c)]}")


def test_uint8_reg_persists():
    """Already-defined width 8: unaffected by the constant-block edit."""
    sim_reset()
    a = sim_call(counter_uint8)
    b = sim_call(counter_uint8)
    assert [int(a), int(b)] == [1, 2], f"got {[int(a), int(b)]}"
    print(f"test_uint8_reg_persists PASS  {[int(a), int(b)]}")


def test_bogus_reg_type_raises():
    """Reg[T] annotation whose T can't be resolved must fail loudly (NotImplementedError)
    at MAIN-registration time, not silently run with wrong (unregistered) state.

    Written to a real temp file (not exec()'d from a string) because the
    Reg[T]/Feedback[T] scan relies on inspect.getsource(), which requires the
    function to have real backing source -- exec()'d/compiled-string code has
    no linecache entry and getsource() fails, masking the very check under test.
    """
    import subprocess
    import sys as _sys
    import tempfile

    src = (
        "import sys\n"
        f"sys.path.insert(0, {str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))!r})\n"
        "from pypeline import MAIN, Reg, uint32_t\n"
        "@MAIN\n"
        "def bogus() -> uint32_t:\n"
        "    cnt: Reg[not_a_real_pypeline_type] = 0\n"
        "    cnt = cnt + 1\n"
        "    return cnt\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as f:
        f.write(src)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [_sys.executable, tmp_path], capture_output=True, text=True
        )
        assert result.returncode != 0, "expected non-zero exit for unresolvable Reg[T] type"
        assert "NotImplementedError" in result.stderr, result.stderr
        assert "not_a_real_pypeline_type" in result.stderr, result.stderr
        print("test_bogus_reg_type_raises PASS")
    finally:
        os.remove(tmp_path)


if __name__ == "__main__":
    test_uint25_reg_persists()
    test_uint8_reg_persists()
    test_bogus_reg_type_raises()
    print("All reg_undefined_width tests passed.")
