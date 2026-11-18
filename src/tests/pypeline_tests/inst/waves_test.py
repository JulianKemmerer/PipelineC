# pyright: reportInvalidTypeForm=none
"""Waveform output (pypelinec --sim --wave FILE): SIM.py's waveform block and
the paths that feed it.

  --variant unit        in-process, no design build: VCD layout of structs,
                        arrays, enums, signed and untyped values, signal paths,
                        tap naming, the sampled-twice NOTE, type changes, clock
                        edges, Wire selection, the --wave refusals and
                        pypeline_sim_debug.py's per-run waveform files
  --variant native_vcd  pypelinec --sim --comb --wave run.vcd on waves_design.py:
                        every signal's value in every cycle, the clock and the
                        end time; standalone pypeline_sim.py writes the same file
  --variant native_fst  the same checks on a .fst, read back through fst2vcd
  --variant elab        waves_design.py elaborates (--no_synth) with no port
                        for any tap or probe
  --variant ghdl        --cocotb --ghdl --wave writes .vcd/.fst/.ghw where asked,
                        and cocotb/top.vcd without --wave

Run standalone: python3 waves_test.py --variant unit
"""

import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
from enum import auto
from types import SimpleNamespace
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, SRC)

import pypeline  # noqa: E402
from pypeline import (  # noqa: E402
    PypelineEnum,
    enum,
    int4_t,
    int8_t,
    struct,
    uint2_t,
    uint8_t,
    uint16_t,
)

PYPELINEC = os.path.join(SRC, "pypelinec")
PYPELINE_SIM = os.path.join(SRC, "pypeline_sim.py")
DESIGN = os.path.join(HERE, "waves_design.py")
# waves_design.FINISH_CYCLE: the cycle whose sim_finish() ends its run
FINISH_CYCLE = 8
# Clock period of waves_design.py's 50 MHz clock, in the VCD's 1 ps timescale
PERIOD = 20000


# ── reading a VCD ───────────────────────────────────────────────────────────


def read_vcd(path):
    """(signals, end time, scope kinds) of the VCD at path. signals maps each
    variable's path ("top/counter/n") to (kind, width, [(time, value), ...]):
    a wire's values are ints (None when x or z), a string variable's strs.
    scope kinds maps each scope's path to its kind ("module", "struct")."""
    with open(path) as f:
        tokens = f.read().split()
    by_code, signals, scopes, scope = {}, {}, {}, []
    i = 0
    while tokens[i] != "$enddefinitions":
        tok = tokens[i]
        if tok == "$scope":
            scope.append(tokens[i + 2])
            scopes["/".join(scope)] = tokens[i + 1]
        elif tok == "$upscope":
            scope.pop()
        elif tok == "$var":
            kind, width, code, name = tokens[i + 1 : i + 5]
            entry = (kind, int(width), [])
            signals["/".join(scope + [name])] = entry
            by_code[code] = entry
        i = tokens.index("$end", i) + 1
    time = end = 0
    tokens = iter(tokens[tokens.index("$end", i) + 1 :])
    for tok in tokens:
        if tok.startswith("#"):
            time = end = int(tok[1:])
        elif tok.startswith("$"):
            continue
        elif tok[0] in "bB":
            bits = tok[1:]
            value = None if set(bits) & set("xXzZ") else int(bits, 2)
            by_code[next(tokens)][2].append((time, value))
        elif tok[0] == "s":
            by_code[next(tokens)][2].append((time, tok[1:]))
        else:
            value = None if tok[0] in "xXzZ" else int(tok[0])
            by_code[tok[1:]][2].append((time, value))
    return signals, end, scopes


def value_at(signals, path, time):
    """The value of the variable at path at time."""
    value = None
    for t, v in signals[path][2]:
        if t > time:
            break
        value = v
    return value


def run(cmd):
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(proc.stdout, flush=True)
    return proc


