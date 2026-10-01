#!/usr/bin/env python3
"""Real Vivado MCP packing/coverage test; --prepare-only needs no Vivado run."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2]
sys.path[:0] = [str(SRC), str(SRC.parent / "include" / "pypeline")]
DESIGN = HERE / "mcp_dsp_packing_design.py"


def run(cmd, out, name, env=None):
    out.mkdir(parents=True, exist_ok=True)
    log = out / (name + ".log")
    print(f"Running {name}: {cmd[0]} (log: {log})", flush=True)
    with log.open("w") as stream:
        result = subprocess.run(list(map(str, cmd)), cwd=out, env=env,
                                stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text()
    if result.returncode:
        raise AssertionError(f"{name} failed ({result.returncode}): {log}\n{text[-5000:]}")
    return text


def build(out, start, prepare=False, comb=False, name="build"):
    env = dict(os.environ)
    env["MCP_DSP_START"] = str(start)
    cmd = [sys.executable, SRC / "pypelinec", DESIGN, "--out_dir", out]
    if prepare:
        cmd += ["--comb", "--no_synth"]
    elif comb:
        cmd.append("--comb")
    text = run(cmd, out, name, env)
    if not prepare:
        # Let the outer suite verify this backend actually ran.
        for line in text.splitlines():
            if line.startswith(("Running:", "Reading log")) and "vivado" in line:
                print(line, flush=True)
    return text


def oracle(a, b, salt):
    acc = salt[0] | (salt[1] << 16)
    for _ in range(3):
        acc = (acc * a + b) & 0xFFFFFFFF
    return acc


def native_protocol(count):
    os.environ["MCP_DSP_START"] = str(count)
    import mcp_dsp_packing_design as design
    from pypeline import sim_call, sim_reset

    for wrapper, n in ((design.fixed_mcp, 4), (design.auto_mcp, count)):
        for a, b, salt in ((17, 41, [13, 29]), (65535, 65535, [65535, 65535]), (0, 0, [0, 0]), (1, 19, [32768, 2])):
            sim_reset()
            accepted = None
            observed = []
            for cycle in range(n + 5):
                request = design.word_if.fwd_t(stream=design.word_if.stream_t(
                    data=design.operands_t(a=a, b=b, salt=salt),
                    valid=int(accepted is None),
                ))
                result = sim_call(wrapper, request, wrapper.out_fb_t(ready=0))
                if accepted is None and result.stream_in_if.ready:
                    accepted = cycle
                if result.stream_out_if.stream.valid:
                    observed.append(cycle)
                    assert int(result.stream_out_if.stream.data) == oracle(a, b, salt)
            assert accepted == 0 and observed == list(range(n + 1, n + 5)), (n, accepted, observed)
    print(f"MCP native data/latency/backpressure PASS (auto={count})", flush=True)


def xdc_pairs(out):
    text = (out / "clocks.xdc").read_text()
    pairs = re.findall(r"set_multicycle_path (\d+) -setup -from \[get_pins \{(.+)/C\}\] -to \[get_pins \{(.+)/D\}\]", text)
    assert len(pairs) == 2, text
    for n, start, end in pairs:
        assert f"set_multicycle_path {int(n)-1} -hold -from [get_pins {{{start}/C}}] -to [get_pins {{{end}/D}}]" in text
    return pairs


def selected_checkpoint(out, text):
    # Confirmation is the last top-level timing run (fresh or reused).
    # Top-level logs are vivado_<hash>_<input signature>.log (VIVADO.INPUT_MANIFEST).
    logs = re.findall(r"(?:Running:|Reading log) (.+/vivado_[0-9a-f]+(?:_[0-9a-f]+)?\.log)", text)
    assert logs, "no top-level synthesis report"
    log = Path(logs[-1])
    checkpoints = list(log.parent.glob("*" + log.stem[len("vivado"):] + ".dcp"))
    assert len(checkpoints) == 1, (log, checkpoints)
    return checkpoints[0]


def audit(out, checkpoint, route=False):
    import VIVADO

    pairs = xdc_pairs(out)
    pair_list = " ".join("{" + n + " {" + a + "} {" + b + "}}" for n, a, b in pairs)
    script = f"""open_checkpoint {{{checkpoint}}}
