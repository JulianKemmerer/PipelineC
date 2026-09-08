```
=============================================================================
                AIR7310 FPGA CORE (Pypeline HDL Architecture)
=============================================================================
 [Host Regs] ---> Sets: Thresholds (High/Low), Min/Max Width, PRI, Amp, Margins
=============================================================================

 1. STIMULUS & EXTERNAL LOOPBACK
 ----------------------------------------------------------------------------
  +-----------------+     TX1 Stream     +------------+      External Cable
  | Pulse Generator | =================> | TX1 RF Out | ===+   to Scope & RX
  +-----------------+                    +------------+    |
                                                           |
                                         +------------+    |
                                    +==> | RX1 RF In  | <==+
                                    |    +------------+
                                    |
 2. RECEIVE DATAPATH (125 MSPS I/Q) |
 -----------------------------------+
                                    v
 +-------------------------------------------------------------------------+
 | TIME-ALIGNED DETECT & DELAY MODULE                                      |
 |                                                                         |
 |   +-----------------------------------+  +---------------------------+  |
 |   | PATH A: DETECT & MEASURE          |  | PATH B: DELAY LINE FIFO   |  |
 |   +-----------------------------------+  +---------------------------+  |
 |   | 1. Magnitude ($I^2+Q^2$)   [L_mag]|  | Shifts raw I/Q to match   |  |
 |   | 2. DSP Conditioning        [L_dsp]|  | latency + N_pre margin    |  |
 |   |    -> DC Blocking / Removal       |  |                           |  |
 |   |    -> Moving Average Smoothing    |  | FIFO Depth =              |  |
 |   | 3. Hysteresis SM           [L_sm] |  |   L_mag + L_dsp + L_sm    |  |
 |   |    (High/Low Thresh Guard Bands)  |  |   + N_pre                 |  |
 |   | 4. Extract Candidate PDW          |  |                           |  |
 |   | 5. Phasor accumulate (freq) +     |  | reads the DELAYED raw     |  |
 |   |    noise-floor track (dB):        |  | I/Q, so a measurement     |  |
 |   |    4 mults, no CORDIC here        |  | describes exactly the     |  |
 |   |                                   |  | samples the host gets     |  |
 |   +-----------------------------------+  +---------------------------+  |
 +-------------------------------------------------------------------------+
                   |                   |                   |
   candidate_pdw_t |                   | (Real-Time Gate   | (Time-Aligned
   (toa, width,    |                   |  & tlast)         |  Raw I/Q)
    peak_power)    v                   v                   v
 +-------------------------------------------------------------------------+
 | QUALIFIED AXIS STORAGE & PDW ENGINE                                     |
 |                                                                         |
 |  1. Gate & Store: Ingest raw samples into Store-and-Forward FIFO        |
 |                   (Depth >= Max_Width + N_pre + N_post)                 |
 |                                                                         |
 |  2. DETECTION NUANCES & FILTERING (Post-Pulse Qualification):           |
 |     -> Glitch Rejection: Reject if pulse_width < Min_Width              |
 |     -> CW Rejection:     Reject if pulse_width > Max_Width              |
 |     -> Rule Validation:  Verify Candidate PDW against Host Regs         |
 |                                                                         |
 |  2b. MEASURE (once per pulse, ~16 cycles, pipelined):                   |
 |     -> Frequency:  CORDIC atan2 of the accumulated phasors              |
 |                    (start AND stop -> modulation on pulse)              |
 |     -> Power/Noise: log2 -> dBFS                                        |
 |     -> PRI:        toa - previous accepted toa                          |
 |                                                                         |
 |  3. Execute:                                                     |
 |     -> If Valid:   Emit valid_pdw_t & Commit/Release AXIS Packet        |
 |     -> If Invalid: Suppress PDW & Rollback/Flush FIFO                   |
 +-------------------------------------------------------------------------+
                   |                                       |
       valid_pdw_t |                                       | Released AXIS
       (toa, width,|                                       | (w/ tlast)
        peak_power,|                                       +---------+
        pkt_samples|                                                 |
        pri, dB,   |                                                 |
        freq start/|                                                 |
        stop,      |                                                 |
        status)    |                                                 |
                   v                                                 v
       +-------------------+                           +-------------+-------------+
       | Host Software     |                           |                           |
       | (PDW Metadata)    |                           v                           v
       |                   |                 +-------------------+       +-------------------+
       | [Valid/Ready Bus] |                 | SDR RX Chan Out   |       | TX2 RF Out        |
       +-------------------+                 | (To Host DMA)     |       | (Target Replay)   |
                                             +-------------------+       +-------------------+
```

# AIR7310 FPGA Core: System Architecture Overview

This document outlines a closed-loop, hardware-accelerated RF pulse detector and DRFM (Digital Radio Frequency Memory) repeater. It is designed to be implemented on the AIR7310 SDR using Pypeline HDL. 

The architecture is built to ingest raw RF, detect pulses in real-time, filter out glitches or continuous-wave interference, and output both the analytical metadata (the Pulse Descriptor Word, or PDW) and a bit-perfect replay of the physical waveform.

## 1. The Stimulus (External Loopback)
To make this a self-contained demonstration, the system generates its own test signals. An internal **Pulse Generator** synthesizes RF pulses, transmits them out of the SDR via **TX1**, and routes them through a physical loopback cable right back into the **RX1** receiver at 125 MSPS. 

## 2. The Time-Aligned Detect & Delay Module
Once the raw I/Q samples enter the FPGA, the datapath splits into two parallel tracks to solve the latency problem of real-time detection:

* **Path A (The Brain):** Calculates the instantaneous power (I^2 + Q^2), runs it through lightweight DSP (like DC blocking and smoothing), and feeds it into a Hysteresis State Machine. When a pulse ends, this path generates a **`candidate_pdw_t`**—a raw, unvalidated guess containing the start time, width, and peak power. It also accumulates, on the time-aligned raw I/Q, the phasor sums the frequency measurement is built from, and tracks the noise floor between pulses.
* **Path B (The Time Machine):** While Path A is doing math, Path B routes the untouched raw I/Q samples through a Delay Line FIFO. This FIFO is mathematically sized to delay the physical waveform by the exact time it takes Path A to compute, plus a pre-trigger safety margin (`N_pre`). 

## 3. The Qualified Storage & PDW Engine
This is the gatekeeper of the system. It takes the real-time triggers from Path A and the time-aligned samples from Path B and manages them using a **Store-and-Forward FIFO**. 

* **Store:** It absorbs the raw samples into memory in the background.
* **Qualify:** When it receives the `candidate_pdw_t` from Path A, it checks it against the host's rules. Did the pulse last long enough to be real (Glitch Rejection)? Was it too long (Continuous Wave Rejection)?
* **Execute:** 
  * If the pulse is **invalid**, the hardware drops the metadata and resets/flushes FIFO, completely erasing the glitch.
  * If the pulse is **valid**, the engine commits the packet for output.

## 4. Measurement
Detecting a pulse is not the same as describing one. Between qualification and
output, a per-pulse **measurement engine** turns the accumulations Path A
gathered into the quantities a PDW actually carries: the pulse's **frequency**
(start and stop, so a chirp is visible as modulation on pulse), its **peak
power and the noise floor in dB**, and the **interval since the previous
pulse**. This runs once per pulse rather than once per sample, which is what
makes a CORDIC and two logarithms affordable. See section 5.

## 5. The Outputs
When a pulse is validated, two things happen in hardware:

1. **Metadata to Host:** The engine upgrades the candidate struct to a **`valid_pdw_t`** (adding the total packet sample count and hardware status flags) and serializes it onto its own AXI-Stream master as one 40-byte frame.
2. **Raw Waveform Replay:** The Store-and-Forward FIFO releases the bounded AXI-Stream packet, framed with a `tlast` marker at the end. This pristine I/Q packet is **broadcast** to two masters at once: the **Host DMA** (for software analysis) and the **TX replay** port, to physically replay the pulse back to the target.

