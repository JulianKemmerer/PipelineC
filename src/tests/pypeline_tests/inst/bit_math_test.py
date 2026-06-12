# pyright: reportInvalidTypeForm=none
"""Simulation bit-accuracy tests for typed local variable assignment truncation.

Run directly:
    python3 src/tests/pypeline_tests/inst/bit_math_test.py

Also consumed as hardware definitions by the PipelineC test harness.

Covers:
- _TypedAnnAssignRewriter: `var: int_t = expr` is truncated to the declared width at
  each assignment, matching hardware semantics.
- SIM_STRICT_ARITH: arithmetic on typed SimVals produces hardware-accurate output types.
- Reg[T] with typed local annotations: truncation happens inside the sim body.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    Reg,
    hw_func,
    sim_reset,
    sim_call,
    int16_t,
    int32_t,
    uint8_t,
    uint12_t,
    uint16_t,
    uint32_t,
    uint1_t,
)


# ---------------------------------------------------------------------------
# Hardware functions under test
# ---------------------------------------------------------------------------


@hw_func
def truncate_then_square(a: int16_t, b: int16_t) -> int32_t:
    """Sum a+b, truncate to int16_t, return the square as int32_t.

    Hardware: a+b overflows int16_t → wraps; the squared result differs from
    squaring the full-precision sum.  Simulation must match.
    """
    s: int16_t = a + b  # int17_t result truncated to int16_t
    return s * s  # int16_t * int16_t → int32_t


@hw_func
def nested_truncate(a: int16_t) -> int16_t:
    """Intermediate typed assignments inside an if-branch are rewritten."""
    out: int16_t = 0
    if a > 0:
        big: int16_t = a * a  # int32_t product → truncated to int16_t
        out = big + 1  # may also overflow, but tests that branch bodies are reached
    return out


@hw_func
def counter_uint8(tick: uint1_t) -> uint8_t:
    """8-bit counter that wraps at 256 via typed annotation on the increment step."""
    n: Reg[uint8_t]
    v: uint8_t = n + 1  # truncates to uint8_t → wraps at 256
    n = v
    return n


@MAIN
def bit_math_top(a: int16_t, b: int16_t) -> int32_t:
    """Top-level entry for hardware elaboration; delegates to inner hw_funcs."""
    return truncate_then_square(a, b)


# ---------------------------------------------------------------------------
# Simulation tests
# ---------------------------------------------------------------------------


def test_truncate_then_square():
    """20000 + 20000 = 40000, truncated to int16_t = -25536; -25536^2 = 652086296."""
    sim_reset()
    result = sim_call(truncate_then_square, a=20000, b=20000)
    expected = (-25536) ** 2  # 652_087_296
    assert int(result) == expected, (
        f"truncate_then_square(20000, 20000): expected {expected}, got {int(result)}\n"
        f"(If you got 1600000000 = 40000^2, _TypedAnnAssignRewriter is not applied)"
    )
    print(f"test_truncate_then_square PASS  result={int(result)}")


def test_no_truncation_when_in_range():
    """Typed annotation that does not overflow is a no-op — value is preserved."""
    sim_reset()
    result = sim_call(truncate_then_square, a=100, b=100)
    # 100+100=200, fits in int16_t, 200^2=40000
    assert int(result) == 40000, f"expected 40000, got {int(result)}"
    print(f"test_no_truncation_when_in_range PASS  result={int(result)}")


def test_nested_truncate():
    """Typed assignment inside an if-branch is rewritten by the transformer."""
    sim_reset()
    # a=200: 200*200=40000, fits in int16_t (< 32767? no, 40000 > 32767)
    # int32_t(40000) → _sim_cast(40000, int16_t) = 40000 & 0xffff = 40000; 40000 >= 32768 → 40000-65536 = -25536
    # out = -25536 + 1 = -25535 → _sim_cast(-25535, int16_t) = -25535 (in range)
    result = sim_call(nested_truncate, a=200)
    assert int(result) == -25535, f"expected -25535, got {int(result)}"
    print(f"test_nested_truncate PASS  result={int(result)}")


def test_counter_wraps_at_256():
    """uint8_t typed annotation on the increment causes wrap-around at 256."""
    sim_reset()
    # Each sim_call returns the POST-increment value and writes it to state.
    # Call k returns k; call 256 returns 0 (uint8 wrap).
    # Advance through calls 1..254 (state reaches 254 after last call).
    for _ in range(254):
        sim_call(counter_uint8, tick=1)
    at_255 = sim_call(counter_uint8, tick=1)  # call 255: 254+1=255, return 255
    at_wrap = sim_call(counter_uint8, tick=1)  # call 256: 255+1=256 → uint8 wrap to 0
    assert int(at_255) == 255, f"expected 255, got {int(at_255)}"
    assert int(at_wrap) == 0, f"expected 0 (uint8 wrap), got {int(at_wrap)}"
    print(
        f"test_counter_wraps_at_256 PASS  at_255={int(at_255)} at_wrap={int(at_wrap)}"
    )


# ---------------------------------------------------------------------------
# cx/cy coordinate math from vga_donut.py render_pixel
# ---------------------------------------------------------------------------

_FRAME_WIDTH = 640
_FRAME_HEIGHT = 480


@hw_func
def render_cx(pos_x: uint12_t) -> int16_t:
    """Mirror of render_pixel's cx line: (pos_x << 1) - (FRAME_WIDTH + 1)."""
    cx: int16_t = (pos_x << 1) - (_FRAME_WIDTH + 1)
    return cx


