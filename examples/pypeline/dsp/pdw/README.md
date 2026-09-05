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
 |  3. Execute:                                                     |
 |     -> If Valid:   Emit valid_pdw_t & Commit/Release AXIS Packet        |
 |     -> If Invalid: Suppress PDW & Rollback/Flush FIFO                   |
 +-------------------------------------------------------------------------+
                   |                                       |
       valid_pdw_t |                                       | Released AXIS
       (toa, width,|                                       | (w/ tlast)
        peak_power,|                                       +---------+
        pkt_samples|                                                 |
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

* **Path A (The Brain):** Calculates the instantaneous power (I^2 + Q^2), runs it through lightweight DSP (like DC blocking and smoothing), and feeds it into a Hysteresis State Machine. When a pulse ends, this path generates a **`candidate_pdw_t`**—a raw, unvalidated guess containing the start time, width, and peak power.
* **Path B (The Time Machine):** While Path A is doing math, Path B routes the untouched raw I/Q samples through a Delay Line FIFO. This FIFO is mathematically sized to delay the physical waveform by the exact time it takes Path A to compute, plus a pre-trigger safety margin (`N_pre`). 

## 3. The Qualified Storage & PDW Engine
This is the gatekeeper of the system. It takes the real-time triggers from Path A and the time-aligned samples from Path B and manages them using a **Store-and-Forward FIFO**. 

* **Store:** It absorbs the raw samples into memory in the background.
* **Qualify:** When it receives the `candidate_pdw_t` from Path A, it checks it against the host's rules. Did the pulse last long enough to be real (Glitch Rejection)? Was it too long (Continuous Wave Rejection)?
* **Execute:** 
  * If the pulse is **invalid**, the hardware drops the metadata and resets/flushes FIFO, completely erasing the glitch.
  * If the pulse is **valid**, the engine commits the packet for output.

## 4. The Outputs
When a pulse is validated, two things happen simultaneously in hardware:

1. **Metadata to Host:** The engine upgrades the candidate struct to a **`valid_pdw_t`** (adding the total packet sample count and hardware status flags) and sends it over a standard data/valid/ready handshake bus to the host software.
2. **Raw Waveform Replay:** The Store-and-Forward FIFO releases the bounded AXI-Stream packet, framed with a `tlast` marker at the end. This pristine I/Q packet is routed both to the **Host DMA** (for software analysis) and out of the **TX2 RF Out** port to physically replay the pulse back to the target.

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

**Threshold scaling (as actually built in `top.py`/`pulse_detect.py`).** `threshold_high`/
`threshold_low` are compared against `detect_pulses.power_t` — the DC-blocked,
moving-averaged power estimate — which carries **12 fractional bits**
(`dc_k`(10) + `log2(ma_n)`(2), both `make_detect_pulses()` defaults). So the
raw integer driven into these `uint32_t` ports must be `4096 ×` the intended
power level in `magnitude`'s own units (raw $I^2+Q^2$, 0 fractional bits) —
the example values above are illustrative round numbers, not derived from
this scaling. The `uint32_t` port width in turn caps the usable range to real
power $\lesssim$ 1,048,576 (i.e. a rail amplitude of roughly $\lesssim$ 1024
before `threshold_high` can no longer represent it). `pdw_tb.py` (section 5
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

**`candidate_pdw_t`** (internal to FPGA — 128 bits total)

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | Time of arrival (~4,424 years to roll over) |
| `pulse_width` | `uint32_t` | Raw duration in clock cycles |
| `peak_power` | `uint32_t` | Highest $I^2+Q^2$ value recorded during the pulse |

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

**`valid_pdw_t`** (sent to host via DMA — 192 bits / 24 bytes total)

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | Time of arrival, carried through from the candidate |
| `pulse_width` | `uint32_t` | Validated width |
| `peak_power` | `uint32_t` | Validated peak power |
| `pkt_samples` | `uint32_t` | Total AXI-Stream payload size ($N_{pre} + width + N_{post}$); tells DMA how many samples to slice. **Equals `pulse_width` today** — margins are unbuilt |
| `status_flags` | `uint16_t` | Bitfield: Bit 0 = ADC Clip, Bit 1 = DSP Overflow, Bit 2 = Packet FIFO Full |
| `padding` | `uint16_t` | Reserved, aligns struct to a 192-bit (24-byte) / 256-bit (32-byte) DMA boundary |

`status_flags` is accumulated per packet across all of its beats and re-armed
on each `last`. ADC clip is measured on the **stored** sample — the
time-aligned raw I/Q that actually goes into the packet — so the flag
describes what the host receives, not what the live ADC input was doing.

A `valid_pdw_t` is emitted **before** its own packet's first beat, on a real
valid/ready handshake, which is the order a DMA consumer needs to size the
transfer that follows.

## 5. Testbenches

| File | Scope | Style |
|---|---|---|
| `pulse_gen/pulse_gen_tb.py` | Pulse generator alone | `sim_assert`, hardware-generated stimulus |
| `pulse_detect/pulse_detect_tb.py` | Bare hysteresis FSM (`make_pulse_detect_fsm`), hand-fed a power stream — elastic, valid_only, and CW/`max_width`-cap variants | `sim_assert`, hardware-generated stimulus |
| `pdw_engine/pdw_engine_tb.py` | The PDW engine alone (`make_pdw_engine`), hand-fed synthetic gate streams — accept path + PDW/packet ordering, glitch reject, CW reject, `status_flags`, long-stall backpressure | `sim_assert`, hardware-generated stimulus |
| `pdw_tb.py` | The whole `top.py` — pulse generator through the composed DSP chain (`make_detect_pulses`: magnitude → dc_block → moving_avg → hysteresis FSM), the Path B delay line, the loopback mux, and the PDW engine, all driven through real top-level ports | `@sim_input`/`@sim_output`, exact Python golden model |

`pdw_engine_tb.py` exists alongside `pdw_tb.py` rather than being folded into
it because it reaches cases the real detector cannot produce on demand — most
importantly the ADC-clip flag, which is unreachable end-to-end: an amplitude
that clips the `int16` rail produces a power far past what the `uint32_t`
threshold ports can represent (see section 2's scaling note). It also uses a
counter as the sample value, so a dropped, duplicated or reordered beat shows
up as a wrong integer with no golden model in the way.

`pdw_tb.py` is the only one that exercises `top.py` itself rather than a
submodule in isolation — the only test of `make_detect_pulses`, the Path B
delay/gate, the engine against real detector output, and any top-level
`Input[T]`/`Output[T]` port of this project. It drives `pulse_loopback_en=1`
throughout (exercising the internal generator loopback path, not the external
`rx0_s_axis_*` cable path — a garbage pattern is deliberately driven on that
port so a broken loopback mux fails loudly rather than silently passing),
configures the generator, detector and engine through real ports, and checks
all three output streams (`candidate_pdw_*`, `valid_pdw_*`, `rx0_m_axis_*`)
against a golden model built from `include/pypeline/dsp/dsp_tb.py`'s exact
integer models (`golden_magnitude`/`golden_dc_block`/`golden_moving_avg`, run
against the *same* `magnitude`/`dc_block`/`moving_avg` instances `top.py`
built — exposed via `detect_pulses.magnitude`/`.dc_block`/`.moving_avg`) plus
a hand-transcribed Python model of the hysteresis FSM, the gate, and the
engine's qualification. Checking follows the wireguard-fpga testbenches'
`Scoreboard` pattern (`include/pypeline/axi/axis_sim.py`): one `Scoreboard`
per output stream, `expect()`ed from the golden model, `check()`ed in arrival
order. Both consumers are deliberately stalled on mutually prime periods, so
the store-and-forward path is genuinely exercised.

Seven phases (three PRI periods each): a baseline pulse, a short pulse (tests
`moving_avg`'s edge smear), a **glitch** narrower than `min_width`, a
`max_width` cap that forces the **CW** force-close path, a long pulse at a
different amplitude, a threshold deliberately set to suppress every pulse in
that phase, and an amplitude too weak to cross a calibrated threshold. All
thresholds are calibrated programmatically from the golden power model (see
section 2's scaling note), never hand-picked round numbers. Net: 15 candidates
detected, 9 released, 6 rejected (3 glitch + 3 CW).

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
| `pulse_gen/pulse_gen_synth_top.py` | Pulse generator alone |
| `pulse_detect/pulse_detect_synth_top.py` | Hysteresis FSM alone (elastic, the heavier path) |
| `pdw_engine/pdw_engine_synth_top.py` | PDW engine alone, at the README's real 16K FIFO depth |
| `top.py` | Everything composed |

These are not redundant with the native-sim testbenches: native sim never
emits VHDL, so it cannot catch anything Vivado rejects. Two real bugs in this
project were only visible here — a ternary whose branches had different
integer widths, and an `@enum` member named `RELEASE`, which becomes a VHDL
enum literal verbatim and collides with a reserved word (`reject` is reserved
too, hence `verdict_t`'s `is_glitch`/`is_cw`).

Latest results on `xc7a100tcsg324-1` at the 125 MHz target: `pdw_engine`
alone closes at **161.9 MHz**; the composed `top.py` at **130.9 MHz** — it
meets the target, but with only ~5% margin, so it is worth re-checking after
any change to the detector's arithmetic. Both the 16,384-deep packet FIFO and
the Path B delay line infer Block RAM.