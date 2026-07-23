# pyright: reportInvalidTypeForm=none
from pypeline import Feedback, NamedTuple, uint1_t

from interface.interface import (
    interface,
    make_interface_feedback_type,
    make_interface_type,
)


def make_stream_interface(data_t, feedback_t=uint1_t):
    """The valid/ready streaming interface over `data_t`.

    `data` + `valid` travel feedforward; `ready` is the reverse channel. This is
    the most common use of `@interface`, not a special case of it -- see
    `include/pypeline/interface/interface.py` for the general mechanism.

    `feedback_t` defaults to `uint1_t` (the usual ready bit); a stream whose
    backpressure is wider (a credit count, a struct of flags) sets it here.

    A module declares its ports with the two derived halves:

        stream_if = make_stream_interface(uint32_t)
        s_t  = make_interface_type(stream_if)           # {data, valid}
        s_fb_t = make_interface_feedback_type(stream_if)  # {ready}

    An input port puts `s_t` in an arg and `s_fb_t` in a return field of the same
    name; an output port does the reverse.
    """

    @interface
    class stream_if(NamedTuple):
        data: data_t
        valid: uint1_t
        ready: Feedback[feedback_t]

    return stream_if


def make_stream_t(data_t, feedback_t=uint1_t):
    """The feedforward half (`{data, valid}`) of `make_stream_interface(...)`.

    Convenience for code that only carries the forward direction (e.g. a value
    built and passed along); a module that needs backpressure should take the
    interface's two halves as ports instead.

    Usage:
        axis32_t = make_stream_t(axis32_fragment_t)
    """
    return make_interface_type(make_stream_interface(data_t, feedback_t))
