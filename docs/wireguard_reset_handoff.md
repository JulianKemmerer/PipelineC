# Handoff: synchronous reset for the WireGuard `pypeline_build`

PipelineC has synchronous resets (uncommitted working tree on top of PipelineC
`deac5d21`; see `docs/pypeline_guide.md#resets` there). This is the WireGuard side:
- one reset pin, on by default, that resets every register of the DUT and of the shared
  resources;
- mid-packet reset cases in the random testbenches.

It was made and checked in copies of `3.build/pypeline_build`. The wireguard-fpga
repository itself was not touched.

**Patch:** `/media/1TB/tmp/pypeline_handoffs/wireguard_reset.patch`.
- It is made against wireguard-fpga `215c2eb9`, with paths relative to
  `3.build/pypeline_build`, and applies cleanly there (`git apply --check`).
- From the repository root, apply it with
  `git apply -p1 --directory=3.build/pypeline_build wireguard_reset.patch`.
- It touches 19 files.

## The change

`src/wireguard_env.py`
- `USE_RESET = param("RESET", True, type=bool, ...)`.
- `wg_rst: Input[uint1_t] = make_reset()` is always declared at module top level, because
  global wire discovery reads only top-level declarations. With `-D RESET=0` nothing uses
  it, so it makes no port.
- `wg_clk = make_clock(TARGET_MHZ, reset=wg_rst if USE_RESET else None)` and
  `WG_REGS = "all" if USE_RESET else "requested"`.
- The `except ImportError` fallback, for host tools without PypelineC, gets stand-ins for
  `Input`, `uint1_t`, `make_reset` and `make_clock`, so the module still imports there.

MAINs (every `@MAIN(wireguard_env.TARGET_MHZ)`; `wg_clk` is the same clock)
- The DUT and shared MAINs become
  `@MAIN(wireguard_env.wg_clk, reset_registers=wireguard_env.WG_REGS)`:
  - `encrypt_dataflow` and `decrypt_dataflow`
  - both `*_hw_io`
  - `chacha20_pipeline_shared`
  - the two in `poly1305_mcp_shared`
- The fixed-vector testbench tops (`*_syn_tb.py`, `poly1305_pipelined_syn_tb.py`) get the
  same, so their byte source and sink restart with the DUT.
- The other testbench MAINs become `@MAIN(wireguard_env.wg_clk)`. That is the default
  `"requested"` policy, so they are not reset.

Reset in the random and perf testbenches
- They pass the reset to the converged AXIS models:
  `rst = wireguard_env.wg_rst if wireguard_env.USE_RESET else 0`, then
  `_src.commit(ready, reset=rst)` and `_snk.step(..., reset=rst)`.
- Without this, the simulator's default pulse resets the DUT in cycle 0, packet 0 is
  lost, and every later comparison is off by one packet.
- The `USE_RESET` gate matters: native simulation pulses `wg_rst` even with `RESET=0`,
  when nothing resets.

Mid-packet resets (`-D TB_MID_RESETS=40,120`, random testbenches)
- `tb_common_sim.py` adds:
  - `MID_RESETS`, the requested cycles
  - `RESET_STATE`, the driver's schedule and the cycles it fired in
  - `SOURCES`, each testbench's converged source
  - `resend_lost(src, scoreboard, started, n_checked)`
- In `chacha20poly1305_tb.py`, when `USE_RESET`, `tb_finish_checker` calls a
  `drive_reset` `@sim_input`. It pulses `wg_rst` for one cycle at the first cycle, at or
  after each requested one, in which some packet is part way into the DUT, and in cycle
  0, as the simulator otherwise would.
- A `check_resets` `@final` hook fails the run if a requested reset never fired.
- `encrypt_tb.py` and `decrypt_tb.py` record every packet they started (`started`). When a
  reset fires after cycle 1, they clear the source and scoreboard and send every
  started-but-unchecked packet again, in order. Each is expected exactly once; `resent`
  counts them for the pass message.

## Results

Native, `--comb`, against the PipelineC working tree (frozen copy
`/media/1TB/tmp/reset2/tree_final_b/`), with the patch on wireguard-fpga `215c2eb9`:

