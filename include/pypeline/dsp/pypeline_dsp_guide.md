# Pypeline DSP Library: Filters & Signal Conditioning

The library source lives in `include/pypeline/dsp/` (same directory as this guide).
Example designs that exercise it live in `examples/pypeline/dsp/`.

`include/pypeline/dsp/` is a vendor-neutral FIR filter library in the spirit of the
AMD/Xilinx FIR Compiler and Intel/Altera FIR II IP wizards, built on the
[fixed-point types](../../../docs/pypeline_guide.md#fixed-point-types) and
[`make_stream_pipeline`](../../../docs/pypeline_guide.md#pipelined-stream-wrappers-make_stream_pipeline).
Every filter is a **single feedforward combinational blob** — symmetric pre-adders,
constant multiplies, a balanced adder tree, and the output rounding stage — that
PypelineC AUTOPIPELINEs to whatever depth the target FPGA/fmax needs, wrapped in a
valid/ready stream. **Pipeline depth is never hard-coded**, so the same source retargets
any part instead of needing a per-vendor IP core.

## `make_fir` — single-rate filter

```python
from fixed_point import make_fixed_t
from dsp.fir import make_fir

data_t  = make_fixed_t(1, 15)   # Q1.15 samples
coeff_t = make_fixed_t(1, 15)   # Q1.15 coefficients

fir, fir_t = make_fir(
    [0.25, 0.5, 0.5, 0.25],     # float taps (quantized to coeff_t here) or raw ints
    coeff_t, data_t,
    out_t=data_t,               # None = full-precision accumulator output
    rounding="round_half_even", # truncate | round_half_up | round_half_even | round_half_away
    overflow="saturate",        # wrap | saturate
)

@MAIN(100.0)
def top(stream_in: fir.in_stream_t, stream_out: fir.out_fb_t) -> fir_t:
    return fir(stream_in, stream_out)
```

`fir_t` has the same `.stream_out` / `.stream_in` port fields as
`make_stream_pipeline`, so filters chain like any stream pipeline instance. Remaining
parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `gain` | `1` | Scales the float taps **before** quantization — zero hardware cost (needs `coeff_t` headroom) |
| `symmetry` | `"auto"` | Detects symmetric/anti-symmetric **quantized** taps and folds them into pre-adders, halving the multipliers (like the vendor cores); `"none"` disables |
| `skip_zero_taps` | `True` | Zero-coefficient taps are dropped at elaboration time — a half-band filter costs ~half the multipliers automatically |
| `handshake` | `"elastic"` | `"elastic"` = valid/ready with an output FIFO and in-flight counter (FIFO sized automatically from the AUTOPIPELINE'd core's tool-discovered `.latency`, see [Pipelined Stream Wrappers](../../../docs/pypeline_guide.md#pipelined-stream-wrappers-make_stream_pipeline)); `"valid_only"` = vendor-style free-running stream (no FIFO — downstream must always accept) |

Accumulator sizing is **exact**: interval arithmetic over the actual quantized
coefficient values and `data_t`'s range, so no intermediate can overflow and no bit is
wasted. The `rounding`/`overflow` output stage is a fused
[`make_fixed_resize`](../../../docs/pypeline_guide.md#resizing-rounding--saturation) — the vendor "output precision
control" feature.

## `make_fir_decim` / `make_fir_interp` — integer rate change

```python
from dsp.fir_decim import make_fir_decim
from dsp.fir_interp import make_fir_interp

decim5, decim5_t = make_fir_decim(taps, coeff_t, 5, data_t, out_t=data_t)
interp4, interp4_t = make_fir_interp(taps, coeff_t, 4, data_t, out_t=data_t)
```

Same interface and parameters as `make_fir`. `make_fir_decim` adds a phase counter in
front of the blob: every accepted sample advances the window, but only every
`decim`-th launches a computation (dropped phases never enter the pipeline), and the
output runs at 1/decim of the input rate. `make_fir_interp` puts a backpressured
zero-stuffer (1 input → `interp` beats: the sample then zeros) in front of a full-rate
filter; `gain=None` defaults to `interp` to compensate the stuffing energy loss, folded
into the taps for free. Output rate = `interp`× input rate — the filter's ready
naturally throttles the input. (Elastic only — a rate expander cannot run open-loop.)

## `dsp/fir_tb.py` — testbench library

Reusable `@sim_input`/`@sim_output` (see [Simulation](../../../docs/pypeline_guide.md#simulation))
testbench machinery for any filter the library produces (native sim only — run via
`pypelinec <file> --sim --comb --run N`):

```python
from dsp.fir_tb import make_fir_tb, quantize_samples, two_tone

stim = quantize_samples(two_tone(256, cycles_a=8, cycles_b=96), data_t)
tb = make_fir_tb(fir, stim, ready_pattern="random", name="my_fir", plot=True)

@MAIN
def my_fir_tb():
    stream_in = tb.drive_in()     # holds each sample until the filter accepts it
    out_ready = tb.drive_ready()  # "always" | "random" stalls | callable(cycle)
    o = fir(stream_in, out_ready)
    tb.observe(o)                 # checks against the exact golden model
```

Signal generators (`impulse`/`step`/`sine`/`two_tone`/`chirp`/`white_noise`), an exact
integer golden model (`golden_fir` — convolution plus a bit-exact mirror of
`make_fixed_resize`, so checks are `==` on raw ints, never float tolerance), and
optional matplotlib plots (`plot=True` writes `<name>_tb.png`: input, quantized-tap
frequency response, golden-vs-hardware output overlay; `PYPELINE_TB_SHOW=1` opens a
window). The checker prints `ERROR: ...` on mismatch and `<name>: ... Test DONE!` on
completion, and asserts if the run hasn't finished by `tb.deadline` cycles — pass
`--run` greater than `tb.min_cycles`.

Worked examples in `examples/pypeline/dsp/`: `fir_lowpass_tb.py` (31-tap windowed-sinc
+ two-tone), `fir_decim_tb.py` (the SDR FM radio's 49-tap 5× decimator, raw Q1.15
ints), `fir_interp_tb.py` (4× interpolation of a sine), and `fm_radio_decim.py` (a
synthesizable I/Q 5× decimator pair at 125 MHz — the pypeline port of
`examples/sdr/fm_radio.c`'s front end). Tests:
`src/tests/pypeline_tests/inst/fir_test.py`, `fir_decim_test.py`, `fir_interp_test.py`,
`fir_sim_tb_test.py`.

## `make_magnitude` — complex-sample power (I²+Q²)

```python
from fixed_point import make_fixed_t
from dsp.magnitude import make_magnitude

data_t = make_fixed_t(16, 0)   # int16_t I/Q rails
magnitude, magnitude_t = make_magnitude(data_t)   # out_t=None: full-precision uint32_t power

@MAIN(125.0)
def top(stream_in_if: magnitude.in_fwd_t, stream_out_if: magnitude.out_fb_t) -> magnitude_t:
    return magnitude(stream_in_if, stream_out_if)
```

One pure feedforward blob (two squares, an add, a fused output resize) autopipelined
and wrapped in a stream, the same shape as `make_fir`'s core. `make_complex_t(data_t)`
(a plain `{i, q}` struct) is `magnitude`'s input type, exposed as `.complex_t`/
`.in_data_t`. `out_t=None` gives the exact, lossless power type — for
`make_fixed_t(16, 0)` (`int16_t`) that comes out as `make_fixed_t(32, 0, signed=False)`
(`uint32_t`), the format an RF pulse detector's threshold comparisons run in.
`rounding`/`overflow`/`handshake` mean exactly what they do for `make_fir`.

## `make_dc_block` — leaky-integrator DC removal

```python
from dsp.dc_block import make_dc_block

dc_block, dc_block_t = make_dc_block(data_t, k=10, out_t=data_t, overflow="saturate")
```

```
y[n] = x[n] - mean[n]
mean[n] = mean[n-1] + (x_ext[n] - mean[n-1]) >> k
```

A one-pole highpass: subtract a running leaky-integrator estimate of the signal's DC
level. `mean` is carried with `k` **extra fractional bits** beyond `data_t` — the
standard trick that lets the `>> k` update step keep producing a real (if small)
increment every cycle instead of sticking at 0 once `|x - mean|` drops below one
`data_t` LSB (the classic integer-leaky-integrator dead-zone/limit-cycle). Passband is
flat, unlike the classic `y = x - x_prev + R*y_prev` pole/zero blocker (~2× gain at
Nyquist). `k` sets the pole at `1 - 2^-k`, i.e. a settling time constant of roughly
`2^k` samples. `.mean_t`/`.diff_t`/`.k` are exposed as metadata; the running mean is
itself a useful noise-floor estimate. The mean-update recursion is an inherent IIR
loop, so — unlike `make_fir`/`make_magnitude`/`make_moving_avg` — only the feedforward
output resize is autopipelined, not the whole block.

## `make_moving_avg` — boxcar smoother

```python
from dsp.moving_avg import make_moving_avg

moving_avg, moving_avg_t = make_moving_avg(data_t, 16, out_t=data_t, overflow="saturate")
```

Average of the last `n` samples (window includes the current sample, matching
`golden_fir`'s convention), kept as a running sum — O(1) adders instead of the O(n) an
equivalent all-ones `make_fir` would cost, with no rounding drift (the sum is exact
integer arithmetic). `normalize=True` (default) divides by `n` for free: since `n` is a
power of two, the divide is just a binary-point relabelling (`log2(n)` extra
fractional bits) fused into the same output resize stage every other `dsp/` block
uses — non-power-of-two `n` needs a real reciprocal multiply and isn't implemented
(pass `normalize=False` for the raw running-sum boxcar instead, any `n`). `.n`/
`.normalize`/`.sum_t`/`.avg_t` are exposed as metadata. The delay line is registers,
not BRAM (no RAM primitive in this codebase yet — the same limitation blocking the FIR
library's coefficient-bank roadmap item above), so a large `n` × wide `data_t` costs
flops accordingly.

## `dsp/dsp_tb.py` — testbench library for magnitude/dc_block/moving_avg

Same `@sim_input`/`@sim_output` shape as `dsp/fir_tb.py`, re-exporting its signal
generators and `golden_resize` so a testbench needs one import line:

```python
from dsp.dsp_tb import make_block_tb, golden_magnitude, quantize_samples, sine

expected = golden_magnitude(magnitude, iq_pairs)   # or golden_dc_block / golden_moving_avg
tb = make_block_tb(magnitude, iq_pairs, expected, name="my_magnitude")

@MAIN
def my_magnitude_tb():
    stream_in = tb.drive_in()
    out_ready = tb.drive_ready()
    o = magnitude(stream_in, out_ready)
    tb.observe(o)
```

`golden_magnitude`/`golden_dc_block`/`golden_moving_avg` are exact integer golden
models (bit-exact `golden_resize` mirror, same convention as `golden_fir`).
`make_block_tb` handles both `handshake` modes off the block's own metadata, and takes
`in_value`/`out_value` callables for blocks whose port data isn't a bare
`data_t(val=raw)` (e.g. magnitude's `complex_t(i=..., q=...)`), plus an optional
`on_done(state)` hook for a behavioural check beyond exact golden matching (worked
examples in `examples/pypeline/dsp/`: `magnitude_tb.py` checks a pulse's power
envelope is visible, `dc_block_tb.py` checks the settled output mean, `moving_avg_tb.py`
checks noise variance reduction). Tests:
`src/tests/pypeline_tests/inst/magnitude_test.py`, `dc_block_test.py`,
`moving_avg_test.py`.

## Worked examples

`examples/pypeline/dsp/` contains synthesizable designs and testbenches exercising this
library: `fm_radio_decim.py` (a synthesizable I/Q 5× decimator pair at 125 MHz — the
pypeline port of `examples/sdr/fm_radio.c`'s front end) and the `*_tb.py` files listed
above alongside each block. `examples/pypeline/dsp/pdw/` (pulse-descriptor-word
detector) is a larger worked example with its own
[README](../../../examples/pypeline/dsp/pdw/README.md) — see that file directly rather
than duplicating it here.

## Roadmap (not yet implemented)

- Polyphase interpolation/decimation.
- Resource-folded II>1 "slow" filters (time-shared MACs for fclk >> fs, port of
  `include/dsp/slow_fir.h`).
- Multichannel TDM.
- Runtime-reloadable coefficient banks (blocked on a RAM/ROM primitive).
- A reciprocal-multiply path for non-power-of-two `make_moving_avg` window lengths.
- A BRAM-backed delay line for large `make_moving_avg` windows.
