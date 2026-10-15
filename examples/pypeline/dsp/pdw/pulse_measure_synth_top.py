# pyright: reportInvalidTypeForm=none
"""Standalone measurement timing/area on AIR7310's FPGA.

Run a full synthesis sweep; PDW_ATAN2_METHOD=cordic|rom selects the angle
implementation. This exposes every measurement input/output for comparison.
"""

import pdw_paths  # noqa: F401
from pypeline import MAIN, PART, uint1_t, uint64_t
from pulse_detect import make_pulse_detect
from pulse_measure import make_pulse_measure

PART("xc7a200tffg1156-2")
detector = make_pulse_detect()
measure = make_pulse_measure(detector)

freq_t, noise_t, power_t = detector.freq_accum_t, detector.noise_t, detector.power_t


@MAIN(125.0)
def pulse_measure_top(
    freq: freq_t,
    noise: noise_t,
    power: power_t,
    toa: uint64_t,
    valid: uint1_t,
    accept: uint1_t,
    rst: uint1_t,
) -> measure.return_t:
    return measure(freq, noise, power, toa, valid, accept, rst)
