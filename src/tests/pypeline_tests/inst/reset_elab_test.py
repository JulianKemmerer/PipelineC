"""In-process checks of resets in elaboration and VHDL rendering: each design
below is written to a temp .py file and parsed with PY_TO_LOGIC.PARSE_FILE,
then checked against the parser state, the entity text and name
(VHDL.WRITE_LOGIC_ENTITY at zero added clocks), the raised ElaborationError,
or the printed notes.

- main_resets: a MAIN takes its clock's primary reset under "requested", its
  MAIN(reset=) and reset_registers=, and none with reset=None.
- RESET ports: an entity has the port exactly when something in or below it
  resets under its MAIN's policy; one function under "all", under
  "requested" (with a Reg[T, RESET]) and without reset is per-policy
  entities, and the reset-free one keeps the name a design without resets
  gives it; Reg[T, NO_RESET] stays out of the reset block; raw vhdl(...,
  reset="sync") gets the port under "all" and a constant '0' otherwise.
- Errors: Reg[T, RESET] or reset_registers="all" with no reset, a MAIN reset
  by a reset it drives, an unbound reset, a reset on an Output or with a
  marker or of the wrong type, a reset bound twice, a reset pin used on two
  clocks, a reset Wire driven on another clock, vhdl(reset=) values and a raw
  argument named reset.
- Notes: an unused reset pin is dropped, so it makes no port; raw vhdl()
  without reset= under "all" keeps its state.
- Global instances and same-clock FIFOs reset with their clock's primary
  reset under "all", and keep their names on a clock without one; an "all"
  user with another reset, or at an async FIFO's end, is an error.
- The ASIC initializer rule (CHECK_ASIC_REGISTER_INITS,
  SYN.TARGET_HAS_REGISTER_POWER_UP_VALUES), run by SYN.RESOLVE_BUILD_TARGET
  for a declared ASIC target and not for a build with no target.
"""

import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import AUTO_PIPELINE
import LOGIC
import PY_TO_LOGIC
import SYN
import VHDL

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *

"""


def _parse(src, name):
    """Parse a design; returns (parser_state, printed output)."""
    out = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="reset_elab_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        with contextlib.redirect_stdout(out):
            state = PY_TO_LOGIC.PARSE_FILE(path)
    return state, out.getvalue()


def _expect_error(src, name, must_contain):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token in msg, f"{name}: expected {token!r} in the error, got: {msg}"
        print(f"{name} PASS  ({msg.splitlines()[0][:100]})")
        return
    raise AssertionError(f"{name}: expected an ElaborationError, PARSE_FILE succeeded")


def _entities(state, func):
    """{MAIN: (entity name, entity text)} of each instance of `func`, at zero
    added clocks."""
    timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    out = {}
    for inst in sorted(state.FuncToInstances[func]):
        logic = state.LogicInstLookupTable[inst]
        name = VHDL.GET_ENTITY_NAME(inst, logic, timing, state)
        text = VHDL.WRITE_LOGIC_ENTITY(inst, logic, None, state, timing, return_text=True)
        out[inst.split(LOGIC.SUBMODULE_MARKER)[0]] = (name, text)
    return out


_COUNTER = """
@hw_func
def counter(en: uint1_t) -> uint8_t:
    count: Reg[uint8_t] = 3
    hist: Reg[uint8_t, NO_RESET]
    rv = count + hist
    if en:
        count = count + 1
    hist = count
    return rv
"""


def test_main_resets():
    state, _out = _parse(
        """
rst: Input[uint1_t] = make_reset()
other: Input[uint1_t] = make_reset()
clk = make_clock(100.0, reset=rst)

@MAIN(clk)
def plain():
    n: Reg[uint8_t, RESET]
    n += 1

@MAIN(clk, reset_registers="all")
def every():
    n: Reg[uint8_t]
    n += 1

@MAIN(clk, reset=other, reset_registers="all")
def chosen():
    n: Reg[uint8_t]
    n += 1

@MAIN(clk, reset=None)
def none():
    n: Reg[uint8_t]
    n += 1
""",
        "main_resets_test.py",
    )
    resets = state.main_resets
    assert resets["plain"] == PY_TO_LOGIC.MainReset("rst", "requested"), resets
    assert resets["every"] == PY_TO_LOGIC.MainReset("rst", "all"), resets
    assert resets["chosen"] == PY_TO_LOGIC.MainReset("other", "all"), resets
    assert "none" not in resets, resets
    assert {"rst", "other"} <= state.input_wires
    print("test_main_resets PASS")


def test_per_policy_entities():
    src = (
        """
