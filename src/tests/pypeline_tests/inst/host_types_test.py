# pyright: reportInvalidTypeForm=none
"""The generated standalone host module: pypeline_host.generate / write_host_types.

A host that talks to a Pypeline design needs the design's byte layout, but
cannot have a Pypeline checkout -- copying pypeline.py there does not help,
because a design's TYPES drag in the hardware factory library that defines
them. So pypelinec generates the host's copy of the layout instead.

The load-bearing test here is `test_matches_pypeline_layout`, and it is
deliberately awkward: it runs the generated module in a SUBPROCESS whose
sys.path cannot reach this repo, and compares what that process decodes and
encodes against pypeline's own type_to_bytes/type_from_bytes. Anything cheaper
-- exec'ing the text in this process, or only round-tripping inside the
generated module -- would pass for a self-consistent but wrong layout, which is
exactly the bug this feature exists to prevent (a drifted host copy still
produces a well-formed frame of the right length; it just loads the wrong
values into the wrong registers).
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from enum import IntEnum
from typing import NamedTuple

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import pypeline_host
from pypeline import (
    _host_register,
    _host_reset,
    byte_length,
    char_t,
    enum,
    host_export,
    host_exports,
    int8_t,
    int16_t,
    make_type_to_bytes,
    struct,
    type_from_bytes,
    type_to_bytes,
    uint3_t,
    uint8_t,
    uint12_t,
    uint16_t,
    uint32_t,
    uint64_t,
)

# ── fixtures ──────────────────────────────────


@enum
class mode_t(IntEnum):
    # NB: not `ON` -- @enum member names are emitted verbatim into the VHDL
    # enumeration type and `on` is a VHDL reserved word.
    OFF = 0
    ACTIVE = 1
    STANDBY = 2


@struct
class inner_t(NamedTuple):
    lo: uint3_t  # ragged: masking is load-bearing
    hi: uint12_t


@struct
class nested_t(NamedTuple):
    """Exercises the generic shape walk: enum leaf, nested struct, array."""

    m: mode_t
    inner: inner_t
    arr: uint16_t[3]
    tag: char_t[4]
    signed: int8_t


@struct
class flat_t(NamedTuple):
    """Flat, standard-width, no enum -- so it gets the `struct` fast path.

    Field for field this is PDW's `valid_pdw_t`, on purpose: the format string
    the generator derives for it is asserted below against the one that project
    wrote out by hand.
    """

    toa: uint64_t
    pulse_width: uint32_t
    peak_power: uint32_t
    pkt_samples: uint32_t
    pri: uint32_t
    peak_power_db: int16_t
    noise_power_db: int16_t
    freq_start: int16_t
    freq_stop: int16_t
    status_flags: uint32_t
    channel: uint16_t
    padding: uint16_t


FIXTURES = (nested_t, flat_t, inner_t, uint16_t[4], uint32_t)

# ── helpers ───────────────────────────────────


def _exports_for(*types, **endians):
    """An exports dict as the registry would have built it, without touching
    the process-wide registry."""
    _host_reset()
    for t in types:
        _host_register(t, endians.get(getattr(t, "__name__", ""), "little"))
    return host_exports()


def _plain(v):
    """Normalize a decoded value -- pypeline's or the generated module's -- to
    plain dicts/lists/ints, so the two can be compared directly."""
    if hasattr(v, "_asdict"):
        return {k: _plain(x) for k, x in v._asdict().items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return int(v)


_DRIVER = r"""
import json, os, sys

# Drop every path that could reach the Pypeline checkout, so this process has
# the standard library and the generated module and nothing else. Truncating
# sys.path outright would also remove the stdlib, which is not the claim under
# test -- the claim is that no part of THIS REPO is reachable.
repo = os.path.abspath(sys.argv[3])
sys.path = [p for p in sys.path if not os.path.abspath(p or ".").startswith(repo)]
try:
    import pypeline  # noqa: F401
    raise SystemExit("pypeline was importable; the standalone claim is untested")
except ImportError:
    pass

import pypeline_host_types as H

leaked = [m for m in sys.modules
          if m.startswith("pypeline") and m != "pypeline_host_types"]
vectors = json.load(open(sys.argv[1]))
out = {"leaked": leaked, "results": []}
for v in vectors:
    t = H.TYPES[v["type"]]
    raw = bytes.fromhex(v["raw"])
    value = H.type_from_bytes(t, raw, v["endian"])
    out["results"].append({
        "plain": _plain(value),
        "reencoded": H.type_to_bytes(t, value, v["endian"]).hex(),
        "byte_length": H.byte_length(t),
    })
