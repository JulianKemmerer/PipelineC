# pyright: reportInvalidTypeForm=none
"""Build fixture for auto_pipeline_region_minisweep_test.py: ChaCha-shaped
serial geometry in miniature. Each `step` runs four quarter rounds written in
series on the whole 4-word state, but every word passes through only two of
them (a column pair then a diagonal pair), so the real per-word path is about
half what the delay model's serial layout says. Evenly spaced cuts land out of
phase with the round boundaries; the measured mini-sweep of `step` (one cut
per step, shared boundary banks) is what reaches the goal compactly.

AUTO_PIPELINE_REGION_MINISWEEP_START_LATENCY=<S> tags the call site
start_latency=S, a starting guess only: the sweep must end at the same depth
as the untagged call site (unset)."""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import AUTO_PIPELINE, MAIN, NamedTuple, Reg, hw_func, rotl, struct, uint1_t, uint32_t


@struct
class st4_t(NamedTuple):
    w: uint32_t[4]


def make_qr(a, b, r):
    @hw_func
    def qr(s: st4_t) -> st4_t:
        o: st4_t = s
        x: uint32_t = o.w[a] + o.w[b]
        y: uint32_t = rotl(o.w[b] ^ x, r)
        z: uint32_t = x + y
        o.w[a] = z
        o.w[b] = rotl(y ^ z, r + 2)
        return o

    return qr


qr01 = make_qr(0, 1, 3)
qr23 = make_qr(2, 3, 5)
qr02 = make_qr(0, 2, 7)
qr13 = make_qr(1, 3, 9)


@hw_func
def step(s0: st4_t) -> st4_t:
    s1 = qr01(s0)
    s2 = qr23(s1)
    s3 = qr02(s2)
    s4 = qr13(s3)
    return s4


@hw_func
def chain(s: st4_t) -> st4_t:
    a = step(s)
    b = step(a)
    c = step(b)
    d = step(c)
    e = step(d)
    f = step(e)
    return f


_START = os.environ.get("AUTO_PIPELINE_REGION_MINISWEEP_START_LATENCY")
CHAIN_AP = (
    AUTO_PIPELINE(chain, start_latency=int(_START))
    if _START is not None
    else AUTO_PIPELINE(chain)
)


@MAIN(120.0)
def region_minisweep_main(s: st4_t) -> st4_t:
    # State makes the main itself unsliceable: only the tagged call site
    # takes registers
    toggle: Reg[uint1_t]
    toggle = ~toggle
    return CHAIN_AP(s)
