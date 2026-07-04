# pyright: reportInvalidTypeForm=none
"""sim_model tests: Python simulation models attached to hardware functions.

Run directly (python3 sim_model_test.py) for the Layer-1 sim_call tests, or via
the multi-MAIN runner (pypeline_sim.py sim_model_test.py --run N) for the
wire-convergence no-double-mutation test.
"""

import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import numpy as np

from pypeline import (
    MAIN,
    Reg,
    Wire,
    hw_func,
    sim_call,
    sim_model,
    sim_output,
    sim_reset,
    uint8_t,
    uint32_t,
    vhdl,
)

# Clocked accumulator with a combinational path through to the output
# (return_output includes the current din, matching the models below).
ACCUM_VHDL = """
signal total : unsigned(31 downto 0) := (others => '0');
begin
process(clk) begin
    if rising_edge(clk) then
        if CLOCK_ENABLE(0) = '1' then
            total <= total + din;
        end if;
    end if;
end process;
return_output <= total + din;
"""


# ── DUT #1: raw-VHDL accumulator modeled by a synthesizable @hw_func delegate ──


@hw_func
def accum_hw(din: uint32_t) -> uint32_t:
    vhdl(ACCUM_VHDL)


@sim_model(accum_hw)
@hw_func
def accum_hw_model(din: uint32_t) -> uint32_t:
    total: Reg[uint32_t]
    total = total + din
    return total


# ── DUT #2: same VHDL, modeled by an arbitrary Python class (numpy state) ──


@hw_func
def accum_np(din: uint32_t) -> uint32_t:
    vhdl(ACCUM_VHDL)


@sim_model(accum_np)
class AccumNumpyModel:
    """Sim-only model: every element ever seen is appended to a growing numpy
    array and the output is the sum over the whole array each cycle."""

    def __init__(self):
        self.samples = np.array([], dtype=np.uint64)

    def __call__(self, din):
        self.samples = np.append(self.samples, int(din))
        return int(self.samples.sum())


# ── DUT #3: narrow return type, to check model outputs get boundary casting ──


@hw_func
def accum8(din: uint8_t) -> uint8_t:
    vhdl(ACCUM_VHDL)


@sim_model(accum8)
class Accum8Model:
    def __init__(self):
        self.samples = []

    def __call__(self, din):
        self.samples.append(int(din))
        return sum(self.samples)


# ── DUT #4: copy_state=False in-place model ──


@hw_func
def accum_inplace(din: uint32_t) -> uint32_t:
    vhdl(ACCUM_VHDL)


@sim_model(accum_inplace, copy_state=False)
class AccumInPlaceModel:
    def __init__(self):
        self.total = 0

    def __call__(self, din):
        self.total += int(din)
        return self.total


# ── DUT #5: model overriding an ordinary (non-vhdl) hardware function ──


@hw_func
def add_one(x: uint32_t) -> uint32_t:
    return x + 1


@sim_model(add_one)
class AddOneOverrideModel:
    def __call__(self, x):
        # Deliberately different from the hardware body to prove the model runs.
        return int(x) + 1000000


# ── vhdl func with no model: must still raise NotImplementedError in sim ──


@hw_func
def no_model_vhdl(x: uint32_t) -> uint32_t:
    vhdl(
        """
        begin
        return_output <= x;
        """
    )


def drive_two_sites(a, b):
    """Two distinct call sites of accum_hw = two independent hardware instances."""
    x = accum_hw(a)
    y = accum_hw(b)
    return int(x), int(y)


def test_delegate_model_two_instances():
    sim_reset()
    assert sim_call(drive_two_sites, 3, 5) == (3, 5)
    assert sim_call(drive_two_sites, 3, 5) == (6, 10)
    assert sim_call(drive_two_sites, 1, 1) == (7, 11)


def test_class_model_matches_delegate():
    sim_reset()
    for din in [3, 5, 1, 100]:
        assert int(sim_call(accum_np, din)) == int(sim_call(accum_hw, din))


