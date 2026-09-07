# pyright: reportInvalidTypeForm=none
"""Shared sizing and option validation for the byte-stream serializer/
deserializer pair (`stream/serializer.py`, `stream/deserializer.py`) and the
type-level layers built on them (`stream/type_byte_stream.py`,
`axi/type_axis.py`).

Pure Python -- no hardware here, so a design that mis-sizes a stream fails at
factory-call time (i.e. while the design module is being imported for
elaboration) with a message naming both sizes, rather than elaborating into a
circuit that silently deadlocks. That silent deadlock is exactly what the old
PipelineC macros did: `deserializer.h:41`'s `if(out_counter==OUT_SIZE)` and
`serializer.h:42`'s `if(out_counter==IN_SIZE)` step *over* their target when
the sizes are not divisible, so the buffer never fills/clears and the stream
wedges forever with no diagnostic.
"""
from pypeline import make_uint_t

# Whether one value's elements are padded out to a whole number of output
# beats, or packed back-to-back with the next value's.
ALIGN_MODES = ("beat", "packed")

# Whether a non-divisible size is allowed (expressed via `keep`) or rejected.
PADDING_MODES = ("pad", "exact")

# What a deserializer does with a partial value when the input stream ends.
ON_EOD_MODES = ("discard", "zero_pad", "ignore")


def check_choice(func_name: str, param: str, value, allowed) -> None:
    """Validate a string-valued factory option."""
    if value not in allowed:
        raise ValueError(
            f"{func_name}: {param} must be one of {allowed!r}, got {value!r}"
        )


def check_sizes(func_name: str, in_n: int, out_n: int) -> None:
    if not (isinstance(in_n, int) and in_n >= 1):
        raise ValueError(f"{func_name}: in_n must be a positive int, got {in_n!r}")
    if not (isinstance(out_n, int) and out_n >= 1):
        raise ValueError(f"{func_name}: out_n must be a positive int, got {out_n!r}")


def check_padding(func_name: str, padding: str, in_n: int, out_n: int, what: str) -> None:
    """Enforce `padding="exact"`, which demands that no beat is ever partial.

    `what` names the direction in the message ("out_n", "in_n" ...), since the
    divisibility that matters differs: a deserializer fills out_n elements from
    in_n-element beats (needs out_n % in_n == 0), a serializer drains in_n
    elements out out_n at a time (needs in_n % out_n == 0).
    """
    check_choice(func_name, "padding", padding, PADDING_MODES)
    if padding != "exact":
        return
    big, small = (out_n, in_n) if what == "out_n" else (in_n, out_n)
    if big % small:
        raise ValueError(
            f"{func_name}: padding='exact' requires {what}={big} to be a whole "
            f"multiple of the bus width {small}, but {big} % {small} == {big % small}. "
            f"Use padding='pad' (the default -- the final beat's `keep` carries the "
            f"true element count, so nothing is lost) or change the bus width."
        )


def buffer_len(in_n: int, out_n: int) -> int:
    """Element capacity of the shared serializer/deserializer buffer.

    `in_n + out_n - 1` is the exact size that makes "there is room for one more
    input beat" and "the buffer does not already hold a whole output beat" the
    SAME condition:

        nbase + in_n <= buf_n   <=>   nbase <= out_n - 1   <=>   nbase < out_n

    so both modules' `ready` collapses to one comparison against a constant,
    with no separate full/empty flag. It is also exactly the room needed for
    the deserializer's unconditional keep-agnostic lane writes (see
    `deserializer.py`'s module docstring).
    """
    return in_n + out_n - 1


def counter_t(in_n: int, out_n: int):
    """Fill-count type: wide enough to hold buffer_len(in_n, out_n) itself.

    Sized from the actual buffer length rather than a fixed width -- the old
    macros hardcoded `uint16_t` counters (`serializer_counter_t`,
    `deserializer_counter_t`, `axis_max_len_limiter_count_t`), which both wastes
    bits and invites the mismatched-operand-width class of VHDL-only errors that
    native simulation cannot see.
    """
    return make_uint_t(max(1, buffer_len(in_n, out_n).bit_length()))
