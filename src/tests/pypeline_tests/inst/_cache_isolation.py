#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared cache-isolation helper for inst/*.py tests that want a FRESH area
cache but a WARM delay cache (leading underscore: not a test, see
docs/pypeline_TESTS.md naming convention).

Delay and area live under one `PYPELINEC_CACHE_DIR` root as `cache/delay` and
`cache/area` (SYN.GET_CACHE_ROOT_DIR), so pointing that root at a tempdir
isolates *both* subtrees. A cold `cache/delay` means sky130 really synthesizes
every leaf -- which both blows up the runtime of these tests and breaks the
ones that assert no leaf was re-synthesized on a warm rerun.

make_isolated_cache_root() gives a root whose `area/` is empty and private to
the test, while `delay/` is a symlink to the repo's committed tree and is
therefore read *and written* through to it -- exactly what these tests did
back when the two caches were separate directories and only the area one was
overridden.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import SYN


def committed_cache_root():
    """The repo's own committed cache/ tree, ignoring any active override."""
    old_env = os.environ.pop("PYPELINEC_CACHE_DIR", None)
    try:
        return SYN.GET_CACHE_ROOT_DIR()
    finally:
        if old_env is not None:
            os.environ["PYPELINEC_CACHE_DIR"] = old_env


def make_isolated_cache_root(base_dir):
    """Build <base_dir>/cache as a PYPELINEC_CACHE_DIR root: private area/,
    committed delay/ shared in by symlink. Returns the root path."""
    root = os.path.join(base_dir, "cache")
    os.makedirs(os.path.join(root, "area"), exist_ok=True)
    delay_link = os.path.join(root, "delay")
    if not os.path.exists(delay_link):
        os.symlink(
            os.path.join(committed_cache_root(), "delay"),
            delay_link,
            target_is_directory=True,
        )
    return root
