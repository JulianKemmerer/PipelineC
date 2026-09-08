#!/usr/bin/env python3
"""Produce this design's generated host module, `pypeline_host_types.py`.

Every `pypelinec` build of `top.py` already writes it to
`<out_dir>/host/pypeline_host_types.py`. This is the same thing without the
build: importing `top` is what registers the wire formats (the factories reach
`make_type_to_bytes`, the registration choke point) and what runs its
`host_export` call, so a plain import plus `write_host_types` reproduces exactly
what a build emits, in seconds rather than minutes.

TWO USES.

`ensure_host_types()` is for the in-repo tests. Nothing generated is committed --
there is deliberately no checked-in copy to go stale -- so `pdw_verify.py`'s
hardware constants and `pdw_verify_test.py`'s round trips need the module built
on demand. It generates once per process, puts it on `sys.path`, and returns it.

`python3 pdw_host_gen.py <dir>` is for getting the file onto a radio. Copy the
result next to `airt_pdw_test.py`; it imports nothing but the standard library.

WHY NOT COMMIT IT. A generated file that is checked in can drift from the design
in the one way a generated file otherwise cannot: by nobody regenerating it.
Building it on demand from `top.py` means the design is the only source, full
stop, and there is no staleness left to guard against.
"""

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))

# Scratch lives under /media/1TB/tmp/ by this repo's convention, not /tmp.
_SCRATCH_ROOT = "/media/1TB/tmp"

_CACHED = None


def _design_paths():
    """The sys.path entries `top.py` needs, matching how the tests set up."""
    return [
        os.path.join(_ROOT, "src"),
        os.path.join(_ROOT, "include", "pypeline"),
        os.path.join(_HERE, "pulse_gen"),
        os.path.join(_HERE, "pulse_detect"),
        os.path.join(_HERE, "pdw_engine"),
        os.path.join(_HERE, "pdw_ctrl"),
        _HERE,
    ]


def generate(out_dir):
    """Write `<out_dir>/host/pypeline_host_types.py`. Returns the path."""
    for d in _design_paths():
        if d not in sys.path:
            sys.path.insert(0, d)

    import pypeline_host

    # The import is the point: it runs top.py's factory calls (which register
    # the three struct layouts) and its host_export call (the constants).
    import top  # noqa: F401

    path = pypeline_host.write_host_types(out_dir, "top.py")
    if path is None:
        raise RuntimeError(
            "top.py registered no host types -- expected pdw_ctrl_t, "
            "valid_pdw_t and candidate_rec_t via make_type_to_axis / "
            "make_axis_to_type"
        )
    return path


def ensure_host_types():
    """Generate into a temp dir, import, and return the module. Memoized.

    Safe to call from several test files in one process; the first call does the
    work. The temp dir is intentionally left in place -- it is a few KB, and a
    failing test is much easier to diagnose with the generated file still on
    disk to read.
    """
    global _CACHED
    if _CACHED is not None:
        return _CACHED

    root = _SCRATCH_ROOT if os.path.isdir(_SCRATCH_ROOT) else None
    out_dir = tempfile.mkdtemp(prefix="pdw_host_", dir=root)
    path = generate(out_dir)

    host_dir = os.path.dirname(path)
    if host_dir not in sys.path:
        sys.path.insert(0, host_dir)
    import pypeline_host_types

    _CACHED = pypeline_host_types
    return _CACHED


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    written = generate(target)
    print(f"wrote {written}")
    print("Copy that file next to airt_pdw_test.py on the radio.")
