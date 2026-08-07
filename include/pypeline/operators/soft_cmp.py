"""Soft integer comparators.

Registered the same way any other operator overload is: last registration
for an overlapping matcher wins.

  * make_soft_cmp_prefix (default as of 2026-08, see
    soft.py:register_soft_cmp) -- log2(n)-deep parallel-prefix magnitude
    compare. See its own docstring below for the measured numbers behind
    the promotion, including the narrow-width GTE/LTE tradeoff accepted in
    making it the unconditional default.
  * make_soft_cmp_sub_swapped -- the default through 2026-08 (still
    available via soft.py:register_soft_cmp_sub_swapped): widen, subtract,
    take the sign bit, with the operand order swapped per op so a single
    sign-bit read is always enough (see below). Matches the structure
    SW_LIB.GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE used to generate as C; here
    it is ordinary Pypeline HDL, built on the inferred subtractor (or the
    soft one, if the caller also registered soft sub). Vivado-confirmed
    faster than make_soft_cmp_prefix specifically for GTE/LTE at 8/16-bit
    operand widths -- see make_soft_cmp_prefix's docstring.
  * make_soft_cmp_sub -- same idea but a fixed a-b subtraction reused across
    all four ops, which forces an extra EQ+MUX for GT/LTE (see its
    docstring). Kept for QoR comparison (src/tests/pypeline_tests/
    op_qor_bench.py) and as a simpler reference implementation; never the
    default.
  * make_soft_cmp_bitwise -- MSB-first bitwise magnitude compare, no
    arithmetic at all. Mirrors the (currently dead-code) algorithm in
    RAW_VHDL.py's GET_BIN_OP_GT_GTE_*_C_BUILT_IN_INT_N_/UINT_N_ generators,
    which are unreachable today because C_BUILT_IN_FUNC_IS_RAW_HDL returns
    False for integer GT/GTE/LT/LTE.
  * make_soft_cmp_borrow -- fmax-investigation candidate (docs/
    soft_cmp_fmax_handoff.md): same operand-swap identity as
    make_soft_cmp_sub_swapped, but built as an explicit LSB-to-(width-2)
    borrow-propagate loop over bitwise AND/OR primitives instead of the HDL
    `-` operator, reading the sign as the top DIFFERENCE bit
    (x_msb^y_msb^borrow-in) rather than a final borrow-out (the two are NOT
    the same bit -- an earlier version of this factory read the wrong one and
    failed sim_call against Python's operators on signed operands; fixed by
    computing the top bit's difference explicitly instead of one more borrow
    step). Hypothesis going in: the default's `-` computes a full (n+1)-bit
    difference to read one bit, so skipping the sum bits should be cheaper.
    Measured MUCH WORSE under PyRTL instead (uint32 GT @0cuts: 79.86ns vs the
    default's 10.61-10.88ns -- roughly 7-8x), for a reason unrelated to the
    hypothesis: hand-unrolling the borrow chain into 31 individual bitwise
    AND/OR/XOR @hw_func-leaf operations forfeits whatever lumped/flat delay
    PyRTL's estimator gives the native `-` operator (BIN_OP_MINUS gets one
    cached width-independent delay; see the module docstring's note on
    PyRTL's flat width model) and instead prices 31 serial single-bit gate
    levels individually -- the exact same measurement bias
    make_soft_cmp_bitwise's docstring and docs/SYN_DESIGN.md already document
    (27-47x over-prediction for genuinely serial bitwise structures under
    PyRTL, fine in real synthesis). This result is therefore NOT evidence the
    borrow-chain structure is worse in real hardware, only that PyRTL cannot
    fairly price hand-unrolled bitwise chains against operator-level `-` --
    re-measuring under Vivado is required before ranking this variant, and is
    out of scope for the PyRTL-only pass that produced this docstring. Not
    the default; kept for that follow-up measurement.

Naming: every soft comparator's generated hardware entity name starts with
`soft_cmp_<algorithm>` -- op family first, algorithm second -- e.g.
`soft_cmp_sub_swapped_greater_True_...`. (An earlier version of this file
named the inner functions `soft_sub_cmp*`, which read as an overloaded
*subtraction* operator rather than a subtract-based *comparator* -- `sub`
here has always meant "built via subtract", never "substituted".)

QoR data validity: the recorded PyRTL sweep in op_qor_results_pyrtl.csv has
non-monotonic per-stage delay for GT/uint32/soft_cmp_sub_swapped (10.88ns@0cuts
-> 18.11ns@1cut) and identical values at adjacent cut counts (10.72ns at both
5 and 6 cuts). Verified (2026-08, re-running single cases directly through
pipelinec, comparing generated VHDL) that this is REAL measured data, not a
duplicated-design harness bug: each cut count produces genuinely distinct VHDL
("Pipeline Slices: [...]" differs every time) and a distinct FF count. The
0->1cut dip happens because op_qor_bench.py's --coarse --sweep mode places
cuts at naive even clock-count fractions (GET_BEST_GUESS_IDEAL_SLICES), not by
where delay actually concentrates -- at 1 cut that lands a register mid-way
through the single 33-bit BIN_OP_MINUS's carry chain, splitting it unevenly
under PyRTL's flat (width-independent) per-op delay model, which measures
worse than leaving it whole. The 5==6-cut plateau is the opposite effect: once
enough cuts have isolated the true bottleneck segment, further cuts land in
already-zero-delay regions and stop changing the reported number (a real
slicing floor, not a duplicate). Conclusion: the PyRTL numbers are valid data
points, but noisy at low cut counts for a single-submodule design -- judge
comparators by the whole curve (docstring below), never a single n_cuts point.
The Vivado sweep in op_qor_results_vivado.csv does show make_soft_cmp_sub_swapped
dominating make_soft_cmp_sub at every measured n_cuts>=1 for GT/LTE (identical
for GTE/LT, where the un-swapped default was already cheap).
"""
from pypeline import hw_func, uint1_t, make_int_t, make_uint_t, arith_result_type

