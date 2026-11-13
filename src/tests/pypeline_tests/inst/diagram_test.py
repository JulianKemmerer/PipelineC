#!/usr/bin/env python3
"""In-process tests of the design diagram's data (src/DIAGRAM.py,
docs/DIAGRAM_DESIGN.md): each design is parsed with PARSE_FILE, written with
DIAGRAM.WRITE_DIAGRAM(state, None, top) as a --no_synth build would, and the
JSON embedded in the page is checked.

Designs: built_hardware_top_design.py (+ its imported core: three MAINs over
two files, an @wires port MAIN, an AUTO_PIPELINE and an AUTO_FSM call site),
multi_clock_design.py (two clocks, a sync and an async global FIFO, an ASYNC
wire), diagram_interfaces_design.py (a generated interface function's Feedback
variables typed with plain copies of an interface's halves, two plain stream
types, a @wires call site), a small design written here (a call graph with a
register, a Feedback wire, a global wire and a @pipeline_latency function), and
the C example examples/shared_globals.c.
"""

import functools
import json
import os
import re
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC
import DIAGRAM
import PY_TO_LOGIC
import SYN

INST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_SRC = os.path.abspath(os.path.join(INST_DIR, "../../../"))
REPO_ROOT = os.path.dirname(REPO_SRC)
TOP = os.path.join(INST_DIR, "built_hardware_top_design.py")
CORE = os.path.join(INST_DIR, "built_hardware_core_design.py")
MULTI_CLOCK = os.path.join(INST_DIR, "multi_clock_design.py")
INTERFACES = os.path.join(INST_DIR, "diagram_interfaces_design.py")
C_DESIGN = os.path.join(REPO_ROOT, "examples", "shared_globals.c")

