# pyright: reportInvalidTypeForm=none
"""AUTOFSM example: the donut demo's once-per-frame rotation math, implemented
as a resource-shared FSM instead of a slab of parallel combinational logic.

This is the textbook case for AUTOFSM. In examples/pypeline/vga_donut.py the
`full_update()` function advances the torus orientation at the end of every
frame -- roughly twenty int16 adds and subtracts, all of them the same shape,
laid out as straight-line code. As ordinary combinational logic that is twenty
adders sitting idle for 1.2 MILLION cycles between frames, then doing one
cycle's work.

Wrapped in AUTOFSM, the tool schedules the same math onto a handful of shared
adders over a handful of cycles. The result is dramatically smaller and still
finishes long before the next frame starts -- the slack was always there, it
just had no way to be spent. Nothing in the source says how many states to use
or which operations share what: the tool measures the operations' delays,
schedules them against the clock goal, and reports what it did.

    $ pipelinec examples/pypeline/autofsm_donut_update.py

Look for the `AUTOFSM ...: N ops -> M shared unit(s)` line in the build log,
and compare against a `--comb` build of the same file (where the AUTOFSM call
site stays a plain combinational passthrough) to see the area difference.

Kept separate from vga_donut.py deliberately: this file isolates the update
math so the example is about AUTOFSM, and vga_donut.py stays the reference
full-rate rendering design.
"""

from pypeline import (
    AUTOFSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    struct,
    uint1_t,
    uint32_t,
)

# Frames are long. This is how much slack the FSM gets to spend: at 74.25 MHz
# and 1280x720 there are over a million cycles between end-of-frame pulses, so
# even a very long, very small FSM finishes with room to spare.
CYCLES_PER_FRAME = 1_650_000
# The real donut runs at the 1280x720 pixel clock, 74.25 MHz, on an Artix-7
# (see vga_donut.py, which sets PART). This example deliberately sets no PART
# so it builds anywhere, which means timing comes from PYRTL's rough software
# model -- far more pessimistic than a real device, where a 16-bit add is a
# couple of nanoseconds rather than eleven. So the goal here is set to
# something that model can actually meet; add a PART and raise this to 74.25
# to schedule against real device delays.
CLOCK_MHZ = 40.0
BOUNCE_SPEED_X = 3
BOUNCE_SPEED_Y = 2
BOUNCE_MAX_X = 200
BOUNCE_MAX_Y = 100
CENTER_X = 640
CENTER_Y = 360


@struct
class orientation_t(NamedTuple):
    """The torus orientation carried from frame to frame (Q1.14 fixed point,
    16384 == 1.0), plus the bouncing screen position and its velocity."""

    sB: int16_t
    cB: int16_t
    sA: int16_t
    cA: int16_t
    sAsB: int16_t
    cAsB: int16_t
    sAcB: int16_t
    cAcB: int16_t
    pos_x: int16_t
    pos_y: int16_t
    vel_x: int16_t
    vel_y: int16_t


@hw_func
def next_orientation(s: orientation_t) -> orientation_t:
    """Pure state -> next-state math for one frame: two magic-circle DDA
    rotations plus the position bounce.

    Every line here is an add or a subtract of the same width (the shifts are
    constant, i.e. free rewiring), which is exactly the shape AUTOFSM folds
    well: many instances of one operation, so one adder can do all of them if
    given enough cycles.
    """
    # Rotation pass 1 (shift 5): the A axis.
    new_cA: int16_t = s.cA - (s.sA >> 5)
    new_sA: int16_t = s.sA + (new_cA >> 5)
    new_cAsB: int16_t = s.cAsB - (s.sAsB >> 5)
    new_sAsB: int16_t = s.sAsB + (new_cAsB >> 5)
    new_cAcB: int16_t = s.cAcB - (s.sAcB >> 5)
    new_sAcB: int16_t = s.sAcB + (new_cAcB >> 5)
    # Rotation pass 2 (shift 6): the B axis, chaining pass 1's results.
    new_cB: int16_t = s.cB - (s.sB >> 6)
    new_sB: int16_t = s.sB + (new_cB >> 6)
    new_cAcB2: int16_t = new_cAcB - (new_cAsB >> 6)
    new_cAsB2: int16_t = new_cAsB + (new_cAcB2 >> 6)
    new_sAcB2: int16_t = new_sAcB - (new_sAsB >> 6)
    new_sAsB2: int16_t = new_sAsB + (new_sAcB2 >> 6)

    # Bounce the centre off the edges of its box.
    new_pos_x: int16_t = s.pos_x + s.vel_x
    new_pos_y: int16_t = s.pos_y + s.vel_y
    new_vel_x: int16_t = s.vel_x
    new_vel_y: int16_t = s.vel_y
    if (new_pos_x > CENTER_X + BOUNCE_MAX_X) or (new_pos_x < CENTER_X - BOUNCE_MAX_X):
        new_vel_x = -s.vel_x
    if (new_pos_y > CENTER_Y + BOUNCE_MAX_Y) or (new_pos_y < CENTER_Y - BOUNCE_MAX_Y):
        new_vel_y = -s.vel_y

    return orientation_t(
        sB=new_sB,
        cB=new_cB,
        sA=new_sA,
        cA=new_cA,
        sAsB=new_sAsB2,
        cAsB=new_cAsB2,
        sAcB=new_sAcB2,
        cAcB=new_cAcB2,
        pos_x=new_pos_x,
        pos_y=new_pos_y,
        vel_x=new_vel_x,
        vel_y=new_vel_y,
    )


# One tag, constructed once at module level and captured by the @MAIN below.
UPDATE_FSM = AUTOFSM(next_orientation)


@MAIN(CLOCK_MHZ)
def autofsm_donut_update() -> orientation_t:
    """Drives one update per frame and holds the result for the renderer.

    Note what this code does NOT have to do: no waiting on a done flag, no
    counting the FSM's cycles. The result arrives with a valid pulse whenever
    it arrives, and the frame counter is far longer than any schedule the tool
    could produce -- so the design is correct no matter how many states the
    scheduler picks, which is what lets the tool trade latency for area freely.
    """
    frame_ctr: Reg[uint32_t]
    end_of_frame: uint1_t = 0
    if frame_ctr == CYCLES_PER_FRAME - 1:
        frame_ctr = 0
        end_of_frame = 1
    else:
        frame_ctr += 1

    state: Reg[orientation_t] = orientation_t(
        sB=0,
        cB=16384,
        sA=11583,
        cA=11583,
        sAsB=0,
        cAsB=0,
        sAcB=11583,
        cAcB=11583,
        pos_x=CENTER_X,
        pos_y=CENTER_Y,
        vel_x=BOUNCE_SPEED_X,
        vel_y=BOUNCE_SPEED_Y,
    )

    req: UPDATE_FSM.in_stream_t
    req.data = state
    req.valid = end_of_frame
    resp = UPDATE_FSM(req)
    if resp.valid:
        state = resp.data
    return state
