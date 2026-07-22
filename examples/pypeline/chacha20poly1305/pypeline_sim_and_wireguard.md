# Exploring Pypeline Native Simulation with ChaCha20-Poly1305 Cryptography

Hey folks this is Julian, author of [PypelineC](https://github.com/JulianKemmerer/PipelineC) HDL (PipelineC now with a Python front end).
I want to extend a big thank you to [ChiliCHIPS](https://github.com/chili-chips-ba)
for letting me use the [wireguard-fpga](https://github.com/chili-chips-ba/wireguard-fpga)
project as a real-world testbed for both [original PipelineC](https://github.com/JulianKemmerer/PipelineC/wiki/Example%3A-ChaCha20%E2%80%90Poly1305-for-WireGuard/) and [new Pypeline](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/README.md).
It's very valuable to exercise the language with a full scale real design that has realistic goals and tests.
This write-up details how the verification setup for this design was improved by moving to Pypeline.

Questions? Comments? Reach out, see links from the [Pypeline getting started page](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/README.md).

## What Is This Design?

`wireguard-fpga` is an open-source, FPGA-based implementation of the
WireGuard protocol, see the project's own
[README](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/README.md).
Pypeline is used for the central ChaCha20-Poly1305
AEAD cipher core: the block that actually encrypts/decrypts and
authenticates every packet crossing the tunnel.

For details on the design architecture see [the original PipelineC design write-up](https://github.com/JulianKemmerer/PipelineC/wiki/Example%3A-ChaCha20%E2%80%90Poly1305-for-WireGuard/).

## Verification Strategy

In both PipelineC and Pypeline, the verification strategy for the core has stayed
the same: stream data into the design under test and compare against
expected outputs. Plaintext in, ciphertext out for encrypt; ciphertext in,
plaintext out (plus a tag-verified flag) for decrypt.

## The Old Way: PipelineC Testbenches

The original [`pipelinec_build/`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pipelinec_build/) testbenches are hand-written C-style
testbenches with a handful of manually generated test vectors, that are run through
cocotb+GHDL. That flow works, but falls short in several ways:

- **No native simulation.** PipelineC has no built in C-based(or Python) simulator, so
  simulations required generating VHDL and using a wrapper cocotb+GHDL testbench.
- **No cycle-accurate latency modeling without slow full autopipelined VHDL generation.** There's no
  way to reason about auto-pipelined timing without going through synthesis and using an HDL simulator.
- **Eyeballed pass/fail.** Correctness came down to scanning console output
  for `ERROR` lines by hand, rather than programatic pass/fail signal.
- **Fixed vectors only.** A handful of hand-picked test strings, computed
  once using project's hand rolled implementaiton as golden model,
  with no easy path to broader or randomized coverage.

## Turning the Page: From C to Python

Pypeline addresses all of these gaps at once: Python is good at automation and testing.
A real standard library `cryptography` package for
a RFC 8439-conformant ChaCha20-Poly1305 is now used as reference implementation.
Also native Python-level simulation can run the design as ordinary Python, cycle by
cycle, with no VHDL/GHDL/cocotb required.

### TODO section about Poly1305 multipler bug that was found and fix



## The New Pypeline Testbenches

The port lives at [`wireguard-fpga/3.build/pypeline_build/`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/), and each of the
three design variants (encrypt-only, decrypt-only, and the shared
encrypt+decrypt build) has **two independent testbench styles** sharing
the same DUT-facing wires:

- **Synthesizable-style** ([`encrypt_syn_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/encrypt_syn_tb.py) / [`decrypt_syn_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/decrypt_syn_tb.py)): a
  FSM streams and checks a fixed batch of 8 test
  strings computed once via a pure-Python reference model
  ([`aead_ref_model.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/aead_ref_model.py)) at elaboration time and baked into fixed-size
  shift register buffers. Because this testbench is itself synthesizable
  Pypeline, it can be run through cocotb+GHDL against real
  generated VHDL, or even loaded onto real FPGA hardware for testing.
- **Non-synthesizable** ([`encrypt_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/encrypt_tb.py) / [`decrypt_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/decrypt_tb.py)): uses Pypeline's
  `@sim_input`/`@sim_output` decorators to generate stimulus and check
  outputs as arbitrary live Python, cycle by cycle, during simulation. Each
  run generates 10 random-length (1–1024 byte) packets per direction on the
  fly, calling the same reference model lazily, once per packet, right when
  that packet's random plaintext is generated - no fixed-size arrays, no
  elaboration-time pre-baking. `@sim_input`/`@sim_output` calls are
  invisible to the hardware elaborator, so this style **only runs under
  Pypeline's native simulator**.

Here's a taste of what driving stimulus looks like - ordinary Python, run
live during simulation, not hardware:

TODO better code snippet

```python
@sim_input
def drive_in_word() -> axis128_t:
    if _enc_state["rng"] is None:
        _enc_state["rng"] = random.Random(common.DEFAULT_SEED)
    ...
    return _build_axis_word(chunk, eod)
```

Both styles replaced "scan the log for `ERROR`" with a hard pass/fail
signal: every check is a `sim_assert(...)` (correct ciphertext/plaintext
bytes, exact per-lane `keep` pattern, packet framing, and the tampered-tag
packets' `is_verified_out`), and the whole run ends in `sim_finish()`. A
failing check raises `AssertionError` in native sim - or, downstream, a real
VHDL `assert ... severity failure` under cocotb/GHDL - so the process exits
non-zero on its own. No more eyeballing.

TODO show code snippet of axis if valid and ready then assert data matches expect

Running any of the builds is one line, via the port's [`build.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/build.py):

```bash
./build.py --enc --sim --comb --native     # fastest: combinational native sim
./build.py --enc --sim --syn_tb --comb     # fixed vectors through cocotb/GHDL
```

See the [`pypeline_guide.md` Simulation section](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#4-simulation)
for the full menu of flags, and the port's own
[`3.build/pypeline_build/README.md`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/README.md) for the complete command reference and
source layout.

Additionally, if a mismatch between native Python based simulation and generated VHDL is supected
then [`pypeline_sim_debug.py`](https://github.com/JulianKemmerer/PipelineC/blob/master/src/pypeline_sim_debug.py) (TODO link to pypeline_sim_debug.py sim section of language guide) can be used. It compares `sim_print(..., debug=True)`-tagged output between native the simulator and real cocotb+GHDL. This confirms that not only have no `sim_assert`s failed but also that both simulations 
produce idential *cycle-accurate* behavior.

## A Tiny Practical Example

The smallest possible loop on this design looks like:

```bash
cd 3.build/pypeline_build
export PYPELINEC=/path/to/PipelineC/src/pypelinec
./build.py --enc --sim --comb --native
```

That's a full encrypt-side correctness check: 10 random packets, RFC
8439-verified against a real Python crypto library, zero-latency
combinational timing. No VHDL generated at all, simulation starts immediately and finishes in seconds.
For the underlying language mechanics (`@sim_input`/`@sim_output`, `sim_assert`,
`sim_print`), see the
[`pypeline_guide.md` Simulation section](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#4-simulation).

## Next Steps

This is a work in progess, possible next steps:

- Waveform (e.g. VCD) output for native sim, not just console text.
- A shared valid/ready (AXI-Stream-like) handshaking testbench harness, so
  designs like this one don't each hand-roll their own streaming generators and checkers.
- Finer-grained control over how deep into a design's hierarchy native vs. VHDL sim comparisons can reach.
- Reach out if you have ideas or otherwise want to contribute!