_GRAPH_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from pypeline import (MAIN, Feedback, Output, Reg, Wire, hw_func,
                          pipeline_latency, uint8_t)

    tap: Wire[uint8_t]  # graph_main -> reader_main
    READ_OUT: Output[uint8_t]

    @hw_func
    def add1(a: uint8_t) -> uint8_t:
        return a + 1

    @pipeline_latency(1)
    def delay_one(x: uint8_t) -> uint8_t:
        saved: Reg[uint8_t]
        result: uint8_t = saved
        saved = x
        return result

    @MAIN
    def graph_main(x: uint8_t) -> uint8_t:
        f: Feedback[uint8_t]
        acc: Reg[uint8_t]
        total: uint8_t = add1(f) + acc
        f = add1(x)
        acc = total
        tap = total
        return total

    @MAIN
    def reader_main():
        READ_OUT = delay_one(tap)
    """
).format(repo=REPO_SRC)


def _embedded(html):
    start = html.index('id="design">') + len('id="design">')
    return json.loads(html[start : html.index("</script>", start)])


def _write(state, top):
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="diagram_test_out_")
    with open(DIAGRAM.WRITE_DIAGRAM(state, None, top)) as f:
        return f.read()


@functools.lru_cache(maxsize=None)
def _page(top):
    """(design data, page text) of a .py design parsed for a --no_synth build."""
    html = _write(PY_TO_LOGIC.PARSE_FILE(top), top)
    return _embedded(html), html


@functools.lru_cache(maxsize=None)
def _graph_design():
    path = os.path.join(tempfile.mkdtemp(prefix="diagram_test_src_"), "graph_design.py")
    with open(path, "w") as f:
        f.write(_GRAPH_SRC)
    return _page(path)[0]


def _type(data, t):
    """The type table row of type index t ({} for no type)."""
    return data["types"][t] if t is not None else {}


def _graph(data, func):
    """{node id: node}, [(src id, src port, dst id, dst port, bits, names, fb)]"""
    g = data["funcs"][func]["graph"]
    ids = [n["id"] for n in g["nodes"]]
    return (
        {n["id"]: n for n in g["nodes"]},
        [
            (ids[s], sp, ids[d], dp, _type(data, t).get("bits"), tuple(names), fb)
            for s, sp, d, dp, t, names, fb in g["edges"]
        ],
    )


def _subs(nodes, name):
    return sorted(
        i for i, n in nodes.items() if n["kind"] == "sub" and n["name"] == name
    )


def test_top_file_imports_core_file():
    data = _page(TOP)[0]
    files = data["files"]
    assert files[TOP]["top"] and files[TOP]["kind"] == "design", files[TOP]
    assert CORE in files[TOP]["imports"], files[TOP]["imports"]
    assert files[CORE]["kind"] == "design", files[CORE]
    assert files[TOP]["mains"] == ["built_hardware_ports"], files[TOP]["mains"]
    assert files[CORE]["mains"] == [
        "built_hardware_core_design_body_main",
        "built_hardware_core_design_fsm_main",
    ], files[CORE]["mains"]
    pypeline_py = os.path.join(REPO_SRC, "pypeline.py")
    assert files[pypeline_py]["kind"] == "library", files[pypeline_py]


def test_main_files_and_clocks():
    data = _page(MULTI_CLOCK)[0]
    mains, clocks = data["mains"], data["clocks"]
    assert mains["eth_rx"]["clock"] == "125 MHz eth_rx", mains["eth_rx"]
    assert mains["forward"]["clock"] == "100 MHz", mains["forward"]
    assert clocks["125 MHz eth_rx"]["name"] == "eth_clk", clocks
    assert clocks["125 MHz eth_rx"]["goal_mhz"] == 125.0, clocks
    assert (mains["eth_rx"]["file"], mains["eth_rx"]["line"]) == (MULTI_CLOCK, 35)


def test_wire_links_follow_field_direction():
    links = {(l["src"], l["dst"], l["name"]) for l in _page(MULTI_CLOCK)[0]["links"]}
    # Stream data flows into the FIFO's ends, each ready flows back out
    assert {l for l in links if l[2].startswith("rx.")} == {
        ("eth_rx", "rx_FIFO_wr", "rx.wr.stream.data"),
        ("eth_rx", "rx_FIFO_wr", "rx.wr.stream.valid"),
        ("rx_FIFO_wr", "eth_rx", "rx.wr.ready"),
        ("forward", "rx_FIFO_rd", "rx.rd.ready"),
        ("rx_FIFO_rd", "forward", "rx.rd.stream.data"),
        ("rx_FIFO_rd", "forward", "rx.rd.stream.valid"),
    }, links
    assert ("forward", "pin:LINK", "LINK") in links, links
    async_link = [l for l in _page(MULTI_CLOCK)[0]["links"] if l["name"] == "link_up"]
    assert [(l["src"], l["dst"], l["async"]) for l in async_link] == [
        ("eth_rx", "forward", True)
    ], async_link


def test_wires_main_is_marked_wiring():
    mains = _page(TOP)[0]["mains"]
    assert mains["built_hardware_ports"]["wiring"] == "@wires", mains
    assert mains["built_hardware_core_design_body_main"]["wiring"] is None, mains
    assert mains["built_hardware_core_design_body_main"]["reset"] == "rst", mains
    # Its only logic is a register in a function it calls: not just wiring
    assert _graph_design()["mains"]["reader_main"]["wiring"] is None


def test_function_graph_connects_instances():
    nodes, edges = _graph(_graph_design(), "graph_main")
    first, second = _subs(nodes, "add1")
    plus = _subs(nodes, "BIN_OP_PLUS")[0]
    # x -> add1 (the second call) -> f -> add1 (the first) -> + -> total
    assert any(e[0] == "i:x" and e[2] == second and e[4] == 8 for e in edges), edges
    out_of_plus = [e for e in edges if e[0] == plus]
    assert {e[2] for e in out_of_plus} == {
        "o:return_output",
        "rd:acc",
        "gw:tap",
    }, out_of_plus
    assert all(e[5] == ("total",) for e in out_of_plus), out_of_plus
    assert any(e[0] == "rq:acc" and e[2] == plus for e in edges), edges
    assert nodes[first]["callee"] == nodes[second]["callee"]
    assert _graph_design()["funcs"][nodes[plus]["callee"]]["kind"] == "op"


def test_edge_names_start_at_the_driving_variable():
    nodes, edges = _graph(_graph_design(), "graph_main")
    first, second = _subs(nodes, "add1")
    plus = _subs(nodes, "BIN_OP_PLUS")[0]
    # An input and a register name the edges they drive
    assert ("i:x", "", second, "a", 8, ("x",), 0) in edges, edges
    assert ("rq:acc", "", plus, "right", 8, ("acc",), 0) in edges, edges
    # A call's result passed straight into + is no variable
    assert (first, "return_output", plus, "left", 8, (), 0) in edges, edges


def test_feedback_edges_are_marked():
    nodes, edges = _graph(_graph_design(), "graph_main")
    first, second = _subs(nodes, "add1")
    fb = [e for e in edges if e[6]]
    assert [(e[0], e[2], e[5]) for e in fb] == [(second, first, ("f",))], fb


def test_types_carry_interface_roles():
    data = _page(INTERFACES)[0]
    roles = {t.get("name", t["c"]): t.get("role") for t in data["types"]}
    assert roles["chan_intrf_fwd_t"] == "fwd", roles
    assert roles["chan_intrf_fb_t"] == "fb", roles
    # A generated interface function types its Feedbacks with plain copies
    # of the halves, which keep the fields but not the role
    assert roles["chan_intrf_fwd_t_plain"] == "fwd", roles
    assert roles["chan_intrf_fb_t_plain"] == "fb", roles
    assert roles["stream_t<uint8_t>"] == "fwd", roles  # a plain {data, valid} stream
    assert roles["route_t"] == "fwd", roles  # holds a forward half
    assert roles["uint8_t"] is None, roles


def test_type_names_read_like_the_source():
    data = _page(INTERFACES)[0]
    named = {t["c"]: t.get("name") for t in data["types"]}
    # Two stream types are classes named stream_t: their factory arguments
    # tell them apart
    streams = sorted(n for n in named.values() if n and n.startswith("stream_t"))
    assert streams == ["stream_t<uint1_t>", "stream_t<uint8_t>"], named
    assert named["chan_intrf_t_data_uint16_t_valid_uint1_t"] == "chan_intrf_fwd_t", named
    assert named["uint8_t"] is None, named  # a scalar's C name is its source name


def test_feedback_edges_carry_their_types():
    data = _page(INTERFACES)[0]
    (merge,) = [f for f in data["funcs"] if f.startswith("merge_if")]
    _nodes, edges = _graph(data, merge)
    g = data["funcs"][merge]["graph"]
    roles = sorted(_type(data, e[4]).get("role") for e in g["edges"] if e[6])
    # What the later call feeds back to the earlier one is forward data; the
    # backpressure it returns is feedback
    assert set(roles) == {"fb", "fwd"}, roles
    assert all(e[5] for e in edges if e[6]), edges  # each names its Feedback


def test_wiring_call_sites_are_marked():
    funcs = _page(INTERFACES)[0]["funcs"]
    assert funcs["pass_through"]["wiring"] == "@wires", funcs["pass_through"]
    # A constant field select is only wiring, an adder is not
    selects = [f for n, f in funcs.items() if n.startswith("CONST_REF_RD")]
    assert selects and all(f.get("wiring") == "no logic" for f in selects), selects
    adds = [f for n, f in funcs.items() if n.startswith("BIN_OP_PLUS")]
    assert adds and all("wiring" not in f for f in adds), adds
    # A user's function that only routes fields stays a block of its own
    assert "wiring" not in funcs["route"], funcs["route"]


def test_call_site_kinds():
    data = _page(TOP)[0]
    nodes, _ = _graph(data, "built_hardware_core_design_body_main")
    (site,) = _subs(nodes, "divide_body")
    assert nodes[site]["auto_pipeline"] == "built_hardware_body", nodes[site]
    nodes, _ = _graph(data, "built_hardware_core_design_fsm_main")
    (fsm_site,) = [n for n in nodes.values() if n["kind"] == "sub"]
    assert fsm_site["auto_fsm"] == "built_hardware_core_design_mixed_ops", fsm_site
    assert data["funcs"][fsm_site["callee"]]["kind"] == "fsm"
    # The walk stops at an AUTO_FSM call site: the function it schedules is not
    # drawn as part of the hierarchy
    assert "built_hardware_core_design_mixed_ops" not in data["funcs"]
    # A global FIFO's raw VHDL is a leaf block with ports, not a graph
    fifo = _page(MULTI_CLOCK)[0]["funcs"]
    raw = [f for f in fifo.values() if f["kind"] == "vhdl"]
    assert raw and all("graph" not in f and f["inputs"] for f in raw), raw


def test_async_fifo_ends_share_one_node():
    data = _page(MULTI_CLOCK)[0]
    mains = data["mains"]
    for side in ("rx_FIFO_wr", "rx_FIFO_rd"):
        assert mains[side]["kind"] == "fifo", mains[side]
        assert mains[side]["group"] == "rx", mains[side]
        assert mains[side]["wiring"] is None, mains[side]
    assert "group" not in mains["cmds_FIFO"], mains["cmds_FIFO"]
    crossing = [l for l in data["links"] if l["crossing"]]
    assert [(l["src"], l["dst"]) for l in crossing] == [("rx_FIFO_wr", "rx_FIFO_rd")]


def test_pipeline_latency_without_synthesis():
    data = _graph_design()
    nodes, _ = _graph(data, "reader_main")
    (site,) = _subs(nodes, "delay_one")
    assert data["inst_latency"].get("reader_main____" + site[2:]) == 1, data[
        "inst_latency"
    ]
    assert data["mains"]["reader_main"]["latency"] == 1, data["mains"]
    assert data["mains"]["graph_main"]["latency"] == 0, data["mains"]


def test_two_parses_write_identical_pages():
    first = _page(MULTI_CLOCK)[1]
    second = _write(PY_TO_LOGIC.PARSE_FILE(MULTI_CLOCK), MULTI_CLOCK)
    assert first == second


def test_page_loads_nothing_external():
    html = _page(TOP)[1]
    assert not re.search(r"<(link|img|iframe)\b", html, re.I), "external element"
    assert not re.search(r"\b(src|href)\s*=", html, re.I), "external reference"
    assert not re.search(r"\b(fetch|XMLHttpRequest|import)\s*\(", html), "network call"
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", html))
    assert urls <= {"http://www.w3.org/2000/svg"}, urls


def test_c_design_gets_a_diagram():
    C_TO_LOGIC.MULT_STYLE = (
        C_TO_LOGIC.MULT_STYLE_INFERRED
    )  # the driver's --mult default
    data = _embedded(_write(C_TO_LOGIC.PARSE_FILE(C_DESIGN), C_DESIGN))
    assert data["build"]["front_end"] == "c"
    assert data["files"][C_DESIGN]["mains"] == [
        "another_read_main",
        "not_same_clk_read_main",
        "read_main",
        "write_main",
    ], data["files"]
    links = data["links"]
    assert {l["src"].split("____")[0] for l in links} == {"write_main"}, links
    assert sorted(l["dst"].split("____")[0] for l in links) == [
        "another_read_main",
        "not_same_clk_read_main",
        "read_main",
    ], links
    assert all(
        l["wire"] == "the_global" and _type(data, l["t"])["bits"] == 32 for l in links
    ), links
    nodes, _ = _graph(data, "write_main")
    assert [n["callee"] for n in nodes.values() if n["kind"] == "sub"] == ["write_func"]
    assert data["mains"]["not_same_clk_read_main"]["clock"] == "50 MHz", data["mains"]


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
