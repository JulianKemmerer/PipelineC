# Exploring Pypeline Native Simulation with ChaCha20-Poly1305 Cryptography

Hey folks this is Julian, author of [PypelineC](https://github.com/JulianKemmerer/PipelineC).

**PypelineC = Pypeline + PipelineC.** PipelineC is the original C-like hardware
description language built around automatic pipelining. Pypeline is a newer
Python front end for that same compiler and pipelining engine: same
underlying tool, different (and now preferred) surface syntax. PypelineC is
the umbrella name for the whole project, covering both front ends.

I want to extend a big thank you to [ChiliCHIPS](https://github.com/chili-chips-ba)
for letting me participate in the [wireguard-fpga](https://github.com/chili-chips-ba/wireguard-fpga)
project as a real-world testbed for both [original PipelineC](https://github.com/JulianKemmerer/PipelineC/wiki/Example%3A-ChaCha20%E2%80%90Poly1305-for-WireGuard/) and [new Pypeline](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/README.md). It's very valuable to exercise the language with a full scale real design that has realistic goals and tests. This write-up details how the verification setup was improved by moving to Pypeline.

Questions? Comments? Reach out, see links from the [Pypeline getting started page](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/README.md).

## What Is This Design?

<p align="center">
  <img width="80%" src="https://raw.githubusercontent.com/chili-chips-ba/wireguard-fpga/refs/heads/main/0.doc/Wireguard/wireguard-fpga-muxed-Architecture-HW-SW-Partitioning.webp">
</p>

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

- **No native simulation.** PipelineC has no built in C-based (or Python-based) simulator, so
  simulations required generating VHDL and using a wrapper cocotb+GHDL testbench.
- **No cycle-accurate latency modeling without slow full autopipelined VHDL generation.** There's no
  way to reason about auto-pipelined timing without going through synthesis and using an HDL simulator.
- **String search pass/fail.** Correctness came down to scanning console output
  for `ERROR` lines, rather than a more programmatic pass/fail signal.
- **Fixed vectors only.** A handful of hand-picked test strings, computed
  once using the project's hand-rolled implementation as the golden model,
  with no easy path to broader or randomized coverage.

## Turning the Page: From C to Python

Pypeline addresses all of these gaps at once: Python is good at automation and testing.
A real standard library `cryptography` package for
a RFC 8439-conformant ChaCha20-Poly1305 is now used as reference implementation.
Also native Python-level simulation can run the design as ordinary Python, cycle by
cycle, with no VHDL/GHDL/cocotb required.

### Case in Point: Catching a Real Poly1305 Math Bug

Moving to Pypeline's random, reference-model-checked testbenches actually turned up a real bug that has since been fixed.
The original `poly1305.h`'s 320-bit limb math (ported line-for-line into
`poly1305.py`) had three interlocking bugs. See details in [`wireguard-fpga/3.build/pypeline_build/README.md`](https://github.com/chili-chips-ba/wireguard-fpga/tree/main/3.build/pypeline_build#fixed-poly1305-320-bit-math-is-now-rfc-8439-correct).

The old fixed-vector testbenches never caught this, the same incorrect software C code was used as the reference model for test vectors and as PipelineC code for the hardware design.
The design was internally self-consistent, but far from RFC 8439-conformant.
Pypeline testbenches can easily generate and check random packets against the `cryptography` Python
package's real ChaCha20-Poly1305 implementation to find bugs like these.

## The New Pypeline Testbenches

### Applying Inputs and Checking Outputs

The port lives at [`wireguard-fpga/3.build/pypeline_build/`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/), and each of the
three design variants (encrypt-only, decrypt-only, and the shared
encrypt+decrypt build) has **two independent testbench styles** sharing
the same DUT-facing wires:

- **Synthesizable-style** ([`encrypt_syn_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/encrypt_syn_tb.py) / [`decrypt_syn_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/decrypt_syn_tb.py)): a
  FSM streams and checks a fixed batch of 8 small test
  strings computed once via a pure-Python reference model
  ([`aead_ref_model.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/aead_ref_model.py)) at elaboration time and baked into fixed-size
  shift register buffers. Because this testbench is itself synthesizable
  Pypeline, it can be run through cocotb+GHDL using real
  generated VHDL, or even loaded onto an FPGA for hardware testing. That's the
  point of keeping it synthesizable at all: it's the one testbench style that
  travels all the way from a quick native-sim check up through real VHDL and
  onto real silicon, unmodified.
- **Non-synthesizable** ([`encrypt_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/encrypt_tb.py) / [`decrypt_tb.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/src/chacha20poly1305/decrypt_tb.py)): uses Pypeline's
  `@sim_input`/`@sim_output` decorators to generate stimulus and check
  outputs as arbitrary live Python, cycle by cycle, during simulation. Each
  run generates 10 packets per direction on the fly, calling the same
  reference model lazily, once per packet, right when that packet's random
  plaintext is generated - no fixed-size arrays, no elaboration-time
  pre-baking. `@sim_input`/`@sim_output` calls are invisible to the hardware
  elaborator, so this style **only runs under Pypeline's native simulator**.

  This is where a small taste of constrained-random stimulus generation shows
  up: packet length isn't just `random.randrange`d freely, it's *constrained*
  to a `[1, 1024]`-byte range, with a handful of lengths (16, 17, 64, 128 —
  the partial-final-word and block-boundary corner cases) stratified in and
  guaranteed to appear every run before the rest fill in uniformly at random.
  It's a modest version of the same idea SystemVerilog/UVM random-constrained
  stimulus is built on — where a full functional-coverage model would
  declaratively describe the scenarios to hit and let the tool solve for
  stimulus that reaches them, here the "coverage model" is just this one
  hand-picked length list. Growing that connection for real is a good
  candidate for Next Steps.

Here's a taste of what driving stimulus looks like: ordinary Python, run
live during simulation. Both the streaming generator/checker and the
expected-vs-actual scoreboard bookkeeping come from a shared, reusable Pypeline testbench
library ([`include/pypeline/axi/axis.py`](https://github.com/JulianKemmerer/PipelineC/blob/master/include/pypeline/axi/axis.py)/[`axis_sim.py`](https://github.com/JulianKemmerer/PipelineC/blob/master/include/pypeline/axi/axis_sim.py),
documented in [`pypeline_guide.md`](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#23-axi-stream-axis_t)).

```python
scoreboard = Scoreboard()
src = AxisSimSource(axis128_intrf, 16)
snk = AxisSimSink(axis128_intrf, 16, scoreboard=scoreboard)

@sim_input
def drive_in_word() -> axis128_intrf.fwd_t:
    if enc_state["in_packet_idx"] < common.NUM_RANDOM_PACKETS and src.idle():
        # Starting a new packet: pick a length, generate random plaintext,
        # and compute the expected ciphertext+tag right now, once, lazily.
        idx = enc_state["in_packet_idx"]
        length = common.next_packet_length(enc_state["rng"], idx)
        plaintext = bytes(enc_state["rng"].randrange(256) for _ in range(length))
        ciphertext, tag = generate_encrypt_vector(KEY, NONCE, AAD, plaintext)
        scoreboard.expect(ciphertext + tag, idx=idx)
        src.send(ciphertext + tag)
        enc_state["in_packet_idx"] += 1

    return src.step(chacha20poly1305_encrypt_ports.axis_in_ready)
```

Both styles replaced "scan the log for `ERROR`" with a hard pass/fail
signal: every check is a `sim_assert(...)` (correct ciphertext/plaintext
bytes, exact per-lane `keep` pattern, packet framing, and the tampered-tag
packets' `is_verified_out`), and the whole run ends in `sim_finish()`. A
failing check raises `AssertionError` in native sim - or, downstream, a real
VHDL `assert ... severity failure` under cocotb/GHDL - so the process exits
non-zero on its own. No more looking for special strings in the output text.

The output-checking side is the mirror image: pop a completed frame off the
sink, check it against the scoreboard, and report whatever comes back:

```python
@sim_output
def check_out():
    snk.step(chacha20poly1305_encrypt_ports.axis_out)
    result = snk.check_nowait()
    if result is None:
        return
    if not result["passed"]:
        sim_print(f"ERROR: Encrypt: mismatch, packet {result['idx']}")
    sim_print(f"Encrypt: Test {result['idx']} DONE!")
```

Running any of the builds is one line, via the port's [`build.py`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/build.py):

```bash
./build.py --enc --sim --comb --native     # fastest: combinational native sim
./build.py --enc --sim --syn_tb --comb     # fixed vectors through cocotb/GHDL
```

Both of those are `--comb` runs without added pipelining.
Dropping `--comb` gets an autopipelined cycle accurate simulation instead:

```bash
./build.py --enc --sim --native            # pipelined native sim (slow!)
```

See the [`pypeline_guide.md` Simulation section](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#4-simulation)
for the full menu of flags, and the port's own
[`3.build/pypeline_build/README.md`](https://github.com/chili-chips-ba/wireguard-fpga/blob/main/3.build/pypeline_build/README.md) for the complete command reference and
source layout.

### Cycle Accuracy

The old PipelineC design had no way to inspect how many cycles any of the
design's automatically pipelined functions actually elaborated to after synthesis iterations.
That latency information only existed after a real VHDL build invisible to any C-level user code being written.

Pypeline improves on that in two ways:
First,  [`AUTOPIPELINE(...)`](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#15-tool-chosen-implementation-autopipeline-and-autofsm) lets
design code (and testbenches) read back the real, synthesis-discovered
pipeline depth of an autopipelined function — see
["`.latency`: reading back the discovered pipeline depth"](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#latency-reading-back-the-discovered-pipeline-depth).
Second, a non-`--comb` `pypelinec --sim` build uses that same discovered
latency to drive the native simulator: it builds the full autopipelined
design first (through the real synthesis tool, to find each submodule's
true latency), then native-simulates that design with those latencies
emulated, cycle by cycle.

That emulation isn't a full gate-level pipeline model though, it's an
approximation: each pipelined call runs as an instantaneous (zero-cycle)
Python function call, with its result pushed through a shift-register-style
delay line to reproduce the right number of cycles of latency before the
result appears. That's cheap enough to make pipelined native sim practical,
but it's still an emulation of timing, not a real per-stage register model
— see ["Pipelined native sim"](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_sim_DESIGN.md#pipelined-native-sim-non---comb-pipelinec---sim)
in `pypeline_sim_DESIGN.md` for the mechanics.

If a mismatch between native Python based simulation and generated VHDL is suspected
then [`pypeline_sim_debug.py`](https://github.com/JulianKemmerer/PipelineC/blob/master/docs/pypeline_guide.md#pypeline_sim_debugpy--native-vs-vhdl-cycle-diff-tool) can be used. It compares `sim_print(..., debug=True)`-tagged output between the native simulator and real cocotb+GHDL. This confirms that not only have no `sim_assert`s failed but also that both simulations produce identical *cycle-accurate* behavior.

## Next Steps

This is a work in progress, possible next steps:

- Waveform (e.g. VCD) output for native sim, not just console text.
- Randomized backpressure test coverage: none of these testbenches drive randomized `ready` yet, only static 1.
- Integrate mainstream design verification methodology: UVM, UVVM, formal techniques, etc
  - A real declarative functional-coverage model driving constrained-random stimulus.
- Finer-grained control over how deep into a design's hierarchy native vs. VHDL sim comparisons can reach.
- Explore use of manually specified pipeline depths instead of automatically determined.
- Add LLM MCP or skills to further facilitate testbench generation, execution, and post-processing of sim outcomes.

Reach out if you have ideas or otherwise want to contribute!

Thanks for your time!
