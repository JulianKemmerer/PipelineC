# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    MAIN,
    Reg,
    Feedback,
    uint1_t,
    uint8_t,
    uint32_t,
    uint34_t,
    hw_func,
    sim_reset,
    sim_call,
)

# Path for pypeline_tests import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)
import pypeline_tests

"""
TODO
Single clock domain simulator?
    want to output waveform files? is that useful if names dont match exactly with elaborator?
    one local func first: regs 
        then feedback(test not fully/at all driven feedback and output wires)
    then global wires
    pypeline_sim.py could provide a mechanism to set their value before each cycle (a future enhancement)
        how to set Input[T] sim values?
    ~0 is prints as -1, need hw func like sim cast for print args
    Fix name conflict with locals and wires?
    Wire names must not collide with local variables
    The _GlobalWireRewriter rewrites ALL Name loads matching a wire name inside the function body
      — including names used as local variables that happen to share a name with a global wire.
        This is actually correct by design (same as how PY_TO_LOGIC.py treats them), 
        but if a user accidentally shadows a wire name with a local variable, behavior will be surprising. 
        No special handling needed — it matches elaboration semantics.
    Multi-file sim support is future work; 
Aim for VGA as demo on simulation+board?
    Sphery ... or similar chasing the beam VGA with auto pipeline is good demo?
Dream is really some kind of software->hardware flow right?
BACKLOG
# Multiple clock domains
# CDC/Global FIFOS CANT be implemented by user since cdc
#       allow overload of sync fifo by user func
# TODO printf for sim? is special func?
# TODO RAW VHDL
# Revisit register init values
# Do something nice with port/pin mappings for constraint gen
# TODO unions? struct methods, only void return for now? struct.thing(a,b,c) to struct = struct_t_thing(struct,a,b,c)
#       ex. float_var .to/from uint(), .bit_length(), .bits() for to from slv stuff
# TODO all of old SW_LIB includes fabric multiply, div, etc
# TODO support tuple=concat assignment
#       ex. left: float32_t ; (left.sign, left.exp, left.man) = left_as_u32
# TODO stream(type_t) equivalent with valid flag
# TODO handshake(type) w/ valid+ feedback ready
#         what can be done with feedback wires to automate connection handshakes with ready?
# TODO constant wires based reduction that interacts with graph submodule instances:
#         ex. var ref assign/read into constant
#         ex. shift by a uint6_t type wire driven by constant
#         ... some day might be helpful for making simulator
"""


@MAIN
def regs_multi_inst(sel: uint1_t, data_in: uint32_t) -> uint32_t:
    rv: uint32_t
    if sel:
        rv = pypeline_tests.accumulator(data_in)  # instance1
    else:
        rv = pypeline_tests.accumulator(data_in)  # instance0
    return rv


def test_regs_multi_inst():
    sim_reset()
    assert sim_call(regs_multi_inst, sel=1, data_in=1) == 1  # instance1 acc: 0→1
    assert sim_call(regs_multi_inst, sel=0, data_in=1) == 1  # instance0 acc: 0→1
    assert sim_call(regs_multi_inst, sel=1, data_in=1) == 2  # instance1 acc: 1→2
    print("test_regs_multi_inst PASS")


if __name__ == "__main__":
    test_regs_multi_inst()


@MAIN
def feedback_test(a: uint1_t, b: uint1_t) -> uint1_t:
    # Declare feedback, is not zero initalized in hardware
    # (is zero initialized for simulation evaluation)
    f: Feedback[uint1_t]
    # Use feedback before it has been assigned a value
    # (typically would be zeros for hw elab, but not for feedback)
    # (is zero for simulation first pass of evaluation before feedback)
    rv: uint1_t = f | a
    # Do the 'later' computation that needs to be fed back
    f = ~b
    return rv


def sim_feedback_test():
    sim_reset()
    # b=0 → f=~0=1, rv=1|a
    assert sim_call(feedback_test, a=0, b=0) == 1
    assert sim_call(feedback_test, a=1, b=0) == 1
    # b=1 → f=~1=0, rv=0|a
    assert sim_call(feedback_test, a=0, b=1) == 0
    assert sim_call(feedback_test, a=1, b=1) == 1
    print("sim_feedback_test PASS")


