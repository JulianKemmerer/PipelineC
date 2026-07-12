# pyright: reportInvalidTypeForm=none
"""Shared FIR building blocks: elaboration-time coefficient analysis and the
single pure-combinational dot-product blob (`make_fir_core`) that every filter
in this library wraps.

The blob is deliberately one flat feedforward function -- pre-adders (when the
quantized coefficients are symmetric/anti-symmetric), constant multiplies, a
balanced binary adder tree, and the fixed-point output resize stage all live in
one `@hw_func` so PipelineC's AUTOPIPELINE retimes the whole thing together to
whatever depth the target FPGA/fmax needs. Pipeline depth is never hard-coded
anywhere in this library.

All sizing is exact: the accumulator width comes from interval arithmetic over
the actual quantized coefficient values and the data type's representable
range, so no intermediate can overflow and no bit is wasted.
"""

from pypeline import Reg, hw_func, uint1_t

from fixed_point import make_fixed_t, make_fixed_resize


def analyze_coeffs(coeffs_q):
    """Elaboration-time analysis of QUANTIZED (raw integer) coefficients.

    Returns (symmetry, zero_taps):
      symmetry:  "symmetric" | "antisymmetric" | None
      zero_taps: set of tap indices whose quantized coefficient is exactly 0

    Analysis runs on the quantized integers, not the original floats, so a
    coefficient set that only folds after quantization still folds, and one
    that stops folding due to quantization is not mis-folded.
    """
    if len(coeffs_q) == 0:
        raise ValueError("analyze_coeffs: empty coefficient list")
    if all(c == 0 for c in coeffs_q):
        raise ValueError(
            "analyze_coeffs: all coefficients quantize to 0 -- the filter "
            "would be hardwired to output 0 (coeff_t too narrow for these taps?)"
        )
    symmetry = None
    if list(coeffs_q) == list(coeffs_q)[::-1]:
        symmetry = "symmetric"
    elif list(coeffs_q) == [-c for c in coeffs_q[::-1]]:
        # For odd N this implies the center tap is 0 (c == -c).
        symmetry = "antisymmetric"
    zero_taps = {i for i, c in enumerate(coeffs_q) if c == 0}
    return symmetry, zero_taps