_STRICT = {"GT": True, "LT": True, "GTE": False, "LTE": False}
_GREATER = {"GT": True, "GTE": True, "LT": False, "LTE": False}


def make_soft_cmp_sub(op):
    """Return a factory(l_t, r_t) -> hw_func implementing `op` via
    widen + subtract + sign-bit (op in "GT"/"GTE"/"LT"/"LTE")."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        # NOTE: arith_result_type("MINUS", ...) mirrors the built-in path's
        # rule that same-sign operands produce a same-sign (here: unsigned,
        # wrapping) result -- exactly wrong for a sign-bit trick. The
        # comparator instead needs an explicitly SIGNED, wide-enough-to-never-
        # overflow subtraction: width = max(operand widths) + 1 bits covers
        # every a-b in [-(2**n-1), 2**n-1] for n-bit unsigned operands.
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t)) + 1
        sub_t = make_int_t(width)

        @hw_func
        def soft_cmp_sub(a: l_t, b: r_t) -> uint1_t:
            ae: sub_t = a
            be: sub_t = b
            # a - b: sign(diff) tells us a<b (negative) vs a>=b (non-negative);
            # strict/non-strict and greater/less variants derived from that.
            diff: sub_t = ae - be
            neg: uint1_t = diff[len(sub_t) - 1]
            is_zero: uint1_t = 1 if diff == 0 else 0
            result: uint1_t = 0
            if greater:
                if strict:
                    result = (1 - neg) & (1 - is_zero)
                else:
                    result = 1 - neg
            else:
                if strict:
                    result = neg
                else:
                    result = neg | is_zero
            return result

        return soft_cmp_sub

    return factory


def make_soft_cmp_sub_swapped(op):
    """The library default through 2026-08 (see
    soft.py:register_soft_cmp_sub_swapped; superseded as the unconditional
    default by make_soft_cmp_prefix, see its docstring): operand-swap
    instead of a fixed diff + separate is_zero test, matching the structure
    SW_LIB.GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE actually used (see
    docs/SYN_DESIGN.md) -- one subtract, one sign-bit read, no EQ submodule
    and no MUX. `a>b` == neg(b-a); `a>=b` == !neg(a-b); `a<b` == neg(a-b);
    `a<=b` == !neg(b-a). Still Vivado-confirmed faster than
    make_soft_cmp_prefix specifically for GTE/LTE at 8/16-bit operand
    widths -- see make_soft_cmp_prefix's docstring for the numbers."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t)) + 1
        sub_t = make_int_t(width)

        @hw_func
        def soft_cmp_sub_swapped(a: l_t, b: r_t) -> uint1_t:
            ae: sub_t = a
            be: sub_t = b
            result: uint1_t = 0
            if greater:
                # a>b: neg(b-a).  a>=b: !neg(a-b)
                if strict:
                    diff: sub_t = be - ae
                else:
                    diff: sub_t = ae - be
                neg: uint1_t = diff[len(sub_t) - 1]
                result = neg if strict else (1 - neg)
            else:
                # a<b: neg(a-b).  a<=b: !neg(b-a)
                if strict:
                    diff: sub_t = ae - be
                else:
                    diff: sub_t = be - ae
                neg: uint1_t = diff[len(sub_t) - 1]
                result = neg if strict else (1 - neg)
            return result

        return soft_cmp_sub_swapped

    return factory


