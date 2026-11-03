"""Each AUTO_FSM call site's decode estimate and persistent search reuse depend
only on its own inputs: another call site's decode shapes, an edit to another
call site's function or to a function no call site uses, and which call site
was searched first leave a call site's estimate, search digest and recorded
reads unchanged, while anything its search reads changes them.

The fixture has two call sites in two files and a function neither uses.
Adders are given 3 ns, so at 200 MHz each state holds one add: call site A
(two chained adds) gets two states and 2-way selects, B (four) four states and
4-way selects. No synthesis runs."""

import contextlib
import json
import os
import pickle
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

# Standalone compiler imports; tests write only under the runner's TMPDIR.
sys.path[:0] = [
    str(Path(__file__).resolve().parents[3]),
    str(Path(__file__).resolve().parents[4] / "include" / "pypeline"),
]
# The fixture is edited in place within one second; a cached bytecode file
# that matches the old size and time would run the old source.
sys.dont_write_bytecode = True

import AUTO
import AUTO_FSM
import PY_TO_LOGIC
import SYN
import pypeline

FSM_A_SOURCE = """
from pypeline import AUTO_FSM, INFERRED, NamedTuple, hw_func, register_operator, struct, uint16_t
@struct
class a_in_t(NamedTuple):
    x: uint16_t
    y: uint16_t
    z: uint16_t
@hw_func
def fsm_a_func(v: a_in_t) -> uint16_t:
    s: uint16_t = v.x + v.y
    return s + v.z
register_operator("PLUS", uint16_t, uint16_t, INFERRED, scope=fsm_a_func)
FSM_A = AUTO_FSM(fsm_a_func)
"""

FSM_B_SOURCE = """
from pypeline import AUTO_FSM, INFERRED, NamedTuple, hw_func, register_operator, struct, uint16_t
@struct
class b_in_t(NamedTuple):
    p: uint16_t
    q: uint16_t
    r: uint16_t
    s: uint16_t
    t: uint16_t
@hw_func
def fsm_b_func(v: b_in_t) -> uint16_t:
    a: uint16_t = v.p + v.q
    b: uint16_t = a + v.r
    c: uint16_t = b + v.s
    return c + v.t
register_operator("PLUS", uint16_t, uint16_t, INFERRED, scope=fsm_b_func)
FSM_B = AUTO_FSM(fsm_b_func)
"""

TOP_SOURCE = """
from pypeline import MAIN, hw_func, uint1_t, uint16_t
from fsm_a import FSM_A, a_in_t
from fsm_b import FSM_B, b_in_t
@hw_func
def unrelated(x: uint16_t) -> uint16_t:
    return x ^ 5
@MAIN(200.0)
def top(a: a_in_t, b: b_in_t, valid: uint1_t) -> uint16_t:
    ra: FSM_A.in_stream_t
    ra.data = a
    ra.valid = valid
    rb: FSM_B.in_stream_t
    rb.data = b
    rb.valid = valid
    oa = FSM_A(ra)
    ob = FSM_B(rb)
    return unrelated(oa.data ^ ob.data)
"""

A, B = "fsm_a_func", "fsm_b_func"
# HARVEST_AUTO_FSM_SCHEDULES's request part of the digest for these tests:
# budget scale, carried schedule, area sweep, encoding, forced patterns.
REQUEST = [AUTO_FSM.DEFAULT_BUDGET_SCALE, None, True, "v3", [], []]


def write_design(tmp, b_source=FSM_B_SOURCE, top_source=TOP_SOURCE):
    Path(tmp, "fsm_a.py").write_text(FSM_A_SOURCE)
    Path(tmp, "fsm_b.py").write_text(b_source)
    path = Path(tmp, "top.py")
    path.write_text(top_source)
    return str(path)


def parse(path):
    """A parse with every adder at 3 ns, as a build's measurement would set
    them. Returns (parser, {function name: (key, tag)})."""
    parser = PY_TO_LOGIC.PARSE_FILE(path)
    SYN.PART_SET_TOOL(parser.part)
    for name, logic in parser.FuncLogicLookupTable.items():
        if name.startswith("BIN_OP_PLUS_"):
            logic.delay = 30
    sites = {
        tag.func.__name__: (key, tag) for key, tag in AUTO_FSM.GET_TAGS(parser).items()
    }
    return parser, sites


