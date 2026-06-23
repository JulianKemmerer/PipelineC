# pyright: reportInvalidTypeForm=none
from pypeline import hw_func, struct, NamedTuple, Reg, uint1_t, uint8_t, make_uint_t

from kept_data_bus import make_kept_data_bus_t
from ndarray import make_ndarray_fragment_t
from stream.stream import make_stream_t


def make_axis_t(n, elem_t=uint8_t, ndims=1):
    """Composes kept_data_bus_t -> ndarray_fragment_t -> stream_t.

    Only literally AXI-Stream-compliant when elem_t is uint8_t (the default,
    i.e. tdata/tkeep are bytes) — with another elem_t this is the same
    keep-per-lane shape generalized to a per-lane struct stream.

    Usage:
        axis32_t = make_axis_t(4)   # stream(ndarray_fragment(1, kept_data_bus(uint8_t, 4)))
    """
    bus_t = make_kept_data_bus_t(elem_t, n)
    fragment_t = make_ndarray_fragment_t(bus_t, ndims)
    return make_stream_t(fragment_t)


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
    narrow_axis_t = make_stream_t(narrow_frag_t)
    wide_axis_t = make_stream_t(wide_frag_t)
    return (
        narrow_bus_t,
        wide_bus_t,
        narrow_frag_t,
        wide_frag_t,
        narrow_axis_t,
        wide_axis_t,
    )


def make_split_to_chunks(narrow_n, ratio, narrow_axis_t, wide_frag_t):
    """wide_frag_t -> narrow_axis_t[ratio]. Generalizes axis512_to_axis128_array."""
    chunks_t = narrow_axis_t[ratio]

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