if __name__ == "__main__":
    sim_feedback_test()


@MAIN
def fb_reg_accumulate(load: uint1_t, data: uint8_t) -> uint8_t:
    acc: Reg[uint8_t]  # accumulates across calls
    f: Feedback[uint1_t]  # 1 when acc is odd (LSB of acc)
    # use feedback before it is driven
    out: uint8_t = acc + f
    # feedback driver: LSB of the initial acc value for this cycle
    f = acc & 1
    # conditionally load a new value or accumulate
    if load:
        acc = data
    else:
        acc = out
    return out


def sim_fb_reg_accumulate_test():
    sim_reset()
    # load=1, data=3: acc_init=0, f=0&1=0 (converges immediately),
    #   out=0+0=0, acc committed=3, return 0
    assert sim_call(fb_reg_accumulate, load=1, data=3) == 0
    # load=0: acc_init=3, f=3&1=1 (needs 2 passes to converge),
    #   out=3+1=4, acc committed=4, return 4
    assert sim_call(fb_reg_accumulate, load=0, data=0) == 4
    # load=0: acc_init=4, f=4&1=0 (converges immediately),
    #   out=4+0=4, acc committed=4, return 4
    assert sim_call(fb_reg_accumulate, load=0, data=0) == 4
    print("sim_fb_reg_accumulate_test PASS")


if __name__ == "__main__":
    sim_fb_reg_accumulate_test()


@MAIN
def ce_accum_test(sel0: uint1_t, sel1: uint1_t, data_in: uint32_t) -> uint32_t:
    rv: uint32_t
    if sel0:
        if sel1:
            rv = pypeline_tests.accumulator(data_in)
    return rv


@MAIN
def comp_null_test(sel: uint1_t) -> pypeline_tests.point_xy_t:
    p: pypeline_tests.point_xy_t
    if sel:
        p.x = 1
    else:
        p.y = 1
    return p


@MAIN
def void_ret_test2(sel: uint1_t):
    p: pypeline_tests.point_xy_t
    if sel:
        p.x = 1
    else:
        p.y = 1


@MAIN
def test_point_u8_t(point: pypeline_tests.point_u8_t) -> pypeline_tests.point_u8_t:
    return point


@MAIN
def types_test_main(point: pypeline_tests.point_t) -> pypeline_tests.point_t:
    return pypeline_tests.types_test_foo(point)