**On ordering.** Inside the engine the record is still handed over in
`EMIT_PDW` before `SEND_PKT` begins. On the wire that no longer means the
record's first beat comes first: it goes through a serializer whose first beat
costs a fill cycle the packet path does not pay, and then a skid buffer's
registered stage on top of that, so the record's first beat lands **after** its
packet's and the two then stream concurrently on separate ports. The exact skew
is `pdw_skid.latency` plus the serializer's fill, not a constant worth
memorising. What still holds — and what `pdw_tb.py` asserts
— is that record *k* begins before packet *k+1* does, so a record never slips
into the next pulse's slot. A consumer that needs `pkt_samples` before the
payload must therefore buffer or use `tlast`, rather than assume the metadata
stream leads.

# Top-Level Ports

Every top-level port is a flattened 32-bit AXI-Stream: `_tdata` (`uint32_t`),
`_tkeep` (4 bits), `_tlast`, `_tvalid`, `_tready`. Interface types live inside
the design; the boundary is plain `uintN_t`.

| Port | Dir | Carries | Beats/frame |
|---|---|---|---|
| `rx0_s_axis_*` | slave in | ADC I/Q samples, one sample per beat | free-running |
| `tx0_s_axis_*` | slave in | `pdw_ctrl_t` control-register struct | 10 |
| `rx0_m_axis_*` | master out | released pulse packet (broadcast leg 0) | N samples |
| `rx1_m_axis_*` | master out | `valid_pdw_t` records | 10 |
| `rx2_m_axis_*` | master out | `candidate_rec_t` records (observability) | 4 |
| `tx0_m_axis_*` | master out | pulse generator stimulus | free-running |
| `tx1_m_axis_*` | master out | released pulse packet (broadcast leg 1, replay) | N samples |

**Signals present for uniformity but not carrying information.** Each is
commented at its declaration in `top.py`:

* `rx0_s_axis_tkeep` — ignored; a sample beat is always four real bytes.
* `rx0_s_axis_tlast` — ignored; the ADC stream is continuous and unframed.
* `rx0_s_axis_tready` — **driven constant 1**; an ADC cannot be back-pressured.
* `tx0_m_axis_tkeep` / `_tlast` — constant `0xF` / `0`; the stimulus is
  continuous and unframed.
* `tx0_m_axis_tready` — **ignored**; a fixed-rate DAC cannot back-pressure a
  fixed-rate generator.
* `rx0_m_axis_tkeep` / `tx1_m_axis_tkeep` — constant `0xF`, one whole sample
  per beat.

> ⚠ **Tie `tx1_m_axis_tready` high if the replay port is unused.** The
> broadcast is a combinational valid/ready interlock, so it ANDs both legs'
> ready together — a leg held low wedges the host capture port as well.

Every master's `tlast` is qualified by that master's own `tvalid`, and on the
two broadcast legs that is not cosmetic. The interlock copies the source word
to every leg and then zeroes `valid` on a leg whose sibling is not ready yet,
so a leg can present `eod = 1` with `valid = 0`. That is legal *inside* the
library — AXI leaves `tlast` don't-care while `tvalid` is low — but a top-level
master must not emit it, and this design did until the reset work shifted the
stall alignment enough for `pdw_tb` to catch it. It is the same defect
`include/pypeline/axi/type_axis.py` records as `axis.h:539`, which is why that
testbench asserts the stricter invariant on every port rather than trusting the
producer.

**Backpressure policy.** Ready propagates backwards as each block already
intends and **stops at the store-and-forward FIFO**, which is the design's one
overflow point: `rx1_m_axis_tready` reaches the engine's `EMIT_PDW` state and
`rx0_m`/`tx1_m` reach `SEND_PKT`, so a stalled host backs up into that FIFO,
and when it fills, beats are dropped and the affected packet is flagged in-band
with `status_flags` bit 2. The datapath ahead of it is valid-only and
real-time; nothing back-pressures the ADC.

`rx2_m_axis` (candidates) is the exception: its `tready` is fully functional —
the serializer honours it and holds mid-frame — but it does **not** reach Path
A, which cannot stall. A candidate offered while the serializer is still busy
is dropped silently, with no status field. A deployed system is expected to tie
this port ready and ignore it; `pdw_tb.py` stalls it anyway so the path stays
real rather than decorative.

## Reset

Every channel carries an active-high `*_axis_rst` — `rx0_s_axis_rst`,
`tx0_s_axis_rst`, `rx0_m_axis_rst`, `rx1_m_axis_rst`, `rx2_m_axis_rst`,
`tx0_m_axis_rst`, `tx1_m_axis_rst`. All seven OR into one `global_rst`, one
register stage behind the pins (`RST_LATENCY`, exported from `top.py`). That
register is a fanout break, not a metastability synchroniser: these resets are
synchronous to the design clock, but the reset reaches the detector's input
valid, a 320-bit control-register mux, three FIFO read enables and a few dozen
register clears, which is more than a seven-input OR of pins should drive
combinationally in a design with ~2 ns of margin.

> ⚠ **Tie an unused channel's reset LOW.** A channel whose reset a platform
> holds asserted because the host never opened it holds the *entire* design in
> reset forever. `rx2_m_axis` is the likeliest to be hit, being already
> expected-unused above.

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

**Block.** The generator's output valid and the detector's input valid are
gated. One gate stops the whole detector: `detect_pulses` drives Path A and
Path B from the same input stream, and every piece of state behind it — the
hysteresis SM, the noise estimator, the phasor accumulators, `toa_counter` —
advances only on an accepted sample. All four master `tvalid`s (and their
`tlast`s) are gated too, so no drain traffic is ever visible outside.

**Drain.** While reset is asserted, every FIFO read enable is forced and the
buffers empty into the bit bucket. This is not a convenience — it is the only
mechanism available. The three FIFOs in `packet_store` and Path B's delay line
are `make_fifo` instances, black-box wrappers over `pipelinec_fifo_fwft.vhd`
exposing only push/pop, with no flush. Nothing can *clear* them, so their
contents have to be clocked out. Each block forces its own read enables
(`data_ready |= rst` and friends), so the packet path drains with no help from
the consumer: `pdw_reset_test.py` holds `pkt_out_ready` low for the entire reset
window and still gets a byte-exact drain.

Because the drain is only as fast as the data, **reset must be held**: emptying
a full packet FIFO takes up to its depth in cycles, ~131 µs at 125 MHz.
`top.py` exports `RST_MIN_HOLD_CYCLES`. Any real platform reset exceeds it
comfortably; a shorter one leaves buffers partly full.

**The two record serializers** are the one part the read-enable trick cannot
reach: `rx1_m`/`rx2_m` are fed by library serializers whose `buf`/`fill` empty
only through `tready`. Each therefore sits behind a **fully-registered AXIS skid
buffer** (`make_axis_skid_buffer`, `mode="full"` — two slots, +1 cycle, 100%
throughput), which derives both of its outputs from registers alone. That cuts
the port pin out of the serializer's ready path entirely, so reset can force
that ready unconditionally and the serializers drain like everything else.

The slice is load-bearing, not decorative. Driving the serializer's ready
straight from `pin | rst` was measured at **−8.3 MHz** (128.5 → 120.2, i.e.
missing the 125 MHz target): it put a LUT into the path feeding the serializer's
`nfill`, which is the *variable index* of a 43-element buffer write already 12
logic levels deep — a path `serializer.py` documents as combinational on
`stream_out_if.ready` by design, and one `make_type_to_axis` exposes no
`registered_ready` knob to break (only the deserializer side has one). With the
slice in place the OR lands on the slice's own registered output ready instead.

