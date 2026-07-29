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