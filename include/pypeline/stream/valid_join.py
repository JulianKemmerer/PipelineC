"""Bounded, completion-driven join of ordered valid-only result streams.

Every input must supply one word per transaction, in the same order. Each
branch has its own FWFT FIFO; a result is emitted only when every head is
present, and all heads are consumed together. This retains early responses
as well as early metadata, including a response that precedes FIFO warm-up.

There is no backpressure. Depth bounds the number of unmatched words, rather
than specifying any component's latency. Overflow is sticky and asserted in
simulation, since losing one word destroys transaction pairing until reset.
Reset blocks writes/output and drains all FIFOs; hold it long enough to drain
the queues and the upstream pipelines. Clock-enable pauses freeze everything.
"""

import hashlib

import pypeline as py
from fifo import make_fifo


def make_valid_join(data_ts, depth=32):
    """Return (join, joined_t).

    join(data0, valid0, data1, valid1, ..., rst) ->
        joined_t{p0, p1, ..., valid, overflow}

    The downstream consumer always accepts results. The join can emit one
    registered result per enabled clock. The output register cuts paths from
    FIFO RAM into downstream arithmetic. `depth` is each FIFO's memory depth;
    make_fifo rounds it up to a power of two and adds a separate output word.
    """
    data_ts = tuple(data_ts)
    if len(data_ts) < 2:
        raise ValueError("make_valid_join: at least two branches are required")
    if depth < 2:
        raise ValueError("make_valid_join: depth must be at least two")
    signature = "|".join(py.ctype_name(t) for t in data_ts) + f"|depth={depth}"
    suffix = hashlib.sha256(signature.encode()).hexdigest()[:12]
    func_name = f"valid_join_h{suffix}"
    joined_t = py.struct(
        py.NamedTuple(
            f"joined_t_h{suffix}",
            [(f"p{i}", t) for i, t in enumerate(data_ts)]
            + [("valid", py.uint1_t), ("overflow", py.uint1_t)],
        )
    )
    params = ", ".join(
        f"data{i}: DATA{i}_T, valid{i}: uint1_t" for i in range(len(data_ts))
    )
    lines = [
        "@hw_func",
        f"def {func_name}({params}, rst: uint1_t) -> JOINED_T:",
        "    pop: Feedback[uint1_t]",
        "    dropped: Reg[uint1_t]",
        "    result: Reg[JOINED_T]",
        "    o: JOINED_T = result",
        "    n: JOINED_T",
    ]
    ns = dict(
        hw_func=py.hw_func,
        Feedback=py.Feedback,
        Reg=py.Reg,
        uint1_t=py.uint1_t,
        sim_assert=py.sim_assert,
        JOINED_T=joined_t,
    )
    for i, data_t in enumerate(data_ts):
        fifo, _ = make_fifo(data_t, depth)
        ns[f"DATA{i}_T"] = data_t
        ns[f"FIFO{i}"] = fifo
        lines += [
            f"    f{i} = FIFO{i}(pop, data{i}, valid{i} & ~rst)",
            f"    n.p{i} = f{i}.data_out",
            f"    lost{i}: uint1_t = valid{i} & ~rst & ~f{i}.data_in_ready",
        ]
    present = " & ".join(f"f{i}.data_out_valid" for i in range(len(data_ts)))
    lost = " | ".join(f"lost{i}" for i in range(len(data_ts)))
    lines += [
        f"    complete: uint1_t = {present}",
        "    pop = complete | rst",
        "    n.valid = complete & ~rst",
        f"    if {lost}:",
        "        dropped = 1",
        "    if rst:",
        "        dropped = 0",
        "    n.overflow = dropped",
        "    result = n",
        "    o.valid = o.valid & ~rst",
        "    o.overflow = dropped",
        '    sim_assert(~dropped, "valid_join: unmatched-result FIFO overflow")',
        "    return o",
    ]
    join = py._exec_generated_func(
        func_name, "\n".join(lines) + "\n", ns, folder="stream"
    )
    join.out_t = joined_t
    join.depth = depth
    join._sim_clocked_pipeline_boundary = True
    return join, joined_t