**Clear.** Every register in this project's own code returns to its power-on
value — the generator's LFSRs and phase accumulator (so the stimulus is
bit-reproducible across a reset), the hysteresis SM, the phasor accumulators,
the noise estimator, `packet_store`'s FSM and its write-side accumulators, and
`toa_counter`. Two pairings in that list are not optional:

* **`gate_armed` with the delay-line drain.** Path B's delay is
  self-establishing — it is however many pushes happen before the first drain,
  latched when the sticky `gate_armed` first sets. Drain the line without
  clearing `gate_armed` and the alignment is destroyed silently, with no
  symptom but wrong packet contents. `pdw_reset_test.py` has that as a negative
  control.
* **`prev_toa`/`have_prev` with `toa_counter`.** PRI is `toa - prev_toa`.
  Clearing the counter while leaving `prev_toa` holding a value from the
  previous epoch makes the first pulse after release report a wrapped, enormous
  PRI as though it were real. Cleared together, it reports
  `STATUS_PRI_INVALID`, exactly as the first pulse after power-on does.

Since `toa_counter` restarts, TOA is **not unique across a session**: two
pulses in different reset epochs can carry the same TOA. A host correlating
pulses across a channel reopen needs its own epoch counter.

### What reset does not reach

`magnitude`, `dc_block`, `moving_avg` and the CORDIC/`log2_db` pipelines are
library blocks in `include/pypeline/dsp/`, which this project does not put a
reset into. The pipelines are valid-gated and self-flush, but `dc_block`'s
running mean and `moving_avg`'s window are *frozen* by the input gate and thaw
still holding pre-reset power.

The visible consequence: for a sample or two after release the conditioned
power reads high, and the hysteresis SM declares a tiny pulse that never
happened. `min_width` (glitch rejection) is exactly the mechanism for it, so a
deployment that sets `min_width` at all never sees it — but a deployment that
leaves `min_width` at its default of 0 will see one spurious short PDW after
each mid-stream reset. `pdw_reset_test.py` measures the artifact (2 samples)
and asserts it stays below the `min_width` used there, so a future change that
lengthened it fails loudly instead of quietly leaking real-looking PDWs.

## Control registers (`pdw_ctrl_t`)

Written as one 40-byte frame on `tx0_s_axis_*` into a local register file with
power-on defaults (`pdw_ctrl/pdw_ctrl.py`). Framing policy is exactly sized:
a frame **longer** than 40 bytes has its excess dropped, and a frame
**shorter** is discarded, leaving the registers untouched — neither can desync
the frames that follow.

| Field | Type | Meaning |
|---|---|---|
| `pulse_gen_pri` | `uint32_t` | Generator PRI, in samples |
| `pulse_gen_width` | `uint32_t` | Generator pulse width, in samples |
| `pulse_gen_freq` | `int32_t` | Carrier phase increment/sample, turns × 2³² |
| `pulse_gen_chirp_rate` | `int32_t` | Added to that increment each pulse sample (LFM) |
| `pulse_gen_amplitude` | `int16_t` | Peak I/Q amplitude |
| `pulse_gen_noise_amp` | `uint16_t` | LFSR noise scale; 0 disables |
| `threshold_high` | `uint32_t` | Hysteresis SM upper threshold |
| `threshold_low` | `uint32_t` | Hysteresis SM lower threshold |
| `max_width` | `uint32_t` | Path A force-close cap **and** CW rejection |
| `min_width` | `uint32_t` | Glitch rejection |
| `flags` | `uint32_t` | bit 0 = `CTRL_FLAG_LOOPBACK_EN` |

Control is never back-pressured (`tx0_s_axis_tready` is always 1) and new
values are readable `pdw_ctrl.latency` cycles after a frame's last beat is
accepted. That number is measured by `pdw_ctrl/pdw_ctrl_test.py` rather than
asserted, and `pdw_tb.py` reads the attribute rather than hardcoding it.

The defaults leave an unconfigured device **quiet and in a known state**, not
merely zeroed: amplitude 0 and `pri = 1` mean the generator emits zeros with
its PRI counter pinned at 0 (so it starts from a defined phase the instant a
real PRI is written), and the thresholds sit at their maximum so the hysteresis
SM cannot leave IDLE. Zero thresholds would instead declare one continuous
pulse forever. With the staged bring-up above, a device that follows the
sequence never actually runs on them — they are the safety state for one that
does not.

Reset for this block is `tx0_s_axis_rst` alone (see **Reset**). While it is
asserted the registers are pinned to the defaults, so a frame arriving then is
decoded and discarded; the deserializer is flushed at the same time, so a host
torn down mid-frame cannot leave a byte prefix that joins up with the next
frame into a struct that is wrong but perfectly well formed.

# Host software (AirStack / SoapySDR)

`airt_pdw_test.py` brings the design up on a Deepwave AIR-T and verifies its
output. It is **not** part of `run_all.py` — it needs SoapySDR and hardware —
but everything it depends on is covered in-repo without a radio (see
**Testbenches**).

**Three files copy to the radio**, with no Pypeline checkout: `pdw_ctrl_record.py`
(builds control frames), `gr_pdw_record.py` (parses records, and gr-pdw's
columns) and `pdw_verify.py` (checks a record against its samples). Each carries
its layout in pure `struct`; `pdw_host_types_test.py` guards those copies
against drift.

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
`dwd_tx1_m_axis_tready` **HIGH** as well: this design has no `tx1_s_axis` port
to consume software's writes to that channel, so without it the priming write
below blocks on the very port it is meant to unblock.

## CS16 is the design's own packing

Deepwave specifies `I = tdata[15:0]; Q = tdata[31:16]` — identical to this
project's convention. A CS16 buffer is interleaved little-endian `int16`, so
four bytes of an `np.int16` buffer **are** one 32-bit AXIS beat. Conversion is
`np.frombuffer(raw, '<i2')` and `.tobytes()`: a reinterpret, never a conversion,
with no byte swapping anywhere. A 40-byte record or control frame is exactly ten
CS16 elements.

## Thresholds are scaled, and amplitude is capped

The easiest thing for a host program to get wrong. `threshold_high`/`threshold_low`
are compared against `power_t`, which carries **12 fractional bits**, so the
integer on the wire is `power × 4096` — see the threshold-scaling note in
section 2. `pdw_ctrl_record.POWER_SCALE` holds that factor and
`pdw_host_types_test.py` pins it against `power_t.frac_bits`.

It fails silently in both directions: 4096× too small is crossed by the noise
floor and the detector declares one endless pulse; 4096× too large is never
crossed and the device looks dead. Both present as "the hardware is broken".

The same scaling caps amplitude near **1024** (`MAX_AMPLITUDE`), since
`threshold_high` and the record's `peak_power` are both `uint32_t` holding
`power × 4096`. `build_config` refuses anything larger rather than letting it
wrap, and `--dry-run` prints thresholds in both raw and power units so the
factor is visible before a frame is ever sent.

## Bring-up order

The two reset domains exist for this sequence, and it is not optional:

1. nothing activated — all resets asserted, buffers draining
2. `activateStream(TX,0)` **alone** — control block live, datapath still held
3. write one `pdw_ctrl_t` frame — config lands, datapath still held
4. activate RX0, RX1, TX1 — datapath starts **already configured**

Step 4 is the payoff, and it also gives the capture loop its RX0/RX1 lockstep
for free: because `global_rst` is the OR, nothing is emitted until every stream
is open, so both streams start empty whatever order they activate in.

Hold reset at least `RST_MIN_HOLD_CYCLES` (16448, ≈132 µs at 125 MHz) before
re-activating — the drain is only as fast as the data (see **Reset**).