json.dump(out, open(sys.argv[2], "w"))
"""

_DRIVER_PLAIN = r"""
def _plain(v):
    if hasattr(v, "_asdict"):
        return {k: _plain(x) for k, x in v._asdict().items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return int(v)
"""


def _run_standalone(module_text, vectors):
    """Write the generated module to a scratch dir and drive it from a process
    that cannot import anything from this repo. Returns the driver's output."""
    tmp = tempfile.mkdtemp(prefix="pypeline_host_test_")
    try:
        with open(os.path.join(tmp, "pypeline_host_types.py"), "w") as f:
            f.write(module_text)
        with open(os.path.join(tmp, "drive.py"), "w") as f:
            f.write(_DRIVER_PLAIN + _DRIVER)
        vec_path = os.path.join(tmp, "vectors.json")
        out_path = os.path.join(tmp, "out.json")
        with open(vec_path, "w") as f:
            json.dump(vectors, f)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)  # nothing from this repo may leak in
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../")
        )
        proc = subprocess.run(
            [
                sys.executable,
                os.path.join(tmp, "drive.py"),
                vec_path,
                out_path,
                repo_root,
            ],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
        )
        assert (
            proc.returncode == 0
        ), f"standalone driver failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
        with open(out_path) as f:
            return json.load(f)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _random_vectors(seed=1234, per_type=12):
    """Raw random byte frames -- deliberately NOT canonicalized through pypeline.

    Canonicalizing first (decode then re-encode, so every ragged leaf already
    holds a value that fits) would hide the leaf MASK WIDTH: with a uint3_t leaf
    already reduced to 3 bits, a generator that masked it to 8 would decode it
    identically. That mutation was verified to slip past a canonicalized
    vector set and to be caught by this one. Raw bytes drive every leaf's mask
    with bits it must discard.
    """
    rng = random.Random(seed)
    vectors = []
    for t in FIXTURES:
        name = _host_name_of(t)
        n = byte_length(t)
        for endian in ("little", "big"):
            for _ in range(per_type):
                raw = bytes(rng.randrange(256) for _ in range(n))
                vectors.append(
                    {"type": name, "endian": endian, "raw": raw.hex(), "_t": t}
                )
    return vectors


def _host_name_of(t):
    order = pypeline_host._emit_order(_exports_for(*FIXTURES)[0])
    names = pypeline_host._assign_host_names(order)
    from pypeline import _bytes_type_key

    return names[_bytes_type_key(t)]


# ── tests ─────────────────────────────────────


def test_matches_pypeline_layout():
    """Decode and encode in a Pypeline-free process agree with pypeline itself,
    for every fixture, both endians, over random frames."""
    exports, values = _exports_for(*FIXTURES)
    text = pypeline_host.generate(exports, values, "fixture_design.py")
    vectors = _random_vectors()
    payload = [{k: v for k, v in vec.items() if k != "_t"} for vec in vectors]
    out = _run_standalone(text, payload)
    assert out["leaked"] == [], f"generated module pulled in {out['leaked']}"
    for vec, res in zip(vectors, out["results"]):
        t, endian, raw = vec["_t"], vec["endian"], bytes.fromhex(vec["raw"])
        assert res["byte_length"] == byte_length(t), (t, res["byte_length"])
        decoded = type_from_bytes(t, raw, endian)
        # DECODE agrees with pypeline field for field -- including every leaf's
        # mask, since `raw` carries bits a ragged leaf has to throw away.
        assert res["plain"] == _plain(decoded), (t, endian, raw.hex())
        # ENCODE agrees too: re-packing what each side decoded must give the
        # same bytes (which is pypeline's canonical form of `raw`, not `raw`
        # itself, precisely because ragged leaves dropped bits).
        assert res["reencoded"] == type_to_bytes(t, decoded, endian).hex(), (
            t,
            endian,
            raw.hex(),
        )
    print(f"test_matches_pypeline_layout PASS ({len(vectors)} frames)")


def test_struct_format_reproduces_handwritten_one():
    """The `struct` fast path is derived from the same leaf walk, never authored.

    PDW's gr_pdw_record.py wrote `RECORD_FORMAT = "<QIIIIhhhhIHH"` by hand for
    exactly `flat_t`'s field list; the generator must land on that string
    character for character, or one of the two is wrong.
    """
    assert pypeline_host._struct_format(flat_t) == "QIIIIhhhhIHH"
    assert byte_length(flat_t) == 40
    # ...and no fast path where it could disagree with the generic walk.
    assert pypeline_host._struct_format(nested_t) is None
    assert pypeline_host._struct_format(inner_t) is None  # ragged widths
    assert pypeline_host._struct_format(uint16_t[4]) is None  # not a struct
    print("test_struct_format_reproduces_handwritten_one PASS")


def test_generation_is_deterministic():
    exports, values = _exports_for(*FIXTURES)
    first = pypeline_host.generate(exports, values, "d.py")
    exports2, values2 = _exports_for(*reversed(FIXTURES))
    second = pypeline_host.generate(exports2, values2, "d.py")
    assert first == second, "generated text depends on registration order"
    print("test_generation_is_deterministic PASS")