rst: Input[uint1_t] = make_reset()
clk = make_clock(100.0, reset=rst)
"""
        + _COUNTER
        + """
@MAIN(clk, reset_registers="all")
def dut(en: uint1_t) -> uint8_t:
    return counter(en)

@MAIN(clk)
def ctrl(en: uint1_t) -> uint8_t:
    pc: Reg[uint8_t, RESET] = 7
    rv = pc + counter(en)
    pc = pc + en
    return rv

@MAIN(clk, reset=None)
def free(en: uint1_t) -> uint8_t:
    return counter(en)
"""
    )
    state, _out = _parse(src, "per_policy_test.py")
    ents = _entities(state, "counter")
    (all_name, all_text) = ents["dut"]
    (req_name, req_text) = ents["ctrl"]
    (free_name, free_text) = ents["free"]
    # Under "all" the counter resets; under "requested" (no Reg[T, RESET] in it)
    # and with no reset it does not, and is one entity
    assert " RESET : in std_logic;" in all_text, all_text
    assert "RESET" not in req_text and req_name == free_name, (req_name, free_name)
    assert all_name != free_name
    # The reset-free entity keeps the name a design without resets gives it
    plain_state, _ = _parse(
        _COUNTER
        + """
@MAIN(100.0)
def free(en: uint1_t) -> uint8_t:
    return counter(en)
""",
        "per_policy_plain_test.py",
    )
    assert _entities(plain_state, "counter")["free"][0] == free_name
    # The MAIN with a Reg[T, RESET] has the port; its counter's instance does not
    timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    ctrl_text = VHDL.WRITE_LOGIC_ENTITY(
        "ctrl", state.LogicInstLookupTable["ctrl"], None, state, timing, return_text=True
    )
    assert " RESET : in std_logic;" in ctrl_text and "pc <= to_unsigned(7, 8);" in ctrl_text
    print("test_per_policy_entities PASS")


def test_no_reset_register_kept():
    state, _out = _parse(
        """
rst: Input[uint1_t] = make_reset()
"""
        + _COUNTER
        + """
@MAIN(100.0, reset=rst, reset_registers="all")
def dut(en: uint1_t) -> uint8_t:
    return counter(en)
""",
        "no_reset_test.py",
    )
    _name, text = _entities(state, "counter")["dut"]
    block = text.split("if RESET = '1' then", 1)[1].split("end if;", 1)[0]
    assert "count <= to_unsigned(3, 8);" in block, block
    assert "hist" not in block, block
    print("test_no_reset_register_kept PASS")


def test_requested_policy_resets_only_marked():
    state, _out = _parse(
        """
rst: Input[uint1_t] = make_reset()

@hw_func
def two() -> uint8_t:
    a: Reg[uint8_t, RESET] = 1
    b: Reg[uint8_t] = 2
    rv = a + b
    a += 1
    b += 1
    return rv

@MAIN(100.0, reset=rst)
def req() -> uint8_t:
    return two()

@MAIN(100.0, reset=rst, reset_registers="all")
def every() -> uint8_t:
    return two()
""",
        "requested_test.py",
    )
    ents = _entities(state, "two")
    req_block = ents["req"][1].split("if RESET = '1' then", 1)[1].split("end if;", 1)[0]
    all_block = ents["every"][1].split("if RESET = '1' then", 1)[1].split("end if;", 1)[0]
    assert "a <= to_unsigned(1, 8);" in req_block and " b <=" not in req_block, req_block
    assert "a <= to_unsigned(1, 8);" in all_block and "b <= to_unsigned(2, 8);" in all_block
    assert ents["req"][0] != ents["every"][0]
    print("test_requested_policy_resets_only_marked PASS")


_RAW = """
@hw_func
def held(x: uint8_t) -> uint8_t:
    vhdl('''
signal r : unsigned(7 downto 0) := (others => '0');
begin
process(clk) begin
  if rising_edge(clk) then
    r <= x;
    if RESET = '1' then r <= (others => '0'); end if;
  end if;
end process;
return_output <= r;
''', reset="sync")
"""


def test_raw_vhdl_reset_port_or_constant():
    state, out = _parse(
        "rst: Input[uint1_t] = make_reset()\n"
        + _RAW
        + """
