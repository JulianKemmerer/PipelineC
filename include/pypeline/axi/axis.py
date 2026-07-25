# pyright: reportInvalidTypeForm=none
from pypeline import hw_func, struct, NamedTuple, Reg, uint1_t, uint8_t, make_uint_t

from kept_data_bus import make_kept_data_bus_t
from ndarray import make_ndarray_fragment_t
from stream.stream import make_stream_interface, make_stream_t


def make_axis_interface(n, elem_t=uint8_t, ndims=1):
    """Composes kept_data_bus_t -> ndarray_fragment_t -> the stream interface.

    Only literally AXI-Stream-compliant when elem_t is uint8_t (the default,
    i.e. tdata/tkeep are bytes) — with another elem_t this is the same
    keep-per-lane shape generalized to a per-lane struct stream.

    Usage:
        axis32_intrf = make_axis_interface(4)
        axis32_intrf.fwd_t   # {stream: {data, valid}}
        axis32_intrf.fb_t    # {ready}
    """
    bus_t = make_kept_data_bus_t(elem_t, n)
    fragment_t = make_ndarray_fragment_t(bus_t, ndims)
    return make_stream_interface(fragment_t)


def make_axis_t(n, elem_t=uint8_t, ndims=1):
    """A genuinely one-directional (valid-only) axis stream: `{data, valid}`
    with no `ready`/reverse half. See `stream.make_stream_t` -- this is that
    over the same fragment type `make_axis_interface(...)` composes from.

    Usage:
        axis32_t = make_axis_t(4)
    """
    bus_t = make_kept_data_bus_t(elem_t, n)
    fragment_t = make_ndarray_fragment_t(bus_t, ndims)
    return make_stream_t(fragment_t)


def make_axis_broadcast_interlock(axis_intrf, n):
    """Combinatorially broadcasts one axis stream to n sink streams.

    Named 'interlock' rather than 'fork' because it is pure combinational
    valid/ready interlocking (no buffering/registers): the source is ready
    only when every sink is ready, and each sink sees valid=1 only once
    every sink can accept the transfer (or is already not ready itself,
    since no transfer happens on it anyway that cycle).

    `axis_out` is an *array* port: one interface per sink, each independently
    back-pressured. Inside an interface function the whole thing is implied —
    `bcast = broadcast(src)` then handing `bcast.axis_out[i]` to each sink is
    the entire wiring.

    Returns (axis_broadcast_interlock, axis_broadcast_interlock_t):
        axis_broadcast_interlock(axis_in_if: axis_intrf.fwd_t, axis_out_if: axis_intrf.fb_t[n])
            -> axis_broadcast_interlock_t
        axis_broadcast_interlock_t fields:
          .axis_out_if (axis_intrf.fwd_t[n]) - one forked copy of axis_in_if per sink
          .axis_in_if  (axis_intrf.fb_t)   - reverse half of the source port
    """
    @struct
    class axis_broadcast_interlock_t(NamedTuple):
        axis_out_if: axis_intrf.fwd_t[n]
        axis_in_if: axis_intrf.fb_t

    @hw_func
    def axis_broadcast_interlock(
        axis_in_if: axis_intrf.fwd_t, axis_out_if: axis_intrf.fb_t[n]
    ) -> axis_broadcast_interlock_t:
        o: axis_broadcast_interlock_t
        all_sinks_ready: uint1_t = 1
        for i in range(n):
            all_sinks_ready = all_sinks_ready & axis_out_if[i].ready
        for i in range(n):
            out_i: axis_intrf.fwd_t = axis_in_if
            out_i.stream.valid = 0
            if all_sinks_ready | ~axis_out_if[i].ready:
                out_i.stream.valid = axis_in_if.stream.valid
            o.axis_out_if[i] = out_i
        o.axis_in_if.ready = all_sinks_ready
        return o

    axis_broadcast_interlock.axis_intrf = axis_intrf
    axis_broadcast_interlock.fwd_t = axis_intrf.fwd_t
    axis_broadcast_interlock.fb_t = axis_intrf.fb_t
    return axis_broadcast_interlock, axis_broadcast_interlock_t