# ── unit: SIM.py's waveform block in-process ────────────────────────────────


@enum
class mode_t(PypelineEnum):
    IDLE = auto()
    BUSY = auto()


@struct
class point_t(NamedTuple):
    x: uint8_t
    y: int4_t
    mode: mode_t
    lanes: uint2_t[3]


class FakeMain:
    """What WaveRecorder reads of a @MAIN wrapper: its hardware name."""

    def __init__(self, name):
        self._pypeline_main = SimpleNamespace(name=name)


def record(path, cycles, period=1000, clock="clk_1000p0"):
    """A WaveRecorder on path; cycles is a list, one per cycle, of
    [(tap name, value, main), ...]. Returns what the run printed."""
    import SIM

    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        recorder = SIM.WaveRecorder(path, "top", clock, period)
        for cycle, taps in enumerate(cycles):
            for name, value, main in taps:
                recorder.tap(name, value, main)
            recorder.end_cycle(cycle)
        recorder.close()
    return printed.getvalue()


def test_struct_array_enum_and_signed_layouts():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        p0 = point_t(x=1, y=-2, mode=mode_t.IDLE, lanes=[1, 2, 3])
        p1 = point_t(x=200, y=7, mode=mode_t.BUSY, lanes=[0, 2, 1])
        lane = pypeline._sim_cast(5, int8_t)
        record(
            path,
            [
                [("/p", p0, None), ("/l", [lane, lane], None)],
                [("/p", p1, None), ("/l", [lane, lane], None)],
            ],
        )
        signals, _end, scopes = read_vcd(path)
    assert scopes["top/p"] == "struct", scopes
    assert signals["top/p/x"][:2] == ("wire", 8)
    assert signals["top/p/y"][:2] == ("wire", 4)
    assert signals["top/p/mode"][0] == "string"
    assert [signals[f"top/p/lanes[{i}]"][1] for i in range(3)] == [2, 2, 2]
    assert value_at(signals, "top/p/y", 0) == 0b1110, "int4_t -2, two's complement"
    assert value_at(signals, "top/p/mode", 0) == "IDLE"
    assert value_at(signals, "top/p/mode", 1000) == "BUSY"
    assert value_at(signals, "top/p/x", 1000) == 200
    assert value_at(signals, "top/p/lanes[2]", 1000) == 1
    assert signals["top/l[0]"][:2] == ("wire", 8) and "top/l[1]" in signals
    # Only changes are written: lanes[1] stays 2 in cycle 1
    assert [t for t, _v in signals["top/p/lanes[1]"][2]] == [0]


def test_untyped_ints_grow_and_strings_lose_whitespace():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        record(
            path,
            [
                [("/n", 3, None), ("/s", "warm up", None), ("/b", True, None)],
                [("/n", 300, None), ("/s", "", None), ("/b", False, None)],
            ],
        )
        signals, _end, _scopes = read_vcd(path)
    assert signals["top/n"][1] == 9, "as wide as its widest value, 300"
    assert [v for _t, v in signals["top/n"][2]] == [3, 300]
    assert signals["top/b"][1] == 1
    assert [v for _t, v in signals["top/s"][2]] == ["warm_up", ""]


def test_tap_paths_absolute_relative_and_scoped():
    lane0 = FakeMain("lane0")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        record(
            path,
            [
                [
                    ("/abs", 1, lane0),
                    ("rel", 1, lane0),
                    ("fifo.in/valid", 1, lane0),
                    ("bare", 1, None),
                ]
            ],
        )
        signals, _end, scopes = read_vcd(path)
    assert {"top/abs", "top/lane0/rel", "top/lane0/fifo/in/valid", "top/bare"} <= set(
        signals
    )
    assert scopes["top/lane0/fifo"] == "module"