def make_soft_cmp_borrow(op):
    """fmax-investigation candidate: same operand-swap identity as
    make_soft_cmp_sub_swapped, but implemented as an explicit LSB-to-MSB
    borrow chain (mirroring make_soft_add_ripple's carry chain in soft_add.py)
    instead of the HDL `-` operator, so no difference/sum bit is ever
    materialized -- only the final borrow-out, which is exactly the sign bit
    the default reads. See the module docstring for the measured result."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t)) + 1
        sub_t = make_int_t(width)

        @hw_func
        def soft_cmp_borrow(a: l_t, b: r_t) -> uint1_t:
            ae: sub_t = a
            be: sub_t = b
            # Same per-op operand swap as soft_cmp_sub_swapped: x - y's borrow
            # chain, where (x, y) is (b, a) or (a, b) depending on op.
            x: sub_t = ae
            y: sub_t = be
            if greater:
                if strict:
                    x = be
                    y = ae
            else:
                if not strict:
                    x = be
                    y = ae
            # Ripple the borrow through bits 0..width-2 only -- the sign bit
            # of a two's-complement difference is the DIFFERENCE bit at the
            # top position (x_msb ^ y_msb ^ borrow-in), not the borrow that
            # ripples past it (which reflects wraparound, not sign).
            borrow: uint1_t = 0
            for i in range(width - 1):
                xi: uint1_t = x[i]
                yi: uint1_t = y[i]
                borrow = ((1 - xi) & yi) | ((1 - xi) & borrow) | (yi & borrow)
            x_msb: uint1_t = x[width - 1]
            y_msb: uint1_t = y[width - 1]
            neg: uint1_t = (x_msb ^ y_msb) ^ borrow
            result: uint1_t = neg if strict else (1 - neg)
            return result

        return soft_cmp_borrow

    return factory


def make_soft_cmp_bitwise(op):
    """Return a factory(l_t, r_t) -> hw_func implementing `op` via MSB-first
    bitwise magnitude comparison (no adder/subtractor at all)."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        # arith_result_type("MINUS", ...) only sign-promotes -- for
        # mismatched-width unsigned operands (e.g. uint32_t vs uint3_t) it
        # returns eff_l_t/eff_r_t at their ORIGINAL differing widths, not a
        # common one (confirmed: arith_result_type("MINUS", uint32_t, uint3_t)
        # == (uint32_t, uint3_t, ...)). Indexing both at n_bits=len(eff_l_t)
        # then overruns the narrower operand. Resize both to one common width
        # explicitly, same pattern make_soft_cmp_sub uses.
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        n_bits = max(len(eff_l_t), len(eff_r_t))
        is_signed = str(l_t).startswith("int") or str(r_t).startswith("int")
        make_t = make_int_t if is_signed else make_uint_t
        common_t = make_t(n_bits)

        @hw_func
        def soft_cmp_bitwise(a: l_t, b: r_t) -> uint1_t:
            ae: common_t = a
            be: common_t = b
            gt: uint1_t = 0
            lt: uint1_t = 0
            decided: uint1_t = 0
            # MSB carries sign meaning for signed operands: an unset "gt/lt"
            # decision after the top bit flips outcome for mismatched signs.
            for bit_idx in range(n_bits):
                i = n_bits - 1 - bit_idx
                ai: uint1_t = ae[i]
                bi: uint1_t = be[i]
                if is_signed and i == n_bits - 1:
                    # Sign bit: 0 (non-negative) is greater than 1 (negative).
                    this_gt: uint1_t = (1 - ai) & bi
                    this_lt: uint1_t = ai & (1 - bi)
                else:
                    this_gt: uint1_t = ai & (1 - bi)
                    this_lt: uint1_t = (1 - ai) & bi
                if not decided:
                    if this_gt:
                        gt = 1
                        decided = 1
                    elif this_lt:
                        lt = 1
                        decided = 1
            result: uint1_t = 0
            if greater:
                result = gt if strict else (gt | (1 - (gt | lt)))
            else:
                result = lt if strict else (lt | (1 - (gt | lt)))
            return result

        return soft_cmp_bitwise

    return factory


