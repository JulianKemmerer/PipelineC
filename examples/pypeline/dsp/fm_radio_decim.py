# pyright: reportInvalidTypeForm=none
"""Synthesizable I/Q 5x decimator pair -- the FM radio front-end slice of
examples/sdr/fm_radio.c, rebuilt with the pypeline DSP library.

Two make_fir_decim instances (one per I/Q rail) with the exact 49-tap Q1.15
coefficient set of the old macro library's `decim_5x`. Each filter is one
autopipelined combinational blob wrapped in a valid/ready stream: at the
125 MHz constraint below the tool picks the pipeline depth for the target
part -- nothing here hard-codes latency, so the same source retargets any
FPGA (the vendor-portable alternative to a Xilinx FIR Compiler / Intel FIR II
IP instance).

Elaborate + estimate combinational timing:
    python3 src/pipelinec examples/pypeline/dsp/fm_radio_decim.py --comb
Full autopipelining throughput sweep to the 125 MHz goal:
    python3 src/pipelinec examples/pypeline/dsp/fm_radio_decim.py

For a simulation testbench with plots, see fir_decim_tb.py next to this file
(same filter, driven by dsp/fir_tb.py's @sim_input/@sim_output machinery).
"""

from pypeline import MAIN, uint1_t

import board.arty.part100t  # sets PART for the Arty A7-100T; swap for other boards

from fixed_point import make_fixed_t
from dsp.fir_decim import make_fir_decim

# fmt: off
# Identical values to examples/sdr/fm_radio.h decim_5x FIR_DECIM_COEFFS.
DECIM_5X_COEFFS_Q15 = [
    -165, -284, -219, -303, -190, -102, 98, 268, 430, 482, 420, 207,
    -117, -498, -835, -1022, -957, -576, 135, 1122, 2272, 3429, 4419,
    5086, 5321, 5086, 4419, 3429, 2272, 1122, 135, -576, -957, -1022,
    -835, -498, -117, 207, 420, 482, 430, 268, 98, -102, -190, -303,
    -219, -284, -165,
]
# fmt: on

data_t = make_fixed_t(1, 15)  # int16 Q1.15 I/Q samples
coeff_t = make_fixed_t(1, 15)

# Separate instance per rail (each has its own sample window state).
# truncate/wrap matches the old library's `accum >> 15` output stage exactly.
i_decim_5x, i_decim_5x_t = make_fir_decim(
    DECIM_5X_COEFFS_Q15,
    coeff_t,
    5,
    data_t,
    out_t=data_t,
    rounding="truncate",
    overflow="wrap",
)
q_decim_5x, q_decim_5x_t = make_fir_decim(
    DECIM_5X_COEFFS_Q15,
    coeff_t,
    5,
    data_t,
    out_t=data_t,
    rounding="truncate",
    overflow="wrap",
)


@MAIN(125.0)
def i_chan(
    stream_in_if: i_decim_5x.in_fwd_t, stream_out_if: i_decim_5x.out_fb_t
) -> i_decim_5x_t:
    return i_decim_5x(stream_in_if, stream_out_if)


@MAIN(125.0)
def q_chan(
    stream_in_if: q_decim_5x.in_fwd_t, stream_out_if: q_decim_5x.out_fb_t
) -> q_decim_5x_t:
    return q_decim_5x(stream_in_if, stream_out_if)