def test_source_text_names_one_argument_calls():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "taps.py")
        with open(src, "w") as f:
            f.write(
                "sim_wave(o.axis_in_if.ready)\n"
                "sim_wave(\n    a + b\n)\n"
                "sim_wave(x); sim_wave(y)\n"
                "sim_wave('named', z)\n"
            )
        calls = pypeline._sim_wave_one_arg_calls(src)
        frame = lambda line: SimpleNamespace(  # noqa: E731
            f_code=SimpleNamespace(co_filename=src), f_lineno=line
        )
        assert pypeline._sim_wave_source_name(frame(1)) == "o.axis_in_if.ready"
        assert (
            pypeline._sim_wave_source_name(frame(3)) == "a+b"
        ), "inside a call's lines"
        for line in (5, 6):  # two calls on one line; a named call only
            try:
                pypeline._sim_wave_source_name(frame(line))
            except ValueError as e:
                assert "name the signal" in str(e), e
            else:
                raise AssertionError(f"line {line} named a signal")
    assert len(calls) == 4, calls


def test_sampled_twice_keeps_last_value_and_notes_once():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        printed = record(
            path,
            [[("/x", 1, None), ("/x", 2, None)], [("/x", 3, None), ("/x", 4, None)]],
        )
        signals, _end, _scopes = read_vcd(path)
    assert [v for _t, v in signals["top/x"][2]] == [2, 4]
    assert printed.count("sampled more than once") == 1, printed


def test_type_change_raises_and_untyped_int_fits_typed_signal():
    u8 = pypeline._sim_cast(7, uint8_t)
    u16 = pypeline._sim_cast(7, uint16_t)
    for second in (u16, point_t(x=1, y=1, mode=mode_t.IDLE, lanes=[0, 0, 0]), "seven"):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                record(
                    os.path.join(tmp, "t.vcd"),
                    [[("/x", u8, None)], [("/x", second, None)]],
                )
            except ValueError as e:
                assert "keeps the type it started with" in str(e), e
            else:
                raise AssertionError(f"{second!r} replaced a uint8_t signal")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        record(path, [[("/x", u8, None)], [("/x", 300, None)]])
        signals, _end, _scopes = read_vcd(path)
    assert [v for _t, v in signals["top/x"][2]] == [7, 300 & 0xFF]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            record(os.path.join(tmp, "t.vcd"), [[("/x", -1, None)]])
        except ValueError as e:
            assert "negative" in str(e), e
        else:
            raise AssertionError("a negative int of no type was recorded")


def test_clock_edges_values_at_cycle_times_and_end_time():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        record(path, [[("/k", k, None)] for k in range(4)], period=1000, clock="clk")
        signals, end, _scopes = read_vcd(path)
    assert end == 4000
    assert signals["top/clk"][2] == [
        (0, 0),
        (1000, 1),
        (1500, 0),
        (2000, 1),
        (2500, 0),
        (3000, 1),
        (3500, 0),
    ]
    for k in range(4):
        assert value_at(signals, "top/k", k * 1000) == k
        if k:
            assert value_at(signals, "top/k", k * 1000 - 1) == k - 1


def test_header_is_written_at_close_with_late_signals():
    import SIM

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        with contextlib.redirect_stdout(io.StringIO()):
            recorder = SIM.WaveRecorder(path, "top", "clk", 1000)
            recorder.tap("/early", 1, None)
            recorder.end_cycle(0)
            recorder.tap("/late", 1, None)
            recorder.end_cycle(1)
            assert not os.path.exists(path), "the header waits for close"
            assert os.path.exists(path + ".body.tmp")
            recorder.close()
        assert not os.path.exists(path + ".body.tmp")
        signals, end, _scopes = read_vcd(path)
    assert signals["top/late"][2] == [(1000, 1)] and end == 2000


