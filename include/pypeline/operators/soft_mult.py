"""Soft multipliers: shift-and-add (default) and a recursive Karatsuba split
(alternate flavor, built on the soft adder/subtractor so it exercises the
same composability the plan calls for).

UNSIGNED OPERANDS ONLY. Both multipliers here sum `a << i` over the set bits of
b treating b as unsigned; for a signed b the MSB carries weight -2**(n-1), so
the final partial product would have to be subtracted rather than added.
register_soft_mult/register_soft_mult_karatsuba therefore register these for
any_uint_t x any_uint_t only, so a signed multiply falls through to the built-in
inferred HDL `*` (correct for signed) instead of to wrong soft logic. Callers
that bypass the registry and use these factories directly -- AUTOFSM.py's
resource-sharing map does -- are responsible for that restriction themselves.
A signed soft multiplier has not been written yet."""
from pypeline import (
    hw_func,
    wires,
    uint1_t,
    bit_dup,
    bit_assign,
    arith_result_type,
    make_uint_t,
    array_to_uint_le,
)


def make_soft_add_tree_shifted(n_leaves, leaf_t, out_t, level=0, max_width=None):
    """Sum `n_leaves` leaf_t values, where leaf i contributes `terms[i] << i`,
    into out_t via a balanced binary tree (log2(n_leaves) deep) of the inferred
    + operator.

    Rather than pre-shifting every leaf to its final bit position (which forces
    every leaf to full out_t width immediately), each *level* shifts its pairs'
    odd-indexed operand left by 2**level, so node width grows only by what that
    level actually needs. Same staged width bookkeeping as
    SW_LIB.GET_BIN_OP_MULT_UINT_N_C_CODE's p_i/p_i_shifted/sum_layerN stages,
    as native Pypeline HDL.

    Correctness invariant: entering level L with step = 2**L, node k carries
    positional weight 2**(k*step). Combining new[i] = node[2i] + (node[2i+1] <<
    step) rebases the odd operand onto the even one, so new[i] has weight
    2**(i*2*step) -- the same invariant one level up. An odd leftover node moves
    up unshifted, its weight already correct for the next level's stride.

    Capping node width at out_t is safe: every partial product is non-negative
    and the full product fits out_t by arith_result_type's contract, so node k
    is bounded by 2**(out_width - k*step) and the k=0 worst case still fits.

    Each level is its own @hw_func, so per-level operand widths are visible to
    the timing model as genuinely different leaf ops -- see the note on
    make_soft_mult_shift_add for why that matters for autopipelining.

    NOTE: a constant << returns its LEFT operand's width unchanged
    (PY_TO_LOGIC.py:4293-4311), so each operand is widened to shifted_t BEFORE
    being shifted, never after.
    """
    leaf_width = len(leaf_t)
    if max_width is None:
        max_width = len(out_t)
    if n_leaves < 2:
        raise ValueError(
            "make_soft_add_tree_shifted needs >= 2 leaves; callers handle the "
            "single-partial-product case inline (see make_soft_mult_shift_add)"
        )
    in_t = leaf_t[n_leaves]

    step = 1 << level
    n_pairs = n_leaves // 2
    odd_leftover = (n_leaves % 2) == 1
    shifted_width = min(leaf_width + step, max_width)
    node_width = min(max(leaf_width, shifted_width) + 1, max_width)
    shifted_t = make_uint_t(shifted_width)
    node_t = make_uint_t(node_width)
    n_next = n_pairs + (1 if odd_leftover else 0)

    if n_next == 1:
        # Terminal level (n_leaves == 2): do the final add here and return out_t
        # directly. Recursing into a 1-leaf passthrough @hw_func instead would
        # emit a rewire-only zero-delay entity, which makes PyRTL's max_freq
        # divide by zero (pyrtl/analysis.py:251 via PYRTL.py:267).
        @hw_func
        def soft_add_tree(terms: in_t) -> out_t:
            wide: shifted_t = terms[1]
            shifted: shifted_t = wide << step
            result: out_t = terms[0] + shifted
            return result

        return soft_add_tree

    next_add = make_soft_add_tree_shifted(n_next, node_t, out_t, level + 1, max_width)

    @hw_func
    def soft_add_tree(terms: in_t) -> out_t:
        level_nodes: node_t[n_next]
        for i in range(n_pairs):
            wide: shifted_t = terms[2 * i + 1]
            shifted: shifted_t = wide << step
            level_nodes[i] = terms[2 * i] + shifted
        if odd_leftover:
            leftover: node_t = terms[n_leaves - 1]
            level_nodes[n_pairs] = leftover
        return next_add(level_nodes)

    return soft_add_tree


