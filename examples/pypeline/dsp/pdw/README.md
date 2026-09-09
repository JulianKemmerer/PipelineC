# PDW: an FPGA pulse-descriptor-word detector

A closed-loop RF pulse detector and DRFM repeater, written in Pypeline HDL. It
ingests raw I/Q at 125 MSPS, detects pulses in real time, rejects glitches and
CW, measures each surviving pulse, and emits both the **Pulse Descriptor Word**
(the metadata) and a bit-perfect replay of the waveform it describes.

The block names follow [gr-pdw](https://github.com/gtri/gr-pdw), GTRI's GNU
Radio module for the same job, so its documentation reads across:
`pulse_detect` identifies pulse start/stop, `pulse_extract` obtains the pulse's
I/Q and computes its characteristics, and `gr_pdw_record.py` produces gr-pdw's
own nine-column record.

**Target and part.** The deployment target is a Deepwave AIR-T (AIR7310); the
in-repo synthesis checks build against `xc7a100tcsg324-1` (Artix-7 100T) as a
timing proxy, since that is the part this repo can run end to end. Every fmax
number below is that part at the 125 MHz system clock.

```
 1. STIMULUS & EXTERNAL LOOPBACK
  +-----------------+     TX0 stream     +------------+      External cable
  | pulse_gen       | =================> | TX0 RF out | ===+   to scope & RX
  +-----------------+                    +------------+    |
        (or the internal loopback mux,                     |
         CTRL_FLAG_LOOPBACK_EN)          +------------+    |
                                    +==> | RX0 RF in  | <==+
                                    |    +------------+
 2. pulse_detect (125 MSPS I/Q)     |
 -----------------------------------+
                                    v
 +-------------------------------------------------------------------------+
 |   PATH A: DETECT & MEASURE            PATH B: DELAY LINE                 |
 |   1. magnitude (I^2+Q^2)              Holds the raw I/Q until Path A's   |
 |   2. dc_block -> moving_avg           verdict on it is ready. Self-      |
 |   3. hysteresis SM (high/low)         timed off the SM's gate_advance,   |
 |   4. emit candidate_pdw_t             so no latency constant exists      |
 |   5. phasor accumulate (freq) +       anywhere. Each gate beat carries   |
 |      noise-floor track, on the        exactly the raw sample whose       |
 |      TIME-ALIGNED raw I/Q             power produced it.                 |
 +-------------------------------------------------------------------------+
        | candidate_pdw_t       | gate stream (data+valid+last)
        v                       v
 +-------------------------------------------------------------------------+
 | 3. pulse_extract                                                         |
 |    Store:    every gate beat into the data FIFO, one descriptor per      |
 |              completed pulse into the descriptor FIFO                    |
 |    Qualify:  glitch (width < min_width), CW (width >= max_width)         |
 |    Measure:  pulse_measure, once per pulse, ~16 cycles pipelined --      |
 |              CORDIC atan2 for frequency, log2->dB, PRI                   |
 |    Release:  accepted -> emit valid_pdw_t, then the packet               |
 |              rejected -> drop the record, flush the beats                |
 +-------------------------------------------------------------------------+
        | valid_pdw_t                          | released packet (w/ tlast)
        v                                      v
   rx1_m_axis                        rx0_m_axis (host DMA) + tx1_m_axis (replay)
```

## Architecture

**1. Stimulus.** `pulse_gen` synthesizes RF pulses with a real carrier (a
rotation-mode CORDIC NCO), an optional LFM chirp and an optional LFSR noise
source, all deterministic so golden models stay bit-exact. It drives TX0 for a
physical loopback cable, and `CTRL_FLAG_LOOPBACK_EN` shortcuts the same samples
straight into the detector.

The carrier is not decoration: a flat DC step with `Q = 0` is a signal at
exactly 0 Hz, against which an estimator with an inverted sign, a broken quadrant
fix, or one returning a constant zero all agree with the right answer. The chirp
control matters for the same reason one level up — with a pure tone `freq_start`
and `freq_stop` are bit-identical, so a wrong stop-frequency implementation still
passes.

**2. `pulse_detect` — Path A and Path B.** Path A computes instantaneous power,
conditions it (`dc_block` then `moving_avg`), and runs a hysteresis state
machine that emits a `candidate_pdw_t` — an unvalidated guess carrying start
time, width and peak power — when a pulse ends. It also accumulates, on the
*time-aligned* raw I/Q, the phasor sums the frequency measurement is built from,
and tracks the noise floor between pulses.

Path B carries the untouched raw I/Q through a delay line so the samples arrive
in step with Path A's verdict on them. The delay is **self-timed, not
fixed-depth**: the line pushes on every valid input sample and drains on the SM's
`gate_advance` — built as the *structural twin* of the SM's own `gate_valid`
register chain (the same two `if accepted:`-gated registers, with `in_pulse`
replaced by a constant 1). A FWFT FIFO held un-drained loads its output register
once and then freezes, so the queue behind it grows one entry per push, and the
achieved delay is exactly the number of pushes before the first drain. Since
draining begins on the first cycle a gate beat could exist, **the delay lands on
the DSP chain's real latency automatically, for any DSP latency, with no cycle
count written down anywhere.** `delay_depth` (64) is capacity only; over-sizing
it is free, and `make_delay_line` `sim_assert`s if it is ever too small.
`pdw_tb.py`'s golden model indexes `raw[s - gate_latency]` against
`pulse_detect.get_path_b_delay()`, and perturbing its `raw_idx` by ±1 fails.

**3. `pulse_extract` — qualify, measure, release.** Gate beats go into a data
FIFO; one descriptor per completed pulse goes into a descriptor FIFO. The read
side pops a descriptor and moves exactly `pkt_samples` beats — downstream if
accepted, into the bit bucket if not. That is observably identical to a rollback,
at the cost of spending read bandwidth to discard, and it is what the library
makes available: `make_fifo` exposes push and pop only (see
[the guide's FIFO section](../../../../docs/pypeline_guide.md#fifos-make_stream_fifo)).
Discarding is affordable because a glitch is shorter than `min_width` by
definition, and a CW event parks the SM in RECOVER — emitting no beats at all —
while its `max_width` beats drain.

The count stored in the descriptor is the number of beats **actually pushed**,
not the candidate's `pulse_width`, which is what makes the read side robust to a
full FIFO: the flush count still matches what is really buffered, so one corrupt
packet cannot desynchronize every packet after it.

**Qualification rules as built** (`make_pdw_qualify`):

* **Glitch rejection** is `pulse_width < min_width`.
* **CW rejection** is `pulse_width >= max_width`, not `>`. The hysteresis SM
  force-terminates a runaway pulse the moment its width *reaches* `max_width`
  and emits exactly one candidate of that width, so `== max_width` **is** the CW
  marker and a strict `>` would never fire.
* Consequence worth stating plainly: **`max_width` is a detection limit, not
  just a rejection threshold.** A genuine pulse longer than `max_width` is
  reported as CW and discarded, indistinguishably from a jammer.

`n_pre_margin`/`n_post_margin` are **not implemented**: the packet is exactly the
detected pulse's gate window, so `pkt_samples == pulse_width` for every accepted
pulse. Adding them needs Path B's delay line deepened by `N_pre` and the gate
held open `N_post` beats past `gate_last` — at which point `pkt_samples` stops
equalling `pulse_width`, which is why it is a separate field rather than a
derived one.

**4. Outputs.** On acceptance the engine emits a `valid_pdw_t` on its own
AXI-Stream master as one 40-byte frame, and releases the packet, `tlast`-framed,
**broadcast** to two masters at once: the host DMA and the TX replay port.

*On ordering.* Inside the engine the record is handed over in `EMIT_PDW` before
`SEND_PKT` begins, but on the wire the record's first beat lands **after** its
packet's — it goes through a serializer whose first beat costs a fill cycle the
packet path does not pay, plus a skid buffer's registered stage. The two then
stream concurrently on separate ports. What holds, and what `pdw_tb.py` asserts,
is that record *k* begins before packet *k+1* does, so a record never slips into
the next pulse's slot. **A consumer needing `pkt_samples` before the payload must
buffer or use `tlast`, not assume the metadata stream leads.**

## Streams and stream interfaces: where backpressure begins

The design is deliberately in two halves, and knowing which half a signal is in
tells you what happens when something goes wrong. For what `_if`, `.fwd_t`,
`.fb_t` and `make_stream_t` mean, see
[the language guide](../../../../docs/pypeline_guide.md#the-stream-interface-validready-handshaking);
this section is only about where the line falls in *this* design.

```
   VALID-ONLY (data + valid, real-time, cannot stall)
   rx0_s_axis --> loopback mux --> pulse_detect ----------+--> gate stream
                                   magnitude                   candidate stream
                                   dc_block                    freq_acc / noise_est
                                   moving_avg                          |
                                   hysteresis SM                       v
                                   delay line              pulse_extract write side
   ==========================================================================
                          THE OVERFLOW POINT: the three FIFOs
   ==========================================================================
   ELASTIC (data + valid + ready)
   pulse_extract read side --> pkt_out_if --> broadcast --> rx0_m_axis
                                                       \-> tx1_m_axis
                           --> pdw_out_if --> serializer --> skid --> rx1_m_axis
   pulse_detect.pdw_out_if --> serializer --> skid --> rx2_m_axis
```

**The valid-only side has no `ready` anywhere and nothing can stop it.** Every
name there is a plain `{data, valid}` (or `{data, valid, last}`) value —
`in_stream`, `gated_out`, `freq_acc` — and none of them ends in `_if`.
`rx0_s_axis_tready` is a constant 1; an ADC cannot be back-pressured.

**The elastic side is real valid/ready.** Those ports are declared as stream
interfaces, so their names end in `_if` and their types are `.fwd_t`/`.fb_t`
halves: `pkt_out_if`, `pdw_out_if`, `axis_in_if`. Ready propagates backwards
from the host and **stops at the store-and-forward FIFO**.

### What happens at the overflow point

This is the only place in the design where data can be lost, and none of the
three losses is reported in the record format:

| Full FIFO | What happens | Reaches a host? |
|---|---|---|
| **data** (16,384 beats) | Beats dropped. `status_flags` bit 2 set **and** the packet force-rejected (`accept & ~new_bad`) — its contents are no longer what the detector saw — so the record carrying the flag is flushed rather than emitted. `pkt_samples` still equals what was really pushed, so nothing after it desyncs. | **No.** Bit 2 is set correctly and only ever on records that are discarded; `pdw_tb.py` asserts a delivered record never carries it. Alarm only. |
| **descriptor** (16 pulses) | That pulse's beats stay in the data FIFO with no owner, so **every later packet is offset by them**, permanently. | **No.** Later records look perfectly well formed. Alarm only. |
| **measurement** (16 pulses) | The descriptor/measurement lockstep breaks, so **every later record carries the previous pulse's frequency, dB and PRI**. | **No.** Same. Alarm only. |

The guards on the last two are `sim_assert`s — which halt GHDL and compile to
nothing whatsoever in a bitstream. Both are reachable from a host that stalls:
`dwd_rx*_s_axis`'s `tready` is asserted only "as DMA reads occur", so the design
is back-pressured for exactly as long as the host spends between reads. All
three conditions are latched (`fifo_full`, `desc_drop`, `meas_drop`) and feed
the **internal-error alarm**, which is the only way a host ever learns of them.
`PKT_QUEUE_DEPTH` (16) and `PKT_FIFO_DEPTH` are exported to the host so
`airt_pdw_test.py` sizes its pulse rate against the real numbers.

### The two asymmetries

* **`rx2_m_axis` (candidates) has a real `tready` that does not reach Path A.**
  The serializer honours it and holds mid-frame, but Path A cannot stall, so a
  candidate offered while the serializer is busy is **dropped silently, with no
  status field**. A deployed system ties this port ready and ignores it;
  `pdw_tb.py` stalls it anyway so the path stays real rather than decorative.
* **`rx0_s_axis_tready` goes low on purpose, and only for the alarm.** See
  [The internal-error alarm](#the-internal-error-alarm).

# Top-Level Ports

Every top-level port is a flattened 32-bit AXI-Stream: `_tdata` (`uint32_t`),
`_tkeep` (4 bits), `_tlast`, `_tvalid`, `_tready`. Interface types live inside
the design; the boundary is plain `uintN_t`. I/Q packing everywhere is
`I = tdata[15:0]`, `Q = tdata[31:16]`.

| Port | Dir | Carries | Beats/frame |
|---|---|---|---|
| `rx0_s_axis_*` | slave in | ADC I/Q samples, one sample per beat | free-running |
| `tx0_s_axis_*` | slave in | `pdw_ctrl_t` control-register struct | 10 |
| `rx0_m_axis_*` | master out | released pulse packet (broadcast leg 0) | N samples |
| `rx1_m_axis_*` | master out | `valid_pdw_t` records | 10 |
| `rx2_m_axis_*` | master out | `candidate_rec_t` records (observability) | 4 |
| `tx0_m_axis_*` | master out | pulse generator stimulus | free-running |
| `tx1_m_axis_*` | master out | released pulse packet (broadcast leg 1, replay) | N samples |

**Signals present for uniformity but carrying no information**, each commented
at its declaration in `top.py`: `rx0_s_axis_tkeep` (a sample beat is always four
real bytes), `rx0_s_axis_tlast` (the ADC stream is continuous and unframed),
`tx0_m_axis_tkeep`/`_tlast` (constant `0xF`/`0`), `tx0_m_axis_tready` (a
fixed-rate DAC cannot back-pressure a fixed-rate generator), and
`rx0_m_axis_tkeep`/`tx1_m_axis_tkeep` (constant `0xF`).

> ⚠ **Tie `tx1_m_axis_tready` high if the replay port is unused.** The broadcast
> is a combinational valid/ready interlock that ANDs both legs' ready together,
> so a leg held low wedges the host capture port as well.

Every master's `tlast` is qualified by that master's own `tvalid`, which on the
two broadcast legs is not cosmetic — the interlock can present `eod = 1` with
`valid = 0` on a stalled leg. That is legal inside the library and illegal at a
top-level master; see
[the guide's AXI-Stream section](../../../../docs/pypeline_guide.md#axi-stream-axis_t).
`pdw_tb.py` asserts the stricter invariant on every port rather than trusting
the producer.

## Reset

Every channel carries an active-high `*_axis_rst` — seven in all. They OR into
one `global_rst`, one register stage behind the pins (`RST_LATENCY`, exported
from `top.py`). That register is a fanout break, not a metastability
synchroniser: these resets are synchronous to the design clock, but the reset
reaches the detector's input valid, a 320-bit control-register mux, three FIFO
read enables and a few dozen register clears — more than a seven-input OR of
pins should drive combinationally in a design with ~2 ns of margin.

> ⚠ **Tie an unused channel's reset LOW.** A channel whose reset a platform
> holds asserted because the host never opened it holds the *entire* design in
> reset forever. `rx2_m_axis` is the likeliest to be hit.

### Two domains, and the bring-up sequence they exist for

The control register file follows **`tx0_s_axis_rst` alone**, not the combined
reset. That is what makes a staged bring-up possible:

1. all seven resets asserted — everything held, buffers draining;
2. `tx0_s_axis_rst` deasserts — the register file is live, the datapath is not;
3. the host writes one `pdw_ctrl_t` frame — configuration lands;
4. the remaining six deassert — **the datapath starts already configured**.

Step 4 is the point. The detector's first sample is measured against real
thresholds rather than running on `CTRL_DEFAULTS` for however long a control
frame takes to arrive, so those defaults stop being the configuration a running
design starts from and become purely a power-on safety state. If the control
channel drops mid-session the datapath resets with it, which is the right
response given its configuration has just reverted to defaults.

### Block, drain, clear

**Block.** The generator's and the detector's input valids are gated. One gate
stops the whole detector: `pulse_detect` drives both paths from the same input
stream, and every piece of state behind it — the hysteresis SM, the noise
estimator, the phasor accumulators, `toa_counter` — advances only on an accepted
sample. All four master `tvalid`s (and their `tlast`s) are gated too, so no drain
traffic is ever visible outside.

**Drain.** While reset is asserted every FIFO read enable is forced and the
buffers empty into the bit bucket — not a convenience but the only mechanism
available, since `make_fifo` has no flush. Each block forces its own read enables
(`data_ready |= rst` and friends), so the packet path drains with no help from
the consumer: `pdw_reset_test.py` holds the packet port's ready low for the whole
reset window and still gets a byte-exact drain. Because the drain is only as fast
as the data, **reset must be held** — emptying a full packet FIFO takes its depth
in cycles, ~131 µs at 125 MHz, and `top.py` exports `RST_MIN_HOLD_CYCLES`
(16448). Any real platform reset exceeds it comfortably; a shorter one leaves
buffers partly full.

**The two record serializers** are the one part the read-enable trick cannot
reach: their `buf`/`fill` empty only through `tready`. Each therefore sits behind
a fully-registered AXIS skid buffer (`make_axis_skid_buffer`, `mode="full"`), so
reset can force that ready unconditionally. That slice is load-bearing: driving
the serializer's ready straight from `pin | rst` measured **−8.3 MHz** (128.5 →
120.2). See
[the guide](../../../../docs/pypeline_guide.md#skid-buffers-make_skid_buffer).

**Clear.** Every register in this project's own code returns to its power-on
value. Two pairings in that list are not optional:

* **`gate_armed` with the delay-line drain.** Path B's delay is
  self-establishing — however many pushes happen before the first drain, latched
  when the sticky `gate_armed` first sets. Drain the line without clearing
  `gate_armed` and the alignment is destroyed silently, with no symptom but wrong
  packet contents. `pdw_reset_test.py` has that as a negative control.
* **`prev_toa`/`have_prev` with `toa_counter`.** PRI is `toa - prev_toa`.
  Clearing the counter while leaving `prev_toa` holding a value from the previous
  epoch makes the first pulse after release report a wrapped, enormous PRI as
  though it were real. Cleared together, it reports `STATUS_PRI_INVALID`, exactly
  as the first pulse after power-on does.

Since `toa_counter` restarts, **TOA is not unique across a session**: two pulses
in different reset epochs can carry the same TOA. A host correlating pulses
across a channel reopen needs its own epoch counter.

### What reset does not reach

`magnitude`, `dc_block`, `moving_avg` and the CORDIC/`log2_db` pipelines are
library blocks in `include/pypeline/dsp/`, which this project does not put a
reset into. The pipelines are valid-gated and self-flush, but `dc_block`'s
running mean and `moving_avg`'s window are *frozen* by the input gate and thaw
still holding pre-reset power.

The visible consequence: for a sample or two after release the conditioned power
reads high and the SM declares a tiny pulse that never happened. `min_width` is
exactly the mechanism for it, so a deployment that sets `min_width` at all never
sees it — but one leaving it at 0 will see one spurious short PDW after each
mid-stream reset. `pdw_reset_test.py` measures the artifact (2 samples) and
asserts it stays below the `min_width` used there.

## Control registers (`pdw_ctrl_t`)

Written as one 40-byte frame on `tx0_s_axis_*` into a local register file with
power-on defaults (`pdw_ctrl.py`). Framing policy is exactly sized: a frame
**longer** than 40 bytes has its excess dropped, and a frame **shorter** is
discarded leaving the registers untouched — neither can desync the frames that
follow.

| Field | Type | Meaning |
|---|---|---|
| `pulse_gen_pri` | `uint32_t` | Generator PRI, in samples |
| `pulse_gen_width` | `uint32_t` | Generator pulse width, in samples |
| `pulse_gen_freq` | `int32_t` | Carrier phase increment/sample, turns × 2³². 0 is DC, 2³¹ is Fs/2, negative is a negative frequency |
| `pulse_gen_chirp_rate` | `int32_t` | Added to that increment each pulse sample (LFM) |
| `pulse_gen_amplitude` | `int16_t` | Peak I/Q amplitude |
| `pulse_gen_noise_amp` | `uint16_t` | LFSR noise scale; 0 disables |
| `threshold_high` | `uint32_t` | Hysteresis SM upper threshold — **scaled, see below** |
| `threshold_low` | `uint32_t` | Hysteresis SM lower threshold — **scaled, see below** |
| `max_width` | `uint32_t` | Path A force-close cap **and** CW rejection |
| `min_width` | `uint32_t` | Glitch rejection |
| `flags` | `uint32_t` | bit 0 = `CTRL_FLAG_LOOPBACK_EN`, 1 = `CTRL_FLAG_ALARM_EN`, 2 = `CTRL_FLAG_ALARM_TEST` |

> ⚠ **Thresholds carry 12 fractional bits: the integer on the wire is
> `power × 4096`.** They are compared against `pulse_detect.power_t` — the
> DC-blocked, moving-averaged power estimate — whose fractional bits are
> `dc_k`(10) + `log2(ma_n)`(2). Getting this wrong fails silently in both
> directions: 4096× too small is crossed by the noise floor and the detector
> declares one endless pulse; 4096× too large is never crossed and the device
> looks dead. Both present as "the hardware is broken". `top.py` exports
> `POWER_FRAC_BITS` straight from `power_t.frac_bits`, so the host derives the
> factor rather than copying it, and `--dry-run` prints thresholds in both raw
> and power units. The same scaling caps usable amplitude near **1024**
> (`MAX_AMPLITUDE`), since `threshold_high` and `peak_power` are both `uint32_t`
> holding `power × 4096`; `build_config` refuses anything larger rather than
> letting it wrap. `pdw_tb.py` derives its thresholds programmatically from the
> golden power model for exactly this reason.

Control is never back-pressured (`tx0_s_axis_tready` is always 1) and new values
are readable `pdw_ctrl.latency` cycles after a frame's last beat is accepted.
That number is measured by `pdw_ctrl_test.py` rather than asserted, and
`pdw_tb.py` reads the attribute rather than hardcoding it.

The defaults leave an unconfigured device **quiet and in a known state**, not
merely zeroed: amplitude 0 and `pri = 1` mean the generator emits zeros with its
PRI counter pinned at 0 (so it starts from a defined phase the instant a real PRI
is written), and the thresholds sit at their maximum so the hysteresis SM cannot
leave IDLE. Zero thresholds would instead declare one continuous pulse forever.

Reset for this block is `tx0_s_axis_rst` alone. While it is asserted the
registers are pinned to the defaults, so a frame arriving then is decoded and
discarded; the deserializer is flushed at the same time, so a host torn down
mid-frame cannot leave a byte prefix that joins up with the next frame into a
struct that is wrong but perfectly well formed.

# Record formats

**`candidate_pdw_t`** (internal) — `toa` (`uint64_t`), `pulse_width`
(`uint32_t`), `peak_power` (`power_t`).

**`candidate_rec_t`** (the port-facing form on `rx2_m_axis_*` — 16 bytes, four
beats) is the same three fields with `peak_power` truncated to `uint32_t`.
`candidate_pdw_t`'s own `peak_power` is the 46-bit `power_t`, which would make an
18-byte record with a ragged final beat; truncating is exactly what
`valid_pdw_t.peak_power` already does, so the two observability views of the same
pulse report the same number.

**`valid_pdw_t`** (to the host — 320 bits / 40 bytes, ten beats):

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | Time of arrival, in samples (~4,424 years to roll over) |
| `pulse_width` | `uint32_t` | Validated width, in samples |
| `peak_power` | `uint32_t` | Validated peak power, linear (`power_t` truncated) |
| `pkt_samples` | `uint32_t` | AXI-Stream payload size — tells DMA how many samples to slice. **Equals `pulse_width` today**; margins are unbuilt |
| `pri` | `uint32_t` | Samples since the previous **accepted** pulse |
| `peak_power_db` | `int16_t` | Peak power in dBFS, Q8.8 (1 LSB = 1/256 dB) |
| `noise_power_db` | `int16_t` | Noise floor in dBFS, Q8.8 |
| `freq_start` | `int16_t` | Frequency over the first samples, turns × 2¹⁶ — the full range spans ±½ turn, so multiply by the sample rate for Hz |
| `freq_stop` | `int16_t` | Frequency over the last samples. Differs from `freq_start` exactly when the pulse is modulated |
| `status_flags` | `uint32_t` | bit 0 = ADC clip, 1 = DSP overflow, 2 = packet FIFO full, 3 = frequency degenerate, 4 = PRI invalid |
| `channel` | `uint16_t` | RX chain index. Always 0 — single-channel design |
| `padding` | `uint16_t` | Reserved, aligns to 40 bytes |

There is deliberately **no SNR field**: it is `peak_power_db - noise_power_db`
and both are present, so the host subtracts. A hardware SNR would span ±135 dB
and not fit the Q8.8 the other two use. gr-pdw's own record likewise carries
pulse power and noise power as separate columns.

`status_flags` is accumulated per packet across all of its beats and re-armed on
each `last`. ADC clip is measured on the **stored** sample — the time-aligned raw
I/Q that actually goes into the packet — so the flag describes what the host
receives, not what the live ADC input was doing. Two bits do not mean what
per-packet framing suggests:

* **Bit 1, DSP overflow, is sticky until reset.** The SM's `overflow` register
  has no clear input, and `top.py` drives the detector in valid-only mode where
  that path is reachable. "Record 47 has `dsp_overflow`" means the detector
  overflowed at some point, not that pulse 47 did.
* **Bit 2, packet FIFO full, is unreachable in a delivered record** — see
  [What happens at the overflow point](#what-happens-at-the-overflow-point).

**`toa` as built.** A free-running counter inside the SM, latched on the
`IDLE -> PULSE` edge (read-before-increment, so it is the index of the same
sample that sets `pulse_width = 1`). It counts the SM's own *accepted input
samples* — the conditioned power stream — so it trails the raw ADC sample index
by a constant DSP-chain latency. The SM cannot see its own upstream latency, so
that bias is documented rather than corrected; subtract
`pulse_detect.get_dsp_latency()` if an absolute ADC-referenced time is needed.
PRI is immune to it, since a constant offset cancels in a difference.

**`peak_power`**, in both structs, is `power_t` truncated to `uint32_t`. Keep a
pulse's peak under 2³² in `power_t`'s scaled units or this field silently wraps;
`pdw_tb.py` asserts this at build time for every phase it drives.

## Mapping to gr-pdw's record

`gr_pdw_record.py` (host-side Python, no hardware) parses the 40-byte records
into gr-pdw's own nine-column `float64` array, so its `pdw.py` reader, pandas and
HDF5 flow work on FPGA output unmodified:

| gr-pdw column | from this design |
|---|---|
| `pdw_channel` | `channel` |
| `pulse_width_samps` | `pulse_width` |
| `pulse_width_secs` | `pulse_width / fs` |
| `pulse_power` | `peak_power_db / 256 + ref_level` |
| `noise_power` | `noise_power_db / 256 + ref_level` |
| `freq_start` | `freq_start / 65536 × fs` |
| `stop_freq` | `freq_stop / 65536 × fs` |
| `toa_course` | `toa // fs` |
| `toa_fine` | `toa % fs` |

Two caveats, both stated in that module's docstring rather than papered over:
`ref_level` is a **host-side additive offset**, exactly as in gr-pdw (its USRP
calibration-table blocks stay on the host; the FPGA emits dBFS); and **TOA is not
a unix timestamp** — this design has no PPS input and no time-of-day register, so
`toa` counts samples since reset and the coarse/fine split is a formatting
convenience carrying the DSP-latency bias above.

# Measurements

Detection alone makes an energy detector; the measurement is what makes a PDW.
The organizing idea, and what makes a CORDIC and two logarithms fit in a design
with ~5% timing margin:

* **Fast path — every sample, 125 MSPS.** Kept tiny: four multipliers (a
  conjugate product), a few accumulators, one leaky integrator. No CORDIC, no
  logarithm, no division.
* **Measurement path — once per pulse**, iterative and pipelined, ~16 cycles. A
  pulse closes at most every `min_width` samples and realistically every PRI
  (~125,000 samples), so this hardware is idle almost all the time.

Measured cost of the fast-path addition: **zero timing margin** (the detector
closes at 130.9 MHz before and after) and about 400 LUTs, 350 flip-flops and 4
DSP48s.

## Frequency

The instantaneous frequency between consecutive samples is the angle of
$z[n]\cdot\overline{z[n-1]}$. The obvious implementation takes an arctangent per
sample and averages the angles; this one **accumulates the products first and
takes a single angle per pulse**. That is both far cheaper — one `atan2` per
pulse instead of one per sample at 125 MSPS — and more accurate: summing the
phasors is the maximum-likelihood estimator for a tone in white noise, whereas
averaging angles weights a noisy sample as heavily as a strong one.

`freq_start` and `freq_stop` come from two accumulator sets: the first `block_k`
products of the pulse, and a ping-pong block accumulator holding the most recent
`block_k`..`2·block_k`. An unmodulated pulse gives the same angle for both; an
LFM chirp gives two different ones — modulation-on-pulse detection for the cost
of one extra accumulator pair.

The angle comes from a vectoring-mode CORDIC; see
[the DSP guide](../../../../include/pypeline/dsp/pypeline_dsp_guide.md#make_cordic_atan2--make_cordic_rotate--angles-without-a-multiplier-or-a-rom)
for its properties. Angles are in **turns**, so converting to Hz is a pure scale
by the sample rate with no π anywhere.

**This is a deliberate divergence from gr-pdw's algorithm**, and the first thing
its authors would ask about. gr-pdw zero-pads the pulse, takes an FFT and picks
the peak bin, because in numpy that is free. In an FPGA it is not: there is no
RAM/ROM primitive in the Pypeline library for the twiddle table, and a 256-point
FFT would dwarf the entire rest of this design. The phasor-sum estimator costs 4
DSP48s and gives a continuous-valued frequency rather than one quantized to a
bin.

## Power and the noise floor

`peak_power_db` and `noise_power_db` come from a shared
[`make_log2_db`](../../../../include/pypeline/dsp/pypeline_dsp_guide.md#make_log2_db--linear-power-to-dbfs)
conversion. Two things specific to this design:

* **The fractional bits must be subtracted** — `power_t` is fixed-point, so the
  integer the hardware holds is 2¹² times the value it represents. `log2_db`
  does this from `in_t.frac_bits`; the trap is documented in the DSP guide.
* **The noise floor cannot be measured after the DC blocker.** `dc_block`
  subtracts the running mean of the power, which *is* the noise floor, leaving a
  residual that sits at zero. The estimator therefore runs on the **pre-`dc_block`
  magnitude**, gated by the hysteresis SM's `in_idle`.

That gate needs one more thing. `in_idle` is aligned with the SM's input, which
lags the magnitude stream, so on every pulse's leading edge a few samples the SM
still calls idle have already risen. Folding those in makes the reported floor a
duty-cycle-weighted fraction of the *pulse* power — measured at ~10 dB below
peak regardless of the actual noise, a plausible-looking number that means
nothing. So a sample must also *look* like noise: no more than 4× the running
estimate, plus a seed so the estimator can start from zero. This is the standard
sample-excision guard a CFAR noise estimator uses, and it needs no knowledge of
pipeline latency — which matters, because those latencies are AUTOPIPELINE
results deliberately not available at elaboration time.

With the guard in place, a phase driven with `noise_amp=8` measures a **16.22
dBFS** floor against **16.2 dBFS** predicted by hand from the LFSR's statistics;
phases with no noise report the converter's floor, as they should.

## PRI

`toa - prev_toa`, taken between **accepted** pulses so a rejected glitch cannot
corrupt the interval reported for the next real one. The first accepted pulse
after reset has no predecessor, so it reports 0 and sets `status_flags` bit 4
rather than emitting a meaningless number.

## Known limitation: I/Q DC offset

The frequency estimator runs on the raw I/Q, and `dc_block` operates on the
*power*, not on the I/Q rails. A DC offset on either rail therefore adds a 0 Hz
component that pulls the measurement toward zero, roughly in proportion to
$|d|^2/|s|^2$. The internal generator is zero-mean by construction (the LFSR
noise is read as signed, deliberately), so this does not show up in simulation,
but a real receiver's ADC/mixer offset would. Correcting it needs an I/Q DC
blocker ahead of the conjugate product, which is not built.

# Host software (AirStack / SoapySDR)

`airt_pdw_test.py` brings the design up on a Deepwave AIR-T and verifies its
output. It is **not** part of `run_all.py` — it needs SoapySDR and hardware — but
everything it depends on is covered in-repo without a radio. **Four files copy to
the radio**, with no Pypeline checkout:

| File | What it is |
|---|---|
| `airt_pdw_test.py` | the script; the config arithmetic lives here |
| `pypeline_host_types.py` | **generated** — every struct layout and exported constant |
| `gr_pdw_record.py` | gr-pdw's columns, the dB/frequency scaling |
| `pdw_verify.py` | the independent FFT check of a record against its samples |

`pypeline_host_types.py` is generated and must not be edited. Every `pypelinec`
build of `top.py` drops it in `<out_dir>/host/`, and `python3 pdw_host_gen.py
<dir>` produces the same file without a build. It comes from the same leaf walk
the hardware serializer is built from, so the frame this project sends cannot
disagree with the frame the hardware expects. Nothing generated is committed — no
checked-in copy to go stale — so the in-repo tests build it on demand via
`pdw_host_gen.ensure_host_types()`. See
[Host-Side Generated Types](../../../../docs/pypeline_guide.md#host-side-generated-types).
`top.py`'s `host_export` call carries the non-layout constants across too:
`CTRL_DEFAULTS`, `CTRL_FLAG_*`, the `STATUS_*` bits, `POWER_FRAC_BITS`,
`FREQ_BLOCK_K` and the two FIFO depths — read off the built instances, so a
host-side pin on those numbers is unnecessary rather than merely automated.

## Channel map (2-channel bitstream mode)

Deepwave names its ports from **its** side, so every `m`/`s` letter is mirrored
relative to this design's names. They pair correctly — only the letter flips —
and assuming a match silently swaps a whole channel.

| SoapySDR call | Deepwave port | This design | Carries |
|---|---|---|---|
| `writeStream(TX,0)` | `dwd_tx0_m_axis` | `tx0_s_axis` | `pdw_ctrl_t`, 10 beats, END_BURST |
| — (to radio) | `dwd_tx0_s_axis` | `tx0_m_axis` | generator stimulus |
| `readStream(RX,0)` | `dwd_rx0_s_axis` | `rx0_m_axis` | pulse packets, variable length |
| — (from radio) | `dwd_rx0_m_axis` | `rx0_s_axis` | ADC samples |
| `readStream(RX,1)` | `dwd_rx1_s_axis` | `rx1_m_axis` | `valid_pdw_t`, 40 bytes |
| `writeStream(TX,1)` priming | `dwd_tx1_m_axis` | *(unconnected)* | dummy, discarded |
| — (to radio) | `dwd_tx1_s_axis` | `tx1_m_axis` | packet replay |

**Wrapper tie-offs, all three required.** There is no RX2 in 2-channel mode, so
tie `rx2_m_axis_rst` **LOW** and `rx2_m_axis_tready` **HIGH**; `global_rst` is
the OR of every channel reset, so an asserted or floating one holds the whole
design in reset forever and the host simply sees no pulses. Tie
`dwd_tx1_m_axis_tready` **HIGH** as well: this design has no `tx1_s_axis` port to
consume software's writes to that channel, so without it the priming write blocks
on the very port it is meant to unblock.

**CS16 is this design's own packing.** Deepwave specifies
`I = tdata[15:0]; Q = tdata[31:16]` — identical to this project. A CS16 buffer is
interleaved little-endian `int16`, so four bytes of an `np.int16` buffer **are**
one 32-bit AXIS beat: `np.frombuffer(raw, '<i2')` and `.tobytes()` are
reinterprets, never conversions, with no byte swapping anywhere. A 40-byte record
or control frame is exactly ten CS16 elements.

## Bring-up order

The two reset domains exist for this sequence, and it is not optional:

1. nothing activated — all resets asserted, buffers draining;
2. `activateStream(TX,0)` **alone** — control block live, datapath still held;
3. write one `pdw_ctrl_t` frame — config lands, datapath still held;
4. activate RX0, RX1, TX1 — datapath starts **already configured**.

Step 4 also gives the capture loop its RX0/RX1 lockstep for free: because
`global_rst` is the OR, nothing is emitted until every stream is open, so both
streams start empty whatever order they activate in. Hold reset at least
`RST_MIN_HOLD_CYCLES` (16448, ≈132 µs at 125 MHz) before re-activating.

## Framing, without an end-of-burst on receive

`writeStream` produces a `tlast` cycle via `SOAPY_SDR_END_BURST`, which is how
the control frame gets framed. **`readStream` surfaces no such marker**, so the
receive side is framed by counting: records are a fixed 40 bytes, and each
record's `pkt_samples` gives the exact length of the packet that follows it. That
works because `pkt_samples` is the **true on-wire length** — written from
`n_pushed`, which counts only beats that actually entered the FIFO.

Counting only works while the count is trustworthy, and nothing here
re-synchronises: one lost or extra byte makes every later read garbage that still
looks exactly like data. So every record goes through `validate_record` before it
is acted on. `channel` and `padding` are **four bytes of known zero** in every
record, the cheapest desync detector available; `pkt_samples` must equal
`pulse_width` (two independently-transmitted fields that must agree while the
margins are unbuilt) and must fit inside `PKT_FIFO_DEPTH`; `toa` must advance;
and `status_flags` must carry no undefined bit and no `pkt_fifo_full`, which a
delivered record cannot have. Without this the first thing the script does with a
slipped stream is allocate `2 × pkt_samples` of memory from it.

## The TX1 replay leg can wedge the packet path

`packet_store`'s FSM is `IDLE → WAIT_MEAS → EMIT_PDW → SEND_PKT`. `EMIT_PDW`
waits on the PDW port's ready (RX1), but `SEND_PKT` waits on the broadcast
interlock's `all_sinks_ready` — the AND of RX0's ready **and** the TX1 replay
leg's. So a TX1 `tready` that never rises parks the FSM in `SEND_PKT` forever,
with a distinctive signature:

> **one PDW record on RX1, zero bytes on RX0, then silence.**

Two mitigations, since neither is certain alone: the script writes a short dummy
burst to TX1 after activating it (`--no-prime-tx1` to skip), and it detects that
signature and reports it rather than hanging. The fallback is the
`tx1_m_axis_tready` tie-off above.

## Verifying records against their own samples

`pdw_verify.py` checks each record against the packet it describes using an
**FFT**, where the hardware uses phasor accumulation plus a CORDIC atan2. The
difference is the point: two independent algorithms agreeing is evidence, while a
Python re-implementation of the phasor method would only re-check the arithmetic
and would agree with a conceptually wrong design. It takes its FFT over the same
window `freq_accum` accumulates over (`block_k` = 32), which matters only for a
modulated pulse but matters a lot there.

Because the generator is internal and the host commanded it, the comparison is
three-way — **commanded** (the `pdw_ctrl_t` written) ↔ **software** (numpy over
the samples read back) ↔ **hardware** (the record): the first leg proves the
samples are the pulse that was ordered, the second that the measurement matches
those samples. What is honestly checkable is narrower than the record:

| Field | Check |
|---|---|
| `freq_start`, `freq_stop` | independent and absolute — the strongest here |
| `pkt_samples`, `pulse_width`, `pri`, `toa` | exact integers |
| `peak_power_db` | exact against `peak_power`, to the log block's own 0.046 dB |
| `peak_power` | **approximate, and duty-cycle dependent** — Path A is `magnitude → dc_block → moving_avg`, so the reported peak is a DC-blocked, smoothed envelope, not `max(I²+Q²)`. The DC blocker subtracts a running mean, so the higher the duty cycle the more of the pulse's own power gets subtracted back out: measured across `pdw_tb.py`'s phases (duty cycles up to ~50%) the ratio ranges **0.035–0.64**, near 1 at a realistic duty cycle. A wide-tolerance ratio check whose measured value is always reported |
| `noise_power_db` | **not checkable** from a packet — the floor is estimated between pulses. Bounded by SNR > 0 only |

`--csv` writes gr-pdw's own nine columns via `gr_pdw_record.write_csv`, readable
by its `pdw.py` tooling unmodified; `--ref-level-db` matches what gr-pdw's
`usrp_power_cal_table` block adds.

## Recording and replaying a session

`--record <file>` writes every record and packet exactly as received; `--replay
<file>` runs the identical capture loop over that file with no SoapySDR at all.
The second is the reason it exists: a bring-up session that went wrong stays
debuggable in the repo against the same checks, and it is what gives
`airt_pdw_test.py` a test at all (`airt_pdw_replay_test.py`). The format is
deliberately trivial and stdlib-only — an 8-byte magic and the sample rate, then
length-prefixed `(record, packet)` pairs, raw bytes as they came off the wire — so
a replay parses what the radio sent, not something the script already interpreted.

## The options that matter for bring-up

| Option | Why |
|---|---|
| `--stage {preflight,ctrl,streams,capture}` | stop at the ladder rung being proved, so a failure is localised instead of reported from the bottom of the capture loop |
| `--record` / `--replay` | above |
| `--alarm`, `--alarm-test` | arm the internal-error alarm; fire one to prove the path |
| `--resync-on-error` | reset and start over instead of stopping — for soaks. Every resync restarts `toa` |
| `--duration` | soak for a wall-clock time instead of a pulse count |
| `--pulses-per-sec` | **a correctness constraint, not a throughput choice.** Only `PKT_QUEUE_DEPTH` (16) completed pulses may await release; the rate is what buys the host time to verify and print. `build_config` refuses a rate leaving under a second of headroom, and the capture loop reports slowest-iteration against it |

**RF note.** With loopback enabled the detector is fed internally, but TX0 still
carries the generator's samples to the radio. Bench work wants a cable and
terminator, not an antenna.

# Bring-up and debugging

## The one symptom

There is no RX2 in 2-channel mode, so the candidate-record stream — the only
thing that distinguishes *detected but rejected* from *never detected* — is
unreachable on the target radio. Seven root causes therefore share one symptom:

| Root cause | What the host sees |
|---|---|
| wrong bitstream, or none | silence |
| a channel reset left asserted (`global_rst` is the OR of seven) | silence |
| the control frame never landed, or reverted to `CTRL_DEFAULTS` | silence |
| thresholds wrong by the ×4096 scaling | silence |
| every candidate glitch- or CW-rejected | silence |
| the TX1 replay leg wedging the release path | one record, then silence |
| a dropped descriptor or measurement | plausible records, wrong contents, forever |

That is why bring-up is a ladder rather than one run of `airt_pdw_test.py`. Each
rung proves one thing and has a defined failure signature; do not climb past a
rung that is red, because nothing above a red rung is interpretable. `--stage`
stops the script at the rung being proved.

## The internal-error alarm

The last row of that table is the one the design could not report at all — see
[What happens at the overflow point](#what-happens-at-the-overflow-point) for the
three conditions and why each is permanent and invisible. Until the alarm, the
only thing that noticed any of them was a `sim_assert`, which halts GHDL and
compiles to nothing whatsoever in a bitstream.

With no spare channel to report on, the alarm borrows the one back-channel that
exists. AirStack documents that on the ADC receive interface *"constant flow
control `tready` assertion is assumed, deasserting `tready` drops `tdata` samples
causing overflow"*, and that overflow events are reported by its API. So
`pdw_alarm.py` deasserts `rx0_s_axis_tready` on purpose, the platform drops
samples, and `readStream` returns `SOAPY_SDR_OVERFLOW`.

**The counter counts dropped samples, not cycles**, and that is the mechanism
rather than a detail. A sample is destroyed only on a cycle where `tvalid` is
high *and* `tready` is low; holding `tready` low while the input is idle destroys
nothing, raises no overflow and delivers no message. A cycle-based countdown would
therefore fail silently in exactly the case a gapped or not-yet-running input
makes likely — which is the case a bring-up is most likely to be in.
`ALARM_MAX_CYCLES` is only the other side of that: an input that never presents a
sample can never finish the count, and `tready` must not stay low forever on its
account.

| | |
|---|---|
| Arm | `CTRL_FLAG_ALARM_EN` (`flags` bit 1), or `--alarm` |
| Fire one now | `CTRL_FLAG_ALARM_TEST` (bit 2), or `--alarm-test` |
| Samples destroyed per alarm | `ALARM_DROP_SAMPLES` = 4096 (32.8 µs at 125 MSPS) |
| Backstop | `ALARM_MAX_CYCLES` = 2²⁰ (~8.4 ms) |
| Triggers | `packet_store`'s sticky `fifo_full`, `desc_drop`, `meas_drop` |

**Off by default**, in `CTRL_DEFAULTS` and in the script. Arming it means
consenting to destroy real samples to send a one-bit message, which is only the
right trade when a host is watching for it. Two properties make it cheap in
practice: **in loopback the alarm is free**, because the detector is fed from
`pulse_gen` and those ADC samples were not being used for anything; and the
triggers are sticky, so `error_alarm` deliberately limits a standing trigger to
**one** alarm rather than taking the receive path down permanently.

The `_TEST` bit exists so the signalling path can be proved on a good day (rung
6) instead of first being exercised during a fault, when nobody knows what the
overflow means.

## The ladder

**Rung 0 — before the radio.** `run_all.py` green for the ten PDW entries. Then
`python3 pdw_host_gen.py <dir>` and `--dry-run`, so the exact frame bytes are
known before any are sent.

**Rung 1 — platform identity.** `--stage preflight`. Driver and **BitStream
version** (rung 3 depends on it), sample rate — Deepwave enforces that it equals
the AXIS master clock — and the queue headroom the configured pulse rate buys.
*Failure:* wrong or absent bitstream.

**Rung 2 — TX0 accepts the control frame.** `--stage ctrl`. Activate TX0 alone,
write the 40-byte frame with `END_BURST`, confirm `writeStream` returns 10.
*Failure:* a short return or timeout means `dwd_tx0_m_axis_tready` is not reaching
`tx0_s_axis_tready`, which is tied high unconditionally — so a stall is a wrapper
or channel-map fault, not a design one.

**Rung 3 — does the configuration survive?** Do this before anything that depends
on it. AirStack 2.1.0 asserts `dwd_tx_axis_rst[*]` for 64 cycles *"during the idle
time between one transmission ending and the queued start time of the
following"*. `tx0_s_axis_rst` is both the register file's reset — reverting it to
`CTRL_DEFAULTS`, whose `0xFFFFFFFF` thresholds are indistinguishable from dead
hardware — and a term in `global_rst`, where 64 cycles is far short of
`RST_MIN_HOLD_CYCLES` and leaves buffers *partly* drained. It is documented for
queued *timed* writes, which this script does not use, so it may never fire.
**There is no register readback, so the discriminator is external:** put a
spectrum analyser or second receiver on the TX0 SMA. Config landed ⇒ pulses at the
commanded PRI and carrier; reverted ⇒ amplitude 0, silence. *If it fires*, drop
the runtime `if rst: regs = pdw_ctrl_t(...)` in `pdw_ctrl.py` — the
elaboration-time `Reg[pdw_ctrl_t] = CTRL_DEFAULTS` still makes power-on safe,
while a spurious reset then only flushes the deserializer.

**Rung 4 — a record appears.** `--stage capture`, RX0/RX1/TX1 activated and TX1
primed. *Failures in likelihood order:* nothing at all → rung 3, then the ×4096
threshold scaling, then `rx2_m_axis_rst`; one record then nothing on RX0 → the TX1
wedge, whose three fixes the script prints.

**Rung 5 — the record is about that packet.** `pdw_verify.check` runs on every
pulse. *Failure:* `freq_start`/`freq_stop` off by a large constant is a channel-map
or I/Q-packing fault, not a measurement one — CS16 and this design's packing are
byte-identical, so any offset means the streams are crossed.

**Rung 6 — the alarm path.** `--alarm --alarm-test`, once, while everything else
is known good. Skipping it means the first alarm ever seen will be during a real
fault.

**Rung 7 — soak and stress.** `--duration` with `--resync-on-error`, sweeping the
pulse rate toward the queue-headroom limit, adding `--chirp-rate` (the only real
test of `freq_stop`), `--noise-amp` and `--threshold-scale`, with `--record`
throughout so a session that goes wrong stays replayable.

**Rung 8 — real RF.** `--no-loopback`, TX0 → attenuator → RX0 by cable — the
analog path last, with every digital question already answered.

## Failure-mode reference

| Symptom | Most likely | How to tell |
|---|---|---|
| no records at all | a reset still asserted, or config never landed | rung 3's TX0 measurement; then check the three wrapper tie-offs |
| no records, config confirmed live | thresholds, or everything rejected | `--dry-run` prints thresholds in both raw and power units; widen `min_width`/`max_width` |
| one record, then nothing on RX0 | TX1 replay leg wedged | `--prime-tx1`, or tie `tx1_m_axis_tready` high |
| records stop after N pulses | host stalled past the queue headroom | the capture loop prints slowest-iteration vs headroom |
| `readStream` OVERFLOW | host fell behind — or, if armed, the alarm | see the alarm above; either way, resync |
| records arrive but fail validation | the stream has slipped | `channel`/`padding` are known-zero; framing is pure counting, so nothing after this is interpretable |
| records pass validation, `pdw_verify` fails frequency | channels crossed, or I/Q swapped | a large *constant* offset means wiring, not measurement |
| every record after some point has wrong measurements | a dropped descriptor or measurement (permanent) | only a reset clears it; arm the alarm to be told next time |
| `dsp_overflow` on every record | sticky, set once | says *when it started*, not that this pulse overflowed |

# Files

Everything lives flat in this directory. Hardware first, then host-side.

| File | What |
|---|---|
| `top.py` | The composed design and every top-level AXIS port. Three `@MAIN`s: reset tree, control register file, datapath |
| `pulse_gen.py` | Stimulus generator: NCO carrier, LFM chirp, LFSR noise |
| `pulse_detect.py` | `make_pulse_detect` (the composed Path A + Path B block) and its parts: `make_pulse_detect_fsm`, `make_delay_line`, `make_pdw_gate`, `make_freq_accum` |
| `pulse_extract.py` | `make_pulse_extract`: qualification (`make_pdw_qualify`) and store-and-forward release (`make_packet_store`) |
| `pulse_measure.py` | Per-pulse measurement: CORDIC atan2 ×2, log2→dB ×2, PRI |
| `pdw_ctrl.py` | The AXIS-written control register file and `pdw_ctrl_t` |
| `pdw_alarm.py` | The internal-error alarm |
| `pdw_paths.py` | One `sys.path` setup, imported by every module above |
| `pdw_host_gen.py` | Generates `pypeline_host_types.py` without a full build |
| `gr_pdw_record.py`, `pdw_verify.py`, `airt_pdw_test.py` | Host-side; no Pypeline import, these three copy to the radio |
| `*_tb.py`, `*_test.py`, `*_synth_top.py` | See [Testing](#testing) |

# Testing

| File | Scope | Style |
|---|---|---|
| `pulse_gen_tb.py` | Generator alone — carrier, LFM chirp, noise source, and the zero-mean check a DC-biased noise source would fail | `sim_assert`, hardware-generated stimulus |
| `pulse_detect_tb.py` | Bare hysteresis FSM, hand-fed a power stream — elastic, valid_only, and CW/`max_width`-cap variants | `sim_assert`, hardware-generated stimulus |
| `pulse_extract_tb.py` | The engine alone, hand-fed synthetic gate streams — accept path + PDW/packet ordering, glitch reject, CW reject, `status_flags`, long-stall backpressure | `sim_assert`, hardware-generated stimulus |
| `pulse_measure_test.py` | The measurement engine over its full input range, where a width or normalization mistake shows up (`pdw_tb.py` only covers the levels the real detector happens to produce) | `sim_call` vs a bit-exact model |
| `pdw_ctrl_test.py` | Reset defaults, apply latency (measured, then checked against the advertised attribute), ready never dropping, back-to-back writes, and the two malformed cases — a padded frame whose excess must be dropped and a runt that must leave the registers untouched, neither desyncing the frame after it; plus reset, and an abandoned frame flushed rather than joined to the next | `sim_call`, `type_to_bytes` + `AxisSimSource` |
| `pdw_reset_test.py` | Reset semantics for the composed datapath — a reset landing **mid-pulse**: nothing emitted for the interrupted pulse, its buffered samples drained rather than prepended to the next packet, TOA and PRI restarting, and the release artifact bounded below `min_width`. Both the drain term and the `gate_armed` clear have negative controls | `sim_call` on `pulse_detect` + `pulse_extract` wired as `top.py` wires them |
| `pdw_alarm_test.py` | The alarm alone. Its job is to destroy a known number of ADC samples, so the property tested is "exactly N samples were dropped", not "tready went low" — and those diverge only when the input is **gapped**. Carries its own negative control: the same stimulus through a deliberately-wrong cycle-counting model, asserted to get a different answer | `sim_call` |
| `pdw_verify_test.py` | That `pdw_verify.py` actually catches a wrong record. Mostly negative controls: corrupt one field, assert the check for **that** field fails and the others do not. Also generates `pypeline_host_types.py` and checks the host files compose with it | numpy, synthetic pulses |
| `airt_pdw_replay_test.py` | `airt_pdw_test.py`'s capture loop with no radio — the framing, `validate_record`, and the loop itself, served from a `--record` file | numpy, `pdw_verify_test`'s helpers |
| `pdw_tb.py` | The whole `top.py` — see below | `@sim_input`/`@sim_output`, exact Python golden model |

`pulse_extract_tb.py` exists alongside `pdw_tb.py` rather than being folded into
it because it reaches cases the real detector cannot produce on demand — most
importantly the ADC-clip flag, which is unreachable end to end (an amplitude that
clips the `int16` rail produces a power far past what the `uint32_t` threshold
ports can represent). It also uses a counter as the sample value, so a dropped,
duplicated or reordered beat shows up as a wrong integer with no golden model in
the way.

## `pdw_tb.py`

The only test that exercises `top.py` itself — the only test of
`make_pulse_detect`, the Path B delay/gate, the engine against real detector
output, and every top-level AXIS port. It configures every block by **writing real
control frames** on `tx0_s_axis_*` (one per phase, built with `type_to_bytes`,
driven by `AxisSimSource`), setting `CTRL_FLAG_LOOPBACK_EN` from phase 0 onward —
so the internal loopback path is what runs, while a garbage pattern is
deliberately driven on the external `rx0_s_axis_*` path so a broken loopback mux
fails loudly rather than passing silently.

All four master streams are checked against a golden model built from
`include/pypeline/dsp/dsp_tb.py`'s exact integer models (run against the *same*
`magnitude`/`dc_block`/`moving_avg` instances `top.py` built) plus a
hand-transcribed model of the hysteresis FSM, the gate and the engine's
qualification. Records are decoded with `type_from_bytes` *and* pushed through
`gr_pdw_record.unpack_records()` and compared field by field, so the host-side
decoder is tested against real hardware bytes. Finally every (record, packet) pair
goes through `pdw_verify.py` — which adds what the golden model cannot, since the
model reproduces the hardware's *own* phasor/CORDIC arithmetic and would agree
with a conceptually wrong estimator, whereas an FFT disagrees.

It also asserts `rx0_s_axis_tready` never goes low across the run. No phase arms
the alarm, so a single low cycle means either the alarm fired unbidden — implying
an internal FIFO drop the rest of the file should also be failing on — or its
polarity is inverted.

**Eight phases** (three PRI periods each): a baseline pulse at +Fs/8, a short
pulse at **−Fs/8** (a negative frequency, which a sign-flipped `atan2` fails), a
**glitch** narrower than `min_width`, a `max_width` cap forcing the **CW**
force-close path, a long pulse at a different amplitude, an **LFM chirp** (the
only phase where `freq_start` and `freq_stop` must differ), a threshold set to
suppress every pulse in that phase, and an amplitude too weak to cross a
calibrated threshold. All thresholds are calibrated programmatically from the
golden power model, never hand-picked. Net: 18 candidates detected, 12 released,
6 rejected (3 glitch + 3 CW).

Three things about the phase list are load-bearing:

* **Order.** Both rejecting phases sit *before* a releasing one. A rejected pulse
  is erased by draining its buffered beats; if that drain moved the wrong number
  of beats, the damage would only ever show up in the *next released packet*.
  With the rejecting phases last, a flush-count bug would leave no evidence
  anywhere. Phases are referred to by name, not index.
* **The noise phase's placement.** `dc_block`'s running mean carries across
  phases, so the first pulse after a change in signal level is measured against a
  mean still settling — its DC-blocked power comes out several times lower than
  its siblings'. Adding noise on top pushes it below `threshold_low` mid-pulse,
  and the SM then correctly reports one pulse as several. The noise lives on a
  phase whose three peaks agree to ~12%, which has the headroom.
* **Control timing is pinned, not assumed.** Each phase's frame is scheduled from
  `pdw_ctrl.n_beats`/`.latency` so it lands exactly on that phase's first sample;
  the testbench asserts the final beat's handshake really happened on the
  predicted cycle. A build-time assertion checks every frame lands over signal the
  golden model says is idle, so a future phase edit cannot reconfigure the
  generator mid-pulse.

Checking follows the wireguard-fpga pattern (`include/pypeline/axi/axis_sim.py`):
one `AxisSimSink` and one `Scoreboard` per output stream, `expect()`ed from the
golden model and `check()`ed in arrival order, each sink also enforcing
Xilinx-style `tkeep` compliance. The replay leg's frames are compared byte-for-byte
against the capture leg's — the only check of the fanout, since leg 1 could be
mis-wired to a stale register and everything else would still pass.

> ⚠ **Output backpressure here is periodic, not randomized.** All four consumers
> stall on mutually prime fixed periods (`PKT_READY_PERIOD=5`,
> `PDW_READY_PERIOD=7`, `CAND_READY_PERIOD=11`, `TX1_READY_PERIOD=13`) so the
> stalls drift against each other and against every phase's PRI, and the two
> released-packet legs stall on *different* periods, which is what exercises the
> broadcast interlock's ready AND rather than merely passing one ready through.
> But `AxisSimSink` has no randomized-ready facility (only `AxisSimSource` has
> `set_pause_generator`), so **randomized output `tready` flow control has never
> been tested on this design.** That is a known coverage gap, not a claim that it
> works.

## Where the tests live

Everything here tests *this example project*, not the Pypeline DSP library —
whose own unit tests live in `src/tests/pypeline_tests/inst/` (`cordic_test.py`,
`log2_db_test.py`, `magnitude_test.py`, ...). That is why these files stay next to
the design; one under `inst/` would need a `sys.path` hack back into this
directory to import it. All ten are registered in
`src/tests/pypeline_tests/native_sim_tests.py`.

```
python3 src/tests/pypeline_tests/run_all.py -k pdw
python3 src/tests/pypeline_tests/run_all.py -k pulse
```

## Synthesis checks

| File | Checks |
|---|---|
| `pulse_gen_synth_top.py` | Generator alone, including its NCO. `rst` is a real port, so the reset's fanout to every register is measured rather than optimised away |
| `pulse_detect_synth_top.py` | Hysteresis FSM alone (elastic, the heavier path), `rst` likewise a real port |
| `pulse_extract_synth_top.py` | Engine alone at the real 16K FIFO depth. Also the only real timing check on the measurement engine — its CORDIC and both logarithm converters are instantiated inside it. `rst` drives the three FIFO read enables, so it sits directly in the release path |
| `top.py` | Everything composed: all seven AXIS ports, both record serializers, the control deserializer, the broadcast interlock and the seven-input reset OR |

These are not redundant with the native-sim testbenches: native sim never emits
VHDL, so it cannot catch anything Vivado rejects. Several real bugs here were
only ever visible at this level — see
[the guide's limitations table](../../../../docs/pypeline_guide.md#limitations--not-yet-supported).

**Results** on `xc7a100tcsg324-1` at the 125 MHz target:

| Build | fmax |
|---|---|
| `pulse_gen_synth_top.py` | 134.4 MHz |
| `pulse_detect_synth_top.py` | 132.1 MHz |
| `pulse_extract_synth_top.py` (incl. the measurement engine) | 126.7 MHz |
| `top.py`, everything composed | **128.5 MHz** |

The composed design uses 23.9% of the part's LUTs (15,153), 5.7% of its
flip-flops (7,251), 16.7% of its block RAM and 3.3% of its DSP48s. Both the
16,384-deep packet FIFO and the Path B delay line infer block RAM; making every
top-level port an AXI-Stream cost about 3,900 LUTs and no fmax.

Getting there took eight timing fixes, each read off the reported critical path
rather than guessed. Two generalize:

* **Cross-module paths are invisible to per-block synthesis checks.** The
  generator→magnitude path (15.32 ns) and the phasor-accumulator→CORDIC path
  (11.65 ns) each met timing comfortably inside their own block; only the composed
  build showed them. Hence `top.py` being its own synthesis test.
* **A path can break with nothing on it having changed.** `d_im = cur_q·prev_i −
  cur_i·prev_q` needs two DSP48s, and with one pipeline register to place the
  synthesizer chooses which DSP absorbs it: one choice gives BRAM → DSP(A→MREG) ≈
  3.7 ns, the other BRAM → DSP A→P → DSP C setup = 9.69 ns, i.e. 103 MHz. Both are
  legal and Vivado has picked each — this design met its target until adding the
  AXIS ports grew the netlist and flipped it. Registering **all four** raw
  products, not just their sums, removes the choice. A path that depends on a
  synthesizer's packing decision is not meeting timing, it is winning a coin toss.

Every register added along the way is reported through a `.latency` attribute and
consumed as one (`freq_accum.latency`, `cordic_atan2.latency`, ...). Nothing
downstream hardcodes a delay, which is why all of these changes were made without
touching the testbenches' alignment logic or the golden model's structure.