def _make_prefix_tree(n_leaves, level=0):
    """Combine n_leaves per-bit (gt,lt) codes (uint2_t: bit1=gt, bit0=lt,
    00=undecided-so-far) into one root code via a balanced binary tree,
    log2(n_leaves) deep, mirroring make_soft_add_tree_shifted's per-level
    @hw_func shape (soft_mult.py) so each level is priced as its own
    submodule rather than one flat unrolled scan.

    combine(l, r) = l if l is decided (gt or lt) else r -- associative
    (leader-select), so pairing leaves in ANY balanced grouping gives the
    same MSB-first "first decided bit wins" answer as a serial scan, as long
    as leaf order (most-significant leaf first) is preserved through pairing."""
    leaf_t = _uint2_t()
    in_t = leaf_t[n_leaves]
    n_pairs = n_leaves // 2
    odd_leftover = (n_leaves % 2) == 1
    n_next = n_pairs + (1 if odd_leftover else 0)

    if n_leaves == 1:
        # Only reached for the whole-tree n_leaves==1 edge case (single-bit
        # compare) -- identity passthrough, never recursed into (n_next==1
        # from a pair is handled as the terminal case below instead, so this
        # never emits a rewire-only child entity mid-tree).
        @hw_func
        def soft_cmp_prefix(terms: in_t) -> leaf_t:
            return terms[0]

        return soft_cmp_prefix

    if n_next == 1:
        @hw_func
        def soft_cmp_prefix(terms: in_t) -> leaf_t:
            l: leaf_t = terms[0]
            r: leaf_t = terms[1]
            result: leaf_t = r
            if l[1] or l[0]:
                result = l
            return result

        return soft_cmp_prefix

    next_combine = _make_prefix_tree(n_next, level + 1)

    @hw_func
    def soft_cmp_prefix(terms: in_t) -> leaf_t:
        level_nodes: leaf_t[n_next]
        for i in range(n_pairs):
            l: leaf_t = terms[2 * i]
            r: leaf_t = terms[2 * i + 1]
            combined: leaf_t = r
            if l[1] or l[0]:
                combined = l
            level_nodes[i] = combined
        if odd_leftover:
            level_nodes[n_pairs] = terms[n_leaves - 1]
        return next_combine(level_nodes)

    return soft_cmp_prefix


_UINT2_T_CACHE = [None]


def _uint2_t():
    if _UINT2_T_CACHE[0] is None:
        _UINT2_T_CACHE[0] = make_uint_t(2)
    return _UINT2_T_CACHE[0]


