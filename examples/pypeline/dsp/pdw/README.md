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

**Target and part.** The deployment target is Deepwave AIR-T AIR7310. Its
[specification](https://deepwavedigital.com/wp-content/uploads/2024/07/AIR7310_Flyer_r1.0.pdf)
lists **XC7A200T-2FFG1156C**; every PDW synthesis entry point targets Vivado part
**`xc7a200tffg1156-2` at 125 MHz**. These are synthesis timing checks, not routed
timing or validation inside the integrated AirStack project. Historical 100T
proxy measurements remain explicitly identified in [Synthesis checks](#synthesis-checks).

## Table of contents

* [First bench run](#first-bench-run)
* [Architecture](#architecture)
* [Streams and stream interfaces: where backpressure begins](#streams-and-stream-interfaces-where-backpressure-begins)
  * [What happens at the overflow point](#what-happens-at-the-overflow-point)
  * [The two asymmetries](#the-two-asymmetries)
* [Top-Level Ports](#top-level-ports)
  * [Reset](#reset)
    * [Two domains, and the bring-up sequence they exist for](#two-domains-and-the-bring-up-sequence-they-exist-for)
    * [Block, drain, clear](#block-drain-clear)
    * [What reset does not reach](#what-reset-does-not-reach)
  * [Control registers (`pdw_ctrl_t`)](#control-registers-pdw_ctrl_t)
* [Record formats](#record-formats)
  * [Mapping to gr-pdw's record](#mapping-to-gr-pdws-record)
* [Measurements](#measurements)
  * [Frequency](#frequency)
  * [Power and the noise floor](#power-and-the-noise-floor)
  * [PRI](#pri)
  * [Known limitation: I/Q DC offset](#known-limitation-iq-dc-offset)
  * [Self-timed alignment](#self-timed-alignment)
* [Host software (AirStack / SoapySDR)](#host-software-airstack--soapysdr)
  * [Channel map (2-channel bitstream mode)](#channel-map-2-channel-bitstream-mode)
  * [Bring-up order](#bring-up-order)
  * [Framing, without an end-of-burst on receive](#framing-without-an-end-of-burst-on-receive)
  * [The TX1 replay leg can wedge the packet path](#the-tx1-replay-leg-can-wedge-the-packet-path)
  * [Verifying records against their own samples](#verifying-records-against-their-own-samples)
  * [Recording and replaying a session](#recording-and-replaying-a-session)
  * [The options that matter for bring-up](#the-options-that-matter-for-bring-up)
* [Bring-up and debugging](#bring-up-and-debugging)
  * [The one symptom](#the-one-symptom)
  * [The internal-error alarm](#the-internal-error-alarm)
  * [The ladder](#the-ladder)
  * [Failure-mode reference](#failure-mode-reference)
* [Files](#files)
* [Testing](#testing)
  * [`pdw_tb.py`](#pdw_tbpy)
  * [Where the tests live](#where-the-tests-live)
  * [Synthesis checks](#synthesis-checks)

## First bench run

Platform preparation belongs in the [Deepwave BitStream guide](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/):
[loading the bitstream](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/#loading-airstack-bitstream-files-onto-the-air-t),
[clock selection](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/#master-clock-rate), and
[DMA transport settings](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/#data-transport-application-notes).

From the repository root, prepare the four-file host bundle using your completed
build's generated types. Replace `PDW_BUILD` with its output directory:

```sh
PDW_BUILD=/tmp/pdw-top-rom
mkdir -p "$PDW_BUILD/air-t-host"
cp examples/pypeline/dsp/pdw/airt_pdw_test.py \
   examples/pypeline/dsp/pdw/gr_pdw_record.py \
   examples/pypeline/dsp/pdw/pdw_verify.py \
   "$PDW_BUILD/host/pypeline_host_types.py" "$PDW_BUILD/air-t-host/"
python3 "$PDW_BUILD/air-t-host/airt_pdw_test.py" --dry-run --rate 125e6
```

Copy those four files to one directory on the radio. Begin with internal
loopback and the default four pulses/second, 500-sample width and amplitude 800:

```sh
python3 airt_pdw_test.py --stage preflight --rate 125e6
python3 airt_pdw_test.py --stage ctrl --rate 125e6
python3 airt_pdw_test.py --stage capture --rate 125e6 --duration 30 --record first.pdwcap
python3 airt_pdw_test.py --replay first.pdwcap
python3 airt_pdw_test.py --rate 125e6 --alarm --alarm-test
```

`--stage ctrl` proves the control write was accepted while the datapath stays in
reset. Observe the generator during the **active capture run**; `ctrl` and
`streams` both close their channels before returning. RTL/Soapy channel 0 is the
first physical connector, labelled TX1/RX1 on the AIR7310 enclosure. TX0 still
drives RF in internal loopback, so use the intended bench terminations.

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
 |    Measure:  pulse_measure, once per pulse, selected pipeline latency   |
 |              selectable atan2, automatic ROM log2->dB, PRI              |
 |    Release:  accepted -> emit valid_pdw_t, then the packet               |
 |              rejected -> drop the record, flush the beats                |
 +-------------------------------------------------------------------------+
        | valid_pdw_t                          | released packet (w/ tlast)
        v                                      v
   rx1_m_axis                        rx0_m_axis (host DMA) + tx1_m_axis (replay)
```

## Architecture

**1. Stimulus.** `pulse_gen` synthesizes RF pulses with a real carrier (an NCO
built from an automatically pipelined quarter-wave sine ROM, `make_lut_nco`),
an optional LFM chirp and an optional LFSR noise source, all deterministic so golden models stay bit-exact. It drives TX0 for a
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

The measurement engine defaults to ROM atan2, with
`PDW_ATAN2_METHOD=cordic|rom` selecting either implementation, and uses automatic
ROMs for the two logarithm converters. It joins frequency, power, noise and PRI
when all result queues have a head for the same candidate. Packet release waits
for the corresponding measurement. Reset blocks output, drains storage and clears
PRI history. Power and conjugate products retain DSP multipliers; filters,
accumulation, thresholds and PRI remain arithmetic. Their wide, runtime inputs
make direct truth tables impractical, and their existing operations already fit
DSP or carry-chain hardware. The nonlinear sine, logarithm and angle functions
are the useful table candidates.

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
`rx0_s_axis_tready` is 1 except while the internal-error alarm fires; an ADC
cannot be back-pressured.

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
Alignment-queue overflow also feeds `meas_drop`; NCO alignment overflow feeds
the alarm directly. Both destroy transaction pairing and require a reset.
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
reaches the detector's input valid, a 320-bit control-register mux, packet and alignment FIFO
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

The generator's NCO is also fed zero amplitude while reset is held. That matters
because of the bring-up order below: the configuration lands while the datapath
is still in reset, and reset pins the PRI counter at 0, which is *inside* a
pulse. Without the gate, the NCO pipeline fills with the carrier during reset and
the first pulse after release comes out a pipeline-fill interval wider than
commanded — enough to fail `pdw_verify`'s width check on pulse 0 of every hardware
run. The NCO now also blocks requests/valid and drains its alignment queues;
the generator uses zero carrier while NCO valid is low, since an empty FIFO's
payload may still contain old RAM data. `pdw_tb.py` could not see the original
reset-fill problem, because it lands its configuration on the
release cycle itself. `pulse_gen_tb.py`'s `pulse_gen_reset_tb` checks a live
configuration at power-on and a mid-run reset after FIFO addresses have wrapped,
including the silent refill interval and the first pulse's exact width.

**Drain.** While reset is asserted every FIFO read enable is forced and the
buffers empty into the bit bucket — not a convenience but the only mechanism
available, since `make_fifo` has no flush. Each block forces its own read enables
(`data_ready |= rst` and friends), so the packet path drains with no help from
the consumer: `pdw_reset_test.py` holds the packet port's ready low for the whole
reset window and still gets a byte-exact drain. Because the drain is only as fast
as the data, **reset must be held** — emptying a full packet FIFO takes its depth
in cycles, ~131 µs at 125 MHz, and `top.py` exports `RST_MIN_HOLD_CYCLES`
(16448). The host holds reset for at least 50 ms at startup and resync; a shorter
platform pulse can leave buffers partly full and must not be treated as a flush.

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

`magnitude`, `dc_block`, `moving_avg` and the NCO/CORDIC/`log2_db` pipelines are
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
| `peak_power_db` | `int16_t` | Peak power in dB relative to one ADC count squared, Q8.8 (1 LSB = 1/256 dB) |
| `noise_power_db` | `int16_t` | Noise floor in the same count-squared dB units, Q8.8 |
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

**`toa` as built.** An accepted-sample counter inside the SM, latched on the
`IDLE -> PULSE` edge (read-before-increment, so it is the index of the same
sample that sets `pulse_width = 1`). It counts the SM's own *accepted input
samples* — the conditioned power stream. Pipeline transport delays when that
sample is processed, but does not add its cycle count to the sample's index:
**do not subtract `pulse_detect.get_dsp_latency()` from TOA.** The moving average
and hysteresis thresholds can shift the detected edge relative to the waveform's
leading edge. Input-valid gaps pause this counter, so TOA is not a wall-clock
timestamp. PRI is the difference between accepted-pulse TOAs in the same epoch.

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
| `pulse_power` | `peak_power_db / 256 - full_scale_power_db + ref_level` |
| `noise_power` | `noise_power_db / 256 - full_scale_power_db + ref_level` |
| `freq_start` | `freq_start / 65536 × fs` |
| `stop_freq` | `freq_stop / 65536 × fs` |
| `toa_course` | `toa // fs` |
| `toa_fine` | `toa % fs` |

Two caveats, both stated in that module's docstring rather than papered over:
`ref_level` is a **host-side additive offset**, exactly as in gr-pdw (its USRP
calibration-table blocks stay on the host). The host first subtracts
`full_scale_power_db = 20·log10(32768)` to normalize the wire values to dBFS,
using a full-scale CS16 complex-tone amplitude of 32768. Amplitude 800 therefore
reports approximately −32.25 dBFS, rather than +58.06 dB. **TOA is not
a unix timestamp** — this design has no PPS input and no time-of-day register, so
`toa` counts samples since reset and the coarse/fine split is a formatting
convenience; threshold response and input-valid gaps have the effects above.

# Measurements

Detection alone makes an energy detector; the measurement is what makes a PDW.
The organizing idea separates sample-rate work from per-pulse conversion:

* **Fast path — every sample, 125 MSPS.** Kept tiny: four multipliers (a
  conjugate product), a few accumulators, one leaky integrator. No CORDIC, no
  logarithm, no division.
* **Measurement path — once per pulse**, fully pipelined. Each angle and log
  converter accepts one input per enabled clock. Idle gaps between pulses do
  not relax the 125 MHz timing requirement. The selected implementation's
  Queue heads determine when all fields become valid together, without reading
  the selected pipeline latencies during construction.

The historical 100T proxy measurement of the fast-path addition was about
400 LUTs, 350 flip-flops and four DSP48s, with unchanged 130.9 MHz detector timing.
Current 200T measurements are in [Synthesis checks](#synthesis-checks).

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

`PDW_ATAN2_METHOD=cordic|rom` selects vectoring CORDIC or the default
[`make_lut_atan2`](../../../../include/pypeline/dsp/pypeline_dsp_guide.md#make_lut_atan2--an-angle-from-reciprocal-and-arctangent-roms).
The ROM method reduces signs and octants, normalizes to 17 significant bits,
looks up a reciprocal with 18 fractional bits, multiplies, then looks up the
arctangent. Both tables have 4096 entries and use automatic RAM. It avoids a
general divider, trading BRAM and DSPs for shift/add logic and registers.
Axes, diagonals, zero vectors and wrapping are explicit; accuracy is bounded
below 6e-5 turns across input scales. Both implementations emit signed 16-bit
**turns**, so converting to Hz is a pure scale by the sample rate. The golden
model dispatches through the selected implementation. See [Synthesis checks](#synthesis-checks)
for the measured default-selection decision.

**This is a deliberate divergence from gr-pdw's algorithm**, and the first thing
its authors would ask about. gr-pdw zero-pads the pulse, takes an FFT and picks
the peak bin, because in numpy that is free. In an FPGA it is not: the twiddle
table alone needs a ROM, and a 256-point
FFT would dwarf the entire rest of this design. The phasor-sum estimator costs 4
DSP48s and gives a continuous-valued frequency rather than one quantized to a
bin.

## Power and the noise floor

`peak_power_db` and `noise_power_db` come from a shared
[`make_log2_db`](../../../../include/pypeline/dsp/pypeline_dsp_guide.md#make_log2_db--linear-power-to-dbfs)
conversion, its default ROM method: both the exponent and the mantissa terms are
table lookups, good to 0.008 dB. These already were ROMs before automatic RAM
support; the change replaces their manual register placement. Each table starts
its synthesis search at two cycles, and each converter aligns its independently
selected table responses and floored flag through a completion join. The
measurement engine joins both completed converters with the angle outputs and
PRI metadata in candidate order.
Two things specific to this design:

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
pipeline latency — which matters, because those latencies are AUTO_PIPELINE
results deliberately not available at elaboration time.

With the guard in place, a phase driven with `noise_amp=8` measures a **16.22 dB
count-squared** floor against **16.2 dB** predicted from the LFSR's statistics
(approximately −74.09 dBFS after host normalization);
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

## Self-timed alignment

Path B already follows `gate_advance`, and packet release already waits for a
descriptor and `m.valid`. Prefer that completion-driven style over deriving
register-array lengths from an automatic component's `.latency`.

The remaining paths now use
[`make_valid_join`](../../../../include/pypeline/stream/pypeline_stream_guide.md#completion-joins-make_valid_join):

| Path | Previous latency counting | Implemented completion join |
|---|---|---|
| `pulse_measure` | `LAT = max(angle, power-log, noise-log)` and delay arrays | Five queues: start angle, stop angle, peak dB, noise dB and PRI; pop together only when every head is present |
| NCO and atan2 ROM sidebands | `ROM_LAT`, `RL` and `AL` size amplitude, sign and quadrant delay arrays | Queue signed amplitudes or quadrant metadata and the ROM responses; join in request order |
| `log2_db` table join | Delay the faster mantissa/exponent result to the slower table | Queue both table values and the floor flag; join completed responses |
| Candidate to frequency accumulator | `FL` delays peak, TOA, acceptance and noise | Capture peak, TOA, acceptance and noise at candidate completion; queue frequency responses separately and join by validity |

Each branch enqueues only valid words. A result emits when **all heads are
valid**, and all heads pop on that same enabled clock. This preserves transaction
order through bubbles and unequal or variable completion delays. Both metadata
and **response data** are queued: a fast ROM can answer before its metadata FIFO
presents a head. No transaction IDs are needed because every branch produces
one result per request in order, including rejected candidates.

Each join captures the completed heads into an output register. This cuts the
FIFO BRAM output path before downstream arithmetic: the first synthesis attempt
exposed an 8.90 ns path from the frequency FIFO into atan2's quadrant comparison.
The added register follows completion, so no delay counter or re-elaboration
dependency is introduced.

`join_depth=32` defaults to 32 memory words plus a FWFT output word per branch.
It bounds unmatched work, like Path B's `delay_depth`; it is not an exact delay.
Leave capacity for FIFO warm-up as well as branch skew. One result per enabled
clock is sustained once the branches are flowing. FIFO reads and writes now
both honor clock enable, matching native simulation. Reset blocks writes/output,
drains every queue independently and clears PRI history; the existing minimum
reset hold remains sufficient for the default design. There is no new FIFO reset
primitive. Overflow is sticky, asserts in simulation and reaches the hardware
alarm; reset is required after any word loss.

These factories no longer query automatic `.latency` during construction, so
alignment no longer forces latency-dependent re-elaboration. The compiler still
re-elaborates while searching automatic RAM implementations. `get_latency()` is
an explicit **diagnostic/model** query under continuous clock enable, not a
hardware alignment dependency. Selected one-cycle ROMs give NCO/log conversion
latencies of six clocks and ROM atan2 of fourteen; the measurement join adds three,
giving seventeen clocks (nineteen with the default fourteen-iteration CORDIC).
Queues add storage and a little transport delay in exchange for removing the
per-path delay bookkeeping. They do not make the arithmetic smaller by themselves.

Converter calls now take explicit `rst` (use `0` when unused) and report
`.overflow`. Two compiler limitations encountered here have focused reproducers
in `known_issues_tests.py`: omitted hardware default arguments leave ports
undriven, and nested record names beginning `signed_` take the wrong VHDL scalar
conversion path. Calls pass reset explicitly and the NCO uses `amplitudes_t`.
The existing enum-name workaround is unchanged.

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
build of `top.py` drops it in `<out_dir>/host/`, and
`python3 pdw_host_gen.py <dir>` produces the same file without a build. It comes
from the same leaf walk the hardware serializer is built from, so the frame this
project sends cannot disagree with the frame the hardware expects. Nothing generated is committed — no
checked-in copy to go stale — so the in-repo tests build it on demand via
`pdw_host_gen.ensure_host_types()`. See
[Host Type Export Declarations](../../../../docs/pypeline_guide.md#host-type-export-declarations).
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
| — (from radio) | `dwd_rx1_m_axis` | *(unconnected)* | ADC channel 1, discarded |
| `readStream(RX,1)` | `dwd_rx1_s_axis` | `rx1_m_axis` | `valid_pdw_t`, 40 bytes |
| `writeStream(TX,1)` priming | `dwd_tx1_m_axis` | *(unconnected)* | dummy, discarded |
| — (to radio) | `dwd_tx1_s_axis` | `tx1_m_axis` | packet replay |

**Wrapper tie-offs: four signals, all required.**

* **`rx2_m_axis_rst` LOW and `rx2_m_axis_tready` HIGH.** There is no RX2 in
  2-channel mode. `global_rst` is the OR of every channel reset, so an asserted or
  floating one holds the whole design in reset forever and the host simply sees
  no pulses.
* **`dwd_tx1_m_axis_tready` HIGH.** This design has no `tx1_s_axis` port to
  consume software's writes to that channel, so without it the priming write
  blocks on the very port it is meant to unblock.
* **`dwd_rx1_m_axis_tready` HIGH.** This design has no port for ADC channel 1 at
  all, and AirStack assumes constant `tready` on every ADC stream: a low one drops
  samples, and dropped samples are an *overflow*, which AirStack reports through
  its API — presumably on channel 1's software stream, the one the records come
  back on (the guide does not say which stream carries which channel's overflow).
  Expect `readStream` OVERFLOW on the first RX1 read; `airt_pdw_test.py` names
  this tie-off when it sees an unarmed overflow.

Everything else maps one to one. Per-channel resets: `dwd_rx_axis_rst[0]` drives
`rx0_s_axis_rst` and `rx0_m_axis_rst`, `dwd_rx_axis_rst[1]` drives
`rx1_m_axis_rst`, `dwd_tx_axis_rst[0]` drives `tx0_s_axis_rst` and
`tx0_m_axis_rst`, and `dwd_tx_axis_rst[1]` drives `tx1_m_axis_rst`. All of them
are active high and synchronous to `dwd_axis_clk`, which is this design's 125 MHz
clock.

The whole wrapper, as an instantiation inside AirStack's user logic in 2-channel
mode. The Deepwave names are the `dwd_*` ones from AirStack's programming guide;
check them against your AirStack version's template. The design's top-level
entity is `top`, and each 1-bit port is VHDL `unsigned(0 downto 0)`, i.e. a
`[0:0]` vector from Verilog:

```verilog
top pdw (
  .clk_125p0         (dwd_axis_clk),
  // resets: active high, one per channel; tx0's also gates the control file
  .rx0_s_axis_rst    (dwd_rx_axis_rst[0]),
  .rx0_m_axis_rst    (dwd_rx_axis_rst[0]),
  .rx1_m_axis_rst    (dwd_rx_axis_rst[1]),
  .tx0_s_axis_rst    (dwd_tx_axis_rst[0]),
  .tx0_m_axis_rst    (dwd_tx_axis_rst[0]),
  .tx1_m_axis_rst    (dwd_tx_axis_rst[1]),
  .rx2_m_axis_rst    (1'b0),                    // TIE-OFF: no RX2
  // writeStream(TX,0): pdw_ctrl_t frames in
  .tx0_s_axis_tdata  (dwd_tx0_m_axis_tdata),   .tx0_s_axis_tkeep  (dwd_tx0_m_axis_tkeep),
  .tx0_s_axis_tlast  (dwd_tx0_m_axis_tlast),   .tx0_s_axis_tvalid (dwd_tx0_m_axis_tvalid),
  .tx0_s_axis_tready (dwd_tx0_m_axis_tready),
  // generator stimulus out to DAC 0
  .tx0_m_axis_tdata  (dwd_tx0_s_axis_tdata),   .tx0_m_axis_tkeep  (dwd_tx0_s_axis_tkeep),
  .tx0_m_axis_tlast  (dwd_tx0_s_axis_tlast),   .tx0_m_axis_tvalid (dwd_tx0_s_axis_tvalid),
  .tx0_m_axis_tready (dwd_tx0_s_axis_tready),
  // ADC 0 in to the detector (tready drops only for the alarm)
  .rx0_s_axis_tdata  (dwd_rx0_m_axis_tdata),   .rx0_s_axis_tkeep  (dwd_rx0_m_axis_tkeep),
  .rx0_s_axis_tlast  (dwd_rx0_m_axis_tlast),   .rx0_s_axis_tvalid (dwd_rx0_m_axis_tvalid),
  .rx0_s_axis_tready (dwd_rx0_m_axis_tready),
  // readStream(RX,0): released pulse packets
  .rx0_m_axis_tdata  (dwd_rx0_s_axis_tdata),   .rx0_m_axis_tkeep  (dwd_rx0_s_axis_tkeep),
  .rx0_m_axis_tlast  (dwd_rx0_s_axis_tlast),   .rx0_m_axis_tvalid (dwd_rx0_s_axis_tvalid),
  .rx0_m_axis_tready (dwd_rx0_s_axis_tready),
  // readStream(RX,1): valid_pdw_t records
  .rx1_m_axis_tdata  (dwd_rx1_s_axis_tdata),   .rx1_m_axis_tkeep  (dwd_rx1_s_axis_tkeep),
  .rx1_m_axis_tlast  (dwd_rx1_s_axis_tlast),   .rx1_m_axis_tvalid (dwd_rx1_s_axis_tvalid),
  .rx1_m_axis_tready (dwd_rx1_s_axis_tready),
  // packet replay out to DAC 1
  .tx1_m_axis_tdata  (dwd_tx1_s_axis_tdata),   .tx1_m_axis_tkeep  (dwd_tx1_s_axis_tkeep),
  .tx1_m_axis_tlast  (dwd_tx1_s_axis_tlast),   .tx1_m_axis_tvalid (dwd_tx1_s_axis_tvalid),
  .tx1_m_axis_tready (dwd_tx1_s_axis_tready),
  // candidate records: nowhere to go in 2-channel mode
  .rx2_m_axis_tdata  (), .rx2_m_axis_tkeep (), .rx2_m_axis_tlast (), .rx2_m_axis_tvalid (),
  .rx2_m_axis_tready (1'b1)                     // TIE-OFF
);
assign dwd_tx1_m_axis_tready = 1'b1;            // TIE-OFF: software's TX1 writes, discarded
assign dwd_rx1_m_axis_tready = 1'b1;            // TIE-OFF: ADC 1, discarded
```

**CS16 is this design's own packing:** `I = tdata[15:0]; Q = tdata[31:16]`.
A CS16 buffer is
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
**FFT**, where the hardware uses phasor accumulation plus the selected atan2. The
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
| `peak_power_db` | exact against `peak_power`, to the log block's own 0.008 dB |
| `peak_power` | **approximate, and duty-cycle dependent** — Path A is `magnitude → dc_block → moving_avg`, so the reported peak is a DC-blocked, smoothed envelope, not `max(I²+Q²)`. The DC blocker subtracts a running mean, so the higher the duty cycle the more of the pulse's own power gets subtracted back out: measured across `pdw_tb.py`'s phases (duty cycles up to ~50%) the ratio ranges **0.035–0.64**, near 1 at a realistic duty cycle. A wide-tolerance ratio check whose measured value is always reported |
| `noise_power_db` | **not checkable** from a packet — the floor is estimated between pulses. Bounded by SNR > 0 only |

`--csv` writes gr-pdw's own nine columns via `gr_pdw_record.write_csv`, readable
by its `pdw.py` tooling unmodified; `--ref-level-db` matches what gr-pdw's
`usrp_power_cal_table` block adds.

## Recording and replaying a session

`--record <file>` writes every record and packet exactly as received;
`--replay <file>` runs the identical capture loop over that file with no
SoapySDR at all.
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

For `--no-loopback`, start with explicit `--threshold-high-power` and
`--threshold-low-power` values in **linear CS16 count-squared units**, or supply
`--rx-amplitude` in **CS16 counts** to derive them. The amplitude reference is
optional: it enables the receive amplitude check once the received level is
known. Without it, the record/payload checks still run, and the script does not
compare the received amplitude to the TX digital amplitude. `--rx-gain` selects
manual RX0 gain and `--tx-gain` sets TX0 stimulus gain;
keep the cable attenuation and those gains fixed while verifying a calibration.
The received reference must stay at or below `MAX_AMPLITUDE` because the record's
linear peak-power field has the same range limit as the threshold ports.

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

With no spare channel to report on, the alarm borrows the ADC-input back-channel:
`pdw_alarm.py` deasserts `rx0_s_axis_tready` on purpose, and the host looks for
`SOAPY_SDR_OVERFLOW`. See the
[BitStream transport notes](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/#data-transport-application-notes).

**Nothing else in this design can cause that overflow.** In AirStack's default
passthrough bitstream a host that falls behind back-pressures the ADC and
overflows it. Here the host back-pressures only the design's own output ports,
which its FIFOs absorb — and past `PKT_QUEUE_DEPTH` they corrupt *silently*.
So an unarmed overflow means a wrapper fault, never a slow host (see the tie-offs
above).

**After an alarm, reset and restart the streams** before normal capture resumes.
The project's consequences are:

* An alarm is always followed by a resync. `--resync-on-error` does this
  automatically.
* Once flow stops, `tvalid` stops, so the drop count usually cannot complete.
  The `ALARM_MAX_CYCLES` backstop (8.4 ms) is what ends an alarm on this platform,
  not the 4096-sample count.
* With `--no-loopback` the detector has no input at all until the resync.

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
| Triggers | Sticky packet `fifo_full`, descriptor `desc_drop`, measurement/alignment `meas_drop`, or generator NCO alignment overflow |

**Off by default**, in `CTRL_DEFAULTS` and in the script. Arming it means
consenting to destroy real samples to send a one-bit message, which is only the
right trade when a host is watching for it. Two properties keep the cost down.

* **In loopback the dropped ADC samples cost nothing**, because the detector is
  fed from `pulse_gen`. It is not quite free, though: the detector's input is
  still held for as long as the alarm lasts, whatever its source. At bring-up
  pulse rates that costs at most one pulse.
* **The triggers are sticky**, so `error_alarm` deliberately limits a standing
  trigger to **one** alarm rather than taking the receive path down permanently.

The `_TEST` bit exists so the signalling path can be proved on a good day (rung
6) instead of first being exercised during a fault, when nobody knows what the
overflow means.

## The ladder

**Rung 0 — before the radio.** Run the project tests, including the selected
whole-top `pdw_tb` variant (see [Where the tests live](#where-the-tests-live)). Then
`python3 pdw_host_gen.py <dir>` and `--dry-run`, so the exact frame bytes are
known before any are sent.

**Rung 1 — clock and platform information.** `--stage preflight --rate 125e6`
sets the master clock and checks all four channel rates against it. The script
prints driver/firmware information, the RX DMA buffer parameter when available,
and queue headroom. Firmware identity is informational; this stage does not
prove that a particular custom image is loaded.

**Rung 2 — TX0 accepts the control frame.** `--stage ctrl`. Activate TX0 alone,
write the 40-byte frame with `END_BURST`, confirm `writeStream` returns 10.
*Failure:* a short return or timeout means `dwd_tx0_m_axis_tready` is not reaching
`tx0_s_axis_tready`, which is tied high unconditionally — so a stall is a wrapper
or channel-map fault, not a design one.

**Rung 3 — does the configuration survive?** Connect the observer first, then
run `--stage capture --duration 30` and observe the generator on physical TX1
(RTL/Soapy TX0) **while all streams are active**. `--stage ctrl` leaves the
generator in reset and closes TX0 on exit; it cannot produce this observation.
Pulses at the commanded PRI/carrier support configuration retention. Silence
still needs to be distinguished from gain settings or gating in the TX path.

For platform reset behavior, consult the
[BitStream reset/time documentation](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/#time-api).
In this project, `tx0_s_axis_rst` clears the configuration and participates in
`global_rst`. Preserving just the registers would not fix a reset that partially
drains packet storage. Keep the existing reset/drain contract; if an unexpected
reset occurs, capture it with an ILA and restart with a full drain.

**Rung 4 — a record appears.** `--stage capture`, RX0/RX1/TX1 activated and TX1
primed. *Failures in likelihood order:* nothing at all → rung 3, then the ×4096
threshold scaling, then `rx2_m_axis_rst`; one record then nothing on RX0 → the TX1
wedge, whose three fixes the script prints.

**Rung 5 — the record is about that packet.** `pdw_verify.check` runs on every
pulse. *Failure:* `freq_start`/`freq_stop` off by a large constant is a channel-map
or I/Q-packing fault, not a measurement one — CS16 and this design's packing are
byte-identical, so any offset means the streams are crossed.

**Rung 6 — the alarm path.** `--alarm --alarm-test`, once normal capture works.
The script first verifies a record/packet pair, then writes the test flag. An
explicit OVERFLOW produces `Rung 6 PASSES` and stops the run. If RX1 times out,
the script checks RX0 for a pending overflow before declaring the test
inconclusive. A timeout alone is not proof that the alarm path is broken; use
these [transport notes](https://docs.deepwave.ai/AirStack/Bitstream/programming_guide/#data-transport-application-notes)
to investigate it. A completed capture with no overflow leaves the alarm test
unproven and returns a failure status.

**Rung 7 — soak and stress.** `--duration` with `--resync-on-error`, sweeping the
pulse rate toward the queue-headroom limit, adding `--chirp-rate` (the only real
test of `freq_stop`), `--noise-amp` and `--threshold-scale`, with `--record`
throughout so a session that goes wrong stays replayable.

**Rung 8 — real RF.** `--no-loopback`, TX0 → attenuator → RX0 by cable — the
analog path last, with every digital question already answered. For initial
capture, use explicit receive thresholds and adjust them to the received signal;
keep the selected gains and attenuation fixed. Once the level is known, supply
`--rx-amplitude` to derive thresholds and enable the amplitude check. For example,
`--no-loopback --threshold-high-power 2000 --threshold-low-power 1000` selects
those two count-squared thresholds without an amplitude reference; these values
illustrate the units, rather than specifying a calibration for every RF path.

## Failure-mode reference

| Symptom | Most likely | How to tell |
|---|---|---|
| no records at all | a reset still asserted, or config never landed | rung 3's TX0 measurement; then check the wrapper tie-offs |
| transport TIMEOUT, especially with small frames | DMA configuration or unavailable data | preflight's RX DMA setting and the linked transport notes; a timeout does not uniquely identify a detector fault |
| no records, config confirmed live | thresholds, or everything rejected | `--dry-run` prints thresholds in both raw and power units; widen `min_width`/`max_width` |
| one record, then nothing on RX0 | TX1 replay leg wedged | `--prime-tx1`, or tie `tx1_m_axis_tready` high |
| records stop after N pulses | host stalled past the queue headroom | the capture loop prints slowest-iteration vs headroom |
| `readStream` OVERFLOW on the first RX1 read | `dwd_rx1_m_axis_tready` not tied high | the fourth wrapper tie-off; a slow host **cannot** overflow this design |
| `readStream` OVERFLOW, alarm armed | the alarm: a dropped descriptor, measurement or packet beats | see the alarm above; resync — AirStack keeps the ADC stream down until you do |
| `readStream` OVERFLOW on RX0, alarm not armed | `rx0_s_axis_tready` not reaching `dwd_rx0_m_axis_tready` in the wrapper | the design never drops that tready unarmed |
| records arrive but fail validation | the stream has slipped | `channel`/`padding` are known-zero; framing is pure counting, so nothing after this is interpretable |
| records pass validation, `pdw_verify` fails frequency | channels crossed, or I/Q swapped | a large *constant* offset means wiring, not measurement |
| every record after some point has wrong measurements | a dropped descriptor or measurement (permanent) | only a reset clears it; arm the alarm to be told next time |
| `dsp_overflow` on every record | sticky, set once | says *when it started*, not that this pulse overflowed |

# Files

Everything lives flat in this directory. Hardware first, then host-side.

| File | What |
|---|---|
| `top.py` | The composed design and every top-level AXIS port. Four `@MAIN`s: reset tree, control register file, generator and detector/extraction datapath |
| `pulse_gen.py` | Stimulus generator: NCO carrier, LFM chirp, LFSR noise |
| `pulse_detect.py` | `make_pulse_detect` (the composed Path A + Path B block) and its parts: `make_pulse_detect_fsm`, `make_delay_line`, `make_pdw_gate`, `make_freq_accum` |
| `pulse_extract.py` | `make_pulse_extract`: qualification (`make_pdw_qualify`) and store-and-forward release (`make_packet_store`) |
| `pulse_measure.py` | Per-pulse measurement: selectable CORDIC/ROM atan2 ×2, automatic ROM log2→dB ×2, PRI |
| `pdw_ctrl.py` | The AXIS-written control register file and `pdw_ctrl_t` |
| `pdw_alarm.py` | The internal-error alarm |
| `pdw_paths.py` | One `sys.path` setup, imported by every module above |
| `pdw_host_gen.py` | Generates `pypeline_host_types.py` without a full build |
| `gr_pdw_record.py`, `pdw_verify.py`, `airt_pdw_test.py` | Host-side; no Pypeline import, these three copy to the radio |
| `*_tb.py`, `*_test.py`, `*_synth_top.py` | See [Testing](#testing) |

# Testing

| File | Scope | Style |
|---|---|---|
| `pulse_gen_tb.py` | Generator alone — carrier, LFM chirp, noise source, the zero-mean check a DC-biased noise source would fail, and reset held with a live configuration (nothing from the reset window may leak into the first pulse) | `sim_assert`, hardware-generated stimulus |
| `pulse_detect_tb.py` | Bare hysteresis FSM, hand-fed a power stream — elastic, valid_only, and CW/`max_width`-cap variants | `sim_assert`, hardware-generated stimulus |
| `pulse_extract_tb.py` | The engine alone, hand-fed synthetic gate streams — accept path + PDW/packet ordering, glitch reject, CW reject, `status_flags`, long-stall backpressure | `sim_assert`, hardware-generated stimulus |
| `pulse_measure_test.py` | The measurement engine over its full input range, where a width or normalization mistake shows up (`pdw_tb.py` only covers the levels the real detector happens to produce) | `sim_call` vs a bit-exact model |
| `pdw_ctrl_test.py` | Reset defaults, apply latency (measured, then checked against the advertised attribute), ready never dropping, back-to-back writes, and the two malformed cases — a padded frame whose excess must be dropped and a runt that must leave the registers untouched, neither desyncing the frame after it; plus reset, and an abandoned frame flushed rather than joined to the next | `sim_call`, `type_to_bytes` + `AxisSimSource` |
| `pulse_extract_alignment_test.py` | 28 candidates with independently delayed frequency responses, live noise changing between candidates, glitch/CW rejection and accepted-pulse PRI; exact records and packets, with no `freq_latency` attribute | `sim_call`, ROM and CORDIC |
| `pdw_reset_test.py` | Reset semantics for the composed datapath — a reset landing **mid-pulse**: nothing emitted for the interrupted pulse, its buffered samples drained rather than prepended to the next packet, TOA and PRI restarting, and the release artifact bounded below `min_width`. Both the drain term and the `gate_armed` clear have negative controls | `sim_call` on `pulse_detect` + `pulse_extract` wired as `top.py` wires them |
| `pdw_alarm_test.py` | The alarm alone. Its job is to destroy a known number of ADC samples, so the property tested is "exactly N samples were dropped", not "tready went low" — and those diverge only when the input is **gapped**. Carries its own negative control: the same stimulus through a deliberately-wrong cycle-counting model, asserted to get a different answer | `sim_call` |
| `pdw_verify_test.py` | That `pdw_verify.py` actually catches a wrong record. Mostly negative controls: corrupt one field, assert the check for **that** field fails and the others do not. Also generates `pypeline_host_types.py` and checks the host files compose with it | numpy, synthetic pulses |
| `airt_pdw_replay_test.py` | `airt_pdw_test.py`'s capture loop with no radio — the framing, `validate_record`, the resync paths, what an OVERFLOW is reported as, and `--alarm-test`'s pass and fail, served from a `--record` file | numpy, `pdw_verify_test`'s helpers |
| `airt_pdw_host_test.py` | The live-radio `run()` path with a SoapySDR stand-in: clock/rate selection, activation errors, cleanup, RF threshold choices, delayed alarm firing, and checking RX0 after an RX1 timeout | mocked SoapySDR, generated host types |
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

It is framed by two hooks. An `@initial(sim=True)` hook fills the scoreboards and
prints the phase table before the first cycle; filling them any earlier would let
decoration-time introspection consume a real expected entry (see the comment on
section 6). `check_done` calls `sim_finish()` once every expected output has
arrived, and an `@final(sim=True)` hook then runs the end-of-run checks once: the
per-stream counts, that the reset window was really visited, record-before-next-
packet ordering, the `pdw_verify.py` cross-check and the summary line. The final
hook runs however the simulation ended, so a run that stops early fails on
"simulation ended before every expected output arrived" instead of exiting 0 with
those checks never reached.

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
`lut_atan2_test.py`, `lut_nco_test.py`, `log2_db_test.py`, `magnitude_test.py`, ...). That is why these files stay next to
the design; one under `inst/` would need a `sys.path` hack back into this
directory to import it. They are registered in
`src/tests/pypeline_tests/native_sim_tests.py`. Measurement, reset and end-to-end
entries run with both angle methods. Candidate/frequency alignment tests also
run both methods with independently scheduled responses and no detector latency
attribute. Measurement tests force either log
converter to take longer than atan2, checking every field and PRI alignment.
The DSP tests cover automatic/manual ROM modes and unequal table latencies;
`self_check_dsp_rom_test.py` and `lut_atan2_test.py` provide native/GHDL parity,
including bubbles, clock-enable pauses and in-flight reset drain. `valid_join_test.py`
checks independent arrivals, sustained one-result-per-clock throughput, reset
with unmatched heads and overflow; `self_timed_factory_test.py` forbids automatic
latency reads during construction. The generator reset bench also has native/GHDL
parity, checking old FIFO contents cannot leak during refill. RAM backend, mapping and selected-plan
coverage belongs in the [test-suite RAM section](../../../../docs/pypeline_TESTS.md#ram-coverage).

```
python3 src/tests/pypeline_tests/run_all.py -k pdw
python3 src/tests/pypeline_tests/run_all.py -k pulse
```

There is **one** whole-top testbench source, `pdw_tb.py`. `pdw_tb_rom` runs it
with the default ROM atan2; the entry named `pdw_tb` runs it with CORDIC atan2.
Both use the same stimulus, golden model and checks. To run only the default
whole-top native simulation:

```sh
python3 src/tests/pypeline_tests/run_all.py --category native_sim --test pdw_tb_rom -j 1
```

`airt_pdw_host_test.py` exercises clock selection, activation failures, RF
threshold calibration and the live alarm-test sequence with a SoapySDR stand-in.
It complements the capture-file replay tests, which do not execute `run()`.


## Synthesis checks

| File | Checks |
|---|---|
| `pulse_gen_synth_top.py` | Generator alone, including its NCO. `rst` is a real port, so the reset's fanout to every register is measured rather than optimised away |
| `pulse_detect_synth_top.py` | Hysteresis FSM alone (elastic, the heavier path), `rst` likewise a real port |
| `pulse_measure_synth_top.py` | Measurement alone, exposing all inputs and outputs for CORDIC/ROM timing and area comparisons |
| `pulse_extract_synth_top.py` | Engine alone at the real 16K FIFO depth, including its angle and logarithm converters. `rst` drains packet and alignment FIFOs, so it sits directly in the release path |
| `top.py` | Everything composed: all seven AXIS ports, both record serializers, the control deserializer, the broadcast interlock and the seven-input reset OR |

These are not redundant with the native-sim testbenches: native sim never emits
VHDL, so it cannot catch anything Vivado rejects. Several real bugs here were
only ever visible at this level — see
[the guide's limitations table](../../../../docs/pypeline_guide.md#limitations--not-yet-supported).

Build designs containing automatic ROMs with **full synthesis sweeps**, without
`--comb`. The NCO starts its ROM search at three cycles, and each log/atan2
table at two. A start value is a guess that the sweep can trim; native and
HDL-only flexible RAMs use one cycle. All alignment follows the selected delays.

```sh
for method in cordic rom; do
  python3 src/pypelinec examples/pypeline/dsp/pdw/pulse_measure_synth_top.py \
    -D "PDW_ATAN2_METHOD=$method" --out_dir "/tmp/pdw-measure-$method" -j 1
  python3 src/pypelinec examples/pypeline/dsp/pdw/top.py --no_hier_syn \
    -D "PDW_ATAN2_METHOD=$method" --out_dir "/tmp/pdw-top-$method" -j 1
done
```

`--no_hier_syn` limits preliminary characterization to primitive leaves; these
remain full RAM/operator sweeps with whole-design timing checks. The reports
retain selected plans, achieved clocks and raw RAMB18/RAMB36/LUT/register/DSP counts.

**Fresh 200T baseline**, captured before changing the DSP implementations,
with manual NCO/log ROMs and CORDIC atan2:

| Build | MHz | LUTs | Registers | RAMB18 | RAMB36 | DSPs |
|---|---:|---:|---:|---:|---:|---:|
| Generator | 165.782 | 520 | 345 | 1 | 0 | 4 |
| Detector FSM | 157.011 | 728 | 627 | 0 | 0 | 0 |
| Measurement | 146.735 | 5,649 | 2,961 | 1 | 0 | 0 |
| Extraction engine | 146.735 | 6,193 | 3,864 | 3 | 21 | 0 |
| Composed design | 146.735 | 12,764 | 6,127 | 5 | 21 | 10 |

**Self-timed composed ROM build** (2026-10-11), full Vivado 2019.2 sweep on
`xc7a200tffg1156-2`, with 32-word alignment queues and registered join outputs:

| Build | PDW MHz | Generator/control MHz | LUTs | Registers | RAMB18 | RAMB36 | DSPs |
|---|---:|---:|---:|---:|---:|---:|---:|
| Self-timed ROM (**current**) | 127.600 | 137.212 | 9,172 | 4,709 | 11 | 29 | 12 |
| Previous latency-counted ROM | 132.873 | 134.264 | 8,532 | 4,195 | 7 | 25 | 12 |

All four mains meet 125 MHz and the design fits; reset has a measured lower bound
of 125 MHz in the whole-design report. All six automatic ROMs select one cycle.
The queue implementation adds 640 LUTs, 514 registers, four RAMB18s and four
RAMB36s; DSP count is unchanged. Alignment is simpler to maintain, with some
extra storage and transport delay. The retained PDW margin is about 0.16 ns at
125 MHz. These are synthesis results, not routed AirStack timing.

The [self-timed measurement artifact](../../../../src/tests/pypeline_tests/qor/pdw_self_timed_vivado_200t.json)
retains the command, signatures, selected RAM plans, clocks, resources and
verification results. Both complete native variants pass 7,323 clocks: 18
candidates, 12 released records/packets, six expected rejects and 82 independent
verifier assertions each. Native/GHDL joins, ROM orderings, clock-enable pauses
and generator refill/reset checks pass; removing the generator's NCO-valid mask
fails the mid-run refill check in GHDL. Top elaboration, variable completion and
converter native/GHDL parity also pass with the committed compiler separately
from the compiler changes already in the working tree.

**Pre-join automatic ROM standalone builds** on the same 200T at the 125 MHz goal:

| Build | MHz | DSP latency | LUTs | Registers | RAMB18 | RAMB36 | DSPs |
|---|---:|---:|---:|---:|---:|---:|---:|
| Generator | 133.191 | NCO: 3 | 520 | 311 | 1 | 0 | 4 |
| CORDIC measurement | 146.735 | 16 | 5,581 | 2,938 | 3 | 0 | 0 |
| ROM measurement | 142.816 | 8 | 1,591 | 1,066 | 3 | 4 | 2 |

Every standalone ROM selects one cycle. The automatic NCO trades timing margin
for two fewer cycles and 34 fewer registers; it still meets 125 MHz. The ROM
angle trades four RAMB36s and two DSPs for fewer measurement LUTs/registers and
half the measurement latency. Vivado shares the identical tables across the
two endpoint converters using both physical read ports.

**Pre-join composed automatic-ROM builds**, using full sweeps on the same 200T:

| Angle method | MHz | Measurement latency | LUTs | Registers | RAMB18 | RAMB36 | DSPs |
|---|---:|---:|---:|---:|---:|---:|---:|
| CORDIC | 134.264 | 16 | 12,697 | 6,069 | 7 | 21 | 10 |
| ROM (**default**) | 132.873 | 8 | 8,532 | 4,195 | 7 | 25 | 12 |

In those earlier builds, all ROMs select one cycle, including both angle tables. The NCO takes three
cycles and each log converter takes three; measurement alignment follows the
longest selected conversion. ROM atan2 saves **4,165 LUTs (32.8%) and 1,874
registers (30.9%)** against CORDIC in the composed design, for **four additional
RAMB36s and two DSPs**. Both builds meet 125 MHz and fit the part. ROM is the
default because correctness passes, composed timing reaches the target, and
LUT usage falls without increasing register usage. CORDIC remains selectable
with `-D PDW_ATAN2_METHOD=cordic` or the matching environment variable.

The automatic NCO's shorter implementation reduces the CORDIC composition's
timing margin relative to the manual-ROM baseline, while still meeting the
goal. The ROM composition's limiting path is the accumulated phasor entering
the angle converter's magnitude/octant stage. These are **Vivado 2019.2
out-of-context synthesis** measurements, not routed timing or integrated
AirStack validation.

The [200T measurement artifact](../../../../src/tests/pypeline_tests/qor/pdw_vivado_200t.json)
records baseline revision `2be7c27`, the part-only baseline adjustments,
reproduction commands, retained synthesis signatures, selected RAM plans,
search histories, latencies, resource counts and the default-selection checks.
The baseline snapshot used manual NCO/log ROMs and CORDIC; its standalone
measurement wrapper exposes the same inputs and outputs as the new wrapper.

**Historical proxy results** on `xc7a100tcsg324-1` at the 125 MHz target, using
manual NCO/log ROMs and CORDIC atan2 (not AIR7310's part):

| Build | fmax |
|---|---|
| `pulse_gen_synth_top.py` | 141.5 MHz |
| `pulse_detect_synth_top.py` | 132.0 MHz |
| `pulse_extract_synth_top.py` (incl. the measurement engine) | 126.7 MHz |
| `top.py`, everything composed | **128.6 MHz** |

That historical composed build uses 20.1% of the proxy part's LUTs (12,764), 4.8% of its
flip-flops (6,127), 17.4% of its block RAM and 4.2% of its DSP48s. The
16,384-deep packet FIFO, the Path B delay line, the NCO's sine table and the log
converter's mantissa table all infer block RAM. Making every top-level port an
AXI-Stream cost about 3,900 LUTs and no fmax.

**Tables instead of iterations** (2026-09-27). The generator's NCO was a
16-iteration rotation CORDIC and is now a quarter-wave sine ROM plus two DSP48s
(`make_lut_nco`). The generator alone went from 2,742 LUTs, 1,373 flip-flops and
133.3 MHz to 520 LUTs, 345 flip-flops and 141.5 MHz, for one RAMB18 and two DSP48s.
The NCO's latency went from 18 cycles to 5, and its amplitude is now exact rather
than 0.35% high. `log2_db`'s default is now its ROM method: 0.046 dB worst-case error
became 0.008 dB, with the same latency and slightly less logic. The composed
design lost 2,339 LUTs and 1,124 flip-flops and kept its fmax, because its
critical path is elsewhere. Those measurements used `make_ram` ROMs.
`make_auto_pipeline_ram` now supports Vivado, and the NCO/log defaults use it.
The selectable ROM atan2 uses a reciprocal table and multiplication rather than
a general divider; running only once per pulse does not remove its area or
single-cycle timing cost.

**Historical 100T margin.** Slack at 125 MHz, per destination register, in the
composed proxy build above:

| Slack | Path |
|---|---|
| 0.22 ns | `freq_accum` output → the measurement `atan2`'s magnitude stage |
| 0.36 ns | the hysteresis state machine's `state`/`width`/`peak` recurrence |
| 0.53 ns | the `valid_pdw_t` serializer's buffer |
| 0.73 ns | the NCO's signed-amplitude delay line |

Those proxy margins did not establish integrated AirStack timing. If integration
misses timing, the first path is cheap to fix: split the `atan2` magnitude stage, at +1
cycle, once per pulse. The second is a genuine per-sample recurrence, and it sets
the ceiling after that.

Getting there took eight timing fixes, each read off the reported critical path
rather than guessed. Two generalize:

* **Cross-module paths are invisible to per-block synthesis checks.** The
  generator→magnitude path (15.32 ns) and the phasor-accumulator→CORDIC path
  (11.65 ns) each met timing comfortably inside their own block; only the composed
  build showed them. Hence `top.py` being its own synthesis test.
* **A path can break with nothing on it having changed.**
  `d_im = cur_q·prev_i − cur_i·prev_q` needs two DSP48s, and with one pipeline
  register to place the synthesizer chooses which DSP absorbs it: one choice
  gives BRAM → DSP(A→MREG) ≈ 3.7 ns, the other BRAM → DSP A→P → DSP C setup =
  9.69 ns, i.e. 103 MHz. Both are legal and Vivado has picked each — this design
  met its target until adding the AXIS ports grew the netlist and flipped it. Registering **all four** raw
  products, not just their sums, removes the choice. A path that depends on a
  synthesizer's packing decision is not meeting timing, it is winning a coin toss.

The historical design propagated added registers through `.latency` attributes.
The current design goes further: completion joins absorb those delays without
querying them to construct hardware. Tests and independent models can still
inspect timing explicitly, while the datapath waits for valid results.
