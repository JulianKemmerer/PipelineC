# pyright: reportInvalidTypeForm=none
"""Power (I^2+Q^2) example + testbench.

A complex tone with a rectangular amplitude envelope (a pulse): power should
come out flat and high inside the pulse, near zero outside it -- exactly the
"instantaneous power" stage feeding the PDW hysteresis state machine (see
examples/pypeline/dsp/pdw/README.md, Path A: Detect & Measure).
make_fixed_t(16, 0) is exactly int16_t, so this is the PDW README's own
int16 I/Q -> uint32 power format (out_t=None gives the full-precision,
lossless power type).

Two @MAIN entry points exercise both handshake modes in one run: an elastic
instance under random consumer backpressure, and a valid_only (free-running)
instance.

Run the simulation:
    pypelinec examples/pypeline/dsp/magnitude_tb.py --sim --comb --run 1000
"""

import math
from pypeline import MAIN

from fixed_point import make_fixed_t
from dsp.magnitude import make_magnitude
from dsp.dsp_tb import golden_magnitude, make_block_tb

data_t = make_fixed_t(16, 0)  # int16_t I/Q rails, the PDW's raw ADC format

N = 200
PULSE_START = 40
PULSE_LEN = 80
AMPLITUDE = 20000
CYCLES = 5


def _tone_pulse():
    iq = []
    for n in range(N):
        amp = AMPLITUDE if PULSE_START <= n < PULSE_START + PULSE_LEN else 0
        i = int(round(amp * math.cos(2.0 * math.pi * CYCLES * n / N)))
        q = int(round(amp * math.sin(2.0 * math.pi * CYCLES * n / N)))
        iq.append((i, q))
    return iq


STIM = _tone_pulse()

magnitude_e, magnitude_e_t = make_magnitude(data_t)
expected_e = golden_magnitude(magnitude_e, STIM)


def _in_value(pair):
    i, q = pair
    return magnitude_e.complex_t(i=data_t(val=i), q=data_t(val=q))


def _check_pulse_visible(state):
    hist = state["out_hist"]
    in_pulse = hist[PULSE_START : PULSE_START + PULSE_LEN]
    out_pulse = hist[:PULSE_START] + hist[PULSE_START + PULSE_LEN :]
    avg_in = sum(in_pulse) / len(in_pulse)
    avg_out = sum(out_pulse) / len(out_pulse)
    assert avg_in > 10 * max(1, avg_out), (
        f"pulse not visible in power: in-pulse avg {avg_in} vs "
        f"out-of-pulse avg {avg_out}"
    )
    print(f"magnitude: in-pulse avg power {avg_in:.0f}, out-of-pulse avg {avg_out:.0f}")


tb_e = make_block_tb(
    magnitude_e,
    STIM,
    expected_e,
    name="magnitude_elastic",
    ready_pattern="random",
    in_value=_in_value,
    idle_raw=(0, 0),
    on_done=_check_pulse_visible,
)


@MAIN(125.0)
def magnitude_elastic_tb():
    stream_in = tb_e.drive_in()
    out_ready = tb_e.drive_ready()
    o = magnitude_e(stream_in, out_ready)
    tb_e.observe(o)


magnitude_v, magnitude_v_t = make_magnitude(data_t, handshake="valid_only")
expected_v = golden_magnitude(magnitude_v, STIM)


def _in_value_v(pair):
    i, q = pair
    return magnitude_v.complex_t(i=data_t(val=i), q=data_t(val=q))


tb_v = make_block_tb(
    magnitude_v,
    STIM,
    expected_v,
    name="magnitude_valid_only",
    in_value=_in_value_v,
    idle_raw=(0, 0),
)


@MAIN(125.0)
def magnitude_valid_only_tb():
    stream_in = tb_v.drive_in()
    o = magnitude_v(stream_in)
    tb_v.observe(o)