## Framing, without an end-of-burst on receive

`writeStream` produces a `tlast` cycle via `SOAPY_SDR_END_BURST`, which is how
the control frame gets framed. **`readStream` surfaces no such marker**, so the
receive side is framed by counting: records are a fixed 40 bytes, and each
record's `pkt_samples` gives the exact length of the packet that follows it.

That works because `pkt_samples` is the **true on-wire length** — it is written
from `n_pushed`, which counts only beats that actually entered the FIFO, so even
a packet that lost beats to a full FIFO stays length-accurate and one damaged
packet cannot desync the stream.

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

## Verifying the records against their own samples

`pdw_verify.py` checks each record against the packet it describes, using an
**FFT** — where the hardware uses phasor accumulation plus a CORDIC atan2. That
difference is the point: two independent algorithms agreeing is evidence, while
a Python re-implementation of the phasor method would only re-check the
arithmetic and would agree with a conceptually wrong design. It takes its FFT
over the same window `freq_accum` accumulates over (`block_k` = 32), which
matters only for a modulated pulse but matters a lot there.

Because the generator is internal and the host commanded it, the comparison is
three-way — **commanded** (the `pdw_ctrl_t` written) ↔ **software** (numpy over
the samples read back) ↔ **hardware** (the record). The first leg proves the
samples are the pulse that was ordered; the second proves the measurement
matches those samples.

What is honestly checkable is narrower than the record, and the module says so:

| Field | Check |
|---|---|
| `freq_start`, `freq_stop` | independent and absolute — the strongest here |
| `pkt_samples`, `pulse_width`, `pri`, `toa` | exact integers |
| `peak_power_db` | exact against `peak_power`, to the log block's own 0.046 dB |
| `peak_power` | **approximate, and duty-cycle dependent** — Path A is `magnitude → dc_block → moving_avg`, so the reported peak is a DC-blocked, smoothed envelope, not `max(I²+Q²)`. The DC blocker subtracts a running mean, so the higher the duty cycle the more of the pulse's own power gets subtracted back out: measured across `pdw_tb.py`'s phases (duty cycles up to ~50%) the ratio ranges **0.035–0.64**. Near 1 at a realistic duty cycle. A wide-tolerance ratio check whose measured value is always reported |
| `noise_power_db` | **not checkable** from a packet — the floor is estimated between pulses. Bounded by SNR > 0 only |

`--csv` writes gr-pdw's own nine columns via `gr_pdw_record.write_csv`, readable
by its `pdw.py` tooling unmodified; `--ref-level-db` matches what gr-pdw's
`usrp_power_cal_table` block adds.

**RF note.** With loopback enabled the detector is fed internally, but TX0 still
carries the generator's samples to the radio. Bench work wants a cable and
terminator, not an antenna.

# Parameters

## 1. Base Clock & Data Path

| Parameter | Value |
|---|---|
| System clock | 125 MHz (8 ns/cycle) |
| Sample rate | 125 MSPS |
| Raw I/Q format | One complex sample per cycle (`int16_t I`, `int16_t Q` packed into a single 32-bit word: `I = tdata[15:0]`, `Q = tdata[31:16]`). AXI-Stream (`tdata`/`tvalid`/`tready`/`tlast`) is the top-level module interface only; internally, blocks are connected with Pypeline `stream(sample_t)` (valid/ready handshake, no AXIS overhead) |
| Power format ($I^2+Q^2$) | `uint32_t` (max $2\times(2^{15}-1)^2$ fits without saturation logic) |

## 2. Configuration Parameters

Runtime-configurable knobs, each a flat input wire into the design (no register bus/protocol — plain top-level ports).

| Parameter | Type | Default | Meaning @ 125 MSPS |
|---|---|---|---|
| `threshold_high` | `uint32_t` | 2,500,000 | Power level to declare pulse START |
| `threshold_low` | `uint32_t` | 1,000,000 | Power level to declare pulse END |
| `min_width` | `uint32_t` | 12 | 96 ns; pulses shorter than this are rejected (glitches) |
| `max_width` | `uint32_t` | 12,500 | 100 µs; pulses longer than this are rejected (CW/jamming) |
| `n_pre_margin` | `uint16_t` | 16 | 128 ns; samples captured before threshold crossing |
| `n_post_margin` | `uint16_t` | 16 | 128 ns; samples captured after dropping below threshold |
| `test_gen_pri` | `uint32_t` | 125,000 | 1 ms; PRI for the internal loopback tester |
| `test_gen_width` | `uint32_t` | 125 | 1 µs; width of the internally generated test pulse |
| `test_gen_freq` | `int32_t` | 0 | Carrier: phase increment per sample, in turns × 2³². 0 is DC, 2³¹ is Fs/2, negative is a negative frequency |
| `test_gen_chirp_rate` | `int32_t` | 0 | Added to that increment on every sample of a pulse, giving a linear-FM chirp |
| `test_gen_noise_amp` | `uint16_t` | 0 | Scales a deterministic LFSR noise source added to both rails |

**The generator's carrier is not decoration.** The first version emitted a flat
DC amplitude step with `Q` hardwired to zero — a signal at exactly 0 Hz. Every
frequency measurement downstream is untestable against such a stimulus: an
estimator with an inverted sign, a broken quadrant fix, or one that returns a
constant zero all agree with the correct answer on a real-only input. The chirp
control matters for the same reason one level up: with a pure tone, start
frequency and stop frequency are bit-identical, so a wrong stop-frequency
implementation still passes. The noise source mirrors the Gaussian source in
gr-pdw's own reference flowgraph, and is what makes a measured noise floor and
SNR mean anything. All three are deterministic, so golden models stay
bit-exact.

The carrier comes from a phase accumulator driving a rotation-mode CORDIC
(`include/pypeline/dsp/cordic.py`), not a lookup table: there is no RAM or ROM
primitive in the Pypeline library, and a table coarse enough to be affordable
as an unrolled constant mux would quantize the phase badly enough to bias the
very measurement it exists to test.

**Threshold scaling (as actually built in `top.py`/`pulse_detect.py`).** `threshold_high`/
`threshold_low` are compared against `detect_pulses.power_t` — the DC-blocked,
moving-averaged power estimate — which carries **12 fractional bits**
(`dc_k`(10) + `log2(ma_n)`(2), both `make_detect_pulses()` defaults). So the
raw integer driven into these `uint32_t` ports must be `4096 ×` the intended
power level in `magnitude`'s own units (raw $I^2+Q^2$, 0 fractional bits) —
the example values above are illustrative round numbers, not derived from
this scaling. The `uint32_t` port width in turn caps the usable range to real
power $\lesssim$ 1,048,576 (i.e. a rail amplitude of roughly $\lesssim$ 1024
before `threshold_high` can no longer represent it). `pdw_tb.py` (section 6
below) derives its thresholds programmatically from the golden power model
for exactly this reason, rather than hand-picking round numbers.

**Qualification rules as built** (`pdw_engine/pdw_engine.py`,
`make_pdw_qualify`). `min_width` and `max_width` are both live:

* **Glitch rejection** is `pulse_width < min_width`, exactly as above.
* **CW rejection** is `pulse_width >= max_width`, *not* the table's literal
  `> max_width`. The hysteresis SM force-terminates a runaway pulse the moment
  its width reaches `max_width` and emits exactly one candidate of that width
  (see `make_pulse_detect_fsm`), so `== max_width` **is** the CW marker and a
  strict `>` would never fire.
* Consequence worth stating plainly: **`max_width` is a detection limit, not
  just a rejection threshold.** A genuine pulse longer than `max_width` is
  reported as CW and discarded, indistinguishably from a jammer.

