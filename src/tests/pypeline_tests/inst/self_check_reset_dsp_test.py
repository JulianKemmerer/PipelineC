# pyright: reportInvalidTypeForm=none
"""Self-checking reset-equivalence test of the DSP library blocks: one chain
of make_lut_nco, make_log2_db and make_lut_atan2 (ROM requests in flight;
their own rst input is 0), make_cordic_atan2, an elastic make_fir (fixed
latency 2: a FIFO, an in-flight count and pipeline stages), a valid-only
make_fir_decim, make_moving_avg and make_dc_block (filter history and an
integrator) and make_magnitude (fixed latency 1), with its source, runs in
two MAINs under reset_registers="all":

- dut_a is reset in cycle RESET_AT, with samples in flight;
- dut_b is held in reset from cycle 0 to RESET_AT.

Both see the same input gaps and output backpressure, functions of the
cycle. After RESET_AT every block is in its power-up state, so the two chains
must produce the same output in every cycle: the checker (the default
"requested" policy, not reset) asserts that, comparing data only with valid.

Registered in native_vs_vhdl_sim_tests.py (--comb), which diffs native and
cocotb+GHDL sim_print(debug=True) output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    int8_t,
    int16_t,
    int32_t,
    make_clock,
    make_int_t,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
    uint32_t,
)
from fixed_point import make_fixed_t
from dsp.cordic import make_cordic_atan2
from dsp.dc_block import make_dc_block
from dsp.fir import make_fir
from dsp.fir_decim import make_fir_decim
from dsp.log2_db import make_log2_db
from dsp.lut_atan2 import make_lut_atan2
from dsp.magnitude import make_magnitude
from dsp.moving_avg import make_moving_avg
from dsp.nco import make_lut_nco
from stream.stream import make_stream_t

RESET_AT = 21
N_CYCLES = 70

TAPS = [0.125, 0.375, 0.375, 0.125]
d8_t = make_fixed_t(1, 7)
d16_t = make_fixed_t(1, 15)
coeff_t = make_fixed_t(2, 6)
power_t = make_fixed_t(34, 12, signed=True)
xy_t = make_int_t(20)

nco = make_lut_nco(int16_t)
log = make_log2_db(power_t)
atan = make_lut_atan2(xy_t)
cordic = make_cordic_atan2(xy_t, n_iters=10, work_bits=20)
fir = make_fir(TAPS, coeff_t, d8_t, out_t=d8_t, rounding="round_half_even",
               overflow="saturate", latency=2)
decim = make_fir_decim(TAPS, coeff_t, 2, d8_t, out_t=d8_t, rounding="round_half_even",
                       overflow="saturate", handshake="valid_only")
mavg = make_moving_avg(d16_t, 4, handshake="valid_only")
dcb = make_dc_block(d16_t, k=5, handshake="valid_only")
mag = make_magnitude(d16_t, handshake="valid_only", latency=1)
fir_out_t = make_stream_t(fir.out_t)


@struct
class dsp_out_t(NamedTuple):
    nco: nco.return_t
    log: log.return_t
    atan: atan.return_t
    cordic: cordic.return_t
    fir: fir_out_t
    decim: decim.return_t
    mavg: mavg.return_t
    dcb: dcb.return_t
    mag: mag.return_t


clk = make_clock(100.0)
rst_a: Wire[uint1_t] = make_reset()
rst_b: Wire[uint1_t] = make_reset()
t_out: Wire[uint8_t]
present: Wire[uint1_t]
sink_ready: Wire[uint1_t]
a_out: Wire[dsp_out_t]
b_out: Wire[dsp_out_t]


@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    rst_a = t == RESET_AT
    rst_b = t <= RESET_AT
    t_out = t
    present = (t & 7) != 5
    sink_ready = (t & 3) != 2
    t += 1


@hw_func
def source_and_chain() -> dsp_out_t:
    n: Reg[uint16_t]  # samples given to the valid-only and ROM blocks
    m: Reg[uint16_t]  # samples the elastic FIR took
    o: dsp_out_t
    v: uint1_t = present
    s: uint16_t = n * 1237 + 11
    s16: int16_t = s
    s8: int8_t = s >> 8
    phase: uint32_t = n * 177777777
    pw: int32_t = n * 91919 - 5000
    x: xy_t = s16 * 7
    y: xy_t = (n * 7919) & 0x3FFF
    o.nco = nco(phase, s16, v, 0)
    o.log = log(power_t(val=pw), v, 0)
    o.atan = atan(x, y, v, 0)
    o.cordic = cordic(x, y, v)
    o.decim = decim(decim.in_stream_t(data=d8_t(val=s8), valid=v))
    o.mavg = mavg(mavg.in_stream_t(data=d16_t(val=s16), valid=v))
    o.dcb = dcb(dcb.in_stream_t(data=d16_t(val=s16), valid=v))
    c = mag.complex_t(i=d16_t(val=s16), q=d16_t(val=s16 >> 3))
    o.mag = mag(mag.in_stream_t(data=c, valid=v))
    if v:
        n += 1
    f8: int8_t = (m * 29 + 3) & 0xFF
    f = fir(
        fir.in_fwd_t(stream=fir.in_intrf.stream_t(data=d8_t(val=f8), valid=v)),
        fir.out_fb_t(ready=sink_ready),
    )
    o.fir = f.stream_out_if.stream
    if v & f.stream_in_if.ready:
        m += 1
    return o


@MAIN(clk, reset=rst_a, reset_registers="all")
def dut_a():
    a_out = source_and_chain()


@MAIN(clk, reset=rst_b, reset_registers="all")
def dut_b():
    b_out = source_and_chain()


@MAIN(clk)
def checker():
    t: uint8_t = t_out
    if t == N_CYCLES + 1:
        sim_finish()
    a: dsp_out_t = a_out
    b: dsp_out_t = b_out
    if (t > RESET_AT) & (t <= N_CYCLES):
        sim_assert(a.nco.valid == b.nco.valid, f"nco valid differs at {t}")
        sim_assert(a.log.valid == b.log.valid, f"log valid differs at {t}")
        sim_assert(a.atan.valid == b.atan.valid, f"atan valid differs at {t}")
        sim_assert(a.cordic.valid == b.cordic.valid, f"cordic valid differs at {t}")
        sim_assert(a.fir.valid == b.fir.valid, f"fir valid differs at {t}")
        sim_assert(a.decim.valid == b.decim.valid, f"decim valid differs at {t}")
        sim_assert(a.mavg.valid == b.mavg.valid, f"mavg valid differs at {t}")
        sim_assert(a.dcb.valid == b.dcb.valid, f"dcb valid differs at {t}")
        sim_assert(a.mag.valid == b.mag.valid, f"mag valid differs at {t}")
        if a.nco.valid:
            sim_assert((a.nco.i == b.nco.i) & (a.nco.q == b.nco.q), f"nco differs at {t}")
            sim_print(f"t={t} nco {a.nco.i} {a.nco.q}", debug=True)
        if a.log.valid:
            sim_assert((a.log.db == b.log.db) & (a.log.floored == b.log.floored),
                       f"log differs at {t}")
            sim_print(f"t={t} log {a.log.db} {a.log.floored}", debug=True)
        if a.atan.valid:
            sim_assert(a.atan.angle == b.atan.angle, f"atan differs at {t}")
            sim_print(f"t={t} atan {a.atan.angle}", debug=True)
        if a.cordic.valid:
            sim_assert(a.cordic.angle == b.cordic.angle, f"cordic differs at {t}")
            sim_print(f"t={t} cordic {a.cordic.angle}", debug=True)
        if a.fir.valid:
            sim_assert(a.fir.data.val == b.fir.data.val, f"fir differs at {t}")
            sim_print(f"t={t} fir {a.fir.data.val}", debug=True)
        if a.decim.valid:
            sim_assert(a.decim.data.val == b.decim.data.val, f"decim differs at {t}")
            sim_print(f"t={t} decim {a.decim.data.val}", debug=True)
        if a.mavg.valid:
            sim_assert(a.mavg.data.val == b.mavg.data.val, f"mavg differs at {t}")
            sim_print(f"t={t} mavg {a.mavg.data.val}", debug=True)
        if a.dcb.valid:
            sim_assert(a.dcb.data.val == b.dcb.data.val, f"dcb differs at {t}")
            sim_print(f"t={t} dcb {a.dcb.data.val}", debug=True)
        if a.mag.valid:
            sim_assert(a.mag.data.val == b.mag.data.val, f"mag differs at {t}")
            sim_print(f"t={t} mag {a.mag.data.val}", debug=True)