def test_wire_selection_by_glob():
    import SIM
    import pypeline_sim

    wires = pypeline_sim._DesignWires(
        (
            [
                ("pypeline_design.rst", uint2_t),
                ("pypeline_design.top_wire", uint8_t),
                ("pkg.ports_mod.axis_in_if", uint8_t),
                ("pkg.ports_mod.other", uint8_t),
            ],
            [],
        )
    )
    wires.ports = frozenset({"pypeline_design.rst"})
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.vcd")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            recorder = SIM.WaveRecorder(path, "top", "clk", 1000)
            recorder.add_wires(wires, ["*ports_mod/axis*", "top_wire", "nothing*"])
            recorder.close()
        signals, _end, _scopes = read_vcd(path)
    assert set(signals) == {
        "top/clk",
        "top/rst",
        "top/top_wire",
        "top/pkg_ports_mod/axis_in_if",
    }, signals
    assert "--wave_signals 'nothing*' matches no global Wire" in printed.getvalue()


def test_check_wave_args_refusals():
    import SIM

    def refusal(tool, **settings):
        args = SimpleNamespace(
            wave="run.vcd", wave_signals=[], sim=True, ghdl=False, makefile=None
        )
        vars(args).update(settings)
        saved = SIM.SIM_TOOL
        SIM.SIM_TOOL = tool
        try:
            SIM.CHECK_WAVE_ARGS(args)
        except SystemExit as e:
            return str(e.code)
        finally:
            SIM.SIM_TOOL = saved
        return None

    native, cocotb = SIM.pypeline_sim, SIM.COCOTB
    assert refusal(native) is None
    assert refusal(cocotb, ghdl=True, wave="run.ghw") is None
    assert refusal(native, wave=None) is None
    assert "add --sim" in refusal(native, sim=False)
    assert ".ghw is GHDL's own format" in refusal(native, wave="run.ghw")
    assert "name the waveform file" in refusal(native, wave="run.txt")
    assert "give --wave too" in refusal(native, wave=None, wave_signals=["*"])
    assert "does not exist" in refusal(native, wave="/no/such/dir/run.vcd")
    assert "SIM_ARGS" in refusal(cocotb, ghdl=True, makefile="Makefile")
    assert "native simulation's global Wires" in refusal(
        cocotb, ghdl=True, wave_signals=["*"]
    )
    assert "--cocotb --ghdl" in refusal(SIM.VERILATOR)


def test_sim_debug_gives_each_run_its_own_waveform():
    import pypeline_sim_debug

    native, vhdl = pypeline_sim_debug._wave_run_args("x/any.fst", ["a*"], "/out")
    assert native == ["--wave", "/out/native.fst", "--wave_signals", "a*"], native
    assert vhdl == ["--wave", "/out/vhdl.fst"], vhdl
    assert pypeline_sim_debug._wave_run_args(None, [], "/out") == ([], [])
    for wave, signals in (("x.ghw", []), (None, ["a*"])):
        try:
            pypeline_sim_debug._wave_run_args(wave, signals, "/out")
        except ValueError:
            continue
        raise AssertionError(f"--wave {wave} --wave_signals {signals} accepted")


def test_sim_wave_records_only_with_a_recorder_in_a_final_pass():
    taps = []
    recorder = SimpleNamespace(
        tap=lambda name, value, main: taps.append((name, int(value)))
    )
    assert not pypeline.sim_wave_enabled()
    pypeline.sim_wave("/x", 1)  # no recorder: nothing to do
    pypeline.SET_SIM_WAVE_RECORDER(recorder)
    try:
        assert pypeline.sim_wave_enabled()
        pypeline.sim_wave("/x", 2)
        pypeline._sim_converging = True
        assert not pypeline.sim_wave_enabled()
        pypeline.sim_wave("/x", 3)  # convergence pass: skipped
        pypeline._sim_converging = False
        with pypeline._ConstFolding():
            try:
                pypeline.sim_wave("/x", 4)
            except pypeline.SimOnlyCallInElab:
                pass
            else:
                raise AssertionError("sim_wave ran while elaboration folded constants")
        main = FakeMain("pipe")
        pypeline._sim_pipelined_main_info[main] = {}
        pypeline._sim_current_main = main
        try:
            pypeline.sim_wave("/x", 5)
        except RuntimeError as e:
            assert "sim_wave('/x', ...)" in str(e) and "pipelined pure MAIN" in str(
                e
            ), e
        else:
            raise AssertionError("a tap inside a pipelined MAIN was recorded")
        finally:
            pypeline._sim_current_main = None
            pypeline._sim_pipelined_main_info.clear()
    finally:
        pypeline._sim_converging = False
        pypeline.SET_SIM_WAVE_RECORDER(None)
    assert taps == [("/x", 2)], taps