def make_soft_mult_shift_add(l_t, r_t):
    """Grade-school shift-and-add multiplier: for each bit of b produce an
    UNSHIFTED partial product (a masked by that bit, or 0), then combine them
    with make_soft_add_tree_shifted, a balanced binary adder tree (log2(n) deep) that
    folds each partial's positional shift into its tree level. Same
    partial-product structure as SW_LIB.GET_BIN_OP_MULT_UINT_N_C_CODE, as
    Pypeline HDL, with per-level width growth instead of one uniform
    out_t-wide node array.

    Why per-level widths and one @hw_func per level, measured not assumed
    (uint16 x uint16, Vivado xc7a200tffg1156-2, coarse cut sweep):

      cuts  0      1      2      3
      flat  6.45   4.17   3.43   2.85 ns
      this  6.46   3.69   3.25   2.92 ns

    Combinationally the two are equivalent -- both reduce to the same effective
    adder widths (18/21/26/32 for 16x16) after constant propagation, and Vivado
    maps them to the same silicon (249 vs 252 LUTs, 6.45 vs 6.46 ns). The win is
    in *pipelining*: because each level is a separate entity with genuinely
    different operand widths, the timing model prices the levels at 1.950 /
    2.115 / 2.146 / 2.409 ns instead of four identical 2.409 ns adders, so the
    delay axis the slicer cuts on has the right shape. Estimate-vs-measured
    over-prediction drops from 1.64x to 1.47x (Vivado) and 1.83x to 1.21x
    (PyRTL), and when a cut does land badly inside a leaf it splits a narrower,
    cheaper adder. Above ~4 cuts at this width both shapes hit the Artix-7 -2
    device fmax ceiling (~450 MHz), where no multiplier shape can differ.

    Note the yosys/PyRTL backend disagrees: `synth -flatten` gives this shape
    ~19% more cells (2025 vs 1706) and a longer critical path than the flat one,
    but that penalty does not survive real FPGA place-and-route -- Vivado shows
    no area or comb-delay cost. Judge this design on the vendor numbers.
    """
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    left_bits = len(eff_l_t)
    r_bits = len(eff_r_t)

    if r_bits == 1:
        # Single partial product -- no tree at all (and no rewire-only child
        # entity; see make_soft_add_tree_shifted's terminal-level note).
        @hw_func
        def soft_mult_shift_add(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            bit_mask: eff_l_t = bit_dup(be[0], left_bits)
            result: out_t = ae & bit_mask
            return result

        return soft_mult_shift_add

    soft_add_tree = make_soft_add_tree_shifted(r_bits, eff_l_t, out_t)

    @hw_func
    def soft_mult_shift_add(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        partials: eff_l_t[r_bits]
        for i in range(r_bits):
            bit_mask: eff_l_t = bit_dup(be[i], left_bits)
            partials[i] = ae & bit_mask
        return soft_add_tree(partials)

    return soft_mult_shift_add


def make_soft_mult_karatsuba(l_t, r_t, threshold=16):
    """Recursive Karatsuba multiply. Below `threshold` bits, falls back to
    the shift-and-add multiplier (same style as a soft library implementation
    pinning its own base case rather than recursing forever).

    threshold must be >= 3: a 3-bit operand splits into half=1 / hi=2 with
    mid = max(1,2)+1 = 3 bits, so the middle sub-multiply is the same width
    as its parent and the recursion terminates only because 3 <= threshold
    can be true. threshold=2 makes mid=3 > threshold, so the middle
    sub-multiply recurses into an identical 3-bit split forever
    (RecursionError, confirmed by measurement).

    Default raised from 8 to 16 (docs/SYN_DESIGN.md section 10): swept every
    structurally-distinct threshold at uint8 and uint16 (PyRTL, --coarse
    --sweep) and found NO threshold in [3, n_bits) ever beats the trivial
    n_bits<=threshold case (no split at all) at any cut count -- comb delay
    falls monotonically as threshold rises with no interior optimum, e.g.
    uint16 best sliced fmax at cuts>=1: T=3 27.7 MHz, T=6/T=8 (old default)
    38.3 MHz, T=16 (no split) 77.7 MHz. Recombination overhead (two adds, a
    3-way subtract, a 3-way shifted sum, all near full out_t width) dominates
    completely below 16 bits; there is nothing for the module-boundary
    slicing advantage to recover. Widths above 16 bits were NOT measured this
    round -- 16 is the ceiling of what was actually tested, chosen so this
    change can only remove already-confirmed-harmful splitting and cannot by
    construction make an untested wider design recurse less than it already
    would have. Whether a real optimum exists above 16 bits is open; see
    docs/SYN_DESIGN.md section 10."""
    if threshold < 3:
        raise ValueError(
            f"make_soft_mult_karatsuba: threshold must be >= 3 (got {threshold}). A "
            "3-bit operand splits into half=1 / hi=2 with mid = max(1,2)+1 = 3 bits, "
            "so the middle sub-multiply is the same width as its parent and the "
            "recursion never terminates below this threshold."
        )
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    n_bits = max(len(eff_l_t), len(eff_r_t))

    if n_bits <= threshold:
        return make_soft_mult_shift_add(l_t, r_t)

    from pypeline import make_uint_t

    half = n_bits // 2
    lo_t = make_uint_t(half)
    hi_t = make_uint_t(n_bits - half)
    mid_t = make_uint_t(max(half, n_bits - half) + 1)

    mult_lo = make_soft_mult_karatsuba(lo_t, lo_t, threshold)
    mult_hi = make_soft_mult_karatsuba(hi_t, hi_t, threshold)
    mult_mid = make_soft_mult_karatsuba(mid_t, mid_t, threshold)

    @hw_func
    def soft_mult_karatsuba(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        a_lo: lo_t = ae
        a_hi: hi_t = ae >> half
        b_lo: lo_t = be
        b_hi: hi_t = be >> half
        z0: out_t = mult_lo(a_lo, b_lo)
        z2: out_t = mult_hi(a_hi, b_hi)
        a_sum: mid_t = a_lo + a_hi
        b_sum: mid_t = b_lo + b_hi
        z1_full: out_t = mult_mid(a_sum, b_sum)
        z1: out_t = z1_full - z0 - z2
        result: out_t = z2
        result = (result << (2 * half)) + (z1 << half) + z0
        return result

    return soft_mult_karatsuba


# ─────────────────────────────────────────────
# Carry-save (deferred-carry) multiplier
# ─────────────────────────────────────────────
#
# Port of a CoHDL-generated uint16 x uint16 -> uint32 multiplier measured
# against the same sky130 latchup target this library targets
# (docs/SYN_DESIGN.md section 11). make_soft_mult_shift_add's tree does a FEW
# FULL-WIDTH carry-propagate adds (15 adds up to 32 bits at uint16x16, ~97
# bits of serial carry chain overall) -- cheap on an FPGA's dedicated carry
# chain, expensive on an ASIC with none. This multiplier instead defers carry
# propagation across MANY pipeline-visible stages: every add is capped at
# `max_width` bits, and the add's own carry-out bit is never resolved in
# place -- it is concatenated onto the result as an extra bit and becomes
# part of the NEXT stage's input, exactly like a 2-row carry-save
# representation except the "rows" are folded back together into one packed
# bus after every stage rather than kept separate until the very end.
#
# The reduction is planned ENTIRELY in Python before any hardware is built
# (mirrors the reference's own @cohdl.pyeval-driven pipelined_add/add_pair,
# which is likewise a compile-time-only construction of a fixed structure).
# _plan_carry_save_levels below is a pure-Python, hardware-free port of that
# algorithm, independently validated against real integer arithmetic (1080/
# 1080 exact across widths 4-16 and max_width 2-16, using ONLY the same
# slice/shift/mask/concat primitives the generated HDL below actually uses --
# not a shortcut model) before a single line of HDL was written from it.
#
# Composition is entirely nested factory-function calls, never text
# generation: ONE @hw_func per reduction level (not per op). A level's op
# list varies in count and shape between levels (some pairs need one chunk
# add, others several; some elements just pass through) but each level's
# own body is a SINGLE unrolled Python `for` loop over that level's
# closure-planned op list, branching on each op's elaboration-time-constant
# kind -- exactly the idiom make_soft_div_radix's soft_div_radix already
# uses (operators/soft_div.py:204-277: `for step_idx in range(len(steps)):`
# over a closure-planned `steps` list, indexing per-iteration-varying
# closure data, bit_assign-ing an inline varying-width slice). An earlier
# version of this file's comment claimed this was impossible ("rules out
# one uniform hw_func loop body... no existing precedent") -- that was
# wrong; soft_div_radix was already doing it two files over. Every
# DECLARED LOCAL inside the loop keeps one fixed type across every
# iteration (op_t, sum_t); only elaboration-time integers (bit offsets,
# widths) vary, which is what the loop var and the closure-planned op
# tuples actually carry.
#
# This collapses what used to be ~2,700 entities (one @wires leaf per bit
# slice, one @wires node per 2-input concat, one @hw_func wrapper per add,
# dozens of distinct add shapes from `rest`-width fragmentation) for a
# uint16 x uint16 multiply down to roughly one entity per level plus ONE
# shared add entity per max_width -- confirmed by measurement, not just
# argued: 2,489 -> ~40 .vhd files for the same design (docs/SYN_DESIGN.md
# section 11). Two things made the old per-op-entity shape seem necessary
# and turned out not to matter:
#
# 1. An indexed call target is not callable (`leaf_fns[j](...)` fails --
#    confirmed again at PY_TO_LOGIC.py:4697/5004, `callee_name =
#    expr.func.id`; documented workaround at soft_cmp.py:530-546). This is
#    real and still true, but it only forces every loop iteration to call
#    the SAME bare-named entity, not a *different* entity per op -- which
#    is exactly what one shared, WIDTH-NORMALIZED add entity already gives.
# 2. Every add's operands are zero-extended (by plain reassignment into an
#    already-declared max_width-wide local) up to one common shape before
#    the call, and the result is narrowed back down via an inline slice at
#    the bit_assign call site. This costs nothing measurable: a level's
#    critical path is set by its WIDEST op, which is never padded, and
#    real synthesis constant-folds the padded zero bits away, so measured
#    combinational area is unaffected too (only the pre-synthesis estimate
#    inflates, and section 11 never ranks on that estimate).
#
# A note on how this squares with VHDL giving every signal exactly one
# type, since the Python source visibly assigns values of different
# widths into the same-named local across branches/iterations: it does
# NOT rely on a VHDL variable changing type. Every assignment SITE gets
# its own freshly aliased VHDL variable (PY_TO_LOGIC names it after the
# source line/column, e.g. `VAR_x_soft_mult_py_l123_c45_...`), and
# VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS (VHDL.py:6962) inserts an explicit
# `resize(...)` call at THAT alias's creation point whenever its width
# differs from the declared target type; branches are then reconciled by
# a MUX over the per-branch aliases (_elab_if). This is elaboration-time
# bookkeeping, not a hardware-level polymorphic signal -- confirmed by
# inspecting real generated VHDL (every declared `variable` has exactly
# one, fixed subtype). It is also narrower than it might look: this free
# same-signedness-any-width coercion is specific to the int/uint family
# (TYPE_RESOLVE_ASSIGNMENT_RHS:6992-7010; VHDL's numeric_std.resize on an
# UNSIGNED zero-pads on widen and takes the low N bits on narrow, i.e.
# exactly C/this-file's-native-sim truncation semantics -- the extra
# sign-routing at :6998-7008 is for SIGNED narrowing only, never exercised
# here since every type in this reduction is unsigned). Arrays get a much
# narrower form requiring an exact/near-exact element type
# (VHDL.py:7059-7084, hard `sys.exit(-1)` on mismatch) and there is no
# general multi-field struct branch at all -- this file only ever
# reassigns uint-typed scalars, so none of that restriction is in play,
# but a future soft-op author leaning on this same trick for a compound
# type should not assume it "just works" the way it does here.


class _CSElem:
    """Elaboration-time-only descriptor: one summand's (width, shift) in the
    carry-save reduction. Pure Python bookkeeping consumed only by
    _plan_carry_save_levels -- never touches hardware."""

    __slots__ = ("width", "shift", "off")

    def __init__(self, width, shift, off):
        self.width = width
        self.shift = shift
        self.off = off


def _plan_carry_save_levels(initial_widths_shifts, out_bits, max_width):
    """Pure-Python (no hardware) planner. Ports the reference's
    pipelined_add/add_pair: repeatedly sort summands by (shift, width), pair
    adjacent OVERLAPPING ones (add, chunked to at most max_width bits per
    chunk, with any lower non-overlapping 'rest' bits of the smaller-shift
    operand split off and concatenated back on unchanged) and pass through
    non-overlapping ones untouched, until one summand remains.

    initial_widths_shifts: list of (width, shift) for the starting summands
    (bare partial products for a fresh multiply; a Wallace-reduced (sum,
    carry) pair if this is seeding the finishing stage of a different
    front-end -- this function does not care which).

    Returns (levels, final_width). levels[i] is level i's list of ops, each
    an elaboration-time-constant tuple over BIT OFFSETS into that level's own
    packed input/output bus (offset 0 = LSB):
      ('pass', in_off, width, out_off)
      ('add', ac_off, ac_w, bc_off, bc_w, op_w, rest_off, rest_w, out_off)
    final_width may exceed out_bits (the carry-deferred sum can overshoot the
    true product's width by a couple of bits before the final truncation);
    the final single element's shift is asserted 0, matching the reference's
    own final `.lsb(target_width)` truncation -- has held on every width/
    max_width combination checked (4-32 bits, max_width 2-32); truncation is
    only ever safe because it discards bits the real product cannot need.

    Degenerate-width safety: if EVERY remaining summand is simultaneously
    non-overlapping with its neighbors (only possible when every summand is
    1 bit wide -- i.e. a multiply against a 1-bit operand, where every
    partial product is a single disjoint bit), the pairing scan below marks
    everything 'pass' and the naive element count would never shrink,
    looping forever (confirmed: uint1 x uint5 hung indefinitely before this
    was added). Consecutive 'pass' ops that are shift-CONTIGUOUS (one ends
    exactly where the next starts -- true for disjoint single-bit leaves,
    never true for a real, covered gap) are merged into one wider element
    for the NEXT iteration's bookkeeping only; the HDL-facing op list itself
    is unchanged (still one 'pass' per original sub-range, concatenated by
    the same recursive combine tree every level already uses). A hard
    iteration cap is kept as a safety net in case some other, un-anticipated
    non-convergent shape exists.
    """
    init = []
    off = 0
    for width, shift in initial_widths_shifts:
        init.append(_CSElem(width, shift, off))
        off += width
    levels = []
    cur = init
    max_iters = 4 * len(init) + 16
    n_iters = 0
    while len(cur) != 1:
        n_iters += 1
        if n_iters > max_iters:
            raise RuntimeError(
                f"_plan_carry_save_levels: did not converge after {max_iters} "
                f"iterations (out_bits={out_bits}, max_width={max_width}, "
                f"{len(cur)} summands remaining) -- likely a new non-shrinking "
                "shape; needs investigation, not a larger cap."
            )
        order = sorted(cur, key=lambda e: (e.shift, e.width))
        ops = []
        prev = None
        for el in order:
            if prev is None:
                prev = el
                continue
            if prev.shift + prev.width <= el.shift:
                ops.append(("pass", prev.off, prev.width, prev.shift))
                prev = el
                continue
            A_off, A_w, A_sh = prev.off, prev.width, prev.shift
            B_off, B_w, B_sh = el.off, el.width, el.shift
            offa = B_sh - A_sh
            if offa != 0:
                rest_off, rest_w = A_off, offa
                A_off, A_w = A_off + offa, A_w - offa
            else:
                rest_off, rest_w = None, 0
            sh = A_sh
            a_rem, b_rem = A_w, B_w
            a_cur_off, b_cur_off = A_off, B_off
            while a_rem is not None and b_rem is not None:
                if a_rem > max_width:
                    ac_off, ac_w = a_cur_off, max_width
                    a_cur_off += max_width
                    a_rem -= max_width
                else:
                    ac_off, ac_w = a_cur_off, a_rem
                    a_rem = None
                if b_rem > max_width:
                    bc_off, bc_w = b_cur_off, max_width
                    b_cur_off += max_width
                    b_rem -= max_width
                else:
                    bc_off, bc_w = b_cur_off, b_rem
                    b_rem = None
                op_w = max(ac_w, bc_w) + 1
                if sh + op_w > out_bits:
                    op_w = out_bits - sh
                ops.append(("add", ac_off, ac_w, bc_off, bc_w, op_w, rest_off, rest_w, sh))
                rest_off, rest_w = None, 0
                sh += max_width + offa
                offa = 0
            if sh < out_bits:
                if a_rem is not None:
                    ops.append(("pass", a_cur_off, a_rem, sh))
                if b_rem is not None:
                    ops.append(("pass", b_cur_off, b_rem, sh))
            prev = None
        if prev is not None:
            ops.append(("pass", prev.off, prev.width, prev.shift))

        out_off = 0
        new_elems = []
        out_ops = []
        for op in ops:
            if op[0] == "pass":
                _, ioff, w, sh = op
                # Merge into the previous new_elem iff it's ALSO a bare pass
                # and shift-contiguous with it (see the degenerate-width note
                # above) -- purely a bookkeeping merge for the outer loop's
                # progress; the op list itself always gets one 'pass' per
                # original sub-range, unchanged.
                if new_elems and new_elems[-1].shift + new_elems[-1].width == sh and (
                    out_ops and out_ops[-1][0] == "pass"
                ):
                    prev_elem = new_elems[-1]
                    new_elems[-1] = _CSElem(prev_elem.width + w, prev_elem.shift, prev_elem.off)
                else:
                    new_elems.append(_CSElem(w, sh, out_off))
                out_ops.append(("pass", ioff, w, out_off))
                out_off += w
            else:
                _, ac_off, ac_w, bc_off, bc_w, op_w, rest_off, rest_w, sh = op
                total_w = op_w + rest_w
                new_elems.append(_CSElem(total_w, sh, out_off))
                out_ops.append(
                    ("add", ac_off, ac_w, bc_off, bc_w, op_w, rest_off, rest_w, out_off)
                )
                out_off += total_w

        levels.append(out_ops)
        cur = new_elems

    final = cur[0]
    assert final.shift == 0, (
        f"_plan_carry_save_levels: final element shift {final.shift} != 0 -- "
        "the reduction did not converge to bit 0 as expected; this is a "
        "planner bug, not a data problem."
    )
    return levels, final.width


def _carry_save_level_out_width(ops):
    def _op_end(op):
        return op[3] + op[2] if op[0] == "pass" else op[8] + op[5] + op[7]

    return max(_op_end(op) for op in ops)


_CS_CHUNK_ADD_CACHE = {}


def _get_carry_save_chunk_add(w):
    """Memoized SHARED adder: uint{w} + uint{w} -> uint{w+1}, inferred `+`
    (same choice make_soft_add_tree_shifted's own terminal level makes for
    its leaf add -- "soft" in this library names the DECOMPOSITION
    strategy, not a rule that every scalar primitive must be hand-built
    from raw gates). One entity per max_width, shared by EVERY add at
    EVERY level of the whole reduction: every op's operands are
    zero-extended up to w bits before the call (see the module comment
    above), so the (ac_w, bc_w, op_w, rest_w)-keyed fragmentation the old
    per-op-leaf construction had (44 distinct shapes at max_width=2 on a
    uint16 x uint16 multiply) collapses to exactly one."""
    cached = _CS_CHUNK_ADD_CACHE.get(w)
    if cached is not None:
        return cached
    op_t = make_uint_t(w)
    sum_t = make_uint_t(w + 1)

    @hw_func
    def chunk_add(ac: op_t, bc: op_t) -> sum_t:
        result: sum_t = ac + bc
        return result

    _CS_CHUNK_ADD_CACHE[w] = (chunk_add, sum_t)
    return chunk_add, sum_t


def _flatten_carry_save_ops(ops):
    """Normalize a level's op list (as _plan_carry_save_levels emits it)
    into fixed-shape int tuples a single unrolled hw_func loop can index
    (OPS[i][k] for a constant k) without ever tuple-unpacking -- the
    elaborator tries to emit a whole tuple as one hardware value on
    unpack, soft_div.py:214-217 -- and without ever indexing a Python list
    of distinct per-op closures by a loop variable -- an indexed call
    target is not callable, soft_cmp.py:530-546.

    `rest` (the low bits below an add's shift, unaffected by the add)
    becomes its own ordinary 'pass' entry at the add's output offset; the
    add's own result is placed just above it. This is what lets one
    shared add entity (see _get_carry_save_chunk_add) replace the 44
    per-(ac_w,bc_w,op_w,rest_w) shapes the old construction needed --
    `rest` used to be baked into the add leaf's own signature and was the
    single biggest source of that fragmentation (rest_w ranged 0..31 on a
    uint16 x uint16 multiply).

    Returns a tuple of:
      (0, in_off, width, out_off)                    -- pass
      (1, ac_off, ac_w, bc_off, bc_w, op_w, out_off)  -- add
    """
    flat = []
    for op in ops:
        if op[0] == "pass":
            _, ioff, w, ooff = op
            flat.append((0, ioff, w, ooff))
        else:
            _, ac_off, ac_w, bc_off, bc_w, op_w, rest_off, rest_w, out_off = op
            if rest_w > 0:
                flat.append((0, rest_off, rest_w, out_off))
                flat.append((1, ac_off, ac_w, bc_off, bc_w, op_w, out_off + rest_w))
            else:
                flat.append((1, ac_off, ac_w, bc_off, bc_w, op_w, out_off))
    return tuple(flat)


def _build_carry_save_stage(levels, idx, in_width, out_bits, max_width, final_out_t):
    """Build levels[idx:] as ONE @hw_func PER LEVEL: a single unrolled loop
    over that level's flattened op list (_flatten_carry_save_ops), building
    `result` up bit-by-bit via bit_assign -- the same "closure-planned op
    list, one hw_func, per-iteration inline slices" idiom
    make_soft_div_radix's soft_div_radix already uses (soft_div.py:204-
    277) -- with the hand-off to the NEXT level folded into the SAME
    entity's own tail call (bare name, like make_soft_add_tree_shifted's
    own levels call each other) rather than a separate wrapper stage.
    Deeper levels are built FIRST via plain Python recursion at
    factory-construction time, so this level's body can close over the
    next one's bare name -- the same ordering make_soft_add_tree_shifted's
    own `next_add = make_soft_add_tree_shifted(...)` uses.

    Every declared local inside the loop (ac_raw/bc_raw/s) keeps ONE fixed
    type across every iteration; only the elaboration-time integers
    (offsets, widths) vary, via branch elimination on OPS[i][0] (kind) --
    a closure-constant int, so `if kind == 0: ... else: ...` never becomes
    a hardware mux, exactly like soft_div_radix's own `if op ==
    _OP_SHL1:`.

    The final level's raw reduction result can be wider OR narrower than
    out_bits (_plan_carry_save_levels's own docstring) -- handled by ONE
    plain annotated assignment to final_out_t either way, relying on
    VHDL.TYPE_RESOLVE_ASSIGNMENT_RHS's implicit resize() (see the module
    comment above): for same-signedness uint-to-uint, VHDL's numeric_std
    resize() zero-pads on widen and takes the low N bits on narrow --
    exactly the truncation semantics wanted, no explicit slice needed in
    either direction, and no separate code path for the two cases.

    A level with NO 'add' op (every element disjoint -- only possible
    when every summand is 1 bit wide, i.e. multiplying against a 1-bit
    operand) produces a result that is pure routing -- confirmed NOT rare
    enough to special-case away as "just the whole-design degenerate
    case": an exhaustive sweep (out_bits 2-64 x every leaf width x
    max_width in {1,2,3,4,6,8,16,32} x n_leaves in {2,3,4,5,8,16,32},
    93,911 cases) found 1,604 cases where an INTERIOR level of a
    multi-level chain -- not only a single-level whole design -- is
    all-pass. Tagged @wires for the same reason the old per-slice leaves
    were: an @hw_func whose own synthesized result is 100% flip-flops
    with zero combinational cells makes PyRTL's max_freq divide by zero
    the first time it is independently timing-estimated (confirmed by
    hitting this for real during the prior construction's development,
    uint8 x uint8 at the per-slice-leaf granularity). A level WITH at
    least one add is genuinely combinational and must stay @hw_func --
    tagging it @wires would be a lie the framework would believe, hiding
    real delay from every estimate instead of merely avoiding a crash.
    The loop body is IDENTICAL either way (the add branch, when present
    in the source but never selected by any op in OPS, costs no hardware
    -- elaboration-time branch elimination, not a runtime mux) so the
    @wires/@hw_func branches below are a byte-for-byte copy of each other
    except that one line; duplicated rather than chosen via a variable
    decorator, matching this codebase's convention of never applying
    @wires/@hw_func outside literal `@` syntax.

    Returns (stage_fn, is_wires): is_wires is true only when THIS level
    has no add AND (for a non-final level) the rest of the chain is also
    wires -- a real add anywhere from here down makes every stage above
    it in the chain genuinely combinational, regardless of what deeper
    levels do."""
    ops = levels[idx]
    OPS = _flatten_carry_save_ops(ops)
    n_ops = len(OPS)
    out_width = _carry_save_level_out_width(ops)
    has_add = any(o[0] == 1 for o in OPS)
    is_last = idx == len(levels) - 1
    bus_in_t = make_uint_t(in_width)
    bus_out_t = make_uint_t(out_width)
    op_t = make_uint_t(max_width)
    sum_t = make_uint_t(max_width + 1)
    chunk_add, _sum_t = _get_carry_save_chunk_add(max_width)

    if is_last:
        is_wires = not has_add

        if is_wires:

            @wires
            def stage(terms: bus_in_t) -> final_out_t:
                result: bus_out_t = 0
                for i in range(n_ops):
                    kind = OPS[i][0]
                    if kind == 0:
                        ioff = OPS[i][1]
                        w = OPS[i][2]
                        ooff = OPS[i][3]
                        if w == 1:
                            result = bit_assign(result, terms[ioff], ooff)
                        else:
                            result = bit_assign(result, terms[ioff + w - 1:ioff], ooff)
                    else:
                        ac_off = OPS[i][1]
                        ac_w = OPS[i][2]
                        bc_off = OPS[i][3]
                        bc_w = OPS[i][4]
                        op_w = OPS[i][5]
                        out_off = OPS[i][6]
                        ac_raw: op_t = 0
                        bc_raw: op_t = 0
                        if ac_w == 1:
                            ac_raw = terms[ac_off]
                        else:
                            ac_raw = terms[ac_off + ac_w - 1:ac_off]
                        if bc_w == 1:
                            bc_raw = terms[bc_off]
                        else:
                            bc_raw = terms[bc_off + bc_w - 1:bc_off]
                        s: sum_t = chunk_add(ac_raw, bc_raw)
                        if op_w == 1:
                            result = bit_assign(result, s[0], out_off)
                        else:
                            result = bit_assign(result, s[op_w - 1:0], out_off)
                final_result: final_out_t = result
                return final_result

        else:

            @hw_func
            def stage(terms: bus_in_t) -> final_out_t:
                result: bus_out_t = 0
                for i in range(n_ops):
                    kind = OPS[i][0]
                    if kind == 0:
                        ioff = OPS[i][1]
                        w = OPS[i][2]
                        ooff = OPS[i][3]
                        if w == 1:
                            result = bit_assign(result, terms[ioff], ooff)
                        else:
                            result = bit_assign(result, terms[ioff + w - 1:ioff], ooff)
                    else:
                        ac_off = OPS[i][1]
                        ac_w = OPS[i][2]
                        bc_off = OPS[i][3]
                        bc_w = OPS[i][4]
                        op_w = OPS[i][5]
                        out_off = OPS[i][6]
                        ac_raw: op_t = 0
                        bc_raw: op_t = 0
                        if ac_w == 1:
                            ac_raw = terms[ac_off]
                        else:
                            ac_raw = terms[ac_off + ac_w - 1:ac_off]
                        if bc_w == 1:
                            bc_raw = terms[bc_off]
                        else:
                            bc_raw = terms[bc_off + bc_w - 1:bc_off]
                        s: sum_t = chunk_add(ac_raw, bc_raw)
                        if op_w == 1:
                            result = bit_assign(result, s[0], out_off)
                        else:
                            result = bit_assign(result, s[op_w - 1:0], out_off)
                final_result: final_out_t = result
                return final_result

        return stage, is_wires

    rest_fn, rest_wires = _build_carry_save_stage(
        levels, idx + 1, out_width, out_bits, max_width, final_out_t
    )
    is_wires = (not has_add) and rest_wires

    if is_wires:

        @wires
        def stage(terms: bus_in_t) -> final_out_t:
            result: bus_out_t = 0
            for i in range(n_ops):
                kind = OPS[i][0]
                if kind == 0:
                    ioff = OPS[i][1]
                    w = OPS[i][2]
                    ooff = OPS[i][3]
                    if w == 1:
                        result = bit_assign(result, terms[ioff], ooff)
                    else:
                        result = bit_assign(result, terms[ioff + w - 1:ioff], ooff)
                else:
                    ac_off = OPS[i][1]
                    ac_w = OPS[i][2]
                    bc_off = OPS[i][3]
                    bc_w = OPS[i][4]
                    op_w = OPS[i][5]
                    out_off = OPS[i][6]
                    ac_raw: op_t = 0
                    bc_raw: op_t = 0
                    if ac_w == 1:
                        ac_raw = terms[ac_off]
                    else:
                        ac_raw = terms[ac_off + ac_w - 1:ac_off]
                    if bc_w == 1:
                        bc_raw = terms[bc_off]
                    else:
                        bc_raw = terms[bc_off + bc_w - 1:bc_off]
                    s: sum_t = chunk_add(ac_raw, bc_raw)
                    if op_w == 1:
                        result = bit_assign(result, s[0], out_off)
                    else:
                        result = bit_assign(result, s[op_w - 1:0], out_off)
            return rest_fn(result)

    else:

        @hw_func
        def stage(terms: bus_in_t) -> final_out_t:
            result: bus_out_t = 0
            for i in range(n_ops):
                kind = OPS[i][0]
                if kind == 0:
                    ioff = OPS[i][1]
                    w = OPS[i][2]
                    ooff = OPS[i][3]
                    if w == 1:
                        result = bit_assign(result, terms[ioff], ooff)
                    else:
                        result = bit_assign(result, terms[ioff + w - 1:ioff], ooff)
                else:
                    ac_off = OPS[i][1]
                    ac_w = OPS[i][2]
                    bc_off = OPS[i][3]
                    bc_w = OPS[i][4]
                    op_w = OPS[i][5]
                    out_off = OPS[i][6]
                    ac_raw: op_t = 0
                    bc_raw: op_t = 0
                    if ac_w == 1:
                        ac_raw = terms[ac_off]
                    else:
                        ac_raw = terms[ac_off + ac_w - 1:ac_off]
                    if bc_w == 1:
                        bc_raw = terms[bc_off]
                    else:
                        bc_raw = terms[bc_off + bc_w - 1:bc_off]
                    s: sum_t = chunk_add(ac_raw, bc_raw)
                    if op_w == 1:
                        result = bit_assign(result, s[0], out_off)
                    else:
                        result = bit_assign(result, s[op_w - 1:0], out_off)
            return rest_fn(result)

    return stage, is_wires


def make_soft_add_tree_carry_save(n_leaves, leaf_t, out_t, max_width=2):
    """Sum n_leaves leaf_t values, where leaf i contributes `terms[i] << i`,
    via the deferred-carry reduction described in this section's module
    comment, capping every add at max_width bits. Signature-compatible with
    make_soft_add_tree_shifted so callers (make_soft_mult_carry_save below)
    use it the same way.

    max_width sets the widest single add anywhere in the whole reduction --
    the per-stage delay floor -- and therefore the stage count: smaller
    max_width means more, narrower, faster stages. max_width >= leaf_t's
    width degenerates toward a small number of wide adds (closer to, though
    not identical in shape to, make_soft_add_tree_shifted's own tree)."""
    if n_leaves < 2:
        raise ValueError(
            "make_soft_add_tree_carry_save needs >= 2 leaves; callers handle "
            "the single-partial-product case inline (see make_soft_mult_carry_save)"
        )
    if max_width < 1:
        raise ValueError(f"make_soft_add_tree_carry_save: max_width must be >= 1 (got {max_width})")

    leaf_width = len(leaf_t)
    out_bits = len(out_t)
    initial = [(leaf_width, i) for i in range(n_leaves)]
    levels, _final_width = _plan_carry_save_levels(initial, out_bits, max_width)

    in_t = leaf_t[n_leaves]
    initial_bus_t = make_uint_t(leaf_width * n_leaves)
    chain_fn, chain_wires = _build_carry_save_stage(
        levels, 0, leaf_width * n_leaves, out_bits, max_width, out_t
    )

    # array_to_uint_le is a zero-delay bit-manip primitive (like concat/
    # bit_dup elsewhere in this codebase, its own delay is analytically
    # known rather than something that gets independently timing-estimated
    # and could crash) -- so this wrapper is pure wires iff chain_fn is.
    if chain_wires:

        @wires
        def soft_add_tree_carry_save(terms: in_t) -> out_t:
            packed: initial_bus_t = array_to_uint_le(terms)
            result: out_t = chain_fn(packed)
            return result

    else:

        @hw_func
        def soft_add_tree_carry_save(terms: in_t) -> out_t:
            packed: initial_bus_t = array_to_uint_le(terms)
            result: out_t = chain_fn(packed)
            return result

    return soft_add_tree_carry_save


def make_soft_mult_carry_save(l_t, r_t, max_width=2):
    """Deferred-carry (carry-save-style) multiplier: same AND-mask partial
    products as make_soft_mult_shift_add, summed via
    make_soft_add_tree_carry_save instead of a full carry-propagate tree.
    See this section's module comment and docs/SYN_DESIGN.md section 11 for
    the sky130 measurements behind max_width's default."""
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    left_bits = len(eff_l_t)
    r_bits = len(eff_r_t)

    if r_bits == 1:
        # Single partial product -- no tree at all, same as
        # make_soft_mult_shift_add's own r_bits==1 special case.
        @hw_func
        def soft_mult_carry_save(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            bit_mask: eff_l_t = bit_dup(be[0], left_bits)
            result: out_t = ae & bit_mask
            return result

        return soft_mult_carry_save

    soft_add_tree = make_soft_add_tree_carry_save(r_bits, eff_l_t, out_t, max_width=max_width)

    @hw_func
    def soft_mult_carry_save(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        partials: eff_l_t[r_bits]
        for i in range(r_bits):
            bit_mask: eff_l_t = bit_dup(be[i], left_bits)
            partials[i] = ae & bit_mask
        return soft_add_tree(partials)

    return soft_mult_carry_save