def make_assemble_chunks(narrow_n, ratio, narrow_axis_t, wide_frag_t):
    """narrow_axis_t[ratio] -> wide_frag_t. Generalizes axis128_array_to_axis512."""
    chunks_t = narrow_axis_t[ratio]

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
    elem_t is the array element type (here always a narrow_axis_t) — generic and reused
    by both widen and narrow."""
    arr_t = elem_t[n]

    @hw_func
    def shift_into_top(arr: arr_t, new_elem: elem_t) -> arr_t:
        for c in range(n - 1):
            arr[c] = arr[c + 1]
        arr[n - 1] = new_elem
        return arr

    return shift_into_top


def _make_null_chunk(narrow_n, narrow_bus_t, narrow_frag_t, narrow_axis_t):
    """Zero-valued, invalid narrow_axis_t — a compound-init constant, not a bare declare."""
    return narrow_axis_t(
        data=narrow_frag_t(
            frag=narrow_bus_t(data=[0] * narrow_n, keep=[0] * narrow_n),
            eod=[0],
        ),
        valid=0,
    )


def make_dwidth_widen(elem_t, narrow_n, ratio):
    """Combines `ratio` narrow_axis_t beats into one wide_axis_t beat.
    Generalizes axis128_to_axis512. Returns (dwidth_widen, narrow_axis_t, wide_axis_t)."""
    (
        narrow_bus_t,
        wide_bus_t,
        narrow_frag_t,
        wide_frag_t,
        narrow_axis_t,
        wide_axis_t,
    ) = _make_dwidth_types(elem_t, narrow_n, ratio)
    wide_n = narrow_n * ratio
    chunks_t = narrow_axis_t[ratio]

    split_to_chunks = make_split_to_chunks(narrow_n, ratio, narrow_axis_t, wide_frag_t)
    assemble_chunks = make_assemble_chunks(narrow_n, ratio, narrow_axis_t, wide_frag_t)
    shift_into_top = make_shift_into_top(narrow_axis_t, ratio)

    @struct
    class dwidth_widen_result_t(NamedTuple):
        wide_out: wide_axis_t
        narrow_in_ready: uint1_t

    @hw_func
    def dwidth_widen(
        narrow_in: narrow_axis_t, wide_out_ready: uint1_t
    ) -> dwidth_widen_result_t:
        o: dwidth_widen_result_t
        narrow_in_reg: Reg[narrow_axis_t]
        wide_out_reg: Reg[wide_axis_t]

        o.wide_out = wide_out_reg
        if o.wide_out.valid & wide_out_ready:
            wide_out_reg.valid = 0
            for i in range(wide_n):
                wide_out_reg.data.frag.keep[i] = 0
            wide_out_reg.data.eod[0] = 0

        out_reg_ready: uint1_t = ~wide_out_reg.valid
        if narrow_in_reg.valid & out_reg_ready:
            chunks: chunks_t = split_to_chunks(wide_out_reg.data)
            chunks = shift_into_top(chunks, narrow_in_reg)
            last_cycle: uint1_t = narrow_in_reg.data.eod[0]
            narrow_in_reg.valid = 0
            for i in range(narrow_n):
                narrow_in_reg.data.frag.keep[i] = 0
            narrow_in_reg.data.eod[0] = 0
            if last_cycle:
                null_chunk: narrow_axis_t = _make_null_chunk(
                    narrow_n, narrow_bus_t, narrow_frag_t, narrow_axis_t
                )
                for i in range(ratio - 1):
                    if ~chunks[0].valid:
                        chunks = shift_into_top(chunks, null_chunk)
            wide_out_reg.data = assemble_chunks(chunks)
            wide_out_reg.valid = chunks[0].valid

        o.narrow_in_ready = ~narrow_in_reg.valid
        if narrow_in.valid & o.narrow_in_ready:
            narrow_in_reg = narrow_in

        return o

    return dwidth_widen, narrow_axis_t, wide_axis_t


def make_dwidth_narrow(elem_t, narrow_n, ratio):
    """Splits one wide_axis_t beat into `ratio` narrow_axis_t beats, one per cycle.
    Generalizes axis512_to_axis128. Returns (dwidth_narrow, wide_axis_t, narrow_axis_t)."""
    (
        narrow_bus_t,
        wide_bus_t,
        narrow_frag_t,
        wide_frag_t,
        narrow_axis_t,
        wide_axis_t,
    ) = _make_dwidth_types(elem_t, narrow_n, ratio)
    wide_n = narrow_n * ratio
    chunks_t = narrow_axis_t[ratio]

    split_to_chunks = make_split_to_chunks(narrow_n, ratio, narrow_axis_t, wide_frag_t)
    assemble_chunks = make_assemble_chunks(narrow_n, ratio, narrow_axis_t, wide_frag_t)
    shift_into_top = make_shift_into_top(narrow_axis_t, ratio)

    @struct
    class dwidth_narrow_result_t(NamedTuple):
        narrow_out: narrow_axis_t
        wide_in_ready: uint1_t

    @hw_func
    def dwidth_narrow(
        wide_in: wide_axis_t, narrow_out_ready: uint1_t
    ) -> dwidth_narrow_result_t:
        o: dwidth_narrow_result_t
        wide_in_reg: Reg[wide_axis_t]
        narrow_out_reg: Reg[narrow_axis_t]

        o.narrow_out = narrow_out_reg
        if o.narrow_out.valid & narrow_out_ready:
            narrow_out_reg.valid = 0
            for i in range(narrow_n):
                narrow_out_reg.data.frag.keep[i] = 0
            narrow_out_reg.data.eod[0] = 0

        out_reg_ready: uint1_t = ~narrow_out_reg.valid
        if wide_in_reg.valid & out_reg_ready:
            chunks: chunks_t = split_to_chunks(wide_in_reg.data)
            narrow_out_reg = chunks[0]
            null_chunk: narrow_axis_t = _make_null_chunk(
                narrow_n, narrow_bus_t, narrow_frag_t, narrow_axis_t
            )
            chunks = shift_into_top(chunks, null_chunk)
            wide_in_reg.data = assemble_chunks(chunks)
            if ~chunks[0].valid:
                wide_in_reg.valid = 0
                for i in range(wide_n):
                    wide_in_reg.data.frag.keep[i] = 0
                wide_in_reg.data.eod[0] = 0

        o.wide_in_ready = ~wide_in_reg.valid
        if wide_in.valid & o.wide_in_ready:
            wide_in_reg = wide_in

        return o

    return dwidth_narrow, wide_axis_t, narrow_axis_t