def test_return_cast_wraps():
    sim_reset()
    assert int(sim_call(accum8, 200)) == 200
    # Model returns raw Python 400; the uint8_t boundary cast must wrap it.
    assert int(sim_call(accum8, 200)) == (400 & 0xFF)


def test_sim_reset_recreates_model_instances():
    sim_reset()
    assert int(sim_call(accum_np, 7)) == 7
    assert int(sim_call(accum_np, 7)) == 14
    sim_reset()
    assert int(sim_call(accum_np, 7)) == 7


def test_copy_state_false_inplace():
    sim_reset()
    assert int(sim_call(accum_inplace, 3)) == 3
    assert int(sim_call(accum_inplace, 5)) == 8
    sim_reset()
    assert int(sim_call(accum_inplace, 2)) == 2


def test_model_overrides_normal_hw_func():
    sim_reset()
    assert int(sim_call(add_one, 1)) == 1000001


def test_no_model_still_raises():
    try:
        sim_call(no_model_vhdl, 1)
    except NotImplementedError:
        return
    raise AssertionError("expected NotImplementedError from model-less vhdl(...)")


def test_errors():
    # Target must be @hw_func/@MAIN decorated.
    def not_hw(x):
        return x

    try:
        sim_model(not_hw)
        raise AssertionError("expected TypeError for undecorated target")
    except TypeError:
        pass

    @hw_func
    def fresh_target(din: uint32_t) -> uint32_t:
        vhdl(ACCUM_VHDL)

    # @hw_func delegate signature must match the target's.
    try:

        @sim_model(fresh_target)
        @hw_func
        def bad_sig(din: uint8_t) -> uint32_t:
            return din

        raise AssertionError("expected TypeError for delegate signature mismatch")
    except TypeError:
        pass

    # Exactly one model per target: a second attachment (either form) raises.
    @sim_model(fresh_target)
    @hw_func
    def good_model(din: uint32_t) -> uint32_t:
        total: Reg[uint32_t]
        total = total + din
        return total

    try:

        @sim_model(fresh_target)
        class SecondModel:
            def __call__(self, din):
                return 0

        raise AssertionError("expected ValueError for second sim_model attachment")
    except ValueError:
        pass

    # A class model must be instance-callable.
    @hw_func
    def another_target(din: uint32_t) -> uint32_t:
        vhdl(ACCUM_VHDL)

    try:

        @sim_model(another_target)
        class NotCallable:
            pass

        raise AssertionError("expected TypeError for class model without __call__")
    except TypeError:
        pass


# ── Multi-MAIN convergence design (run via pypeline_sim.py --run N) ──
# accum_main is registered (and thus queued) BEFORE driver_main, so each cycle
# it first evaluates the model with the stale accum_in value from the previous
# cycle; driver_main then advances the wire, forcing accum_main to re-evaluate
# within the same cycle (plus the final post-convergence pass). The checker
# asserts the model's state still advances exactly once per clock cycle, from
# converged inputs: at cycle N, accum_in has held 0,1,...,N so the numpy model's
# total must be N*(N+1)/2. Any double-mutation from re-evaluation breaks this.

accum_in: Wire[uint32_t]
accum_total: Wire[uint32_t]


@MAIN
def accum_main():
    accum_total = accum_np(accum_in)


@MAIN
def driver_main():
    count: Reg[uint32_t]
    accum_in = count
    count = count + 1


@sim_output
def check_accum(cycle, total):
    expected = (int(cycle) * (int(cycle) + 1)) // 2
    assert int(total) == expected, (
        f"cycle {int(cycle)}: accum_total={int(total)} expected={expected} "
        f"(sim model state advanced more than once per cycle?)"
    )


@MAIN
def checker_main():
    n: Reg[uint32_t]
    check_accum(n, accum_total)
    n = n + 1


if __name__ == "__main__":
    test_delegate_model_two_instances()
    test_class_model_matches_delegate()
    test_return_cast_wraps()
    test_sim_reset_recreates_model_instances()
    test_copy_state_false_inplace()
    test_model_overrides_normal_hw_func()
    test_no_model_still_raises()
    test_errors()
    print("OK: sim_model tests passed")
