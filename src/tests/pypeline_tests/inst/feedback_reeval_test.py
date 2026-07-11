import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import (
    Feedback,
    Reg,
    hw_func,
    make_uint_t,
    sim_call,
    sim_reset,
    struct,
    uint1_t,
)

uint8_t = make_uint_t(8)


# ── Shapes shared across the three scenarios below ──────────────────────────


@hw_func
def consumer_child(en: uint1_t) -> uint8_t:
    """Reg-backed counter, gated by its input -- consumes a Feedback wire."""
    c: Reg[uint8_t]
    if en:
        c = c + 1
    return c


@hw_func
def producer_child(x: uint1_t) -> uint1_t:
    """Reg-driven output: returns the *previous* cycle's input."""
    r: Reg[uint1_t]
    out: uint1_t = r
    r = x
    return out


@struct
class p2_t(NamedTuple):
    cnt: uint8_t
    fb_val: uint1_t


@hw_func
def parent_fb_from_stateful_child(x: uint1_t) -> p2_t:
    """Feedback wire driven from a stateful child's Reg-backed output, and
    consumed by a second stateful child -- the failing shape from bug #5:
    convergence re-invokes both children each pass, and a naive unbuffered
    commit lets a later pass observe an earlier pass's write."""
    fb: Feedback[uint1_t]
    cnt: uint8_t = consumer_child(fb)
    prod: uint1_t = producer_child(x)
    fb = prod
    o: p2_t
    o.cnt = cnt
    o.fb_val = fb
    return o


@hw_func
def parent_fb_reg_same_body(x: uint1_t) -> p2_t:
    """Contrast case: Feedback[T] and Reg[T] in the same function body, no
    child calls -- exercises the existing __reg_init_<name> per-pass reset."""
    acc: Reg[uint8_t]
    fb: Feedback[uint1_t]
    fb = x
    if fb:
        acc = acc + 1
    o: p2_t
    o.cnt = acc
    o.fb_val = fb
    return o


@hw_func
def parent_fb_stateful_child_pure_driver(x: uint1_t) -> p2_t:
    """Contrast case: fb is consumed by a stateful child but driven from a
    pure input (not another stateful child's output)."""
    fb: Feedback[uint1_t]
    fb = x
    cnt: uint8_t = consumer_child(fb)
    o: p2_t
    o.cnt = cnt
    o.fb_val = fb
    return o


def test_feedback_from_stateful_child():
    """Bug #5 repro: fb_val must equal the previous cycle's x every cycle,
    including cycles where producer_child's old/new Reg value differs (the
    cycles that exposed the mixed-pass corruption: index 3 and 6 below)."""
    sim_reset()
    xs = [1, 1, 1, 0, 1, 1, 0, 0]
    prev_x = 0
    exp_cnt = 0
    for cyc, x in enumerate(xs):
        r = sim_call(parent_fb_from_stateful_child, x)
        if prev_x:
            exp_cnt += 1
        assert (
            int(r.fb_val) == prev_x
        ), f"cyc {cyc}: fb_val={int(r.fb_val)} expected {prev_x}"
        assert int(r.cnt) == exp_cnt, f"cyc {cyc}: cnt={int(r.cnt)} expected {exp_cnt}"
        prev_x = x
    print("test_feedback_from_stateful_child PASS")


def test_feedback_reg_same_body():
    sim_reset()
    xs = [1, 1, 0, 1, 0, 0]
    exp_cnt = 0
    for cyc, x in enumerate(xs):
        r = sim_call(parent_fb_reg_same_body, x)
        if x:
            exp_cnt += 1
        assert int(r.fb_val) == x, f"cyc {cyc}: fb_val={int(r.fb_val)} expected {x}"
        assert int(r.cnt) == exp_cnt, f"cyc {cyc}: cnt={int(r.cnt)} expected {exp_cnt}"
    print("test_feedback_reg_same_body PASS")


def test_feedback_stateful_child_pure_driver():
    sim_reset()
    xs = [1, 1, 0, 1, 0, 0]
    exp_cnt = 0
    for cyc, x in enumerate(xs):
        r = sim_call(parent_fb_stateful_child_pure_driver, x)
        if x:
            exp_cnt += 1
        assert int(r.fb_val) == x, f"cyc {cyc}: fb_val={int(r.fb_val)} expected {x}"
        assert int(r.cnt) == exp_cnt, f"cyc {cyc}: cnt={int(r.cnt)} expected {exp_cnt}"
    print("test_feedback_stateful_child_pure_driver PASS")


if __name__ == "__main__":
    test_feedback_from_stateful_child()
    test_feedback_reg_same_body()
    test_feedback_stateful_child_pure_driver()
    print("All feedback_reeval tests passed.")