def test_auto_registration_from_make_type_to_bytes():
    """The whole point of hooking the choke point: no design edit required."""
    _host_reset()
    assert host_exports()[0] == {}
    make_type_to_bytes(flat_t)
    exports, _ = host_exports()
    assert len(exports) == 1
    (entry,) = exports.values()
    assert entry["type"] is flat_t and entry["endians"] == {"little"}
    print("test_auto_registration_from_make_type_to_bytes PASS")


def test_auto_registration_through_axis_factory():
    """A design that only ever calls make_type_to_axis still registers -- that
    factory reaches make_type_to_bytes underneath, which is why PDW's three
    host-facing types would need no design change at all."""
    sys.path.insert(
        0,
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "../../../../include/pypeline"
        ),
    )
    from axi.type_axis import make_type_to_axis

    _host_reset()
    make_type_to_axis(flat_t, 4)
    exports, _ = host_exports()
    assert [e["type"] for e in exports.values()] == [flat_t], list(exports)
    print("test_auto_registration_through_axis_factory PASS")


def test_both_endians_defaults_little_and_says_so():
    _host_reset()
    _host_register(flat_t, "little")
    _host_register(flat_t, "big")
    exports, values = host_exports()
    text = pypeline_host.generate(exports, values, "d.py")
    assert "both little- and big-endian" in text
    assert "'little'" in text
    print("test_both_endians_defaults_little_and_says_so PASS")


def test_host_export_values_and_alias():
    _host_reset()
    defaults = flat_t(*([0] * 11 + [7]))
    host_export(nested_t, DEFAULTS=defaults, FLAG_X=1 << 3, RECORD_T=flat_t, NAME="pdw")
    exports, values = host_exports()
    text = pypeline_host.generate(exports, values, "d.py")
    assert "DEFAULTS = flat_t(" in text and "padding=7" in text
    assert "FLAG_X = 8" in text
    assert "RECORD_T = flat_t" in text  # a type exported under an alias
    assert "NAME = 'pdw'" in text
    out = _run_standalone(text, [])
    assert out["leaked"] == []
    print("test_host_export_values_and_alias PASS")


def test_enum_members_keep_int_to_bytes():
    """An @enum must NOT gain a to_bytes attribute: on an IntEnum that would
    shadow int.to_bytes for every member. Same call pypeline itself declines to
    make on @enum."""
    exports, values = _exports_for(nested_t)
    text = pypeline_host.generate(exports, values, "d.py")
    ns = {}
    exec(compile(text, "generated", "exec"), ns)
    # `hasattr` proves nothing here -- an IntEnum inherits int.to_bytes either
    # way. The claim is that it is still int's, not one the generator added.
    assert ns["mode_t"].to_bytes is int.to_bytes
    assert ns["mode_t"].ACTIVE.to_bytes(2, "little") == b"\x01\x00"
    # ...but it is still convertible through the module-level functions.
    assert ns["type_to_bytes"](ns["mode_t"], ns["mode_t"].STANDBY) == b"\x02"
    print("test_enum_members_keep_int_to_bytes PASS")


def test_char_array_behaves_like_a_string():
    exports, values = _exports_for(nested_t)
    text = pypeline_host.generate(exports, values, "d.py")
    ns = {}
    exec(compile(text, "generated", "exec"), ns)
    raw = type_to_bytes(
        nested_t, type_from_bytes(nested_t, b"\x01" * byte_length(nested_t))
    )
    v = ns["nested_t"].from_bytes(raw)
    assert str(v.tag) == "\x01\x01\x01\x01"
    assert isinstance(v.tag, ns["CharArray"])
    print("test_char_array_behaves_like_a_string PASS")


def test_bad_field_names_rejected():
    @struct
    class kw_t(NamedTuple):
        pass_: uint8_t

    kw_t._fields = ("pass",)  # what a keyword field would look like
    try:
        pypeline_host._check_emittable(kw_t, "kw_t")
        raise AssertionError("expected ValueError for a Python-keyword field")
    except ValueError as e:
        assert "keyword" in str(e)

    @struct
    class collide_t(NamedTuple):
        zero: uint8_t

    try:
        pypeline_host._check_emittable(collide_t, "collide_t")
        raise AssertionError("expected ValueError for a reserved-attribute field")
    except ValueError as e:
        assert "collides" in str(e)
    print("test_bad_field_names_rejected PASS")


def test_write_host_types_places_and_skips():
    tmp = tempfile.mkdtemp(prefix="pypeline_host_out_")
    try:
        _host_reset()
        assert (
            pypeline_host.write_host_types(tmp, "d.py") is None
        ), "a design that serializes nothing must get no host file"
        assert not os.path.exists(os.path.join(tmp, "host"))
        _host_register(flat_t)
        path = pypeline_host.write_host_types(tmp, "d.py")
        assert path == os.path.join(tmp, "host", "pypeline_host_types.py")
        assert "flat_t" in open(path).read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_write_host_types_places_and_skips PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