def make_soft_cmp_prefix(op):
    """Default comparator flavor as of 2026-08 (see
    soft.py:register_soft_cmp; docs/SYN_DESIGN.md section 8 has the full
    investigation writeup). log2(n)-deep parallel-prefix magnitude compare
    -- the missing member of the family make_soft_cmp_bitwise's docstring
    calls out (that one is a SERIAL MSB-first scan, O(n) depth; this
    combines per-bit (gt,lt) pairs with an associative leader-select
    operator in a balanced tree instead, one @hw_func per tree level).

    PyRTL swept this cleanly beating the previous default
    (make_soft_cmp_sub_swapped) at every n_cuts>=1 across all 24 measurable
    (op, width) combinations. Each tree level is its own @hw_func (the
    soft_mult.py per-level-entity lesson), so PyRTL prices each level's
    small 2-bit combine independently instead of unrolling one giant flat
    scan the way make_soft_cmp_borrow does -- that structural difference is
    exactly why this candidate escaped the PyRTL blind spot the borrow chain
    did not.

    Vivado-confirmed (xc7a200tffg1156-2, all 32 (op,width) combinations
    measured) to win 28/32 vs. the previous default at n_cuts>=1 -- decisive
    and width-scaling at 32/64-bit widths across ALL four ops (e.g. uint64
    GTE: up to 40% faster at deep cuts, margin grows with width). The 4
    losses are GTE/LTE specifically at 8/16-bit widths (GT/LT still win even
    there) -- e.g. uint16 GTE: previous default 1.83-1.97ns vs this
    2.15-2.79ns at every cut count, consistently worse, not noise. Real
    synthesis optimizes the previous default's single small subtract
    extremely well (~1.7-2ns) at narrow widths; this structure's fixed
    per-level tree overhead only pays for itself once the base comparator is
    wide enough to be the actual bottleneck. Promoted as the unconditional
    default anyway (net win across the full measured matrix); for a design
    known to be narrow-GTE/LTE-heavy, register_soft_cmp_sub_swapped (soft.py)
    is the Vivado-confirmed better choice specifically there."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        n_bits = max(len(eff_l_t), len(eff_r_t))
        is_signed = str(l_t).startswith("int") or str(r_t).startswith("int")
        make_t = make_int_t if is_signed else make_uint_t
        common_t = make_t(n_bits)
        u2_t = _uint2_t()
        tree = _make_prefix_tree(n_bits)

        @hw_func
        def soft_cmp_prefix(a: l_t, b: r_t) -> uint1_t:
            ae: common_t = a
            be: common_t = b
            leaves: u2_t[n_bits]
            # MSB-first leaf order (index 0 = most significant bit) so the
            # tree's leader-select combine reproduces the serial scan's
            # "first decided bit, scanning from the top" answer.
            for bit_idx in range(n_bits):
                i = n_bits - 1 - bit_idx
                ai: uint1_t = ae[i]
                bi: uint1_t = be[i]
                if is_signed and i == n_bits - 1:
                    this_gt: uint1_t = (1 - ai) & bi
                    this_lt: uint1_t = ai & (1 - bi)
                else:
                    this_gt: uint1_t = ai & (1 - bi)
                    this_lt: uint1_t = (1 - ai) & bi
                leaf: u2_t = 0
                if this_gt:
                    leaf = 2
                elif this_lt:
                    leaf = 1
                leaves[bit_idx] = leaf
            root: u2_t = tree(leaves)
            gt: uint1_t = root[1]
            lt: uint1_t = root[0]
            result: uint1_t = 0
            if greater:
                result = gt if strict else (gt | (1 - (gt | lt)))
            else:
                result = lt if strict else (lt | (1 - (gt | lt)))
            return result

        return soft_cmp_prefix

    return factory


def _make_chunk_leaf(chunk_bits, is_top_chunk, is_signed):
    """One MSB-first bitwise scan (same algorithm as make_soft_cmp_bitwise's
    inner loop), bounded to a single chunk_bits-wide chunk, returning a
    (gt,lt) u2_t code. Sign-bit handling only applies within the top
    (most-significant) chunk's own top bit -- chunks are always plain
    unsigned bit-slices of the parent value; signedness is a property of
    that ONE bit position, not of a chunk's type."""
    u2_t = _uint2_t()
    chunk_t = make_uint_t(chunk_bits)

    @hw_func
    def soft_cmp_chunk(a: chunk_t, b: chunk_t) -> u2_t:
        gt: uint1_t = 0
        lt: uint1_t = 0
        decided: uint1_t = 0
        for bit_idx in range(chunk_bits):
            i = chunk_bits - 1 - bit_idx
            ai: uint1_t = a[i]
            bi: uint1_t = b[i]
            if is_signed and is_top_chunk and i == chunk_bits - 1:
                this_gt: uint1_t = (1 - ai) & bi
                this_lt: uint1_t = ai & (1 - bi)
            else:
                this_gt: uint1_t = ai & (1 - bi)
                this_lt: uint1_t = (1 - ai) & bi
            if not decided:
                if this_gt:
                    gt = 1
                    decided = 1
                elif this_lt:
                    lt = 1
                    decided = 1
        code: u2_t = 0
        if gt:
            code = 2
        elif lt:
            code = 1
        return code

    return soft_cmp_chunk