`n_pre_margin`/`n_post_margin` are still **not implemented** — the packet is
exactly the detected pulse's gate window, so `pkt_samples == pulse_width` for
every accepted pulse. See section 3's note on what adding them involves.

## 3. FIFO Depths

Note: the per-stage cycle counts below ($L_{mag}$, $L_{dsp}$, $L_{sm}$) are rough estimates for sizing intuition only. Actual pipeline latencies are determined automatically by Pypeline's AUTOPIPELINE tooling, not hand-specified — FIFO depths must be pinned to the real measured latencies once the design is built, not these placeholder numbers.

**Delay Line FIFO (Path B)**
$$L_{mag}(3) + L_{dsp}(8) + L_{sm}(1) + N_{pre}(16) = \textbf{28 cycles}$$
Round up to 32 deep.

**As built: self-timed, not fixed-depth.** `make_delay_line` no longer sets
the delay from `delay_depth` at all. It pushes on every valid input sample and
drains on the hysteresis SM's `gate_advance` — a signal built as the
*structural twin* of the SM's own `gate_valid` register chain (the same two
`if accepted:`-gated registers, with `in_pulse` replaced by a constant 1). A
FWFT FIFO held un-drained loads its output register once and then freezes, so
the queue behind it grows one entry per push; the achieved delay is exactly
the number of pushes that happened before the first drain. Since draining
begins on the first cycle a gate beat could exist, the delay lands on
$L_{dsp} + L_{sm}$ automatically, for any DSP latency, with **no cycle count
written down anywhere**. Each gate beat therefore carries precisely the raw
sample whose power produced it. `delay_depth` (now 64) is capacity only, and
over-sizing it is free for correctness; `make_delay_line` `sim_assert`s if it
is ever too small.

Two things this replaced are worth recording, because both were wrong in the
same direction and agreed with each other:

* The old code pushed *and* drained every cycle, so it only ever realised the
  FIFO's incidental 2-cycle push-to-valid latency regardless of `delay_depth`.
* The originally-documented fix — drain from the cycle `moving_avg`'s `.valid`
  first asserts — gives a delay of $L_{dsp}$, which is short by $L_{sm}$. The
  gate stream trails the SM's *input* sample by two accepted samples (two
  register hops: `held_in_pulse` → `gate_valid_r` → presented pre-update), so
  the correct delay is $L_{dsp} + L_{sm}$. `pdw_tb.py`'s golden model indexes
  `raw[s - gate_latency]` and asserts that against
  `detect_pulses.get_path_b_delay()`, so this cannot drift again silently.

**Store-and-Forward Packet FIFO**
$$Max\_Width(12500) + N_{pre}(16) + N_{post}(16) = \textbf{12,532 cycles}$$
Round up to 16,384 deep (16K).

**As built** (`pdw_engine/pdw_engine.py`, `make_packet_store`). The reject path
is described above as "Rollback/Flush FIFO", which suggests rewinding a write
pointer. That is not available: `make_fifo` (`include/pypeline/fifo.py`) is a
black-box wrapper over `src/vhdl/pipelinec_fifo_fwft.vhd` exposing only
push/pop — no pointers, no occupancy, no commit/drop — and there is no RAM
primitive in the Pypeline library. (Amusingly the VHDL still carries the
vestigial `wr_ptr_cur_reg`/`full_cur` signals of the upstream `axis_fifo.v`'s
`FRAME_FIFO`/`DROP_BAD_FRAME` machinery, with the drop logic stripped out —
restoring it is a possible future optimisation.)

So the equivalent behaviour is built from **two plain FIFOs plus a counter**: a
data FIFO holding every gate beat, and a small descriptor FIFO holding one
entry per completed pulse (the finished `valid_pdw_t` plus an accept bit). The
read side pops a descriptor and then moves exactly `pkt_samples` beats —
downstream if accepted, into the bit bucket if not. Observably identical to a
rollback, at the cost of spending read bandwidth to discard; affordable
because a glitch is by definition shorter than `min_width`, and a CW event
parks the SM in RECOVER (emitting no beats at all) while its `max_width` beats
drain. The data FIFO wraps a BRAM-inferable VHDL entity, so 16K × 32 bits is
block RAM, not flops.

The beat count stored in the descriptor is the number of beats **actually
pushed**, not the candidate's `pulse_width`. That is what makes the read side
robust to a full FIFO: the flush count still matches what is really buffered,
so one corrupt packet cannot desynchronize every packet after it. (That packet
is force-rejected anyway and flagged in its own `status_flags` bit 2.)

**Adding N_pre/N_post** (not built) needs the Path B delay line deepened by
$N_{pre}$ and the gate held open $N_{post}$ beats past `gate_last`. At that
point `pkt_samples` stops equalling `pulse_width`, which is why it is a
separate field rather than a derived one.

## 4. PDW Output Structures

**`candidate_pdw_t`** (internal to FPGA)

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | Time of arrival (~4,424 years to roll over) |
| `pulse_width` | `uint32_t` | Raw duration in clock cycles |
| `peak_power` | `power_t` | Highest $I^2+Q^2$ value recorded during the pulse |

**`candidate_rec_t`** (the port-facing form, on `rx2_m_axis_*` — 16 bytes, four
beats) is the same three fields with `peak_power` truncated to `uint32_t`.
`candidate_pdw_t`'s own `peak_power` is the 46-bit `power_t`, which would make
an 18-byte record with a ragged final beat; truncating is exactly what
`valid_pdw_t.peak_power` already does, so the two observability views of the
same pulse report the same number.

**`toa` as built.** A free-running counter inside `make_pulse_detect_fsm`,
latched on the `IDLE -> PULSE` edge (read-before-increment, so it is the index
of the same sample that sets `pulse_width = 1`). It counts the SM's own
*accepted input samples* — i.e. the conditioned power stream — so it trails
the raw ADC sample index by a constant $L_{mag} + L_{dsp}$. The SM cannot see
its own upstream latency, so that bias is documented rather than corrected;
subtract `detect_pulses.get_dsp_latency()` if an absolute ADC-referenced time
is needed.

**`peak_power` as built**, in both structs, is the 46-bit `power_t` field (see
the threshold-scaling note in section 2) truncated to `uint32_t`. Keep a
pulse's peak under $2^{32}$ in `power_t`'s scaled units or this field silently
wraps; `pdw_tb.py` asserts this at build time for every phase it drives.

**`valid_pdw_t`** (sent to host via DMA — 320 bits / 40 bytes, ten 32-bit beats)

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | Time of arrival, carried through from the candidate |
| `pulse_width` | `uint32_t` | Validated width, in samples |
| `peak_power` | `uint32_t` | Validated peak power, linear |
| `pkt_samples` | `uint32_t` | Total AXI-Stream payload size ($N_{pre} + width + N_{post}$); tells DMA how many samples to slice. **Equals `pulse_width` today** — margins are unbuilt |
| `pri` | `uint32_t` | Samples since the previous **accepted** pulse |
| `peak_power_db` | `int16_t` | Peak power in dBFS, Q8.8 (1 LSB = 1/256 dB) |
| `noise_power_db` | `int16_t` | Noise floor in dBFS, Q8.8 |
| `freq_start` | `int16_t` | Frequency over the first samples of the pulse, in turns × 2¹⁶ — the full `int16` range spans ±½ turn, so multiply by the sample rate for Hz |
| `freq_stop` | `int16_t` | Frequency over the last samples of the pulse. Differs from `freq_start` exactly when the pulse is modulated |
| `status_flags` | `uint32_t` | Bit 0 = ADC Clip, 1 = DSP Overflow, 2 = Packet FIFO Full, 3 = Frequency Degenerate, 4 = PRI Invalid |
| `channel` | `uint16_t` | RX chain index. Always 0 — this is a single-channel design |
| `padding` | `uint16_t` | Reserved, aligns the struct to 320 bits / 40 bytes |

