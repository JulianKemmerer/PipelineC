#!/usr/bin/env python3
"""Every repo path must check out on Windows.

The regression is PR #298: `git clone` on Windows failed with
`error: invalid path 'path_delay_cache/gowin/GW2AR-LV18QN88PC8:C/...'`. The part
string becomes a delay-cache directory name, and Gowin parts are spelled
PART:DEVICE_VERSION -- a colon, which Windows forbids in a path component.
SYN.PART_CACHE_DIR_NAME now sanitizes the directory name (the part string
itself keeps its colon; GOWIN.py splits on it).

The paths checked are the ones the next commit from this worktree would hold:
tracked paths still on disk plus untracked, non-ignored ones -- so a new
cache entry a build just wrote under an unsafe name fails here before it is
committed, and a pending rename passes before it is staged. Outside a git
checkout (ex. an installed package), falls back to walking cache/.

Run standalone: python3 path_portability_test.py
"""

import os
import re
import subprocess
import sys
from types import SimpleNamespace

INST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(INST_DIR, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import C_TO_LOGIC  # Establish PipelineC's normal module-import order.
import GOWIN
import SYN

# Windows forbids these (and control characters) in a path component.
_WINDOWS_BAD_CHARS_RE = re.compile(r'[<>:"\\|?*\x00-\x1f]')
# Reserved device names, with or without an extension (nul.txt is still NUL).
_WINDOWS_RESERVED_RE = re.compile(
    r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE
)


def _restore_env(name, old):
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


def _repo_paths():
    """Repo-relative '/'-separated paths the next commit would hold."""
    try:
        out = subprocess.run(
            ["git", "-C", REPO_ROOT, "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        out = None
    if out is not None:
        paths = [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]
        # A tracked path deleted/renamed on disk is not in the next commit.
        return sorted(
            {p for p in paths if os.path.lexists(os.path.join(REPO_ROOT, p))}
        )
    cache_root = os.path.join(REPO_ROOT, "cache")
    assert os.path.isdir(cache_root), f"not a git checkout and no {cache_root}"
    paths = []
    for dirpath, _dirnames, filenames in os.walk(cache_root):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), REPO_ROOT)
            paths.append(rel.replace(os.sep, "/"))
    return sorted(paths)


def _component_problem(component):
    if _WINDOWS_BAD_CHARS_RE.search(component):
        return "forbidden character"
    if component.endswith((".", " ")):
        return "trailing dot or space"
    if _WINDOWS_RESERVED_RE.match(component):
        return "reserved device name"
    return None


def test_repo_paths_windows_portable():
    paths = _repo_paths()
    assert paths, "found no repo paths to check"
    bad = []
    for path in paths:
        for component in path.split("/"):
            problem = _component_problem(component)
            if problem:
                bad.append(f"{path}  ({problem}: {component!r})")
                break
    assert not bad, (
        f"{len(bad)} path(s) would fail a Windows checkout:\n  "
        + "\n  ".join(bad[:20])
        + ("\n  ..." if len(bad) > 20 else "")
    )


def test_repo_paths_no_case_collisions():
    # Windows' (and macOS') default filesystems are case-insensitive: two paths
    # differing only in case check out as one file, silently clobbering it.
    seen = {}
    collisions = []
    for path in _repo_paths():
        key = path.lower()
        if key in seen:
            collisions.append(f"{seen[key]}  vs  {path}")
        else:
            seen[key] = path
    assert not collisions, "case-only path collisions:\n  " + "\n  ".join(
        collisions
    )


def test_part_cache_dir_name():
    assert SYN.PART_CACHE_DIR_NAME("GW2AR-LV18QN88PC8:C") == "GW2AR-LV18QN88PC8_C"
    # A Gowin tool grade carries a '/': one component, not nested directories.
    assert (
        SYN.PART_CACHE_DIR_NAME("GW2AR-LV18QN88PC8/I7:C") == "GW2AR-LV18QN88PC8_I7_C"
    )
    for part in ("xc7a35ticsg324-1l", "LFE5U-85F-6BG381C", "5CEBA4F23C8", "Ti60F225"):
        assert SYN.PART_CACHE_DIR_NAME(part) == part


def test_gowin_cache_dir_is_safe_and_committed():
    # The lookup a real Gowin build does must land on the committed cache --
    # renaming the directory without sanitizing the lookup (or vice versa)
    # would silently orphan it and re-synthesize every leaf.
    old_tool = SYN.SYN_TOOL
    old_planner = SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS
    old_pnr = GOWIN.DO_PNR
    old_cache_env = os.environ.get("PYPELINEC_CACHE_DIR")
    try:
        SYN.SYN_TOOL = GOWIN
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = False
        GOWIN.DO_PNR = None
        os.environ.pop("PYPELINEC_CACHE_DIR", None)
        cache_dir = SYN.GET_PATH_DELAY_CACHE_DIR(
            SimpleNamespace(part=GOWIN.DEFAULT_PART)
        )
    finally:
        SYN.SYN_TOOL = old_tool
        SYN.USE_COMBINATIONAL_PLANNER_WEIGHTS = old_planner
        GOWIN.DO_PNR = old_pnr
        _restore_env("PYPELINEC_CACHE_DIR", old_cache_env)

    assert ":" in GOWIN.DEFAULT_PART  # the case this test exists for
    norm = os.path.normpath(cache_dir).replace(os.sep, "/")
    assert norm.endswith("/cache/delay/gowin/GW2AR-LV18QN88PC8_C/syn"), norm
    assert os.path.isdir(cache_dir), f"committed Gowin cache not found: {norm}"
    delays = [f for f in os.listdir(cache_dir) if f.endswith(".delay")]
    assert delays, f"no .delay entries in {norm}"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
