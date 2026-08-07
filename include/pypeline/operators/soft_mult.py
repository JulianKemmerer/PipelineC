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
from pypeline import hw_func, uint1_t, bit_dup, arith_result_type, make_uint_t


def make_tree_add_shifted(n_leaves, leaf_t, out_t, level=0, max_width=None):
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
    make_soft_shift_add_mult for why that matters for autopipelining.

    NOTE: a constant << returns its LEFT operand's width unchanged
    (PY_TO_LOGIC.py:4293-4311), so each operand is widened to shifted_t BEFORE
    being shifted, never after.
    """
    leaf_width = len(leaf_t)
    if max_width is None:
        max_width = len(out_t)
    if n_leaves < 2:
        raise ValueError(
            "make_tree_add_shifted needs >= 2 leaves; callers handle the "
            "single-partial-product case inline (see make_soft_shift_add_mult)"
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
        def tree_add(terms: in_t) -> out_t:
            wide: shifted_t = terms[1]
            shifted: shifted_t = wide << step
            result: out_t = terms[0] + shifted
            return result

        return tree_add

    next_add = make_tree_add_shifted(n_next, node_t, out_t, level + 1, max_width)

    @hw_func
    def tree_add(terms: in_t) -> out_t:
        level_nodes: node_t[n_next]
        for i in range(n_pairs):
            wide: shifted_t = terms[2 * i + 1]
            shifted: shifted_t = wide << step
            level_nodes[i] = terms[2 * i] + shifted
        if odd_leftover:
            leftover: node_t = terms[n_leaves - 1]
            level_nodes[n_pairs] = leftover
        return next_add(level_nodes)

    return tree_add


def make_soft_shift_add_mult(l_t, r_t):
    """Grade-school shift-and-add multiplier: for each bit of b produce an
    UNSHIFTED partial product (a masked by that bit, or 0), then combine them
    with make_tree_add_shifted, a balanced binary adder tree (log2(n) deep) that
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
        # entity; see make_tree_add_shifted's terminal-level note).
        @hw_func
        def soft_shift_add_mult(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            bit_mask: eff_l_t = bit_dup(be[0], left_bits)
            result: out_t = ae & bit_mask
            return result

        return soft_shift_add_mult

    tree_add = make_tree_add_shifted(r_bits, eff_l_t, out_t)

    @hw_func
    def soft_shift_add_mult(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        partials: eff_l_t[r_bits]
        for i in range(r_bits):
            bit_mask: eff_l_t = bit_dup(be[i], left_bits)
            partials[i] = ae & bit_mask
        return tree_add(partials)

    return soft_shift_add_mult


def make_soft_karatsuba_mult(l_t, r_t, threshold=16):
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
            f"make_soft_karatsuba_mult: threshold must be >= 3 (got {threshold}). A "
            "3-bit operand splits into half=1 / hi=2 with mid = max(1,2)+1 = 3 bits, "
            "so the middle sub-multiply is the same width as its parent and the "
            "recursion never terminates below this threshold."
        )
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    n_bits = max(len(eff_l_t), len(eff_r_t))

    if n_bits <= threshold:
        return make_soft_shift_add_mult(l_t, r_t)

    from pypeline import make_uint_t

    half = n_bits // 2
    lo_t = make_uint_t(half)
    hi_t = make_uint_t(n_bits - half)
    mid_t = make_uint_t(max(half, n_bits - half) + 1)

    mult_lo = make_soft_karatsuba_mult(lo_t, lo_t, threshold)
    mult_hi = make_soft_karatsuba_mult(hi_t, hi_t, threshold)
    mult_mid = make_soft_karatsuba_mult(mid_t, mid_t, threshold)

    @hw_func
    def soft_karatsuba_mult(a: l_t, b: r_t) -> out_t:
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

    return soft_karatsuba_mult