There is deliberately **no SNR field**: it is `peak_power_db - noise_power_db`
and both are present, so the host subtracts. A hardware SNR would span ±135 dB
and not fit the Q8.8 the other two use. gr-pdw's own file record likewise
carries pulse power and noise power as separate columns rather than an SNR.

`status_flags` is accumulated per packet across all of its beats and re-armed
on each `last`. ADC clip is measured on the **stored** sample — the
time-aligned raw I/Q that actually goes into the packet — so the flag
describes what the host receives, not what the live ADC input was doing.

A `valid_pdw_t` is emitted **before** its own packet's first beat, on a real
valid/ready handshake, which is the order a DMA consumer needs to size the
transfer that follows.

## 5. Pulse Measurements

Detection alone makes an energy detector. What makes a PDW is the measurement,
and this is where most of the work went.

### The fast path / measurement path split

The organizing idea, and what makes a CORDIC and two logarithms fit in a design
that had ~5% timing margin to spare:

* **Fast path — every sample, 125 MSPS.** Kept tiny. It gained exactly four
  multipliers (a conjugate product), a few accumulators, and one leaky
  integrator. No CORDIC, no logarithm, no division.
* **Measurement path — once per pulse.** Iterative and pipelined, ~16 cycles.
  A pulse closes at most every `min_width` samples and realistically every PRI
  (~125,000 samples), so this hardware is idle almost all the time.

Measured cost of the fast-path addition: **zero timing margin** (the detector
subsystem closes at 130.9 MHz both before and after) and about 400 LUTs, 350
flip-flops and 4 DSP48s.

### Frequency

The instantaneous frequency between consecutive samples is the angle of
$z[n]\cdot\overline{z[n-1]}$. The obvious implementation takes an arctangent
per sample and averages the angles; this one **accumulates the products first
and takes a single angle per pulse**. That is both far cheaper — one `atan2`
per pulse instead of one per sample at 125 MSPS — and more accurate: summing
the phasors is the maximum-likelihood estimator for a tone in white noise,
whereas averaging angles weights a noisy sample as heavily as a strong one.

`freq_start` and `freq_stop` come from two accumulator sets: the first
`block_k` products of the pulse, and a ping-pong block accumulator holding the
most recent `block_k`..`2·block_k`. An unmodulated pulse gives the same angle
for both; an LFM chirp gives two different ones, which is modulation-on-pulse
detection for the cost of one extra accumulator pair.

The angle itself comes from a vectoring-mode CORDIC
(`include/pypeline/dsp/cordic.py`) — 14 iterations, no multiplier, no lookup
table, one register stage per iteration. Angles are carried in **turns**, not
radians, so converting to Hz is a pure scale by the sample rate with no π
anywhere. Measured worst-case error is 3.4 × 10⁻⁵ turns (≈4.3 kHz at 125 MSPS),
and it is *flat* from a phasor magnitude of 2³ to 2³⁷ — the input is normalized
by count-leading-zeros first, so a weak pulse is measured as accurately as a
strong one.

**This is a deliberate divergence from gr-pdw's algorithm**, and the first
thing its authors would ask about. gr-pdw zero-pads the pulse, takes an FFT and
picks the peak bin, because in numpy that is free. In an FPGA it is not: there
is no RAM/ROM primitive in the Pypeline library for the twiddle table, and a
256-point FFT would dwarf the entire rest of this design. The phasor-sum
estimator costs 4 DSP48s and gives a continuous-valued frequency rather than
one quantized to an FFT bin.

### Power and the noise floor

`peak_power_db` and `noise_power_db` come from a shared conversion
(`include/pypeline/dsp/log2_db.py`): count-leading-zeros for the exponent, plus
a 4-segment piecewise-linear correction for the mantissa, with the
$10/\log_2 10$ scaling folded into the stored constants. Worst-case error is
**0.046 dB** measured over 300k random inputs against `10·log10`.

Two things are easy to get wrong here and are worth stating:

* **The fractional bits must be subtracted.** `power_t` is a fixed-point type,
  so the integer the hardware holds is $2^{12}$ times the value it represents.
  Taking dB of the raw integer both reports the wrong number and overflows the
  output — the raw range reaches 135.5 dB, past Q8.8's +128, while the true
  represented range is −36.1 … +99.4 dB and fits comfortably.
* **The noise floor cannot be measured after the DC blocker.** `dc_block`
  subtracts the running mean of the power, which *is* the noise floor, leaving
  a residual that sits at zero. The estimator therefore runs on the
  **pre-`dc_block` magnitude**, gated by the hysteresis SM's `in_idle`.

That gate needs one more thing. `in_idle` is aligned with the SM's input, which
lags the magnitude stream, so on every pulse's leading edge a few samples the SM
still calls idle have already risen. Folding those in makes the reported noise
floor a duty-cycle-weighted fraction of the *pulse* power — measured at ~10 dB
below peak regardless of the actual noise, which is a plausible-looking number
that means nothing. So a sample must also *look* like noise: no more than 4×
the running estimate, plus a seed so the estimator can start from zero. This is
the standard sample-excision guard a CFAR noise estimator uses, and it needs no
knowledge of the pipeline latency — which matters, because those latencies are
AUTOPIPELINE results that deliberately are not available at elaboration time.

With the guard in place, a phase driven with `noise_amp=8` measures a
**16.22 dBFS** floor, against **16.2 dBFS** predicted by hand from the LFSR's
statistics; phases with no noise report the converter's floor, as they should.

### PRI

`toa - prev_toa`, taken between **accepted** pulses so a rejected glitch cannot
corrupt the interval reported for the next real one. PRI is also the one
measurement immune to `toa`'s documented DSP-latency bias, since a constant
offset cancels in a difference. The first accepted pulse after reset has no
predecessor, so it reports 0 and sets `status_flags` bit 4 rather than emitting
a meaningless number.

### Mapping to gr-pdw's record

`gr_pdw_record.py` (host-side Python, no hardware) parses the 40-byte records
and produces gr-pdw's own nine-column `float64` array, so its `pdw.py` reader,
pandas and HDF5 flow work on FPGA output unmodified:

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

Two honest caveats, both stated in that module's docstring rather than papered
over:

* **`ref_level` is a host-side additive offset**, exactly as in gr-pdw
  (`pulse_power = dbfs + ref_level`). Its USRP calibration-table blocks stay on
  the host; the FPGA emits dBFS.
* **TOA is not a unix timestamp.** gr-pdw's coarse column is integer unix
  seconds from the host clock. This design has no PPS input and no
  time-of-day register, so `toa` counts samples since FPGA reset and the split
  above is a formatting convenience. It also carries the constant DSP-latency
  bias described in section 4.

### Known limitation: I/Q DC offset

The frequency estimator runs on the raw I/Q, and `dc_block` operates on the
*power*, not on the I/Q rails. A DC offset on either rail therefore adds a 0 Hz
component that pulls the measurement toward zero, roughly in proportion to
$|d|^2/|s|^2$. The internal generator is zero-mean by construction (the LFSR
noise is read as signed, deliberately — see `pulse_gen.py`), so this does not
show up in simulation, but a real receiver's ADC/mixer offset would. Correcting
it needs an I/Q DC blocker ahead of the conjugate product, which is not built.

## 6. Testbenches

