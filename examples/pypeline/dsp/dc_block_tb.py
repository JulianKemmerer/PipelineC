# pyright: reportInvalidTypeForm=none
"""DC blocker example + testbench.

A sine wave riding on a large DC pedestal: the settled output mean should be
near zero while the input mean is large -- the "DC Blocking / Removal" stage
of examples/pypeline/dsp/pdw/README.md, Path A: Detect & Measure.

Two @MAIN entry points exercise both handshake modes in one run: an elastic
instance under random consumer backpressure, and a valid_only (free-running)
instance.

Run the simulation:
    pypelinec examples/pypeline/dsp/dc_block_tb.py --sim --comb --run 4000
"""

from pypeline import MAIN

from fixed_point import make_fixed_t
from dsp.dc_block import make_dc_block
from dsp.dsp_tb import golden_dc_block, make_block_tb, quantize_samples, sine

data_t = make_fixed_t(1, 15)  # Q1.15
K = 6  # short time constant (~64 samples) so the sim settles quickly
PEDESTAL = 0.5  # large DC offset relative to the 0.2-amplitude sine

N = 1200
STIM = quantize_samples(
    [PEDESTAL + s for s in sine(N, cycles=15, amplitude=0.2)], data_t
)
# Settling window: skip the first ~8 time constants before judging the mean.
SETTLE = 8 * (1 << K)


def _check_dc_removed(state):
    hist = state["out_hist"]
    settled = hist[SETTLE:]
    scale = 1 << data_t.frac_bits
    in_mean = PEDESTAL
    out_mean = (sum(settled) / len(settled)) / scale
    assert abs(out_mean) < 0.02, (
        f"DC not removed: input pedestal {in_mean}, settled output mean {out_mean}"
    )
    print(f"dc_block: input pedestal {in_mean}, settled output mean {out_mean:.5f}")


dcb_e, dcb_e_t = make_dc_block(data_t, k=K, out_t=data_t, overflow="saturate")
expected_e = golden_dc_block(dcb_e, STIM)
tb_e = make_block_tb(
    dcb_e,
    STIM,
    expected_e,
    name="dc_block_elastic",
    ready_pattern="random",
    on_done=_check_dc_removed,
)


@MAIN(125.0)
def dc_block_elastic_tb():
    stream_in = tb_e.drive_in()
    out_ready = tb_e.drive_ready()
    o = dcb_e(stream_in, out_ready)
    tb_e.observe(o)


dcb_v, dcb_v_t = make_dc_block(
    data_t, k=K, out_t=data_t, overflow="saturate", handshake="valid_only"
)
expected_v = golden_dc_block(dcb_v, STIM)
tb_v = make_block_tb(dcb_v, STIM, expected_v, name="dc_block_valid_only")


@MAIN(125.0)
def dc_block_valid_only_tb():
    stream_in = tb_v.drive_in()
    o = dcb_v(stream_in)
    tb_v.observe(o)