@MAIN(100.0, reset=rst, reset_registers="all")
def every(x: uint8_t) -> uint8_t:
    return held(x)

@MAIN(100.0, reset=rst)
def req(x: uint8_t) -> uint8_t:
    return held(x)
""",
        "raw_reset_test.py",
    )
    ents = _entities(state, "held")
    assert " RESET : in std_logic;" in ents["every"][1]
    assert "constant RESET" not in ents["every"][1]
    assert "constant RESET : std_logic := '0';" in ents["req"][1], ents["req"][1]
    assert " RESET : in std_logic;" not in ents["req"][1]
    assert "keeps its state" not in out
    print("test_raw_vhdl_reset_port_or_constant PASS")


def test_note_raw_vhdl_keeps_state():
    _state, out = _parse(
        """
rst: Input[uint1_t] = make_reset()

@hw_func
def raw_keep(x: uint8_t) -> uint8_t:
    vhdl("return_output <= x;")

@MAIN(100.0, reset=rst, reset_registers="all")
def every(x: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    n = raw_keep(x)
    return n
""",
        "raw_note_test.py",
    )
    assert "'raw_keep' is raw vhdl() without reset=" in out, out
    print("test_note_raw_vhdl_keeps_state PASS")


def test_note_unused_reset_pin_dropped():
    state, out = _parse(
        """
rst: Input[uint1_t] = make_reset()

@MAIN(100.0)
def m():
    n: Reg[uint8_t]
    n += 1
""",
        "unused_reset_test.py",
    )
    assert "rst" not in state.input_wires and "rst" not in state.global_vars
    assert "reset 'rst'" in out and "makes no port" in out, out
    print("test_note_unused_reset_pin_dropped PASS")


def test_error_requested_reg_without_reset():
    _expect_error(
        """
@MAIN(100.0)
def m():
    pc: Reg[uint8_t, RESET]
    pc += 1
""",
        "requested_no_reset_test.py",
        ["'pc'", "Reg[T, RESET]", "has no reset", "make_clock(..., reset=rst)"],
    )


def test_error_all_without_reset():
    _expect_error(
        """
@MAIN(100.0, reset_registers="all")
def m():
    n: Reg[uint8_t]
    n += 1
""",
        "all_no_reset_test.py",
        ['reset_registers="all"', "but no reset"],
    )


def test_error_reset_by_own_logic():
    _expect_error(
        """
gen: Wire[uint1_t] = make_reset()

@MAIN(100.0, reset=gen, reset_registers="all")
def m():
    n: Reg[uint8_t]
    gen = n == 9
    n += 1
""",
        "own_reset_test.py",
        ["MAIN 'm' is reset by reset 'gen'", "drives below it"],
    )


def test_error_unbound_reset():
    _expect_error(
        """
loose = make_reset()

@MAIN(100.0, reset=loose, reset_registers="all")
def m():
    n: Reg[uint8_t]
    n += 1
""",
        "unbound_reset_test.py",
        ["bound to no wire"],
    )


def test_error_reset_binding_forms():
    _expect_error(
        "out_rst: Output[uint1_t] = make_reset()\n",
        "output_reset_test.py",
        ["Output", "cannot carry a reset"],
    )
    _expect_error(
        "a_rst: Input[uint1_t, ASYNC] = make_reset()\n",
        "async_reset_test.py",
        ["takes no ASYNC"],
    )
    _expect_error(
        "w_rst: Input[uint8_t] = make_reset()\n"
        "@MAIN(100.0, reset=w_rst)\ndef m():\n    pass\n",
        "wide_reset_test.py",
        ["must be uint1_t"],
    )
    _expect_error(
        "r = make_reset()\nr1: Input[uint1_t] = r\nr2: Input[uint1_t] = r\n",
        "twice_reset_test.py",
        ["bound twice"],
    )


def test_error_reset_pin_on_two_clocks():
    _expect_error(
        """
rst: Input[uint1_t] = make_reset()
a_clk = make_clock(100.0, reset=rst)
b_clk = make_clock(50.0, reset=rst)

@MAIN(a_clk, reset_registers="all")
def a():
    n: Reg[uint8_t]
    n += 1

@MAIN(b_clk, reset_registers="all")
def b():
    n: Reg[uint8_t]
    n += 1
""",
        "pin_two_clocks_test.py",
        ["Reset pin 'rst'", "two clocks", "other_rst_sync"],
    )


def test_error_reset_wire_other_clock():
    _expect_error(
        """
gen: Wire[uint1_t] = make_reset()
a_clk = make_clock(100.0)
b_clk = make_clock(50.0)

@MAIN(a_clk)
def maker():
    n: Reg[uint8_t]
    gen = n == 3
    n += 1

@MAIN(b_clk, reset=gen, reset_registers="all")
def b():
    n: Reg[uint8_t]
    n += 1
""",
        "wire_other_clock_test.py",
        ["Reset Wire 'gen'", "clk_100p0", "clk_50p0"],
    )


def test_error_raw_vhdl_reset_args():
    _expect_error(
        """
@hw_func
def raw(x: uint8_t) -> uint8_t:
    vhdl("return_output <= x;", reset="async")

@MAIN(100.0)
def m(x: uint8_t) -> uint8_t:
    return raw(x)
""",
        "raw_bad_reset_test.py",
        ["reset='async'", 'reset="sync"'],
    )
    _expect_error(
        """
@hw_func
def raw(reset: uint1_t) -> uint1_t:
    vhdl("return_output <= reset;")

@MAIN(100.0)
def m(x: uint1_t) -> uint1_t:
    return raw(x)
""",
        "raw_reset_arg_test.py",
        ["argument named 'reset'", "RESET port"],
    )


_GLOBAL_INSTS = """
@hw_func
def counter(step: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    rv = n
    n += step
    return rv

c1: Inst[counter]
words: Fifo[uint8_t] = global_fifo(4)

@MAIN(clk, reset_registers=POLICY)
def producer():
    words.wr.stream.data = 1
    words.wr.stream.valid = 1

@MAIN(clk)
def consumer() -> uint8_t:
    words.rd.ready = 1
    c1.step = 1
    return c1.out + words.rd.stream.data
"""


def test_global_insts_reset_with_their_clock():
    state, _out = _parse(
        "rst: Input[uint1_t] = make_reset()\nclk = make_clock(100.0, reset=rst)\n"
        + _GLOBAL_INSTS.replace("POLICY", '"all"'),
        "global_insts_reset_test.py",
    )
    assert state.main_resets["c1_INST"] == PY_TO_LOGIC.MainReset("rst", "all")
    assert state.main_resets["words_FIFO"] == PY_TO_LOGIC.MainReset("rst", "all")
    print("test_global_insts_reset_with_their_clock PASS")


def test_global_insts_without_clock_reset_keep_names():
    src = "clk = make_clock(100.0)\n" + _GLOBAL_INSTS.replace("POLICY", '"requested"')
    state, _out = _parse(src, "global_insts_free_test.py")
    assert "c1_INST" not in state.main_resets and "words_FIFO" not in state.main_resets
    # Named as before resets existed: no element of the entity hash
    timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    for main in ("c1_INST", "words_FIFO"):
        logic = state.LogicInstLookupTable[main]
        assert not VHDL.LOGIC_NEEDS_RESET(main, logic, state, timing), main
    print("test_global_insts_without_clock_reset_keep_names PASS")


def test_error_all_user_with_other_reset():
    _expect_error(
        "rst: Input[uint1_t] = make_reset()\nother: Input[uint1_t] = make_reset()\n"
        "clk = make_clock(100.0, reset=rst)\n"
        + _GLOBAL_INSTS.replace(
            "@MAIN(clk, reset_registers=POLICY)",
            '@MAIN(clk, reset=other, reset_registers="all")',
        ),
        "global_inst_other_reset_test.py",
        ["MAIN 'producer' resets with reset 'other'", "clock's primary", "make_clock"],
    )


def test_error_all_at_async_fifo_end():
    _expect_error(
        """
rst: Input[uint1_t] = make_reset()
a_clk = make_clock(100.0, reset=rst)
b_clk = make_clock(50.0)
q: Fifo[uint8_t] = global_fifo(4)

@MAIN(a_clk, reset_registers="all")
def wr():
    q.wr.stream.data = 1
    q.wr.stream.valid = 1

@MAIN(b_clk)
def rd() -> uint8_t:
    q.rd.ready = 1
    return q.rd.stream.data
""",
        "async_fifo_all_test.py",
        ["an async FIFO", 'reset_registers="requested"'],
    )


_ASIC = """
rst: Input[uint1_t] = make_reset()

@hw_func
def counter() -> uint8_t:
    c: Reg[uint8_t] = 3
    z: Reg[uint8_t]
    rv = c + z
    c += 1
    z += 1
    return rv
"""


def _asic_error(state):
    try:
        PY_TO_LOGIC.CHECK_ASIC_REGISTER_INITS(state, "sky130")
    except PY_TO_LOGIC.ElaborationError as e:
        return str(e)
    return None


def test_asic_initializer_without_reset_fails():
    state, _out = _parse(
        _ASIC + "\n@MAIN(100.0)\ndef m() -> uint8_t:\n    return counter()\n",
        "asic_free_test.py",
    )
    msg = _asic_error(state)
    assert msg is not None and "'c' in 'counter', under MAIN 'm' (no reset)" in msg, msg
    # An omitted initializer (z) is not checked
    assert "'z'" not in msg, msg
    print("test_asic_initializer_without_reset_fails PASS")


def test_asic_available_reset_is_not_enough():
    state, _out = _parse(
        _ASIC + "\n@MAIN(100.0, reset=rst)\ndef m() -> uint8_t:\n    return counter()\n",
        "asic_requested_test.py",
    )
    msg = _asic_error(state)
    assert msg is not None and "reset_registers='requested'" in msg, msg
    print("test_asic_available_reset_is_not_enough PASS")


def test_asic_participating_reset_passes():
    state, _out = _parse(
        _ASIC
        + '\n@MAIN(100.0, reset=rst, reset_registers="all")\n'
        + "def m() -> uint8_t:\n    return counter()\n"
        + "\n@MAIN(100.0, reset=rst)\ndef r() -> uint8_t:\n"
        + "    pc: Reg[uint8_t, RESET] = 5\n    rv = pc\n    pc += 1\n    return rv\n",
        "asic_all_test.py",
    )
    assert _asic_error(state) is None
    print("test_asic_participating_reset_passes PASS")


def test_asic_no_reset_marker_with_initializer_fails():
    state, _out = _parse(
        """
rst: Input[uint1_t] = make_reset()

@MAIN(100.0, reset=rst, reset_registers="all")
def m() -> uint8_t:
    h: Reg[uint8_t, NO_RESET] = 9
    rv = h
    h += 1
    return rv
""",
        "asic_no_reset_test.py",
    )
    msg = _asic_error(state)
    assert msg is not None and "'h' in 'm'" in msg, msg
    print("test_asic_no_reset_marker_with_initializer_fails PASS")


def test_asic_names_the_unreset_instance():
    state, _out = _parse(
        _ASIC
        + '\n@MAIN(100.0, reset=rst, reset_registers="all")\n'
        + "def m() -> uint8_t:\n    return counter()\n"
        + "\n@MAIN(100.0, reset=None)\ndef free() -> uint8_t:\n    return counter()\n",
        "asic_mixed_test.py",
    )
    msg = _asic_error(state)
    assert msg is not None and "under MAIN 'free'" in msg and "MAIN 'm'" not in msg, msg
    print("test_asic_names_the_unreset_instance PASS")


def test_asic_check_runs_at_build_target():
    src = _ASIC + "\n@MAIN(100.0)\ndef m() -> uint8_t:\n    return counter()\n"
    out = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="reset_elab_test_") as tmpdir:
        path = os.path.join(tmpdir, "asic_target_test.py")
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)) + src)
        with contextlib.redirect_stdout(out):
            state = PY_TO_LOGIC.PARSE_FILE(path)
            # No declared target (the driver's later PyRTL fallback): unchecked
            SYN.RESOLVE_BUILD_TARGET(state, path, None, None, False)
            try:
                SYN.RESOLVE_BUILD_TARGET(state, path, None, "pyrtl", False)
            except PY_TO_LOGIC.ElaborationError as e:
                assert "ASIC target pyrtl" in str(e), str(e)
            else:
                raise AssertionError("--syn_tool pyrtl: expected the ASIC initializer error")
    SYN.SYN_TOOL = None
    print("test_asic_check_runs_at_build_target PASS")


def test_asic_target_predicate():
    has = SYN.TARGET_HAS_REGISTER_POWER_UP_VALUES
    assert has("sky130", None) is False
    assert has(None, "device_models") is False
    assert has(None, "pyrtl") is False
    assert has("sky130", "device_models") is False
    assert has("xc7a35ticsg324-1l", None) is True
    assert has(None, "vivado") is True
    assert has(None, None) is None
    print("test_asic_target_predicate PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