| File | Scope | Style |
|---|---|---|
| `pulse_gen/pulse_gen_tb.py` | Pulse generator alone | `sim_assert`, hardware-generated stimulus |
| `pulse_detect/pulse_detect_tb.py` | Bare hysteresis FSM (`make_pulse_detect_fsm`), hand-fed a power stream — elastic, valid_only, and CW/`max_width`-cap variants | `sim_assert`, hardware-generated stimulus |
| `pdw_engine/pdw_engine_tb.py` | The PDW engine alone (`make_pdw_engine`), hand-fed synthetic gate streams — accept path + PDW/packet ordering, glitch reject, CW reject, `status_flags`, long-stall backpressure | `sim_assert`, hardware-generated stimulus |
| `src/tests/pypeline_tests/inst/cordic_test.py` | `dsp/cordic.py` alone — atan2 across all four quadrants and both axes, the (0,0) degenerate case, the ±½-turn boundary, pipeline throughput, and a second instantiation at different widths | `sim_call` vs a bit-exact model and vs `math.atan2` |
| `src/tests/pypeline_tests/inst/log2_db_test.py` | `dsp/log2_db.py` alone — accuracy vs `10·log10`, decade/octave steps, the fractional-bits subtraction, non-positive input, monotonicity, and two instances with different binary points | `sim_call` vs a bit-exact model |
| `pdw_ctrl/pdw_ctrl_test.py` | The control register file alone — reset defaults, apply latency (measured, then checked against the advertised attribute), ready never dropping, back-to-back writes, and the two malformed cases: a padded frame whose excess must be dropped and a runt that must leave the registers untouched, neither desyncing the frame after it; plus reset — writes refused while held, normal service after release, and an abandoned frame flushed rather than joined to the next | `sim_call`, `type_to_bytes` + `AxisSimSource` |
| `pdw_reset_test.py` | Reset semantics for the composed datapath — a reset landing **mid-pulse**: nothing emitted for the interrupted pulse, its buffered samples drained rather than prepended to the next packet, TOA and PRI restarting, and the release artifact bounded below `min_width`. Both the drain term and the `gate_armed` clear have negative controls | `sim_call` on `detect_pulses` + `pdw_engine` wired as `top.py` wires them |
| `pdw_host_types_test.py` | The host-side copies of both wire formats (`pdw_ctrl_record.py`, `gr_pdw_record.py`) and `pdw_verify.py`'s pinned constants, against the real `pdw_ctrl_t`/`valid_pdw_t`/`power_t`/`block_k`. Test vectors set every unsigned field's top bit and make every signed field negative, so a wrong width or signedness changes the bytes — an earlier version's plausible-looking values let a deliberate `uint64→int64` corruption pass unnoticed | pure Python vs `type_to_bytes` |
| `pdw_verify_test.py` | That `pdw_verify.py` actually catches a wrong record. Mostly negative controls: corrupt one field, assert the check for **that** field fails and the others do not — a dB-only error must not fail the linear check, and a corrupted `freq_start` must not fail `freq_stop` | numpy, synthetic pulses (tone, chirp, negative carrier) |
| `pdw_tb.py` | The whole `top.py` — pulse generator through the composed DSP chain (`make_detect_pulses`: magnitude → dc_block → moving_avg → hysteresis FSM), the Path B delay line, the loopback mux, the PDW engine, and all seven AXIS ports: control written as real frames, both record streams decoded, the released-packet broadcast compared leg against leg, the staged two-domain reset bring-up, and `pdw_verify.py` run over every (record, packet) pair | `@sim_input`/`@sim_output`, exact Python golden model |

