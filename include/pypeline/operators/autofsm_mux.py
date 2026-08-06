"""Operand multiplexers for AUTOFSM's shared functional units.

A shared functional unit runs a different operation in each state, so every one
of its input ports needs a multiplexer selecting which state's operand reaches
it. This is the price of resource sharing, and past some granularity it is what
stops sharing from paying -- so AUTOFSM needs the mux to be (a) built the way
that synthesizes best and (b) a REAL entity whose delay and area can be
measured rather than guessed at.

Hence this module rather than an if/elif chain emitted inline into the generated
FSM source:

  * ARRAY-INDEXED, NOT A PRIORITY CHAIN. `choices[sel]` elaborates to the
    elaborator's balanced binary VAR_REF_RD selection tree. A chain of nested
    if/elif muxes is a PRIORITY structure: N-1 muxes deep, delay linear in the
    fold count. The tree is log2(N) deep. Same function, strictly better QoR --
    and the difference grows exactly as sharing gets more aggressive, which is
    the regime AUTOFSM's area sweep pushes into.

  * ONE ENTITY PER (element type, fold count). The factory is memoized, so one
    shape is one canonical entity name -- a pure function of (type, n), stable
    across the driver's repeated re-elaborations. That stability is what lets
    its measured delay be cached on disk and reused build after build.

  * LIVES IN include/pypeline/operators/. Not because it is an operator
    overload, but because SYN._IS_PYPELINE_OPERATOR_LIBRARY_CODE treats
    everything under this directory as shipped library code rather than user
    code -- which is exactly what makes a measured delay eligible for
    path_delay_cache. A mux shape measured once is measured for good.

The entity AUTOFSM measures IS the entity AUTOFSM instantiates: the generated
FSM calls the very same memoized hw_func whose delay the scheduler read.
"""
from pypeline import hw_func, make_uint_t

# (element ctype name, n) -> memoized hw_func. Module-level so one shape is one
# callable identity for the whole process: AUTOFSM reverse-looks-up the entity
# name a callable was elaborated under (via parser_state.pypeline_entity_callables)
# to find its measured delay, and that only works if the object is the same one.
_MUX_CACHE = {}


def mux_sel_t(n: int):
    """Selector type for an n-way mux: just wide enough to index it."""
    return make_uint_t(max(1, (max(2, int(n)) - 1).bit_length()))


def make_operand_mux(t, n: int):
    """n-way multiplexer over values of type `t`, selected by a small index.

    n must be >= 2 -- a single-user port needs no mux at all, and AUTOFSM wires
    it directly rather than paying for a one-input array.
    """
    n = int(n)
    if n < 2:
        raise ValueError(f"make_operand_mux: n must be >= 2, got {n}")
    import pypeline

    key = (pypeline.ctype_name(t), n)
    cached = _MUX_CACHE.get(key)
    if cached is not None:
        return cached

    choices_t = t[n]
    sel_t = mux_sel_t(n)

    @hw_func
    def autofsm_operand_mux(sel: sel_t, choices: choices_t) -> t:
        return choices[sel]

    _MUX_CACHE[key] = autofsm_operand_mux
    return autofsm_operand_mux
