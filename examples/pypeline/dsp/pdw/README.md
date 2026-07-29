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

## 3. FIFO Depths

Note: the per-stage cycle counts below ($L_{mag}$, $L_{dsp}$, $L_{sm}$) are rough estimates for sizing intuition only. Actual pipeline latencies are determined automatically by Pypeline's AUTOPIPELINE tooling, not hand-specified — FIFO depths must be pinned to the real measured latencies once the design is built, not these placeholder numbers.

**Delay Line FIFO (Path B)**
$$L_{mag}(3) + L_{dsp}(8) + L_{sm}(1) + N_{pre}(16) = \textbf{28 cycles}$$
Round up to 32 deep.

**Store-and-Forward Packet FIFO**
$$Max\_Width(12500) + N_{pre}(16) + N_{post}(16) = \textbf{12,532 cycles}$$
Round up to 16,384 deep (16K).

## 4. PDW Output Structures

**`candidate_pdw_t`** (internal to FPGA — 128 bits total)

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | **NOT IMPLEMENTED in first version.** Time of arrival (125 MHz counter, ~4,424 years to roll over) |
| `pulse_width` | `uint32_t` | Raw duration in clock cycles |
| `peak_power` | `uint32_t` | Highest $I^2+Q^2$ value recorded during the pulse |

**`valid_pdw_t`** (sent to host via DMA — 192 bits / 24 bytes total)

| Field | Type | Meaning |
|---|---|---|
| `toa` | `uint64_t` | **NOT IMPLEMENTED in first version.** Time of arrival |
| `pulse_width` | `uint32_t` | Validated width |
| `peak_power` | `uint32_t` | Validated peak power |
| `pkt_samples` | `uint32_t` | Total AXI-Stream payload size ($N_{pre} + width + N_{post}$); tells DMA how many samples to slice |
| `status_flags` | `uint16_t` | Bitfield: Bit 0 = ADC Clip, Bit 1 = DSP Overflow, Bit 2 = Packet FIFO Full |
| `padding` | `uint16_t` | Reserved, aligns struct to a 192-bit (24-byte) / 256-bit (32-byte) DMA boundary |