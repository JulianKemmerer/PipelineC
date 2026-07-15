# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN companion to bit_math_test.py: exercises a representative
subset of its hw_funcs (the stateless, deterministic-constant-input ones --
not counter_uint8's 256-cycle wraparound or the loop-based accumulators, which
would need real multi-cycle sequencing to reproduce here) via sim_assert, then
calls sim_finish() -- no external Python sim_call/assert harness needed.

The hw_funcs are duplicated here rather than imported from bit_math_test.py:
that file has a scalar-argument @MAIN (bit_math_top(a, b)), and pypeline_sim.py
discovers @MAIN functions transitively through imports -- importing the module
would pull bit_math_top into this simulation too, which the CLI --sim
multi-main driver can't drive (it only supports no-arg @MAINs reading global
Wire[T] state), breaking `--sim` for this file.

Registered in both native_sim_tests.py (--sim --run all) and vhdl_sim_tests.py
(--sim --comb --cocotb --ghdl --run all), proving native and VHDL sim agree.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, hw_func, int16_t, int32_t, sim_assert, sim_finish, uint12_t

_FRAME_WIDTH = 640
_FRAME_HEIGHT = 480


@hw_func
def truncate_then_square(a: int16_t, b: int16_t) -> int32_t:
    s: int16_t = a + b  # int17_t result truncated to int16_t
    return s * s  # int16_t * int16_t -> int32_t


@hw_func
def nested_truncate(a: int16_t) -> int16_t:
    out: int16_t = 0
    if a > 0:
        big: int16_t = a * a  # int32_t product -> truncated to int16_t
        out = big + 1
    return out


@hw_func
def render_cx(pos_x: uint12_t) -> int16_t:
    cx: int16_t = (pos_x << 1) - (_FRAME_WIDTH + 1)
    return cx


@hw_func
def render_cy(pos_y: uint12_t) -> int16_t:
    cy: int16_t = (_FRAME_HEIGHT + 1) - (pos_y << 1)
    return cy


@MAIN
def self_check_bit_math():
    # Explicit int16_t-typed locals for each literal arg -- without this, each
    # call site's literal gets its own auto-inferred minimal width, and GHDL
    # rejects the resulting port-width mismatch across the differently-sized
    # truncate_then_square submodule instances ("actual constraints don't
    # match formal ones").
    a1: int16_t = 20000
    b1: int16_t = 20000
    r1: int32_t = truncate_then_square(a1, b1)
    sim_assert(
        r1 == 652087296,
        f"truncate_then_square(20000,20000) expected 652087296 got {r1}",
    )

    a2: int16_t = 100
    b2: int16_t = 100
    r2: int32_t = truncate_then_square(a2, b2)
    sim_assert(r2 == 40000, f"truncate_then_square(100,100) expected 40000 got {r2}")

    n3: int16_t = 200
    r3: int16_t = nested_truncate(n3)
    sim_assert(r3 == -25535, f"nested_truncate(200) expected -25535 got {r3}")

    # Explicit uint12_t-typed locals for each literal arg -- without this, each
    # call site's literal gets its own auto-inferred minimal width, and GHDL
    # rejects the resulting port-width mismatch across the differently-sized
    # render_cx/render_cy submodule instances ("actual constraints don't match
    # formal ones").
    x0: uint12_t = 0
    cx0: int16_t = render_cx(x0)
    sim_assert(cx0 == (-641) % 4096, f"render_cx(0) expected {(-641) % 4096} got {cx0}")
    x320: uint12_t = 320
    cx320: int16_t = render_cx(x320)
    sim_assert(
        cx320 == (-1) % 4096, f"render_cx(320) expected {(-1) % 4096} got {cx320}"
    )
    x321: uint12_t = 321
    cx321: int16_t = render_cx(x321)
    sim_assert(cx321 == 1, f"render_cx(321) expected 1 got {cx321}")
    x639: uint12_t = 639
    cx639: int16_t = render_cx(x639)
    sim_assert(cx639 == 637, f"render_cx(639) expected 637 got {cx639}")

    y0: uint12_t = 0
    cy0: int16_t = render_cy(y0)
    sim_assert(cy0 == 481, f"render_cy(0) expected 481 got {cy0}")
    y240: uint12_t = 240
    cy240: int16_t = render_cy(y240)
    sim_assert(cy240 == 1, f"render_cy(240) expected 1 got {cy240}")
    y241: uint12_t = 241
    cy241: int16_t = render_cy(y241)
    sim_assert(
        cy241 == (-1) % 4096, f"render_cy(241) expected {(-1) % 4096} got {cy241}"
    )
    y479: uint12_t = 479
    cy479: int16_t = render_cy(y479)
    sim_assert(
        cy479 == (-477) % 4096, f"render_cy(479) expected {(-477) % 4096} got {cy479}"
    )

    sim_finish()