# ── native_vcd / native_fst: waves_design.py through pypelinec ──────────────


def n_at(k):
    """waves_design.py's counter n in cycle k: reset holds it 0 through cycle 1."""
    return max(0, k - 1)


def phase_at(k):
    return "IDLE" if k <= 1 else ("COUNT" if k <= 5 else "DONE")


def check_design_waveform(path):
    """Every signal of waves_design.py's waveform at every cycle time."""
    signals, end, scopes = read_vcd(path)
    assert (
        end == (FINISH_CYCLE + 1) * PERIOD
    ), f"end time {end}: sim_finish's cycle is shown"
    assert scopes["top/sample"] == "struct", scopes
    assert "top/unselected" not in signals and "top/link/ready" not in signals
    assert signals["top/sample/phase"][0] == "string"
    assert signals["top/counter/pair[1]"][1] == 9, "n + 2 is a uint9_t"
    assert signals["top/s_axis_tdata"][1] == 16
    expected_paths = set()
    for k in range(FINISH_CYCLE + 1):
        n, t = n_at(k), k * PERIOD
        expect = {
            "top/clk_50p0": 1 if k else 0,
            "top/rst": 1 if k == 0 else 0,
            "top/count": n,
            "top/counter/n": n,
            "top/sample/lanes[0]": n,
            "top/sample/lanes[1]": (n + 1) & 0xFF,
            "top/sample/phase": phase_at(k),
            "top/sample/delta": -n & 0xFF,
            "top/counter/snap/delta": -n & 0xFF,
            "top/marker": "low" if n < 4 else "high",
            "top/counter/pair[0]": n,
            "top/counter/pair[1]": n + 2,
            "top/counter/beat/valid": n & 1,
            "top/counter/beat/ready": n >> 1 & 1,
            "top/counter/fsm": phase_at(k),
            "top/s_axis_tdata": n | ((n + 0x10) & 0xFF) << 8,
            "top/s_axis_tkeep": 1 | (n & 1) << 1,
            "top/s_axis_tlast": int(n == 3),
            "top/s_axis_tvalid": 1,
            "top/s_axis_tready": n >> 1 & 1,
        }
        if k < FINISH_CYCLE:  # sim_finish() stops the MAIN before it returns
            expect["top/counter_return_output"] = n + 1
        for name, value in expect.items():
            got = value_at(signals, name, t)
            assert (
                got == value
            ), f"{name} in cycle {k} (t={t}): {got!r}, expected {value!r}"
        if k:
            # Values change at the cycle's own time, not before
            assert value_at(signals, "top/count", t - 1) == n_at(k - 1), k
            assert value_at(signals, "top/clk_50p0", t + PERIOD // 2) == 0, k
        expected_paths |= set(expect)
    assert set(signals) == expected_paths, set(signals) ^ expected_paths


def native_run(out_dir, wave, *extra):
    proc = run(
        [
            sys.executable,
            PYPELINEC,
            DESIGN,
            "--sim",
            "--comb",
            "--run",
            "all",
            "--wave",
            wave,
            "--wave_signals",
            "sample",
            "--out_dir",
            out_dir,
            *extra,
        ]
    )
    assert proc.returncode == 0, f"pypelinec exited {proc.returncode}"
    assert f"Waveform: {wave}" in proc.stdout


def native_vcd(out_dir):
    wave = os.path.join(out_dir, "run.vcd")
    native_run(os.path.join(out_dir, "build"), wave)
    check_design_waveform(wave)
    standalone = os.path.join(out_dir, "standalone.vcd")
    proc = run(
        [
            sys.executable,
            PYPELINE_SIM,
            DESIGN,
            "--run",
            "all",
            "--wave",
            standalone,
            "--wave_signals",
            "sample",
        ]
    )
    assert proc.returncode == 0, f"pypeline_sim.py exited {proc.returncode}"
    with open(wave) as a, open(standalone) as b:
        assert a.read() == b.read(), "pypeline_sim.py --wave wrote another waveform"


def native_fst(out_dir):
    wave = os.path.join(out_dir, "run.fst")
    native_run(os.path.join(out_dir, "build"), wave)
    assert not os.path.exists(wave + ".vcd"), "the VCD vcd2fst converted is left behind"
    readback = os.path.join(out_dir, "readback.vcd")
    proc = run(["fst2vcd", "-f", wave, "-o", readback])
    assert proc.returncode == 0, f"fst2vcd exited {proc.returncode}"
    check_design_waveform(readback)


# ── elab / ghdl ─────────────────────────────────────────────────────────────


def elab(out_dir):
    import glob

    proc = run([sys.executable, PYPELINEC, DESIGN, "--no_synth", "--out_dir", out_dir])
    assert proc.returncode == 0, f"pypelinec exited {proc.returncode}"
    (top_vhd,) = glob.glob(os.path.join(out_dir, "top", "top*.vhd"))
    with open(top_vhd) as f:
        lines = f.read().splitlines()
    port_lines = lines[lines.index("port(") + 1 :]
    port_lines = port_lines[: [line.strip() for line in port_lines].index(");")]
    ports = {line.split(":")[0].strip() for line in port_lines if " : " in line}
    assert ports == {"clk_50p0", "rst", "count", "counter_return_output"}, ports


def ghdl(out_dir):
    for ext, option in (
        ("vcd", "--vcd"),
        ("fst", "--fst"),
        ("ghw", "--wave"),
        (None, None),
    ):
        run_dir = os.path.join(out_dir, ext or "default")
        cmd = [
            sys.executable,
            PYPELINEC,
            DESIGN,
            "--sim",
            "--comb",
            "--cocotb",
            "--ghdl",
            "--run",
            "all",
            "--out_dir",
            run_dir,
        ]
        wave = os.path.join(out_dir, f"ghdl.{ext}")
        if ext:
            cmd += ["--wave", wave]
        proc = run(cmd)
        assert proc.returncode == 0, f"pypelinec exited {proc.returncode}"
        default = os.path.join(run_dir, "cocotb", "top.vcd")
        if ext is None:
            assert os.path.getsize(default) > 0, "no cocotb/top.vcd without --wave"
            continue
        assert os.path.getsize(wave) > 0, f"GHDL wrote no {wave}"
        assert not os.path.exists(default), "--wave also wrote cocotb/top.vcd"
        with open(os.path.join(run_dir, "cocotb", "Makefile")) as f:
            assert f"SIM_ARGS += {option}={wave} " in f.read(), option


VARIANTS = {
    "native_vcd": native_vcd,
    "native_fst": native_fst,
    "elab": elab,
    "ghdl": ghdl,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=["unit"] + sorted(VARIANTS))
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    if args.variant == "unit":
        from _test_main import run_module_tests

        run_module_tests()
        return
    out_dir = os.path.abspath(args.out_dir or tempfile.mkdtemp(prefix="waves_test_"))
    os.makedirs(out_dir, exist_ok=True)
    VARIANTS[args.variant](out_dir)
    print(f"waves_test {args.variant}: passed")


if __name__ == "__main__":
    main()