def make_keep_count(bus_t, n):
    """Hardware function: popcount of .keep over n lanes."""
    count_t = make_uint_t(n.bit_length())

    def keep_count(lanes: bus_t) -> count_t:
        rv: count_t = 0
        for i in range(n):
            rv = rv + lanes.keep[i]
        return rv

    return keep_count


def make_count_to_keep(n):
    """Hardware function: lane count -> thermometer-coded keep[n]
    (lanes [0, count) asserted)."""
    count_t = make_uint_t(n.bit_length())
    keep_t = uint1_t[n]

    @hw_func
    def count_to_keep(count: count_t) -> keep_t:
        rv: keep_t
        for i in range(n):
            rv[i] = i < count
        return rv

    return count_to_keep


def _make_dwidth_types(elem_t, narrow_n, ratio):
    """Shared type construction so widen/narrow build each type exactly once."""
    wide_n = narrow_n * ratio
    narrow_bus_t = make_kept_data_bus_t(elem_t, narrow_n)
    wide_bus_t = make_kept_data_bus_t(elem_t, wide_n)
    narrow_frag_t = make_ndarray_fragment_t(narrow_bus_t, 1)
    wide_frag_t = make_ndarray_fragment_t(wide_bus_t, 1)
    narrow_axis_intrf = make_stream_interface(narrow_frag_t)
    wide_axis_intrf = make_stream_interface(wide_frag_t)
    return (
        narrow_bus_t,
        wide_bus_t,
        narrow_frag_t,
        wide_frag_t,
        narrow_axis_intrf,
        wide_axis_intrf,
    )


def make_split_to_chunks(narrow_n, ratio, narrow_chunk_t, wide_frag_t):
    """wide_frag_t -> narrow_chunk_t[ratio]. Generalizes axis512_to_axis128_array.

    `narrow_chunk_t` is plain valid-only data (e.g. `stream.make_stream_t(...)`),
    not a real port -- this is a purely combinational data-reshuffling helper,
    not a stream endpoint, so it never pairs with a reverse half."""
    chunks_t = narrow_chunk_t[ratio]

    @hw_func
    def split_to_chunks(wide: wide_frag_t) -> chunks_t:
        chunks: chunks_t
        for c in range(ratio):
            for b in range(narrow_n):
                chunks[c].data.frag.data[b] = wide.frag.data[c * narrow_n + b]
                chunks[c].data.frag.keep[b] = wide.frag.keep[c * narrow_n + b]
            chunks[c].data.eod[0] = 0
            chunks[c].valid = wide.frag.keep[c * narrow_n]
        chunks[ratio - 1].data.eod[0] = wide.eod[0]
        for c in range(ratio - 1):
            next_chunk_is_empty: uint1_t = ~chunks[c + 1].valid
            chunks[c].data.eod[0] = wide.eod[0] & next_chunk_is_empty
        return chunks

    return split_to_chunks


def make_assemble_chunks(narrow_n, ratio, narrow_chunk_t, wide_frag_t):
    """narrow_chunk_t[ratio] -> wide_frag_t. Generalizes axis128_array_to_axis512.

    `narrow_chunk_t` is plain valid-only data, not a real port -- see
    `make_split_to_chunks`."""
    chunks_t = narrow_chunk_t[ratio]

    @hw_func
    def assemble_chunks(chunks: chunks_t) -> wide_frag_t:
        wide: wide_frag_t
        wide.eod[0] = 0
        for c in range(ratio):
            wide.eod[0] = wide.eod[0] | (chunks[c].valid & chunks[c].data.eod[0])
            for b in range(narrow_n):
                wide.frag.data[c * narrow_n + b] = chunks[c].data.frag.data[b]
                wide.frag.keep[c * narrow_n + b] = (
                    chunks[c].valid & chunks[c].data.frag.keep[b]
                )
        return wide

    return assemble_chunks


def make_shift_into_top(elem_t, n):
    """arr: elem_t[n], new_elem: elem_t -> elem_t[n]. Generalizes ARRAY_1SHIFT_INTO_TOP.
    elem_t is the array element type (here always a valid-only narrow chunk type) —
    generic and reused by both widen and narrow."""
    arr_t = elem_t[n]

    @hw_func
    def shift_into_top(arr: arr_t, new_elem: elem_t) -> arr_t:
        for c in range(n - 1):
            arr[c] = arr[c + 1]
        arr[n - 1] = new_elem
        return arr

    return shift_into_top


