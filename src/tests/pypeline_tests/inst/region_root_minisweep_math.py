# pyright: reportInvalidTypeForm=none
"""Arithmetic module of region_root_minisweep_design.py: the ChaCha-shaped
`step` of auto_pipeline_region_minisweep_design.py. Imported by
region_root_minisweep_chain.py, so its calls there are labeled with their bare
names while its functions are named region_root_minisweep_math_*: nothing in
it matches a register name by function name."""
from pypeline import NamedTuple, hw_func, rotl, struct, uint32_t


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
