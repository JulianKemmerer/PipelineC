# pyright: reportInvalidTypeForm=none
"""Pipelined atan2 from normalized reciprocal and arctangent ROMs.

The interface matches make_cordic_atan2: signed int16 turns, valid, and a
degenerate flag for (0, 0). Both ROMs use make_auto_pipeline_ram; bounded
queues join each response with its request metadata. No selected latency is
needed to construct the pipeline. Accepts one vector per enabled clock.
The 17-bit normalized numerator fits one signed DSP48 input after extension.
Table quantization is bounded by the DSP tests' 6e-5-turn accuracy contract.
"""

import math

from pypeline import (
    NamedTuple,
    Reg,
    hw_func,
    struct,
    int16_t,
    uint1_t,
    make_int_t,
    make_uint_t,
)
from bits import make_clz, make_shifter_sl
from ram import make_auto_pipeline_ram
from stream.valid_join import make_valid_join


def atan2_tables():
    reciprocal = [round((1 << 18) / (1 + (i + 0.5) / 4096)) for i in range(4096)]
    angle = [
        round(math.atan((i + 0.5) / 4096) * 65536 / (2 * math.pi)) for i in range(4096)
    ]
    return reciprocal, angle


def make_lut_atan2(in_val_t, *, join_depth=32):
    """Return atan2, with its complete return type at atan2.return_t, with angle/valid/degenerate output fields.

    in_val_t is a signed integer type. Accuracy is independent of input scale;
    axes and diagonals are exact, including the wrapped negative-x axis.
    Call with (x, y, valid_in, rst); pass rst=0 explicitly when unused. Reset
    drains queues and clears valid flags. `join_depth` bounds unmatched words
    in each branch; `.overflow` is sticky until reset. `get_latency()` is only
    a diagnostic for continuous clock enable, not an alignment requirement.
    """
    W = len(in_val_t)
    if str(in_val_t) != f"int{W}_t" or W < 2:
        raise ValueError(
            "make_lut_atan2: input must be a signed integer of at least 2 bits"
        )
    NW = max(W, 17)
    ext_t = make_int_t(W + 1)
    mag_t = make_uint_t(NW)
    shift_t = make_uint_t(NW.bit_length())
    norm_t = make_uint_t(17)
    reciprocal_t = make_uint_t(18)
    product_t = make_uint_t(35)
    index_t = make_uint_t(12)
    angle_t = make_uint_t(14)
    wide_angle_t = make_int_t(18)
    clz = make_clz(mag_t)
    shift = make_shifter_sl(mag_t, amount_t=shift_t)
    RECIP, ANGLE = atan2_tables()
    recip = make_auto_pipeline_ram(
        reciprocal_t, 4096, ports=("r",), init=RECIP, start_latency=2
    )
    atan = make_auto_pipeline_ram(
        angle_t, 4096, ports=("r",), init=ANGLE, start_latency=2
    )

    @struct
    class meta_t(NamedTuple):
        swap: uint1_t
        neg_x: uint1_t
        neg_y: uint1_t
        axis: uint1_t
        diagonal: uint1_t
        zero: uint1_t
        valid: uint1_t

    @struct
    class atan2_t(NamedTuple):
        angle: int16_t
        valid: uint1_t
        degenerate: uint1_t
        overflow: uint1_t

    @struct
    class reciprocal_meta_t(NamedTuple):
        minor: norm_t
        meta: meta_t

    recip_join = make_valid_join((reciprocal_meta_t, reciprocal_t), join_depth)
    angle_join = make_valid_join((meta_t, angle_t), join_depth)

    @hw_func
    def lut_atan2(
        x_in: in_val_t, y_in: in_val_t, valid_in: uint1_t, rst: uint1_t
    ) -> atan2_t:
        result: Reg[atan2_t]
        out: atan2_t = result
        out.valid = result.valid & ~rst
        out.overflow = result.overflow & ~rst
        a_major: Reg[mag_t]
        a_minor: Reg[mag_t]
        a_meta: Reg[meta_t]
        b_major: Reg[mag_t]
        b_minor: Reg[mag_t]
        b_shift: Reg[shift_t]
        b_meta: Reg[meta_t]
        c_major: Reg[norm_t]
        c_minor: Reg[norm_t]
        c_meta: Reg[meta_t]
        product: Reg[product_t]
        pmeta: Reg[meta_t]
        index: Reg[index_t]
        imeta: Reg[meta_t]

        rr = recip(recip.p0_in_t(addr=c_major[15:4], valid=c_meta.valid & ~rst))
        ar = atan(atan.p0_in_t(addr=index, valid=imeta.valid & ~rst))
        rj = recip_join(
            reciprocal_meta_t(minor=c_minor, meta=c_meta),
            c_meta.valid,
            rr.p0.rd_data,
            rr.p0.valid,
            rst,
        )
        aj = angle_join(imeta, imeta.valid, ar.p0.rd_data, ar.p0.valid, rst)
        final_meta: meta_t = aj.p0
        base: wide_angle_t = aj.p1
        if final_meta.diagonal:
            base = 8192
        if final_meta.axis:
            base = 0
        unfolded: wide_angle_t = base
        if final_meta.swap:
            unfolded = 16384 - base
        if final_meta.neg_x:
            unfolded = 32768 - unfolded
        if final_meta.neg_y:
            unfolded = -unfolded
        if final_meta.zero:
            unfolded = 0
        result = atan2_t(
            angle=unfolded[15:0],
            valid=aj.valid,
            degenerate=final_meta.zero,
            overflow=rj.overflow | aj.overflow,
        )

        # Reverse update order preserves old stage values in native and HDL.
        ratio: product_t = product >> 22
        index = 4095 if ratio > 4095 else ratio[11:0]
        imeta = pmeta
        product = rj.p0.minor * rj.p1
        pmeta = rj.p0.meta
        pmeta.valid = rj.valid
        major_shifted: mag_t = shift(b_major, b_shift)
        minor_shifted: mag_t = shift(b_minor, b_shift)
        c_major = major_shifted[NW - 1 : NW - 17]
        c_minor = minor_shifted[NW - 1 : NW - 17]
        c_meta = b_meta
        b_major = a_major
        b_minor = a_minor
        b_shift = clz(a_major)
        b_meta = a_meta
        xe: ext_t = x_in
        ye: ext_t = y_in
        ax: ext_t = xe
        ay: ext_t = ye
        if xe < 0:
            ax = -xe
        if ye < 0:
            ay = -ye
        swapped: uint1_t = ay > ax
        a_major = ay if swapped else ax
        a_minor = ax if swapped else ay
        a_meta = meta_t(
            swap=swapped,
            neg_x=xe < 0,
            neg_y=ye < 0,
            axis=(xe == 0) | (ye == 0),
            diagonal=ax == ay,
            zero=(xe == 0) & (ye == 0),
            valid=valid_in & ~rst,
        )
        if rst:
            a_meta.valid = 0
            b_meta.valid = 0
            c_meta.valid = 0
            pmeta.valid = 0
            imeta.valid = 0
            result.valid = 0
            result.overflow = 0
        return out

    lut_atan2.in_val_t = in_val_t
    lut_atan2.out_t = atan2_t
    lut_atan2.reciprocal_rom = recip
    lut_atan2.angle_rom = atan
    lut_atan2.get_latency = lambda: recip.latency + atan.latency + 12
    lut_atan2.join_depth = join_depth
    lut_atan2._sim_clocked_pipeline_boundary = True
    return lut_atan2


def golden_lut_atan2(block, x, y):
    """Bit-exact integer oracle, independent of the pipeline bookkeeping."""
    W = len(block.in_val_t)

    def signed(v):
        v = int(v) & ((1 << W) - 1)
        return v - (1 << W) if v & (1 << (W - 1)) else v

    x, y = signed(x), signed(y)
    if not x and not y:
        return 0, 1
    if not y:
        return (-32768 if x < 0 else 0), 0
    if not x:
        return (-16384 if y < 0 else 16384), 0
    major, minor = max(abs(x), abs(y)), min(abs(x), abs(y))
    shift = major.bit_length() - 17
    a = major >> shift if shift >= 0 else major << -shift
    b = minor >> shift if shift >= 0 else minor << -shift
    reciprocal = round((1 << 18) / (1 + (((a - 65536) >> 4) + 0.5) / 4096))
    index = min(4095, (b * reciprocal) >> 22)
    angle = round(math.atan((index + 0.5) / 4096) * 65536 / (2 * math.pi))
    if major == minor:
        angle = 8192
    if abs(y) > abs(x):
        angle = 16384 - angle
    if x < 0:
        angle = 32768 - angle
    if y < 0:
        angle = -angle
    return ((angle + 32768) & 65535) - 32768, 0
