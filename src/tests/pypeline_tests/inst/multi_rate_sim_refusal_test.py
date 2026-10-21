"""Native simulation refuses a design whose @MAINs name more than one rate
(issue #354): it would step every MAIN once per cycle, running the clocks
in lockstep. Both entry points, pypeline_sim.py and pypelinec --sim --comb,
must exit non-zero and name both rates and their MAINs. A bare @MAIN next
to one rate names no rate of its own, so that design still simulates.
"""

import os
import subprocess
import sys
import tempfile

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
PYPELINE_SIM = os.path.join(SRC_DIR, "pypeline_sim.py")
PYPELINEC = os.path.join(SRC_DIR, "pypelinec")

TWO_RATES = """
from pypeline import *

@MAIN(100.0)
def fast():
    n: Reg[uint8_t]
    n += 1

@MAIN(50.0)
def slow():
    m: Reg[uint8_t]
    m += 1
"""

ONE_RATE_AND_BARE = """
from pypeline import *

@MAIN(100.0)
def fast():
    n: Reg[uint8_t]
    n += 1

@MAIN
def bare():
    m: Reg[uint8_t]
    if m == 2:
        sim_print("bare MAIN simulated")
    m += 1
"""


def _run(cmd, cwd):
    proc = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return proc.returncode, proc.stdout


def main():
    with tempfile.TemporaryDirectory(prefix="multi_rate_sim_refusal_test_") as tmpdir:
        for name, text in (("two_rates.py", TWO_RATES), ("one_rate.py", ONE_RATE_AND_BARE)):
            with open(os.path.join(tmpdir, name), "w") as f:
                f.write(f"import sys\nsys.path.insert(0, {SRC_DIR!r})\n" + text)
        out_dir = os.path.join(tmpdir, "out")
        runners = {
            "pypeline_sim.py": lambda design: [
                sys.executable, PYPELINE_SIM, design, "--run", "5",
            ],
            "pypelinec --sim --comb": lambda design: [
                sys.executable, PYPELINEC, design, "--sim", "--comb", "--run", "5",
                "--out_dir", out_dir,
            ],
        }
        for label, cmd in runners.items():
            code, out = _run(cmd("two_rates.py"), tmpdir)
            assert code != 0, f"{label}: a two-rate design simulated:\n{out}"
            for token in ("2 rates", "50.0 MHz: slow", "100.0 MHz: fast"):
                assert token in out, f"{label}: expected {token!r} in:\n{out}"
            print(f"{label} refuses two rates PASS")
            code, out = _run(cmd("one_rate.py"), tmpdir)
            assert code == 0, f"{label}: one rate plus a bare MAIN failed:\n{out}"
            assert "bare MAIN simulated" in out, out
            print(f"{label} one rate plus a bare MAIN PASS")
    print("multi_rate_sim_refusal_test: all PASS")


if __name__ == "__main__":
    main()