@contextlib.contextmanager
def compiler_settings(jobs=1, out_dir=None):
    """Run with these -j and output directory, no --syn_cache store, and put
    back what the tests change."""
    saved = (
        SYN.NUM_PROCESSES,
        SYN.SYN_OUTPUT_DIRECTORY,
        SYN.SYNTHESIS_STORE_DIR,
        SYN._COMPILER_SOURCE_HASH,
        SYN.USE_PRIMITIVE_DELAY_MODEL,
    )
    SYN.NUM_PROCESSES = jobs
    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    SYN.SYNTHESIS_STORE_DIR = None
    try:
        yield
    finally:
        (
            SYN.NUM_PROCESSES,
            SYN.SYN_OUTPUT_DIRECTORY,
            SYN.SYNTHESIS_STORE_DIR,
            SYN._COMPILER_SOURCE_HASH,
            SYN.USE_PRIMITIVE_DELAY_MODEL,
        ) = saved
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})


@contextlib.contextmanager
def counted_searches():
    """Yields a list that each area search appends to."""
    searches = []
    real = AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE

    def counting(*args, **kwargs):
        searches.append(args[1])
        return real(*args, **kwargs)

    AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE = counting
    try:
        yield searches
    finally:
        AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE = real


def harvest(parser, key):
    return AUTO_FSM.HARVEST_AUTO_FSM_SCHEDULES(parser, ctl="v3", keys={key})[key]


def stored_record(out_dir, key, digest=None):
    """(path, schedule, reads, found) of the search result stored for `key`:
    the one with `digest`, else the only one."""
    records = []
    for path in sorted(Path(out_dir, "auto_fsm_searches").iterdir()):
        _version, stored_digest, stored_key, schedule, reads, found = pickle.loads(
            zlib.decompress(path.read_bytes())
        )
        if stored_key == key and digest in (None, stored_digest):
            records.append((path, schedule, reads, found))
    assert len(records) == 1, f"{len(records)} search results stored for {key}"
    return records[0]


# ── Decode estimates ──────────────────────────────────────────────────────


def proxy_delays(parser, entities):
    """_measure_entities stand-in: a decode proxy measures 10 du per state
    bit plus its select width, so every shape has a delay of its own."""
    proxies = {
        record["entity"]: record
        for record in parser.pypeline_auto_fsm_control_proxies.values()
    }
    for entity in entities:
        logic = parser.FuncLogicLookupTable[entity]
        record = proxies[entity]
        logic.delay = 10 * record["state_width"] + record["select_width"]
        logic.delay_is_estimated = False
    return parser


def calibrated(order, ctl):
    """{function name: its decode rows} after calibrating the call sites one
    at a time, in `order`."""
    with tempfile.TemporaryDirectory() as tmp, compiler_settings():
        parser, sites = parse(write_design(tmp))
        real = AUTO_FSM._measure_entities
        AUTO_FSM._measure_entities = proxy_delays
        try:
            snapshots = {}
            for name in order:
                key, _tag = sites[name]
                parser, rows = AUTO_FSM._calibrate_controls(
                    parser, {}, ctl, None, keys={key}
                )
                snapshots[name] = rows[key]
        finally:
            AUTO_FSM._measure_entities = real
        return snapshots


def test_each_fsm_select_delay_uses_only_its_own_decode_shapes():
    """A's estimate is the slowest of A's own measured decode shapes. B's
    wider state register and selects decode slower, and must not become A's
    estimate, in either encoding."""
    for ctl in ("v3", "onehot"):
        snapshots = calibrated([A, B], ctl)
        a, b = snapshots[A], snapshots[B]
        assert a and b, (ctl, snapshots)
        assert not set(a) & set(b), (ctl, sorted(a), sorted(b))
        for rows in (a, b):
            assert AUTO_FSM._select_delay(rows, ctl) == max(
                row["delay_du"] for row in rows.values()
            )
        assert AUTO_FSM._select_delay(a, ctl) < AUTO_FSM._select_delay(b, ctl), (
            ctl,
            a,
            b,
        )


def test_another_fsms_proxy_does_not_suppress_own_calibration():
    """A call site calibrated after another one still prepares and measures
    its own decode shapes, so each one's rows are the same in either
    calibration order."""
    for ctl in ("v3", "onehot"):
        assert calibrated([A, B], ctl) == calibrated([B, A], ctl), ctl


# ── Search digests ────────────────────────────────────────────────────────


def digests(path):
    """{function name: its call site's search digest} on a fresh parse."""
    parser, sites = parse(path)
    return {
        name: AUTO_FSM._search_digest(parser, key, tag, REQUEST)
        for name, (key, tag) in sites.items()
    }


