"""Native simulation of @MAINs made in code (MAIN(fn, name=...)). Each design
below runs through pypeline_sim.py in a subprocess; the test checks its
output.

- Counter lanes made by one factory keep their own Reg state: every MAIN
  runs under its own root instance frame.
- Stateless lanes writing different elements of one wire keep all of them:
  each function's wire-claim key is its own, so one lane's per-call reset
  never zeros another lane's element.
- Two stateless made MAINs calling one make_stream_fifo FIFO keep separate
  FIFO model state (native_sim_stateless_model_state.md's cross-MAIN case).
- Two MAINs with one name stop native sim with an error.
- The multi-rate refusal names made MAINs by their MAIN names.
- MAIN() in an @initial(sim) hook is an error: the MAINs are collected.

Registered in native_sim_tests.py.
"""

import os
import subprocess
import sys
import tempfile

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
PYPELINE_SIM = os.path.join(SRC_DIR, "pypeline_sim.py")

COUNTER_LANES = """
from pypeline import *


def make_lane(i):
    @hw_func
    def lane():
        n: Reg[uint8_t]
        sim_print(f"lane{i} n={n}")
        n += i + 1

    return lane


lanes = [MAIN(make_lane(i), name=f"lane{i}") for i in range(3)]
"""

ELEMENT_LANES = """
from pypeline import *

vals: Wire[uint8_t[3]]


def make_lane(i):
    @hw_func
    def lane():
        vals[i] = i + 1

    return lane


lanes = [MAIN(make_lane(i), name=f"lane{i}") for i in range(3)]


@sim_output
def show(v: uint8_t[3]):
    print("vals", int(v[0]), int(v[1]), int(v[2]))


@MAIN
def check():
    show(vals)
"""

FIFO_LANES = """
from pypeline import *
from stream.stream_fifo import make_stream_fifo

F = make_stream_fifo(uint8_t, 4)
outs: Wire[uint8_t[2]]


def make_fifo_lane(i, word):
    @hw_func
    def fifo_lane():
        r = F(
            F.fwd_t(stream=F.stream_intrf.stream_t(data=word, valid=1)),
            F.fb_t(ready=1),
        )
        outs[i] = r.out_stream_if.stream.data

    return fifo_lane


MAIN(make_fifo_lane(0, 7), name="fa")
MAIN(make_fifo_lane(1, 9), name="fb")


@sim_output
def show(v: uint8_t[2]):
    print("outs", int(v[0]), int(v[1]))


@MAIN
def check():
    show(outs)
"""

DUPLICATE_NAMES = """
from pypeline import *


def make_lane(i):
    @hw_func
    def lane():
        n: Reg[uint8_t]
        n += i

    return lane


lanes = [MAIN(make_lane(i)) for i in range(2)]
"""

TWO_RATES = """
from pypeline import *


def make_lane(i):
    @hw_func
    def lane():
        n: Reg[uint8_t]
        n += i

    return lane


MAIN(make_lane(0), name="fast", mhz=100.0)
MAIN(make_lane(1), name="slow", mhz=50.0)
"""

MAIN_IN_HOOK = """
from pypeline import *


def make_lane(i):
    @hw_func
    def lane():
        n: Reg[uint8_t]
        n += i

    return lane


MAIN(make_lane(0), name="lane0")


@initial(sim=True)
def late():
    MAIN(make_lane(1), name="lane1")
"""


def _sim(tmpdir, name, text, cycles=4):
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        f.write(f"import sys\nsys.path.insert(0, {SRC_DIR!r})\n" + text)
    proc = subprocess.run(
        [sys.executable, PYPELINE_SIM, path, "--run", str(cycles)],
        cwd=tmpdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout


def test_counter_lanes_keep_their_own_registers(tmpdir):
    code, out = _sim(tmpdir, "counter_lanes.py", COUNTER_LANES)
    assert code == 0, out
    # Lane i counts by its own step, i + 1, cycle after cycle
    for i in range(3):
        seen = [line for line in out.splitlines() if line.startswith(f"lane{i} ")]
        want = [f"lane{i} n={c * (i + 1)}" for c in range(4)]
        assert seen == want, (seen, want, out)
    print("test_counter_lanes_keep_their_own_registers PASS")


def test_lanes_keep_their_own_wire_elements(tmpdir):
    code, out = _sim(tmpdir, "element_lanes.py", ELEMENT_LANES)
    assert code == 0, out
    lines = [line for line in out.splitlines() if line.startswith("vals")]
    assert lines and all(line == "vals 1 2 3" for line in lines), out
    print("test_lanes_keep_their_own_wire_elements PASS")


def test_stateless_mains_keep_their_own_fifo_models(tmpdir):
    code, out = _sim(tmpdir, "fifo_lanes.py", FIFO_LANES)
    assert code == 0, out
    lines = [line for line in out.splitlines() if line.startswith("outs")]
    # The FWFT FIFO shows each MAIN's own word from cycle 2
    assert lines[2:] and all(line == "outs 7 9" for line in lines[2:]), out
    print("test_stateless_mains_keep_their_own_fifo_models PASS")


def test_two_mains_with_one_name_stop_native_sim(tmpdir):
    code, out = _sim(tmpdir, "duplicate.py", DUPLICATE_NAMES)
    assert code != 0, out
    for token in ("ERROR: Two @MAINs are named 'lane'", "MAIN(fn, name=...)"):
        assert token in out, (token, out)
    print("test_two_mains_with_one_name_stop_native_sim PASS")


def test_multi_rate_refusal_names_made_mains(tmpdir):
    code, out = _sim(tmpdir, "two_rates.py", TWO_RATES)
    assert code != 0, out
    for token in ("2 rates", "50.0 MHz: slow", "100.0 MHz: fast"):
        assert token in out, (token, out)
    print("test_multi_rate_refusal_names_made_mains PASS")


def test_main_in_a_sim_hook_is_an_error(tmpdir):
    code, out = _sim(tmpdir, "main_in_hook.py", MAIN_IN_HOOK)
    assert code != 0, out
    assert "during a simulation run" in out, out
    print("test_main_in_a_sim_hook_is_an_error PASS")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="factory_main_sim_test_") as tmp:
        test_counter_lanes_keep_their_own_registers(tmp)
        test_lanes_keep_their_own_wire_elements(tmp)
        test_stateless_mains_keep_their_own_fifo_models(tmp)
        test_two_mains_with_one_name_stop_native_sim(tmp)
        test_multi_rate_refusal_names_made_mains(tmp)
        test_main_in_a_sim_hook_is_an_error(tmp)
    print("factory_main_sim_test: all PASS")