`pdw_engine_tb.py` exists alongside `pdw_tb.py` rather than being folded into
it because it reaches cases the real detector cannot produce on demand — most
importantly the ADC-clip flag, which is unreachable end-to-end: an amplitude
that clips the `int16` rail produces a power far past what the `uint32_t`
threshold ports can represent (see section 2's scaling note). It also uses a
counter as the sample value, so a dropped, duplicated or reordered beat shows
up as a wrong integer with no golden model in the way.

`pdw_tb.py` is the only one that exercises `top.py` itself rather than a
submodule in isolation — the only test of `make_detect_pulses`, the Path B
delay/gate, the engine against real detector output, and every top-level AXIS
port of this project. It configures the generator, detector and engine by
**writing real control frames** on `tx0_s_axis_*` (one per phase, built with
`type_to_bytes`, driven by `AxisSimSource`), setting `CTRL_FLAG_LOOPBACK_EN`
from phase 0 onward — exercising the internal generator loopback path, not the
external `rx0_s_axis_*` cable path, on which a garbage pattern is deliberately
driven so a broken loopback mux fails loudly rather than silently passing.

It then checks all four master streams — `rx0_m_axis_*` (released packets),
`tx1_m_axis_*` (the replay leg), `rx1_m_axis_*` (PDW records) and
`rx2_m_axis_*` (candidate records) — against a golden model built from
`include/pypeline/dsp/dsp_tb.py`'s exact integer models
(`golden_magnitude`/`golden_dc_block`/`golden_moving_avg`, run against the
*same* `magnitude`/`dc_block`/`moving_avg` instances `top.py` built — exposed
via `detect_pulses.magnitude`/`.dc_block`/`.moving_avg`) plus a
hand-transcribed Python model of the hysteresis FSM, the gate, and the engine's
qualification. Records are decoded with `type_from_bytes`, and each PDW frame
is *additionally* pushed through `gr_pdw_record.unpack_records()` and compared
field by field, so the host-side decoder is tested against real hardware bytes
rather than only against a synthetic record.

At the end of the run it also feeds every (record, packet) pair to
`pdw_verify.py` — the same code that will judge records on the radio, here meeting
real hardware output for the only time it can without a radio. That adds
something the golden model cannot: the model reproduces the hardware's *own*
phasor/CORDIC arithmetic, so it would agree with a conceptually wrong frequency
estimator, whereas `pdw_verify` takes an FFT of the released samples and so
disagrees if the measurement is wrong rather than merely self-consistent. Only
the unambiguous rows are asserted; the `peak_power` ratio is printed, because
Path A's DC blocker and moving average make it approximate by construction and
these phases run down to amplitude 400 with noise enabled, where that
approximation is weakest.

Checking follows the wireguard-fpga testbenches' `AxisSimSource`/`AxisSimSink`/
`Scoreboard` pattern (`include/pypeline/axi/axis_sim.py`): one sink and one
scoreboard per output stream, `expect()`ed from the golden model, `check()`ed
in arrival order. Every sink also enforces Xilinx-style `tkeep` compliance on
every beat it accepts, which is what checks the constant-keep sample ports.
All four consumers are stalled on mutually prime periods — the two
released-packet legs on *different* ones, which is what exercises the broadcast
interlock's ready AND rather than merely passing one ready through. The replay
leg's frames are compared byte-for-byte against the capture leg's; that is the
only check of the fanout, since leg 1 could be mis-wired to a stale register
and everything else would still pass.

**Control timing is pinned, not assumed.** Each phase's frame is scheduled from
`pdw_ctrl.n_beats`/`.latency` so it lands exactly on that phase's first sample;
the testbench then asserts the final beat's handshake really happened on the
predicted cycle and that `tx0_s_axis_tready` never went low. A `PRE_ROLL`
window before sample 0 carries phase 0's frame, during which the registers hold
their defaults — amplitude 0 and `pri = 1`, so the generator emits zeros from a
pinned counter and the same `golden_pulse_gen` models the window exactly. A
build-time assertion checks every frame lands over signal the golden model says
is idle, so a future phase edit cannot reconfigure the generator mid-pulse.

Eight phases (three PRI periods each): a baseline pulse at +Fs/8, a short pulse
at **−Fs/8** (a negative frequency, which a sign-flipped `atan2` fails), a
**glitch** narrower than `min_width`, a `max_width` cap that forces the **CW**
force-close path, a long pulse at a different amplitude, an **LFM chirp** (the
only phase where `freq_start` and `freq_stop` must differ), a threshold
deliberately set to suppress every pulse in that phase, and an amplitude too
weak to cross a calibrated threshold. All thresholds are calibrated
programmatically from the golden power model (see section 2's scaling note),
never hand-picked round numbers. Net: 18 candidates detected, 12 released,
6 rejected (3 glitch + 3 CW).

The measurement fields are checked the same way as everything else — against a
bit-exact Python model, not a tolerance. That model mirrors the NCO, the
conjugate product, the ping-pong block accumulators, all 14 CORDIC iterations
(including the arithmetic-shift floor semantics and the quadrant pre-rotation),
the piecewise-linear logarithm, and the noise estimator's excision guard. The
numbers it produces are independently checkable by hand: the baseline phase
measures **+0.125000 turns/sample** against a carrier set to exactly Fs/8, and
the noise phase measures a **16.22 dBFS** floor against 16.2 dBFS predicted
from the LFSR's statistics.

**The noise phase's placement is load-bearing too.** `dc_block`'s running mean
carries across phases, so the first pulse after a change in signal level is
measured against a mean still settling from the previous phase — its DC-blocked
power comes out several times lower than its siblings'. Adding noise on top of
that pushes it below `threshold_low` mid-pulse, and the hysteresis SM then
correctly reports one pulse as several. The noise lives on a phase whose three
peaks agree to ~12%, which has the headroom.

**The phase order is load-bearing.** Both rejecting phases sit *before* a
releasing one. A rejected pulse is erased by draining its buffered beats and
discarding them; if that drain moved the wrong number of beats, the damage
would only ever show up in the *next released packet*. With the rejecting
phases last, a flush-count bug would leave no evidence anywhere. Phases are
referred to by name, not index, so reordering them cannot silently point an
assertion at the wrong one.

Run:
```
pypelinec examples/pypeline/dsp/pdw/pdw_engine/pdw_engine_tb.py --sim --comb --run 800
pypelinec examples/pypeline/dsp/pdw/pdw_tb.py --sim --comb --run 8000
```

`pdw_tb.py` is also the acceptance test for Path B's sample-exact alignment
(section 3): a released packet must carry exactly the raw I/Q whose power
produced its own gate beats. That check is sample-exact in both directions —
perturbing the golden model's `raw_idx` by ±1 fails it.

### Synthesis checks

| File | Checks |
|---|---|
| `pulse_gen/pulse_gen_synth_top.py` | Pulse generator alone, including its NCO. `rst` is a real port, so the reset's fanout to every register in the block is measured rather than optimised away |
| `pulse_detect/pulse_detect_synth_top.py` | Hysteresis FSM alone (elastic, the heavier path), `rst` likewise a real port |
| `pdw_engine/pdw_engine_synth_top.py` | PDW engine alone, at the README's real 16K FIFO depth. Also the only real timing check on the measurement engine — its CORDIC and both logarithm converters are instantiated inside it. `rst` is a real port: it drives the three FIFO read enables, so it sits directly in the release path |
| `cordic_test.py`, `log2_db_test.py` | The two new DSP primitives, `--comb` elaboration |
| `top.py` | Everything composed, including all seven AXIS ports, both record serializers, the control deserializer, the broadcast interlock and the seven-input reset OR |

These are not redundant with the native-sim testbenches: native sim never
emits VHDL, so it cannot catch anything Vivado rejects. Several real bugs in
this project were only visible here — a ternary whose branches had different
integer widths, and three identifiers that collide with VHDL reserved words: an
`@enum` member named `RELEASE`, a local named `use` in the phasor accumulator,
and a local named `rem` in the count-leading-zeros helper. `reject` and `wait`
are reserved too, hence `verdict_t`'s `is_glitch`/`is_cw` and the packet
store's `WAIT_MEAS`.

They are also where the *timing* work happened, and none of it was guesswork —
each fix came from reading the reported critical path:

* the conjugate product's multiply chaining into a 40-bit accumulate
  (10.13 ns) → one register between them;
* the logarithm's barrel shift chaining into the mantissa multiply
  (12.90 ns) → split into two stages, and the piecewise-linear constants
  narrowed so the multiply stops inferring a DSP48;
* the CORDIC's wide absolute-value and compare chaining into
  count-leading-zeros (12.92 ns) → setup split across two registers;
* `make_clz` itself, whose original form was an `n`-deep chain of dependent
  muxes — at 39 bits that was an entire CORDIC's critical path on its own. It
  is now a `log2(n)`-level binary search, which is strictly better and is
  shared with the floating-point library.

Latest results on `xc7a100tcsg324-1` at the 125 MHz target: `pulse_detect`
closes at **132.1 MHz**, `pdw_engine` (including the measurement engine) at
**126.7 MHz**, and the composed `top.py` at **127.1 MHz** — 22.9% of the part's
LUTs, 5.4% of its flip-flops, 16.7% of its block RAM and 3.3% of its DSP48s.
Both the 16,384-deep packet FIFO and the Path B delay line infer block RAM.
Making every top-level port an AXI-Stream cost **no FMAX at all** (127.097 MHz
before and after, the same critical path in both) and about 3,900 LUTs — the
two record serializers, the control deserializer and the broadcast interlock.

**Every one of those numbers started out failing.** The measurement path added
a CORDIC, two logarithm converters and an NCO to a design that had ~5% margin,
and getting back to 125 MHz took eight separate fixes, each one read off the
reported critical path rather than guessed:

| Path | Was | Fix |
|---|---|---|
| conjugate product → 40-bit accumulate | 10.13 ns | register between product and accumulator |
| log2 barrel shift → mantissa multiply | 12.90 ns | split into two stages |
| log2 exponent scaling | 10.96 / 11.91 ns | constant multiply → **balanced** shift-add tree in its own stage (a *serial* shift-add was worse than the DSP it replaced) |
| CORDIC abs/compare → count-leading-zeros | 12.92 ns | setup split across two registers |
| CORDIC angle table lookup (`make_clz`) | — | `n`-deep mux chain → `log2(n)` binary search |
| generator LFSR → detector's magnitude DSP | 15.32 ns | pipeline the generator's output |
| phasor accumulator → CORDIC front end | 11.65 ns | register the accumulator output |
| NCO quadrant unfold → output adder | 8.23 ns | register the rotator's output |
| delay-line BRAM → conjugate-product DSP chain | 9.69 ns | register all four raw products, not just their sums |

Two of those are worth calling out. The **generator-to-detector** path and the
**accumulator-to-CORDIC** path are both cross-block: each block met timing
comfortably on its own, and only the composed build showed them. A per-block
synthesis check cannot find that class of problem, which is why `top.py` is
registered as its own synthesis test rather than treated as covered by the
three block-level ones.

The last row is a different lesson: **a path can break with nothing on it
having changed.** `d_im = cur_q·prev_i − cur_i·prev_q` is two multiplies and a
subtract, so it needs two DSP48s — and with only one pipeline register
(`d_im_r`) to place, the synthesizer must choose which DSP absorbs it. In the
first DSP the path is BRAM → DSP(A→MREG), about 3.7 ns; in the second, the
first DSP runs combinationally and the path becomes BRAM (2.45) → DSP A→P
(3.84) → DSP C setup (1.70) = 9.69 ns, i.e. 103 MHz. Both are legal, and
Vivado has picked each: this design met 127.1 MHz until adding the AXIS ports
grew the netlist and flipped the choice. Registering all four products removes
the choice — every multiply now has its own register to absorb. A path that
depends on a synthesizer's packing decision is not "meeting timing", it is
winning a coin toss; the fix is to stop offering the coin.

Every register added along the way is reported through a `.latency` attribute
and consumed as one — `freq_accum.latency`, `cordic_atan2.latency`,
`log2_db.latency`, `pulse_gen.latency`. Nothing downstream hardcodes a delay,
so all of these changes were made without touching the testbenches' alignment
logic or the golden model's structure.