def print_build_digests(path, out_dir):
    """Print digests(path) as JSON, with the design's sources frozen as a
    build freezes them (PY_TO_LOGIC.PARSE_FILE_FOR_BUILD). Run in a process
    of its own: freezing lasts for the process."""
    PY_TO_LOGIC.FREEZE_DESIGN_SOURCES(out_dir)
    with compiler_settings():
        print(json.dumps(digests(path)))


def build_digests(path, out_dir):
    """digests(path) as the next build computes them."""
    code = (
        "import auto_fsm_independence_test as t; "
        f"t.print_build_digests({path!r}, {out_dir!r})"
    )
    output = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        check=True,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    ).stdout
    return json.loads(output.strip().splitlines()[-1])


def test_editing_one_fsm_or_unrelated_code_keeps_other_search_digests():
    """Between builds, editing B's function changes B's digest and not A's;
    editing a function no call site uses changes neither. Each build is a
    process of its own, its design sources frozen. The edits keep every line
    where it was, so no generated name moves with a line number."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write_design(tmp)
        out_dir = os.path.join(tmp, "out")
        before = build_digests(path, out_dir)
        write_design(tmp, b_source=FSM_B_SOURCE.replace("c + v.t", "c - v.t"))
        edited_b = build_digests(path, out_dir)
        assert edited_b[A] == before[A]
        assert edited_b[B] != before[B]
        write_design(tmp, top_source=TOP_SOURCE.replace("x ^ 5", "x ^ 6"))
        assert build_digests(path, out_dir) == before


def test_any_input_a_search_reads_changes_its_digest():
    """A's digest changes with a delay or estimated flag of an operation A
    uses, the layout of a struct A reads, A's clock, a delay setting and the
    compiler, and comes back when the change is undone. A delay B alone
    reads is not one of A's inputs."""
    with tempfile.TemporaryDirectory() as tmp, compiler_settings():
        parser, sites = parse(write_design(tmp))
        key, tag = sites[A]

        def digest():
            return AUTO_FSM._search_digest(parser, key, tag, REQUEST)

        first = digest()
        a_entity = AUTO._entity_key_for_callable(parser, tag.func)
        a_uses = AUTO._subtree_entities(parser, a_entity)
        adder = parser.FuncLogicLookupTable[
            next(name for name in sorted(a_uses) if name.startswith("BIN_OP_PLUS_"))
        ]
        layout = parser.struct_to_field_type_dict[pypeline._ctype_str(tag.in_type)]

        def compiler(value):
            SYN._COMPILER_SOURCE_HASH = value

        def primitive_model(value):
            SYN.USE_PRIMITIVE_DELAY_MODEL = value

        hash_before = SYN.COMPILER_SOURCE_HASH()
        model_before = SYN.USE_PRIMITIVE_DELAY_MODEL
        changes = [
            (
                "a delay",
                lambda: setattr(adder, "delay", 31),
                lambda: setattr(adder, "delay", 30),
            ),
            (
                "an estimated flag",
                lambda: setattr(adder, "delay_is_estimated", True),
                lambda: setattr(adder, "delay_is_estimated", False),
            ),
            (
                "a struct layout",
                lambda: layout.__setitem__("z", "uint15_t"),
                lambda: layout.__setitem__("z", "uint16_t"),
            ),
            (
                "the clock",
                # A MAIN's clock sets both its rate and its synthesis-only
                # goal (PY_TO_LOGIC._set_main_clock)
                lambda: (parser.main_mhz.update(top=100.0), parser.main_syn_mhz.update(top=100.0)),
                lambda: (parser.main_mhz.update(top=200.0), parser.main_syn_mhz.update(top=200.0)),
            ),
            (
                "a delay setting",
                lambda: primitive_model(not model_before),
                lambda: primitive_model(model_before),
            ),
            (
                "the compiler",
                lambda: compiler("another compiler"),
                lambda: compiler(hash_before),
            ),
        ]
        for what, change, undo in changes:
            change()
            assert digest() != first, what
            undo()
            assert digest() == first, what + ", undone"
        b_entity = AUTO._entity_key_for_callable(parser, sites[B][1].func)
        b_only = sorted(AUTO._subtree_entities(parser, b_entity) - a_uses)
        assert b_only
        parser.FuncLogicLookupTable[b_only[0]].delay = 7
        assert digest() == first, "a delay only B reads"


