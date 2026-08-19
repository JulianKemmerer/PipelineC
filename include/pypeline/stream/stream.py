# pyright: reportInvalidTypeForm=none
from pypeline import (
    Feedback,
    NamedTuple,
    _ctype_str,
    _exec_generated_func,
    _finalize_hw_name,
    cast,
    register_lazy_cast,
    struct,
    uint1_t,
)

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

    A module declares its ports off the interface directly -- never re-aliased
    to a shorter local name, so a reader can always tell a paired port half
    from a standalone stream type by the name alone:

        stream_intrf = make_stream_interface(uint32_t)
        stream_intrf.fwd_t    # {stream: {data, valid}}
        stream_intrf.fb_t     # {ready}
        stream_intrf.stream_t # {data, valid} -- the plain type nested at .fwd_t.stream

    An input port puts `stream_intrf.fwd_t` in an arg and `stream_intrf.fb_t`
    in a return field of the same name (ending in `_if`); an output port does
    the reverse. Field access on a real port is `port.stream.data` /
    `port.stream.valid` (not `port.data` -- that flat shape is reserved for a
    standalone `make_stream_t(data_t)` value).

    Both halves cast to/from their plain payload (see `pypeline_DESIGN.md`'s
    Casting section) -- `stream_intrf.fwd_t(some_stream_t_value)` and
    `stream_intrf.fb_t(some_feedback_t_value)` (and the reverse,
    `stream_intrf.stream_t(some_fwd_t_value)` / `feedback_t(some_fb_t_value)`)
    all work once this factory has run, without any extra call: registered
    lazily by `_register_stream_casts`, below, so the generated conversion
    functions (and the VHDL entity each produces) are only built the first
    time a design actually casts this particular interface.
    """

    @interface
    class stream_intrf(NamedTuple):
        stream: make_stream_t(data_t)
        ready: Feedback[feedback_t]

    _register_stream_casts(stream_intrf, feedback_t)
    return stream_intrf


def _register_stream_casts(intrf, feedback_t):
    """Register `intrf`'s wrap/unwrap casts, both directions:
    `stream_t <-> .fwd_t` (field `stream`) and `feedback_t <-> .fb_t` (field
    `ready`) -- so e.g. `intrf.fb_t(some_ready_value)` and
    `intrf.fwd_t(some_stream_value)` work as casts, dropping the field name a
    keyword struct-init would otherwise require (both halves have exactly
    one field, so the name carries no information), symmetrically with the
    unwrap direction (`intrf.stream_t(some_fwd_value)`,
    `feedback_t(some_fb_value)`).

    Lazy (register_lazy_cast, not register_cast): the four generated @cast
    functions -- and the one VHDL entity each produces -- are only built the
    first time a design actually casts THIS PARTICULAR interface, not at
    make_stream_interface() call time. Every existing design/test that builds
    a stream interface but never casts it (the overwhelming majority) pays
    nothing.
    """
    stream_t = intrf.stream_t
    fwd_t = intrf.fwd_t
    fb_t = intrf.fb_t
    built = {}

    def _build_all():
        if built:
            return
        built.update(
            _build_wrap_unwrap_cast_pair(
                "fwd", stream_t, fwd_t, "stream", stream_t._pypeline_ctype_name
            )
        )
        if fb_t is not None:
            built.update(
                _build_wrap_unwrap_cast_pair(
                    "fb", feedback_t, fb_t, "ready", _ctype_str(feedback_t)
                )
            )

    def _thunk(key):
        def build():
            _build_all()
            return built[key]

        return build

    register_lazy_cast(stream_t, fwd_t, _thunk("wrap"))
    register_lazy_cast(fwd_t, stream_t, _thunk("unwrap"))
    if fb_t is not None:
        register_lazy_cast(feedback_t, fb_t, _thunk("wrap_fb"))
        register_lazy_cast(fb_t, feedback_t, _thunk("unwrap_fb"))


def _build_wrap_unwrap_cast_pair(tag, plain_t, half_t, field, plain_t_str):
    """Generate and exec() the wrap (`plain_t -> half_t`) and unwrap
    (`half_t -> plain_t`) @cast functions for one interface half (`fwd_t` or
    `fb_t`, distinguished by `tag` only for entity-name/dict-key uniqueness
    -- `field` is the half's sole field name, `stream` or `ready`).

    Entity names are a pure function of the source/destination canonical
    type names (project canonical-name determinism): two independently
    derived interfaces with identical field types produce identical cast
    entity names, and repeated make_stream_interface(T) calls -- which
    memoize the SAME derived fwd_t/fb_t per @interface's own
    _pypeline_iface_derived cache -- never re-generate distinct ones.
    """
    half_t_str = half_t._pypeline_ctype_name
    wrap_name = _finalize_hw_name(f"cast_{half_t_str}_from_{plain_t_str}_{tag}")
    unwrap_name = _finalize_hw_name(f"cast_{plain_t_str}_from_{half_t_str}_{tag}")

    wrap_src = f"""
@cast
def {wrap_name}(x: plain_t) -> half_t:
    return half_t({field}=x)
"""
    unwrap_src = f"""
@cast
def {unwrap_name}(x: half_t) -> plain_t:
    return x.{field}
"""
    globals_ns = {"cast": cast, "plain_t": plain_t, "half_t": half_t}
    wrap_fn = _exec_generated_func(
        wrap_name, wrap_src, globals_ns, folder="pypeline_generated_casts"
    )
    unwrap_fn = _exec_generated_func(
        unwrap_name, unwrap_src, globals_ns, folder="pypeline_generated_casts"
    )
    key_prefix = "" if tag == "fwd" else "_fb"
    return {f"wrap{key_prefix}": wrap_fn, f"unwrap{key_prefix}": unwrap_fn}