@hw_func
def render_cy(pos_y: uint12_t) -> int16_t:
    """Mirror of render_pixel's cy line: (FRAME_HEIGHT + 1) - (pos_y << 1)."""
    cy: int16_t = (_FRAME_HEIGHT + 1) - (pos_y << 1)
    return cy


def test_cx_cy_hardware_arithmetic():
    """cx and cy match hardware's unsigned intermediate arithmetic.

    In hardware, PY_TO_LOGIC types the shift result as uint12_t and the constant
    (e.g. 641) as its minimum unsigned type.  The subtraction is therefore an
    UNSIGNED subtraction: when the mathematical result would be negative it wraps
    mod 2^12 = 4096 instead of producing a true negative.

    This wrapping is what causes the missing bottom half of the vga_donut image:
      cy = (FRAME_HEIGHT+1) - (sig.pos.y<<1)
    For pos_y > 240 the inner expression 481 - 2*pos_y is negative, hardware wraps
    it to a large positive number (> 180), so the donut bounding box check
    `cy < 180` fails and those pixels are not coloured.

    render_cx and render_cy replicate those lines in isolation.  After the
    _infer_literal_ctype + shift-ctype-preservation fixes, simulation now matches.
    """
    sim_reset()
    # cx = (pos_x << 1) - 641.  For pos_x < 321 the mathematical result is negative;
    # hardware wraps mod 4096 (uint12_t).
    cases_cx = [
        (0, (-641) % 4096),  # wraps: 0*2-641 = -641 → 3455
        (320, (-1) % 4096),  # wraps: 320*2-641 = -1  → 4095
        (321, 1),  # positive, no wrap
        (639, 637),  # positive, no wrap
    ]
    for x, expected in cases_cx:
        got = sim_call(render_cx, pos_x=x)
        assert (
            int(got) == expected
        ), f"render_cx({x}): expected {expected}, got {int(got)}"

    # cy = 481 - (pos_y << 1).  For pos_y > 240 the mathematical result is negative;
    # hardware wraps mod 4096 (uint12_t) → large positive → fails cy < 180 → no pixel.
    cases_cy = [
        (0, 481),  # positive, no wrap
        (240, 1),  # positive, no wrap
        (241, (-1) % 4096),  # wraps: 481-482 = -1   → 4095
        (479, (-477) % 4096),  # wraps: 481-958 = -477 → 3619
    ]
    for y, expected in cases_cy:
        got = sim_call(render_cy, pos_y=y)
        assert (
            int(got) == expected
        ), f"render_cy({y}): expected {expected}, got {int(got)}"
    print(
        "test_cx_cy_hardware_arithmetic PASS — unsigned intermediate wrap matches hardware"
    )


# ---------------------------------------------------------------------------
# Plain-Assign inferred truncation: declared type propagates to re-assignments
#
# _TypedAnnAssignRewriter now also rewrites bare `var = expr` (Assign nodes)
# when `var` was previously declared with a scalar integer annotation.
# A variable's type is declared once; hardware truncates on every write.
#
# In the donut loop:
#   d: int16_t = 0        # declaration records d → int16_t
#   ...
#   d = t2 - CORDIC_R1I   # plain Assign — now also rewritten to _sim_cast
#   t = t + d             # same
#
# These two styles are now equivalent in simulation:
#   t: int16_t = t + n    # AnnAssign (explicit re-annotation)
#   t = t + n             # plain Assign (type inferred from initial declaration)
# ---------------------------------------------------------------------------


@hw_func
def loop_annotated_assigns(n: int16_t) -> int16_t:
    """Re-annotates on every loop update — shows explicit form still works."""
    t: int16_t = 512
    count: int16_t = 0
    for _ in range(16):
        t: int16_t = t + n  # AnnAssign → _sim_cast → truncates
        if t < 2048:
            count: int16_t = count + 1
    return count


@hw_func
def loop_plain_assigns(n: int16_t) -> int16_t:
    """Uses plain Assign in loop body — type inferred from initial declaration."""
    t: int16_t = 512
    count: int16_t = 0
    for _ in range(16):
        t = t + n  # plain Assign — type inferred from `t: int16_t = 512`
        if t < 2048:
            count: int16_t = count + 1
    return count


def test_plain_assign_inferred_truncation():
    """Plain-Assign re-uses the declared type and truncates identically to AnnAssign.

    With n=3000, t overflows int16_t at iteration 11 (512 + 11*3000 = 33512 > 32767).
    Hardware wraps t to -32024 (< 2048), so iterations 11-16 each increment count → 6.
    Both the explicit re-annotation form and the plain-Assign form now give 6.
    """
    sim_reset()
    ann_result = sim_call(loop_annotated_assigns, n=3000)
    plain_result = sim_call(loop_plain_assigns, n=3000)
    assert int(ann_result) == 6, f"annotated loop expected 6, got {int(ann_result)}"
    assert (
        int(plain_result) == 6
    ), f"plain-assign loop expected 6, got {int(plain_result)}"
    print(
        f"test_plain_assign_inferred_truncation PASS"
        f"  annotated={int(ann_result)}  plain={int(plain_result)}"
    )


if __name__ == "__main__":
    test_truncate_then_square()
    test_no_truncation_when_in_range()
    test_nested_truncate()
    test_counter_wraps_at_256()
    test_cx_cy_hardware_arithmetic()
    test_plain_assign_inferred_truncation()
    print("\nAll bit_math_test tests passed.")