source {{{HERE / '_mcp_dsp_audit.tcl'}}}
set pairs {{{pair_list}}}
audit_mcps $pairs synthesis
report_exceptions -coverage -file {{{out / 'exception_coverage.rpt'}}}
"""
    if route:
        # The --comb fixture deliberately leaves the separate body unpipelined.
        # Audit MCP endpoints/requirements after routing; whole-design timing
        # closure is not an assertion here. Keep the full report for inspection.
        script += "opt_design\nplace_design\nroute_design\naudit_mcps $pairs routed\n"
        script += f"report_timing_summary -delay_type min_max -file {{{out / 'routed_timing.rpt'}}}\n"
    script += "negative_checks $pairs\n"
    # Vivado batch Tcl failures must produce a failing process, not just a log.
    script = "if {[catch {\n" + script + "\n} message]} {puts stderr $message; exit 1}\nexit 0\n"
    path = out / "audit.tcl"
    path.write_text(script)
    text = run([VIVADO.VIVADO_PATH, "-mode", "batch", "-source", path,
                "-log", out / "audit.vivado.log", "-journal", out / "audit.jou"], out, "audit")
    assert "MCP_DSP_AUDIT_PASS synthesis" in text
    assert "MCP_DSP_NEGATIVE_CHECKS_PASS" in text
    if route:
        assert "MCP_DSP_AUDIT_PASS routed" in text


def ghdl_protocol(out, auto_count):
    """Simulate emitted MCP entities, including preserved aggregate registers."""
    files = [Path(p) for p in (out / "vhdl_files.txt").read_text().split()]
    work = out / "ghdl_mcp"
    work.mkdir(exist_ok=True)
    run(["ghdl", "-i", "--std=08", *files], work, "import")
    holders = []
    for path in files:
        text = path.read_text()
        if 'attribute dont_touch of launch : signal is "true";' in text:
            holders.append((path, text))
    assert len(holders) == 2, [p for p, _ in holders]
    expected = oracle(17, 41, [13, 29])
    for index, (path, text) in enumerate(holders):
        entity = re.search(r"entity (\w+) is", text).group(1)
        # The fixed factory and the auto factory are distinguished in the
        # generated entity name; resolved counts appear in the XDC separately.
        n = auto_count if "auto_multi_cycle" in entity else 4
        ports = dict(re.findall(r"(stream_in_if|stream_out_if|return_output)\s*:\s*(?:in|out)\s+(\w+)", text))
        assert len(ports) == 3, path
        tb_name = f"mcp_protocol_{index}"
        tb = f"""library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.c_structs_pkg.all;
entity {tb_name} is end;
architecture test of {tb_name} is
  signal clk : std_logic := '0';
  signal req : {ports['stream_in_if']};
  signal fb : {ports['stream_out_if']};
  signal result : {ports['return_output']};