def _make_null_chunk(narrow_n, narrow_bus_t, narrow_frag_t, narrow_chunk_t):
    """Zero-valued, invalid narrow_chunk_t — a compound-init constant, not a bare declare."""
    return narrow_chunk_t(
        data=narrow_frag_t(
            frag=narrow_bus_t(data=[0] * narrow_n, keep=[0] * narrow_n),
            eod=[0],
        ),
        valid=0,
    )


def make_dwidth_widen(elem_t, narrow_n, ratio):
    """Combines `ratio` narrow beats into one wide beat.
    Generalizes axis128_to_axis512. Returns (dwidth_widen, narrow_axis_intrf.fwd_t, wide_axis_intrf.fwd_t);
    the interfaces and reverse halves hang off the function as
    `.narrow_in_intrf` / `.wide_out_intrf` / `.narrow_in_fb_t` / `.wide_out_fb_t`."""
    (
        narrow_bus_t,
        wide_bus_t,
        narrow_frag_t,
        wide_frag_t,
        narrow_axis_intrf,
        wide_axis_intrf,
    ) = _make_dwidth_types(elem_t, narrow_n, ratio)
    # narrow_axis_intrf.stream_t is exactly make_stream_t(narrow_frag_t) --
    # split_to_chunks/assemble_chunks/shift_into_top are purely combinational,
    # not stream ports, so they work on that plain valid-only chunk type
    # directly (a real port's `.stream` field IS one, no conversion needed).
    narrow_chunk_t = make_stream_t(narrow_frag_t)
    wide_n = narrow_n * ratio
    chunks_t = narrow_chunk_t[ratio]

    split_to_chunks = make_split_to_chunks(narrow_n, ratio, narrow_chunk_t, wide_frag_t)
    assemble_chunks = make_assemble_chunks(narrow_n, ratio, narrow_chunk_t, wide_frag_t)
    shift_into_top = make_shift_into_top(narrow_chunk_t, ratio)

    @struct
    class dwidth_widen_result_t(NamedTuple):
        wide_out_if: wide_axis_intrf.fwd_t
        narrow_in_if: narrow_axis_intrf.fb_t

    @hw_func
    def dwidth_widen(
        narrow_in_if: narrow_axis_intrf.fwd_t, wide_out_if: wide_axis_intrf.fb_t
    ) -> dwidth_widen_result_t:
        o: dwidth_widen_result_t
        narrow_in_reg: Reg[narrow_axis_intrf.fwd_t]
        wide_out_reg: Reg[wide_axis_intrf.fwd_t]

        o.wide_out_if = wide_out_reg
        if o.wide_out_if.stream.valid & wide_out_if.ready:
            wide_out_reg.stream.valid = 0
            for i in range(wide_n):
                wide_out_reg.stream.data.frag.keep[i] = 0
            wide_out_reg.stream.data.eod[0] = 0

        out_reg_ready: uint1_t = ~wide_out_reg.stream.valid
        if narrow_in_reg.stream.valid & out_reg_ready:
            chunks: chunks_t = split_to_chunks(wide_out_reg.stream.data)
            chunks = shift_into_top(chunks, narrow_in_reg.stream)
            last_cycle: uint1_t = narrow_in_reg.stream.data.eod[0]
            narrow_in_reg.stream.valid = 0
            for i in range(narrow_n):
                narrow_in_reg.stream.data.frag.keep[i] = 0
            narrow_in_reg.stream.data.eod[0] = 0
            if last_cycle:
                null_chunk: narrow_chunk_t = _make_null_chunk(
                    narrow_n, narrow_bus_t, narrow_frag_t, narrow_chunk_t
                )
                for i in range(ratio - 1):
                    if ~chunks[0].valid:
                        chunks = shift_into_top(chunks, null_chunk)
            wide_out_reg.stream.data = assemble_chunks(chunks)
            wide_out_reg.stream.valid = chunks[0].valid

        o.narrow_in_if.ready = ~narrow_in_reg.stream.valid
        if narrow_in_if.stream.valid & o.narrow_in_if.ready:
            narrow_in_reg = narrow_in_if

        return o

    dwidth_widen.narrow_in_intrf = narrow_axis_intrf
    dwidth_widen.wide_out_intrf = wide_axis_intrf
    dwidth_widen.narrow_in_fb_t = narrow_axis_intrf.fb_t
    dwidth_widen.wide_out_fb_t = wide_axis_intrf.fb_t
    return dwidth_widen, narrow_axis_intrf.fwd_t, wide_axis_intrf.fwd_t


