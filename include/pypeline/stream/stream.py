# pyright: reportInvalidTypeForm=none
from pypeline import Feedback, NamedTuple, struct, uint1_t

from interface.interface import interface


def make_stream_t(data_t):
    """A plain `{data, valid}` struct -- no `@interface` involved, no `ready`/
    reverse half at all, ever. A valid-only stream doesn't need an interface to
    define itself; it's just data + a valid bit.

    Convenience for code that only ever carries the forward direction (e.g. a
    value built and passed along with no backpressure). A module that needs
    backpressure should build `make_stream_interface(...)` instead and take its
    `.fwd_t`/`.fb_t` halves as a matched pair of ports.

    `make_stream_interface(data_t).fwd_t` nests this exact type as its `.stream`
    field (`{stream: make_stream_t(data_t), ready: Feedback[...]}`), so crossing
    between a valid-only value and a with-ready port's data+valid half is a
    single `.stream` field access/assignment -- never a per-field copy.

    Usage:
        axis32_t = make_stream_t(axis32_fragment_t)
    """

    @struct
    class stream_t(NamedTuple):
        data: data_t
        valid: uint1_t

    return stream_t


def make_stream_interface(data_t, feedback_t=uint1_t):
    """The valid/ready streaming interface over `data_t`.

    The forward field nests a plain `make_stream_t(data_t)` rather than
    re-declaring `data`/`valid` itself, so the with-ready interface's forward
    half and a standalone valid-only stream are never two independently-shaped
    twins requiring a field-by-field conversion -- the with-ready side's data+
    valid IS a `make_stream_t(data_t)` value, accessed through `.stream`.
    `ready` is the reverse channel. This is the most common use of `@interface`,
    not a special case of it -- see `include/pypeline/interface/interface.py`
    for the general mechanism.

    `feedback_t` defaults to `uint1_t` (the usual ready bit); a stream whose
    backpressure is wider (a credit count, a struct of flags) sets it here.

    A module declares its ports with the two derived halves:

        stream_intrf = make_stream_interface(uint32_t)
        s_t    = stream_intrf.fwd_t   # {stream: {data, valid}}
        s_fb_t = stream_intrf.fb_t    # {ready}

    An input port puts `s_t` in an arg and `s_fb_t` in a return field of the same
    name (ending in `_if`); an output port does the reverse. Field access on a
    real port is `port.stream.data` / `port.stream.valid` (not `port.data` --
    that flat shape is reserved for a standalone `make_stream_t(data_t)` value).
    """

    @interface
    class stream_intrf(NamedTuple):
        stream: make_stream_t(data_t)
        ready: Feedback[feedback_t]

    return stream_intrf