@MAIN
def reg_test(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data_in
    return acc


@MAIN
def while_concat_main(bits_lo: uint1_t[5], bits_hi: uint1_t[6]) -> uint1_t[11]:
    bits: uint1_t[11]
    b = 0
    i = 0
    while i < 5:
        bits[b] = bits_lo[i]
        b = b + 1
        i = i + 1
    i = 0
    while i < 6:
        bits[b] = bits_hi[i]
        b = b + 1
        i = i + 1
    return bits


@MAIN
def adder_extra(a: uint32_t, b: uint32_t, c: uint32_t) -> uint34_t:
    return (a + b) + c


@MAIN
def adder(l: uint32_t, r: uint32_t) -> uint32_t:
    return l + r


@MAIN
def main_const_ref_rd(
    my_points: pypeline_tests.point_xy_t[10],
) -> pypeline_tests.point_xy_t[10]:
    p0 = my_points[0]  # CONST_REF_RD(my_points) -> p0_alias

    my_points[1].x = 1  # env["my_points[1].x"] = alias_1x (driven by const 1)
    my_points[1].y = 2  # env["my_points[1].y"] = alias_1y (driven by const 2)

    my_points[2] = p0  # env["my_points[2]"] = alias_2 driven directly by p0_alias

    p1 = my_points[1]  # CONST_REF_RD(alias_1x, alias_1y) -> p1_alias

    p2 = my_points[2]  # no CONST_REF_RD needed - alias_2 covers [2] entirely

    my_points[3] = p1  # env["my_points[3]"] = alias_3 driven directly by p1_alias

    my_points[4] = p2  # env["my_points[4]"] = alias_4 driven directly by p2_alias

    return my_points


@MAIN
def adder_factory_test(a: uint32_t, b: uint32_t) -> uint32_t:
    return pypeline_tests.add_u32(a, b)


@MAIN
def adder_factory_dedup_test(a: uint32_t, b: uint32_t) -> uint32_t:
    return pypeline_tests.add_u32_dup(a, b)


@MAIN
def adder_factory_u8_test(a: uint8_t, b: uint8_t) -> uint8_t:
    return pypeline_tests.add_u8(a, b)


@MAIN
def nested_func_factory_test(a: uint32_t, b: uint32_t, c: uint32_t) -> uint32_t:
    return pypeline_tests.sum3_u32(a, b, c)


@MAIN
def nested_func_factory_dedup_test(a: uint32_t, b: uint32_t, c: uint32_t) -> uint32_t:
    return pypeline_tests.sum3_u32_dup(a, b, c)


@MAIN
def nested_func_factory_u8_test(a: uint8_t, b: uint8_t, c: uint8_t) -> uint8_t:
    return pypeline_tests.sum3_u8(a, b, c)


@MAIN
def pair_passthrough(p: pypeline_tests.pair_u32_t) -> pypeline_tests.pair_u32_t:
    return p


@MAIN
def pair_swap_fields(p: pypeline_tests.pair_u32_t) -> pypeline_tests.pair_u32_t:
    rv: pypeline_tests.pair_u32_t = pypeline_tests.pair_u32_t(a=p.b, b=p.a)
    return rv


@MAIN
def pair_dup_passthrough(
    p: pypeline_tests.pair_u32_t_dup,
) -> pypeline_tests.pair_u32_t_dup:
    return p


@MAIN
def nested_factory_swap_test(p: pypeline_tests.pair_u32_t) -> pypeline_tests.pair_u32_t:
    return pypeline_tests.swap_u32(p)


@MAIN
def nested_factory_def_test(a: uint32_t) -> uint32_t:
    return pypeline_tests.double_inv_u32(a)


@MAIN
def nested_factory_def_u8_test(a: uint8_t) -> uint8_t:
    return pypeline_tests.double_inv_u8(a)


@MAIN
def shift_const_param(v: uint32_t) -> uint32_t:
    return v << pypeline_tests.SHIFT_AMOUNT


@MAIN
def shift_const_local_param(v: uint32_t) -> uint32_t:
    AMOUNT = 5
    return v << AMOUNT


@MAIN
def shift_const(v: uint32_t) -> uint32_t:
    return v << 5


@MAIN
def uint_inv_test(a: uint32_t) -> uint32_t:
    return ~a


@MAIN
def main_foo_foo_fooo(x: uint1_t) -> uint1_t:
    return pypeline_tests.foo(pypeline_tests.foo(pypeline_tests.foo(x)))


@MAIN
def main_foo(x: uint1_t) -> uint1_t:
    return pypeline_tests.foo(x)


@MAIN
def point_max(points: pypeline_tests.point2d_t[3]) -> uint32_t:
    max_val: uint32_t = points[0].dim[0]
    for i in range(3):
        for j in range(2):
            if points[i].dim[j] > max_val:
                max_val = points[i].dim[j]
    return max_val


def test_point_max():
    def make_points(*pairs):
        return [pypeline_tests.point2d_t(dim=list(pair)) for pair in pairs]

    cases = [
        (make_points((1, 2), (3, 4), (5, 6)), 6),
        (make_points((10, 0), (0, 10), (5, 5)), 10),
        (make_points((0, 0), (0, 0), (0, 0)), 0),
        (make_points((100, 50), (200, 10), (150, 75)), 200),
        (make_points((7, 7), (7, 7), (7, 8)), 8),
    ]
    for points, expected in cases:
        result = sim_call(point_max, points)
        assert (
            int(result) == expected
        ), f"point_max(points) = {result}, expected {expected}"
    print("test_point_max passed")


# cd /media/1TB/Dropbox/PipelineC/git/PipelineC/src && PYTHONPATH=. python3 tests/pypeline_tests/inst/pypeline_test.py 2>&1
if __name__ == "__main__":
    test_point_max()