# ── What a search reads ───────────────────────────────────────────────────


class RecordingTable(dict):
    """FuncLogicLookupTable that, while `active`, notes each entity read."""

    def __init__(self, table):
        super().__init__(table)
        self.active = False
        self.read = set()

    def __getitem__(self, name):
        if self.active:
            self.read.add(name)
        return dict.__getitem__(self, name)

    def get(self, name, default=None):
        if self.active and dict.__contains__(self, name):
            self.read.add(name)
        return dict.get(self, name, default)

    def items(self):
        if self.active:
            self.read.add("<every entity>")
        return dict.items(self)

    def values(self):
        if self.active:
            self.read.add("<every entity>")
        return dict.values(self)


@contextlib.contextmanager
def recording_search(parser):
    """Swap in a RecordingTable, active only inside each area search; yields it."""
    table = RecordingTable(parser.FuncLogicLookupTable)
    parser.FuncLogicLookupTable = table
    real = AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE

    def recording(*args, **kwargs):
        table.active = True
        try:
            return real(*args, **kwargs)
        finally:
            table.active = False

    AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE = recording
    try:
        yield table
    finally:
        AUTO_FSM.SWEEP_MIN_AREA_SCHEDULE = real


def materialized_by(order, path, out_dir):
    """Entities the area searches in `order` add to a fresh parse's table."""
    parser, sites = parse(path)
    before = set(parser.FuncLogicLookupTable)
    with compiler_settings(out_dir=out_dir):
        for name in order:
            harvest(parser, sites[name][0])
    return set(parser.FuncLogicLookupTable) - before


def test_search_reads_only_its_closure():
    """Every entity that existed before A's search and that the search reads
    is in A's digest (_search_closure) or among what its recorded lookups
    found, though B was searched first. An entity B's search made that A's
    search reads is one A's search makes on its own (-j 1, so every read is
    seen)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write_design(tmp)
        made_by_a = materialized_by([A], path, os.path.join(tmp, "alone"))
        parser, sites = parse(path)
        out_dir = os.path.join(tmp, "out")
        with compiler_settings(out_dir=out_dir):
            parsed = set(parser.FuncLogicLookupTable)
            harvest(parser, sites[B][0])
            made_by_b = set(parser.FuncLogicLookupTable) - parsed
            key, tag = sites[A]
            with recording_search(parser) as table:
                harvest(parser, key)
            closure = set(
                AUTO_FSM._search_closure(
                    parser, AUTO._entity_key_for_callable(parser, tag.func)
                )
            )
            _path, _schedule, _reads, found = stored_record(out_dir, key)
        assert "<every entity>" not in table.read
        found_names = {row[0] for row in found}
        outside = sorted((table.read & parsed) - closure - found_names)
        assert not outside, outside
        assert table.read & made_by_b <= made_by_a, sorted(
            (table.read & made_by_b) - made_by_a
        )


def test_reused_search_checks_the_operand_muxes_it_priced():
    """On a re-parse that builds the scheduled FSMs, their operand muxes are
    measured entities; a search of A records each mux shape it priced with
    the measured delay it found, and a changed measurement is a miss. The
    installed schedules share each FSM's adder (no area search), so A's FSM
    instantiates the 2-way mux A's next search prices."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write_design(tmp)
        parser, sites = parse(path)
        out_dir = os.path.join(tmp, "out")
        with compiler_settings(out_dir=out_dir):
            schedules = AUTO_FSM.HARVEST_AUTO_FSM_SCHEDULES(
                parser, ctl="v3", area_sweep=False
            )
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE(schedules)
            parser, sites = parse(path)
            muxes = sorted(
                AUTO._entity_key_for_callable(parser, fn)
                for fn in parser.pypeline_auto_fsm_mux_callables
            )
            assert muxes, "the scheduled FSMs instantiate no operand mux"
            for name in muxes:
                parser.FuncLogicLookupTable[name].delay = 7
            key, tag = sites[A]
            prev = {key: schedules[key]}
            with recording_search(parser) as table:
                AUTO_FSM.HARVEST_AUTO_FSM_SCHEDULES(
                    parser, prev_schedules=prev, ctl="v3", keys={key}
                )
            digest = AUTO_FSM._search_digest(
                parser, key, tag, [REQUEST[0], prev[key]] + REQUEST[2:]
            )
            _path, _schedule, reads, found = stored_record(out_dir, key, digest)
            measured = {
                shape: du
                for (kind, shape), du in reads.items()
                if kind == "auto_fsm_mux"
            }
            assert 7 in measured.values(), measured
            read_muxes = table.read & set(muxes)
            assert read_muxes, "the search priced no measured mux"
            assert AUTO_FSM._search_reads_unchanged(parser, tag, reads, found)
            for name in read_muxes:
                parser.FuncLogicLookupTable[name].delay = 8
            assert not AUTO_FSM._search_reads_unchanged(parser, tag, reads, found)