begin
  clk <= not clk after 5 ns;
  dut: entity work.{entity} port map (
    clk => clk, CLOCK_ENABLE => to_unsigned(1, 1),
    stream_in_if => req, stream_out_if => fb, return_output => result);
  process
    variable accepted : integer := -1;
    variable seen : integer := 0;
  begin
    req.stream.data.a <= to_unsigned(17, 16);
    req.stream.data.b <= to_unsigned(41, 16);
    req.stream.data.salt(0) <= to_unsigned(13, 16);
    req.stream.data.salt(1) <= to_unsigned(29, 16);
    req.stream.valid <= to_unsigned(1, 1);
    fb.ready <= to_unsigned(0, 1);
    for cycle in 0 to {n + 4} loop
      wait until rising_edge(clk);
      if accepted = -1 and result.stream_in_if.ready = 1 then
        accepted := cycle;
        req.stream.valid <= to_unsigned(0, 1);
      end if;
      if result.stream_out_if.stream.valid = 1 then
        assert cycle - accepted >= {n + 1} report "early MCP result" severity failure;
        if seen = 0 then
          assert cycle - accepted = {n + 1} report "wrong MCP latency" severity failure;
        end if;
        assert result.stream_out_if.stream.data = unsigned'(x"{expected:08x}") report "wrong MCP data" severity failure;
        seen := seen + 1;
      end if;
    end loop;
    assert accepted = 0 and seen = 4 report "MCP handshake/backpressure failed" severity failure;
    report "MCP_GHDL_PROTOCOL_PASS";
    std.env.finish;
  end process;
end;
"""
        tb_path = work / (tb_name + ".vhd")
        tb_path.write_text(tb)
        run(["ghdl", "-i", "--std=08", tb_path], work, f"analyze_{index}")
        run(["ghdl", "-m", "--std=08", tb_name], work, f"elaborate_{index}")
        sim = run(["ghdl", "-r", "--std=08", tb_name, "--assert-level=error", "--stop-time=2us"], work, f"sim_{index}")
        assert "MCP_GHDL_PROTOCOL_PASS" in sim


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--native-count", type=int)
    args = parser.parse_args()
    if args.native_count is not None:
        native_protocol(args.native_count)
        return
    assert args.out_dir is not None, "--out_dir is required"
    out = args.out_dir.resolve()
    for count in (1, 4):
        run([sys.executable, Path(__file__).resolve(), "--native-count", count], out, f"native_{count}")
    fixed = out / "four_cycles"
    text = build(fixed, 4, prepare=args.prepare_only, comb=True)
    if not args.prepare_only:
        xdc_pairs(fixed)
    ghdl_protocol(fixed, 4)
    if args.prepare_only:
        print("MCP DSP regression preparation PASS (no Vivado run)")
        return
    audit(fixed, selected_checkpoint(fixed, text), route=True)
    swept = out / "automatic"
    text = build(swept, 1)
    # The count may be raised by in-context feedback or seeded directly from
    # endpoint-qualified isolated evidence before the first synthesis; either
    # way it must end above its start (checked on the final counts below).
    assert "action=auto_multi_cycle(" in text or re.search(
        r"provisional seed \d+->\d+", text
    ), "AUTO_MULTI_CYCLE never grew"
    assert "AUTO_PIPELINE Pass 2" in text, "no latency re-elaboration"
    assert "TIMING NOT MET" not in text
    counts = {key: int(n) for key, n in re.findall(r"^AUTO_MULTI_CYCLE (\S+): (\d+) cycles$", text, re.M)}
    assert len(counts) == 1 and next(iter(counts.values())) > 1, counts
    count = next(iter(counts.values()))
    # The shared helper must have both an unpipelined MCP variant and a
    # pipelined body variant in the accepted final artifact.
    variants = [int(m.group(1))
                for path in (swept / "vhdl_files.txt").read_text().split()
                for m in [re.match(r"dsp_chain_(\d+)CLK_", Path(path).stem)] if m]
    assert 0 in variants and any(n > 0 for n in variants), variants
    audit(swept, selected_checkpoint(swept, text))
    ghdl_protocol(swept, count)
    run([sys.executable, Path(__file__).resolve(), "--native-count", count], out, "native_confirmed")
    before = {p: p.stat().st_mtime_ns for p in swept.rglob("vivado*.log")}
    warm = build(swept, 1, name="warm_build")
    assert "Reading log" in warm and "Running:" not in warm, "warm MCP run re-synthesized"
    assert before == {p: p.stat().st_mtime_ns for p in swept.rglob("vivado*.log")}
    print("MCP DSP packing, setup/hold coverage, simulation, and warm reuse PASS")


if __name__ == "__main__":
    main()
