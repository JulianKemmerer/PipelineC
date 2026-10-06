# Pypeline DSP Library: Filters & Signal Conditioning

The library source lives in `include/pypeline/dsp/` (same directory as this guide).
Example designs that exercise it live in `examples/pypeline/dsp/`.

`include/pypeline/dsp/` is a vendor-neutral FIR filter library in the spirit of the
AMD/Xilinx FIR Compiler and Intel/Altera FIR II IP wizards, built on the
[fixed-point types](../../../docs/pypeline_guide.md#fixed-point-types) and
[`make_stream_auto_pipeline`](../../../docs/pypeline_guide.md#pipelined-stream-wrappers-make_stream_auto_pipeline).
Every filter is a **single feedforward combinational blob** — symmetric pre-adders,
constant multiplies, a balanced adder tree, and the output rounding stage — that
PypelineC auto-pipelines to whatever depth the target FPGA/fmax needs, wrapped in a
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
def top(stream_in_if: fir.in_fwd_t, stream_out_if: fir.out_fb_t) -> fir_t:
    return fir(stream_in_if, stream_out_if)
```

`fir_t` has the same `.stream_out_if` / `.stream_in_if` port fields as
`make_stream_auto_pipeline`, so filters chain like any stream pipeline instance. Remaining
parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `gain` | `1` | Scales the float taps **before** quantization — zero hardware cost (needs `coeff_t` headroom) |
| `symmetry` | `"auto"` | Detects symmetric/anti-symmetric **quantized** taps and folds them into pre-adders, halving the multipliers (like the vendor cores); `"none"` disables |
| `skip_zero_taps` | `True` | Zero-coefficient taps are dropped at elaboration time — a half-band filter costs ~half the multipliers automatically |
| `handshake` | `"elastic"` | `"elastic"` = valid/ready with an output FIFO and in-flight counter, one sample per cycle while downstream is ready (FIFO sized automatically from the AUTO_PIPELINE'd core's tool-discovered `.latency`, see [Pipelined Stream Wrappers](../../../docs/pypeline_guide.md#pipelined-stream-wrappers-make_stream_auto_pipeline)); `"valid_only"` = vendor-style free-running stream (no FIFO — downstream must always accept) |
| `latency` / `start_latency` / `max_latency` (keyword-only) | `None` | Passed to the core [`AUTO_PIPELINE`](../../../docs/pypeline_guide.md#auto_pipeline) in both handshake modes. They count core registers only, excluding the I/O boundary registers. `start_latency=S` seeds the throughput sweep, e.g. from a previously confirmed depth. A matching seed skips the pin-and-confirm pass, and timing failures still grow the core. `max_latency` caps it, and `latency` fixes it. Every other factory below (`make_fir_decim`, `make_fir_interp`, `make_dc_block`, `make_moving_avg`, `make_magnitude`) accepts the same three |

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

stream_in: Input[tb.in_t]  # the filter's plain input stream type
out_ready: Input[uint1_t]

@MAIN
def my_fir_tb():
    stream_in = tb.drive_in()     # holds each sample until the filter accepts it
    out_ready = tb.drive_ready()  # "always" | "random" stalls | callable(cycle)
    o = fir(fir.in_fwd_t(stream=stream_in), fir.out_fb_t(out_ready))
    tb.observe(o)                 # checks against the exact golden model
```

The driver values go into module-level `Input[T]` wires, not locals: a `@sim_input`
result stored in a local is an error, since its value exists only in simulation. That
keeps the testbench top elaborable to HDL (the wires become ports), which a pipelined
(non-`--comb`) `--sim` run needs. An elastic filter's `.fwd_t`/`.fb_t` port halves
are built inline at the call; a `valid_only` filter takes `stream_in` directly.

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

One pure feedforward blob (two squares, an add, a fused output resize) auto-pipelined
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
output resize is auto-pipelined, not the whole block.

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
not BRAM, so a large `n` × wide `data_t` costs flops accordingly. A block-RAM delay line
built on [`make_ram`](../../../docs/pypeline_guide.md#rams-make_ram--make_stream_ram) is a
roadmap item below.

## `make_cordic_atan2` / `make_cordic_rotate` — angles without a multiplier or a ROM

```python
from pypeline import make_int_t
from dsp.cordic import make_cordic_atan2, make_cordic_rotate

atan2, atan2_t = make_cordic_atan2(make_int_t(39), n_iters=14, work_bits=26)
nco,   nco_t   = make_cordic_rotate(int16_t, n_iters=16, work_bits=24, phase_bits=32)
```

One shift-and-add iteration per pipeline stage: no multiplier, no lookup table, and
no ROM. Both modes share the same iteration hardware and the same `atan(2^-i)` angle
table, which is elaboration-time constant.

Which mode needs this and which does not is not symmetric. **Rotation mode now has a
cheaper alternative**: [`make_lut_nco`](#make_lut_nco--an-nco-from-a-sine-rom) does the
same job from a [`make_ram`](../../../docs/pypeline_guide.md#rams-make_ram--make_stream_ram)
sine ROM and one multiplier per rail, and is the better choice wherever a block RAM is
available. **Vectoring mode has no such shortcut**: a table `atan2` has to divide `y`
by `x` before it can look anything up, so the CORDIC stays the right shape for it.

* **Vectoring mode** (`make_cordic_atan2`) drives the *y* rail to zero, so the
  accumulated angle is `atan2(y, x)`:
  `cordic_atan2(x_in, y_in, valid_in) -> {.angle, .valid, .degenerate}`.
  `x`/`y` are treated as a ratio, so the block is scale invariant.
* **Rotation mode** (`make_cordic_rotate`) drives the *angle* rail to zero, rotating a
  `(amplitude, 0)` seed:
  `cordic_rotate(phase, amplitude, valid_in) -> {.i, .q, .valid}` — an NCO.
  `phase` is unsigned `phase_bits` wide and wraps naturally, so a free-running
  accumulator is the whole frequency control.

| Parameter | Default | Meaning |
|---|---|---|
| `n_iters` | 14 / 16 | Iterations. Angle error is ~`2^-n_iters` turns |
| `work_bits` | 26 / 24 | Internal rail width; must leave ~2 bits for the K ≈ 1.647 gain growth |
| `phase_bits` | 32 (rotate) | Width of the phase input, i.e. turns × 2^`phase_bits` |

**Angles are carried in turns, not radians** — `int16_t` spanning ±½ turn, one LSB =
1/65536 turn. Converting to Hz is then a pure scale by the sample rate with no π
anywhere: `freq_hz = angle_turns * fs`.

Both are fully pipelined at `n_iters + 2` cycles — one result per cycle, no
handshake — and both publish `.latency`; read it rather than recomputing it.

Two properties are worth knowing because they are easy to lose:

* **The vectoring input is normalized (count-leading-zeros, then a barrel shift)
  before the iterations.** The `y >> i` shifts discard low bits, so an operand
  sitting low in a wide accumulator runs out of significant bits partway through.
  Normalizing first makes accuracy independent of signal strength — measured
  worst-case error stays flat at 3.4 × 10⁻⁵ turns from an input magnitude of 2³ to
  2³⁷. **Normalize after accumulating, never before**: an arithmetic right shift
  floors, so pre-scaling biases both rails by −0.5 LSB per term, which over N
  accumulated terms rotates the phasor by a signal-independent constant.
* **Rotation mode's gain compensation is a shift-add, not a multiply.** The seed is
  pre-divided by K ≈ 1.64676 using `1/2 + 1/8 - 1/64`, which is 0.35% high — a
  deterministic amplitude error a golden model reproduces exactly, not a distortion.

Tests: `src/tests/pypeline_tests/inst/cordic_test.py` (all four quadrants, both axes,
the `(0,0)` degenerate case, the ±½-turn boundary, pipeline throughput, and a second
instance at different widths, against both a bit-exact model and `math.atan2`).

## `make_lut_nco` — an NCO from a sine ROM

```python
from dsp.nco import make_lut_nco

nco, nco_t = make_lut_nco(int16_t, table_bits=10, phase_bits=32)
# nco(phase, amplitude, valid_in) -> {.i, .q, .valid}   amplitude*(cos, sin)(phase)
```

The same interface as `make_cordic_rotate`, from one `make_ram` ROM read on two ports
and one multiplier per rail. The ROM holds a quarter wave of sine sampled at the
**centre** of each of its `2^table_bits` phase bins, which is what makes the mirror
for the other quadrants a plain bitwise NOT of the index and makes the phase
truncation round rather than floor. The top two phase bits pick the quadrant and the
signs are applied to the amplitude before the multiply.

* **Latency 5**, fully pipelined: the ROM's input register, block-RAM read and output
  register, the multiply, and a round/saturate output register.
* **Measured cost.** Swapped in for a 16-iteration `make_cordic_rotate`, it took
  the PDW example's generator from 2,742 LUTs and 1,373 flip-flops to 520 LUTs and
  345 flip-flops, plus one RAMB18 and two DSP48s, on xc7a100t. Its fmax went from
  133.3 MHz to 141.5 MHz.
* **Amplitude is exact** to a rounding step — there is no CORDIC gain to compensate.
* **Phase truncation produces spurs, not bias.** Measured SFDR is 72 dBc at the
  default 10 table bits, about 6 dB per bit. A phasor-difference frequency estimator
  is not biased by it: the truncation error telescopes over the block it sums, to
  under one LSB of a 16-bit turns result (measured 1.0 × 10⁻⁵ turn, including output
  rounding).

Tests: `src/tests/pypeline_tests/inst/lut_nco_test.py` (bit-exact against
`golden_lut_nco`, the model against `math.cos`/`math.sin` over every phase bin at two
table sizes, the four axis crossings, constant envelope and zero mean over a full
circle, saturation at amplitude −32768, measured SFDR, and frequency-estimate bias).

## `make_log2_db` — linear power to dBFS

```python
from dsp.log2_db import make_log2_db

log_db, log_db_t = make_log2_db(power_t)                  # method="rom", the default
log_pwl, log_pwl_t = make_log2_db(power_t, method="pwl")  # no ROM
# log_db(v: power_t, valid_in: uint1_t) -> {.db (int16_t Q8.8), .valid, .floored}
```

Count-leading-zeros gives the exponent `e`; the mantissa `m` is the bits below the
leading one; `dB = 3.0103 · ((e − frac_bits) + log₂(1+m))`. Two interchangeable
implementations, both with `.latency` 4:

| `method=` | Exponent term | Mantissa term | Worst-case error |
|---|---|---|---|
| `"rom"` (default) | a table indexed by the leading-zero count | a 2^`mant_bits` table (default 10 bits: one RAMB18) | **0.008 dB** |
| `"pwl"` | × 771 by a shift-add tree | chords over 2^`seg_bits` segments: one small multiply | 0.046 dB |

Errors are measured over 300k random inputs against `10·log10`. In the ROM method every
table entry is the exact value rounded once at elaboration time, so there is no
multiplier and no approximation beyond that rounding and the mantissa truncation. Its
mantissa table is sampled at each bin's left edge, so exact powers of two convert
exactly. The PWL method's error is almost all its chords and 8-bit mantissa (0.0455 dB
even with an exact constant in place of 771); use it where a ROM is unwanted. Output
is signed **Q8.8** dB (1 LSB = 1/256 dB), saturated at both ends.

> **The input's fractional bits are subtracted, and they must be.** `in_t` is a
> `fixed_t`, so the integer the hardware holds is `2^frac_bits` times the value it
> represents. The block computes `(e - in_t.frac_bits) * K + correction`, not
> `e * K`. Taking dB of the raw integer instead both reports the wrong number and
> overflows the output — for a 12-fraction-bit power type the raw range reaches
> 135.5 dB, past Q8.8's +128, while the true represented range is −36.1 … +99.4 dB
> and fits comfortably.

Tests: `src/tests/pypeline_tests/inst/log2_db_test.py` (both methods through every
check: accuracy vs `10·log10` in hardware and over 300k inputs in the model, each
against its own budget; the two methods against each other; decade/octave steps, the
fractional-bits subtraction, non-positive input, monotonicity including every octave
boundary, and two instances with different binary points).

## `dsp/dsp_tb.py` — testbench library for magnitude/dc_block/moving_avg

Same `@sim_input`/`@sim_output` shape as `dsp/fir_tb.py`, re-exporting its signal
generators and `golden_resize` so a testbench needs one import line:

```python
from dsp.dsp_tb import make_block_tb, golden_magnitude, quantize_samples, sine

expected = golden_magnitude(magnitude, iq_pairs)   # or golden_dc_block / golden_moving_avg
tb = make_block_tb(magnitude, iq_pairs, expected, name="my_magnitude")

stream_in: Input[tb.in_t]
out_ready: Input[uint1_t]

@MAIN
def my_magnitude_tb():
    stream_in = tb.drive_in()
    out_ready = tb.drive_ready()
    o = magnitude(magnitude.in_fwd_t(stream=stream_in), magnitude.out_fb_t(out_ready))
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
above alongside each block. Every one of them is registered as a test
(`src/tests/pypeline_tests/native_sim_tests.py`, `synth_tests.py`: the PDW synth tops
and `fm_radio_decim.py` under `synth_vivado`) so a documented
example cannot rot unnoticed; the library's own unit tests are the `inst/` files named
under each block above.

`examples/pypeline/dsp/pdw/` (pulse-descriptor-word detector) is a larger worked
example — a whole SDR design rather than one block — with its own
[README](../../../examples/pypeline/dsp/pdw/README.md). It is the biggest consumer of
this library: `make_magnitude` → `make_dc_block` → `make_moving_avg` in `valid_only`
mode form its detector's front end, `make_cordic_atan2` and `make_log2_db` are there
because its measurement engine needed them, and `make_lut_nco` is its stimulus
generator's carrier.

## Roadmap (not yet implemented)

Discussed in [#348](https://github.com/JulianKemmerer/PipelineC/discussions/348).

- Polyphase interpolation/decimation.
- Resource-folded II>1 "slow" filters (time-shared MACs for fclk >> fs, port of
  `include/dsp/slow_fir.h`).
- Multichannel TDM.
- Runtime-reloadable coefficient banks (buildable on `make_ram`).
- A reciprocal-multiply path for non-power-of-two `make_moving_avg` window lengths.
- A BRAM-backed delay line for large `make_moving_avg` windows, on `make_ram`.