def recorded_reads(order, jobs):
    """(reads, found) of A's stored search record after searching the call
    sites in `order` on a fresh parse, at -j `jobs`."""
    with tempfile.TemporaryDirectory() as tmp:
        parser, sites = parse(write_design(tmp))
        out_dir = os.path.join(tmp, "out")
        with compiler_settings(jobs=jobs, out_dir=out_dir):
            for name in order:
                harvest(parser, sites[name][0])
            _path, _schedule, reads, found = stored_record(out_dir, sites[A][0])
        return reads, found


def test_recorded_reads_do_not_depend_on_search_order():
    """A's search records the same reads whether or not B's search ran first
    in the same parse and memoized delays both read: a memo hit replays the
    reads behind it."""
    alone = recorded_reads([A], jobs=1)
    assert alone[0]
    assert recorded_reads([B, A], jobs=1) == alone


def test_recorded_reads_include_forked_workers_reads():
    """At -j 3 the search builds a step's moves in forked workers; its record
    holds their reads too, the same as at -j 1."""
    sizes = []
    real = AUTO_FSM._map_forked

    def counting(fn, items, caches=()):
        sizes.append(len(items))
        return real(fn, items, caches)

    AUTO_FSM._map_forked = counting
    try:
        forked = recorded_reads([A], jobs=3)
    finally:
        AUTO_FSM._map_forked = real
    assert max(sizes) >= 2, f"no step had moves to fork ({sizes})"
    assert forked == recorded_reads([A], jobs=1)


# ── Stored results ────────────────────────────────────────────────────────


def test_search_result_is_stale_when_a_lookup_or_what_it_found_changes():
    """A stored result is reused while each candidate-table lookup finds
    what it found and that entity's graph and numbers are unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        parser, sites = parse(write_design(tmp))
        out_dir = os.path.join(tmp, "out")
        key, tag = sites[A]
        with compiler_settings(out_dir=out_dir):
            harvest(parser, key)
            _path, _schedule, reads, found = stored_record(out_dir, key)
        assert found, "A's search found no candidate"
        assert AUTO_FSM._search_reads_unchanged(parser, tag, reads, found)
        leaf = parser.FuncLogicLookupTable[found[-1][0]]
        saved = leaf.delay
        leaf.delay = 99
        assert not AUTO_FSM._search_reads_unchanged(parser, tag, reads, found)
        leaf.delay = saved
        assert AUTO_FSM._search_reads_unchanged(parser, tag, reads, found)
        (table, lookup), value = next(
            (key_, value)
            for (kind, key_), value in sorted(reads.items(), key=repr)
            if kind == "auto_fsm_lookup" and value is not None
        )
        entries = getattr(parser, table)
        del entries[lookup]
        assert not AUTO_FSM._search_reads_unchanged(parser, tag, reads, found)
        entries[lookup] = value


def test_stale_search_result_is_replaced():
    """A stored result that no longer matches what it read is a miss, and
    the search's new result replaces it, so the next harvest reuses it."""
    with tempfile.TemporaryDirectory() as tmp:
        parser, sites = parse(write_design(tmp))
        out_dir = os.path.join(tmp, "out")
        key, tag = sites[A]
        leaf = Path(tmp, "leaf.delay")
        leaf.write_text("2.0\n")
        with compiler_settings(out_dir=out_dir), counted_searches() as searches:
            harvest(parser, key)
            path, schedule, reads, found = stored_record(out_dir, key)
            digest = AUTO_FSM._search_digest(parser, key, tag, REQUEST)
            stale = dict(reads)
            stale[("delay", str(leaf))] = 1.5
            path.write_bytes(
                zlib.compress(
                    pickle.dumps(
                        (
                            AUTO_FSM._SEARCH_CACHE_VERSION,
                            digest,
                            key,
                            schedule,
                            stale,
                            found,
                        )
                    )
                )
            )
            harvest(parser, key)
            assert len(searches) == 2, "the stale result was reused"
            harvest(parser, key)
            assert len(searches) == 2, "the stale result was not replaced"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