def build_terms(coeffs_q, symmetry, skip_zero_taps):
    """Turn a quantized coefficient list into a uniform table of multiplier
    terms (plain Python lists, consumed at elaboration time).

    Term j computes: (window[A[j]] + SGN[j] * window[B[j]]) * C[j]
      SGN =  1 -> symmetric pre-adder pair
      SGN = -1 -> anti-symmetric pre-subtractor pair
      SGN =  0 -> single tap (B == A; the 0-multiplied operand is
                  constant-folded away by synthesis)

    Folding halves the multiplier count exactly like the vendor cores'
    symmetric-coefficient optimization; `skip_zero_taps` drops zero-coefficient
    terms entirely at elaboration time (half-band filters fall out for free).
    """
    n = len(coeffs_q)
    A, B, SGN, C = [], [], [], []
    if symmetry in ("symmetric", "antisymmetric"):
        sgn = 1 if symmetry == "symmetric" else -1
        for i in range(n // 2):
            if skip_zero_taps and coeffs_q[i] == 0:
                continue
            A.append(i)
            B.append(n - 1 - i)
            SGN.append(sgn)
            C.append(coeffs_q[i])
        if n % 2 == 1:
            mid = n // 2
            # (antisymmetric center tap is 0 by definition and always skipped)
            if coeffs_q[mid] != 0 or not skip_zero_taps:
                A.append(mid)
                B.append(mid)
                SGN.append(0)
                C.append(coeffs_q[mid])
    else:
        for i in range(n):
            if skip_zero_taps and coeffs_q[i] == 0:
                continue
            A.append(i)
            B.append(i)
            SGN.append(0)
            C.append(coeffs_q[i])
    return A, B, SGN, C


def _data_range(data_t):
    """Representable raw-integer range of a fixed_t's .val field."""
    total = data_t.int_bits + data_t.frac_bits
    if data_t.signed:
        return -(1 << (total - 1)), (1 << (total - 1)) - 1
    return 0, (1 << total) - 1


def _signed_bits_for(lo, hi):
    """Smallest signed two's-complement width holding every value in [lo, hi]."""
    b = 1
    while lo < -(1 << (b - 1)) or hi > (1 << (b - 1)) - 1:
        b += 1
    return b


def accum_bounds(A, B, SGN, C, data_t):
    """Exact interval-arithmetic bounds of the full dot product, from the
    actual coefficient values and data_t's raw range. Every partial sum of the
    adder tree also fits these bounds (each term's max contribution is >= 0
    and min contribution is <= 0), so one accumulator type is safe throughout.
    """
    xmin, xmax = _data_range(data_t)
    lo = 0
    hi = 0
    for j in range(len(C)):
        if SGN[j] == 1:
            omin, omax = 2 * xmin, 2 * xmax
        elif SGN[j] == -1:
            omin, omax = xmin - xmax, xmax - xmin
        else:
            omin, omax = xmin, xmax
        p0, p1 = C[j] * omin, C[j] * omax
        lo += min(p0, p1)
        hi += max(p0, p1)
    return lo, hi


def make_samples_window(data_t, n_taps):
    """Shift-register sample window: presents [current sample, previous
    n_taps-1 samples] combinationally, committing the shift only when
    `advance` is high -- so backpressure freezes the window contents.
    (Port of include/dsp/fir.h's window-includes-current-sample semantics,
    plus the advance gate the old library lacked.)
    """
    win_t = data_t[n_taps]

    @hw_func
    def samples_window(sample: data_t, advance: uint1_t) -> win_t:
        window: Reg[win_t]
        shifted: win_t
        shifted[0] = sample
        for i in range(1, n_taps):
            shifted[i] = window[i - 1]
        if advance:
            window = shifted
        return shifted

    return samples_window


def make_fir_core(
    coeffs_q,
    data_t,
    coeff_t,
    out_t=None,
    rounding="truncate",
    overflow="wrap",
    symmetry="auto",
    skip_zero_taps=True,
):
    """The one pure-comb FIR blob: `@hw_func(data_t[n_taps]) -> out_t`.

    coeffs_q: QUANTIZED coefficients (raw ints in coeff_t's representation).
    out_t=None keeps the full-precision accumulator type as the output
    (vendor "Full Precision" mode; rounding/overflow are then unused).
    Otherwise a `make_fixed_resize(accum_t, out_t, rounding, overflow)` stage
    is fused onto the end of the blob so it retimes with everything else.

    Returns (fir_core, out_t_actual, accum_t).
    """
    n_taps = len(coeffs_q)
    detected, _zero_taps = analyze_coeffs(coeffs_q)
    if symmetry == "auto":
        sym = detected
    elif symmetry == "none":
        sym = None
    else:
        raise ValueError(
            f"make_fir_core: unsupported symmetry {symmetry!r}, "
            "expected 'auto' or 'none'"
        )
    A, B, SGN, CQ = build_terms(coeffs_q, sym, skip_zero_taps)
    NT = len(A)

    lo, hi = accum_bounds(A, B, SGN, CQ, data_t)
    acc_bits = _signed_bits_for(lo, hi)
    acc_frac = data_t.frac_bits + coeff_t.frac_bits
    accum_t = make_fixed_t(acc_bits - acc_frac, acc_frac, signed=True)
    accum_val_t = accum_t.typeof("val")

    # Balanced binary adder tree, zero-padded to a power of two (padding terms
    # are constant 0 -- pruned by synthesis). LEVELS=0 when there is 1 term.
    LEVELS = (NT - 1).bit_length()
    NPAD = 1 << LEVELS

    window_t = data_t[n_taps]

    if out_t is None:
        out_t_actual = accum_t

        @hw_func
        def fir_core(window: window_t) -> out_t_actual:
            nodes: accum_val_t[LEVELS + 1][NPAD]
            for j in range(NT):
                nodes[0][j] = (window[A[j]].val + SGN[j] * window[B[j]].val) * CQ[j]
            for j in range(NT, NPAD):
                nodes[0][j] = 0
            for lvl in range(LEVELS):
                for i in range(NPAD >> (lvl + 1)):
                    nodes[lvl + 1][i] = nodes[lvl][2 * i] + nodes[lvl][2 * i + 1]
            acc: out_t_actual = out_t_actual(val=nodes[LEVELS][0])
            return acc

    else:
        out_t_actual = out_t
        resize_fn = make_fixed_resize(accum_t, out_t, rounding, overflow)

        @hw_func
        def fir_core(window: window_t) -> out_t_actual:
            nodes: accum_val_t[LEVELS + 1][NPAD]
            for j in range(NT):
                nodes[0][j] = (window[A[j]].val + SGN[j] * window[B[j]].val) * CQ[j]
            for j in range(NT, NPAD):
                nodes[0][j] = 0
            for lvl in range(LEVELS):
                for i in range(NPAD >> (lvl + 1)):
                    nodes[lvl + 1][i] = nodes[lvl][2 * i] + nodes[lvl][2 * i + 1]
            acc: accum_t = accum_t(val=nodes[LEVELS][0])
            return resize_fn(acc)

    return fir_core, out_t_actual, accum_t