| check | `RESET=1` | `RESET=0` |
|---|---|---|
| `--enc`, random | 12 packets PASSED, cycle 184 | PASSED, cycle 183 |
| `--enc --syn_tb` | PASS, cycle 83 | PASS, cycle 82 |
| `--dec`, random | 13 packets PASSED, cycle 212 | PASSED, cycle 211 |
| `--dec --syn_tb` | PASS, cycle 85 | PASS, cycle 84 |
| shared, random | 12 + 13 packets PASSED, cycle 217 | PASSED, cycle 216 |
| shared `--syn_tb` | PASS, cycle 96 | PASS, cycle 95 |
| `--enc`, `TB_MID_RESETS=40,120` | 12 PASSED, 6 sent again, cycle 238 | n/a |
| `--dec`, `TB_MID_RESETS=40,120` | 13 PASSED, 6 sent again, cycle 299 | n/a |
| shared, `TB_MID_RESETS=40,120` | 12 + 13 PASSED, 6 + 7 sent again, cycle 302 | n/a |

- With the reset, each run takes exactly one more cycle: the reset cycle.
- Negative control: `TB_MID_RESETS=100000`, a reset that never fires, fails in
  `check_resets` as intended.
- Logs: `/media/1TB/tmp/reset2/wg_215_logs/`, run by
  `/media/1TB/tmp/reset2/wg_rebased_checks.sh` in the patched copy
  `/media/1TB/tmp/reset2/wg_head2_b/`. The same 15 runs gave the same results with the
  patch on `acf39232` (`/media/1TB/tmp/reset2/wg_mid/logs/`) and on `7b27d5b7`
  (`/media/1TB/tmp/reset2/wg_rebased_logs/`).

Hardware: the default shared profile (`python3 build.py -D RESET=<0|1>`), 80 MHz goal,
Vivado 2019.2, xc7a200tffg1156-2, with the patch on `acf39232` (not rebuilt since):

| | `RESET=0` | `RESET=1` |
|---|---|---|
| `chacha20_pipeline_shared` | 95.584 MHz, 20 stages | 95.584 MHz, 20 stages |
| `encrypt_dataflow`, `decrypt_dataflow` | 81.321 MHz, 12 stages each | 81.321 MHz, 12 stages each |
| LUT | 81,487 | 81,641 (+154) |
| FF | 67,226 | 69,198 (+1,972) |
| RAMB18 / RAMB36 / DSP48 | 5 / 24 / 332 | 5 / 24 / 332 |
| sweep iterations | 7 | 9 |

- Both builds meet 80 MHz with the same depths, so encrypt and decrypt latencies stay
  equal.
- Both have the same critical path, inside the decrypt Poly1305 prologue: 12.281 ns,
  0.203 ns slack. The reset is not on it.
- Both are separate syntheses: neither was a cache hit, and their input signatures differ.
- Output directories: `/media/1TB/tmp/reset2/wg_hw_r0/` and `wg_hw_r1/`, built by a
  frozen PipelineC copy at `/media/1TB/tmp/reset2/tree_wg2/`.
- Running these builds exposed a PipelineC bug, fixed in the same working tree. The
  hierarchical delay fallback (`SYN.ESTIMATE_HIER_PATH_DELAYS`) crashed on a primitive
  operator that reduces to constants and wires
  (`BIN_OP_NEQ_uint3_t_uint1_t reduces to constants/wires`). The `RESET=0` build needed
  `build.py --continue` after the fix.

## Not done

- **`NO_RESET` for large data registers.** None was needed, since timing is met. If the
  1,972 extra FFs matter, `Reg[T, NO_RESET]` removes the reset from data registers whose
  contents never matter after a reset, for example the cipher state words and the message
  block registers. Which of the extra FFs those are was not measured. Check any such
  change with the mid-packet reset runs.
- **The AXIS boundary.** Under reset, the DUT's top-level `axis_in` ready and `axis_out`
  valid come from reset logic. If the board side must see `tready = 0` during reset, gate
  it in `*_hw_io` with `~wg_rst`.