def make_dwidth_narrow(elem_t, narrow_n, ratio):
    """Splits one wide beat into `ratio` narrow beats, one per cycle.
    Generalizes axis512_to_axis128. Returns (dwidth_narrow, wide_axis_intrf.fwd_t, narrow_axis_intrf.fwd_t);
    the interfaces and reverse halves hang off the function as
    `.wide_in_intrf` / `.narrow_out_intrf` / `.wide_in_fb_t` / `.narrow_out_fb_t`."""
    (
        narrow_bus_t,
        wide_bus_t,
        narrow_frag_t,
        wide_frag_t,
        narrow_axis_intrf,
        wide_axis_intrf,
    ) = _make_dwidth_types(elem_t, narrow_n, ratio)
    # See make_dwidth_widen.
    narrow_chunk_t = make_stream_t(narrow_frag_t)
    wide_n = narrow_n * ratio
    chunks_t = narrow_chunk_t[ratio]

    split_to_chunks = make_split_to_chunks(narrow_n, ratio, narrow_chunk_t, wide_frag_t)
    assemble_chunks = make_assemble_chunks(narrow_n, ratio, narrow_chunk_t, wide_frag_t)
    shift_into_top = make_shift_into_top(narrow_chunk_t, ratio)

    @struct
    class dwidth_narrow_result_t(NamedTuple):
        narrow_out_if: narrow_axis_intrf.fwd_t
        wide_in_if: wide_axis_intrf.fb_t

    @hw_func
    def dwidth_narrow(
        wide_in_if: wide_axis_intrf.fwd_t, narrow_out_if: narrow_axis_intrf.fb_t
    ) -> dwidth_narrow_result_t:
        o: dwidth_narrow_result_t
        wide_in_reg: Reg[wide_axis_intrf.fwd_t]
        narrow_out_reg: Reg[narrow_axis_intrf.fwd_t]

        o.narrow_out_if = narrow_out_reg
        if o.narrow_out_if.stream.valid & narrow_out_if.ready:
            narrow_out_reg.stream.valid = 0
            for i in range(narrow_n):
                narrow_out_reg.stream.data.frag.keep[i] = 0
            narrow_out_reg.stream.data.eod[0] = 0

        out_reg_ready: uint1_t = ~narrow_out_reg.stream.valid
        if wide_in_reg.stream.valid & out_reg_ready:
            chunks: chunks_t = split_to_chunks(wide_in_reg.stream.data)
            narrow_out_reg.stream = chunks[0]
            null_chunk: narrow_chunk_t = _make_null_chunk(
                narrow_n, narrow_bus_t, narrow_frag_t, narrow_chunk_t
            )
            chunks = shift_into_top(chunks, null_chunk)
            wide_in_reg.stream.data = assemble_chunks(chunks)
            if ~chunks[0].valid:
                wide_in_reg.stream.valid = 0
                for i in range(wide_n):
                    wide_in_reg.stream.data.frag.keep[i] = 0
                wide_in_reg.stream.data.eod[0] = 0

        o.wide_in_if.ready = ~wide_in_reg.stream.valid
        if wide_in_if.stream.valid & o.wide_in_if.ready:
            wide_in_reg = wide_in_if

        return o

    dwidth_narrow.wide_in_intrf = wide_axis_intrf
    dwidth_narrow.narrow_out_intrf = narrow_axis_intrf
    dwidth_narrow.wide_in_fb_t = wide_axis_intrf.fb_t
    dwidth_narrow.narrow_out_fb_t = narrow_axis_intrf.fb_t
    return dwidth_narrow, wide_axis_intrf.fwd_t, narrow_axis_intrf.fwd_t