def make_soft_cmp_chunked(op, chunk_bits=8):
    """fmax-investigation candidate (docs/soft_cmp_fmax_handoff.md): split
    into chunk_bits-wide chunks compared in parallel (each chunk its own
    @hw_func, via _make_chunk_leaf), select on the most-significant differing
    chunk by reducing chunk results through the SAME associative
    leader-select tree make_soft_cmp_prefix uses (_make_prefix_tree) -- one
    fewer levels than the per-bit prefix tree since each leaf already covers
    chunk_bits bits, at the cost of each leaf itself being an O(chunk_bits)
    serial scan (make_soft_cmp_bitwise's structure, just narrower).
    chunk_bits is swept the same way make_soft_mult_karatsuba's threshold is
    (see op_qor_bench.py's karatsuba_threshold_reps for the CANONICAL_CALLABLE_KEY
    dedup pattern this can reuse if the chunk width sweep grows large).

    Measured (uint32 GT, chunk_bits=8, PyRTL): 29.48/16.83/12.01/9.20/8.31 ns
    at 0-4 cuts. Beats the shipped default (make_soft_cmp_sub_swapped:
    10.88/18.11/15.51/12.50/12.64) at every n_cuts>=2, loses at 0-1 -- each
    8-bit chunk's internal O(8) serial scan pays the same per-bit-primitive
    PyRTL pricing that hurt make_soft_cmp_borrow, just amortized over 4
    chunks instead of 32 serial bits. Loses to make_soft_cmp_prefix (see its
    docstring) at every cut count measured. Not a leading candidate on
    current data; kept because it is a real, distinct structural point on the
    granularity spectrum between the per-bit prefix tree and the fully serial
    bitwise scan, and its chunk_bits parameter is worth sweeping before
    concluding the tree strictly dominates it."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        n_bits = max(len(eff_l_t), len(eff_r_t))
        is_signed = str(l_t).startswith("int") or str(r_t).startswith("int")
        make_t = make_int_t if is_signed else make_uint_t
        common_t = make_t(n_bits)
        u2_t = _uint2_t()

        # MSB-first chunk boundaries: a leading partial chunk of n_bits % c
        # bits (if any) first, then clean chunk_bits-wide groups -- same
        # leading-partial-group idiom soft_div.py's _make_radix_restoring
        # uses for its non-multiple step list.
        c = chunk_bits
        bounds = []  # list of (hi, lo) MSB-first
        hi = n_bits - 1
        lead = n_bits % c
        if lead != 0:
            bounds.append((hi, hi - lead + 1))
            hi -= lead
        while hi >= c - 1:
            bounds.append((hi, hi - c + 1))
            hi -= c
        n_chunks = len(bounds)

        # The elaborator only accepts a bare-name call target (confirmed by
        # hitting "'Subscript' object has no attribute 'id'" from
        # leaf_fns[j](...)) -- a Python list of distinct per-chunk closures
        # indexed at HDL-loop time is not callable. By construction only the
        # leading (most-significant) chunk can have a width other than `c`,
        # so every OTHER chunk shares one width and can share ONE leaf
        # hw_func, called identically (same bare name) across the unrolled
        # loop; only the top chunk (which alone needs the sign-bit special
        # case) gets its own separate hw_func, called once, also by name.
        top_width = bounds[0][0] - bounds[0][1] + 1
        top_t = make_uint_t(top_width)
        leaf_fn_top = _make_chunk_leaf(top_width, True, is_signed)
        common_chunk_t = make_uint_t(c) if n_chunks > 1 else None
        leaf_fn_common = _make_chunk_leaf(c, False, is_signed) if n_chunks > 1 else None
        tree = _make_prefix_tree(n_chunks) if n_chunks > 1 else None

        @hw_func
        def soft_cmp_chunked(a: l_t, b: r_t) -> uint1_t:
            ae: common_t = a
            be: common_t = b
            root: u2_t = 0
            if n_chunks == 1:
                lo0 = bounds[0][1]
                hi0 = bounds[0][0]
                a_top: top_t = ae[hi0:lo0]
                b_top: top_t = be[hi0:lo0]
                root = leaf_fn_top(a_top, b_top)
            else:
                leaves: u2_t[n_chunks]
                lo0 = bounds[0][1]
                hi0 = bounds[0][0]
                a_top: top_t = ae[hi0:lo0]
                b_top: top_t = be[hi0:lo0]
                leaves[0] = leaf_fn_top(a_top, b_top)
                for j in range(1, n_chunks):
                    lo = bounds[j][1]
                    hi2 = bounds[j][0]
                    a_chunk: common_chunk_t = ae[hi2:lo]
                    b_chunk: common_chunk_t = be[hi2:lo]
                    leaves[j] = leaf_fn_common(a_chunk, b_chunk)
                root = tree(leaves)
            gt: uint1_t = root[1]
            lt: uint1_t = root[0]
            result: uint1_t = 0
            if greater:
                result = gt if strict else (gt | (1 - (gt | lt)))
            else:
                result = lt if strict else (lt | (1 - (gt | lt)))
            return result

        return soft_cmp_chunked

    return factory
