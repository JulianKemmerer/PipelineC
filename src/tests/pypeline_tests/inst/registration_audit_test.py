# pyright: reportInvalidTypeForm=none
"""Meta-test: every `*_test.py` file in inst/ must be registered as a Test in
at least one category module (native_sim_tests.py, native_vs_vhdl_sim_tests.py,
elab_tests.py, elab_introspect_tests.py, unit_tests.py, synth_tests.py,
build_report_tests.py, known_issues_tests.py). A `*_test.py` file registered
nowhere is dead: nothing runs it, and it silently rots.

Naming convention this enforces: `*_test.py` is a registered test file;
`*_design.py` is a fixture another test builds (never registered directly).
A `*_test.py` file that is actually a fixture for another test -- imported or
subprocess-invoked, never registered itself -- should either be renamed to
`*_design.py`, or moved up out of `inst/` into `src/tests/pypeline_tests/`
keeping its name (what autofsm_resources_test.py / autofsm_div_share_test.py /
autofsm_tighten_test.py do) -- rather than being added to some category's list
just to satisfy this check. Only `inst/` is scanned, so either placement works.

Exemptions (checked explicitly below, not registered as Tests themselves):
  - _test_main.py: shared __main__ harness, not a test (leading underscore).
  - registration_audit_test.py: this file -- it IS registered (in
    unit_tests.py), just excluded from its own self-scan.
  - lextab.py / yacctab.py: pycparser-generated, gitignored, not ours.

Run standalone: python3 registration_audit_test.py
"""

import os
import re
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINE_TESTS_DIR = os.path.dirname(INST_DIR)
REPO_ROOT = os.path.abspath(os.path.join(PYPELINE_TESTS_DIR, "..", "..", ".."))
EXAMPLES_PYPELINE_DIR = os.path.join(REPO_ROOT, "examples", "pypeline")
QOR_DIR = os.path.join(PYPELINE_TESTS_DIR, "qor")

CATEGORY_MODULES = [
    "native_sim_tests.py",
    "native_vs_vhdl_sim_tests.py",
    "elab_tests.py",
    "elab_introspect_tests.py",
    "unit_tests.py",
    "synth_tests.py",
    "build_report_tests.py",
    "known_issues_tests.py",
]

EXEMPT_FILENAMES = {
    "_test_main.py",
    "registration_audit_test.py",
    "lextab.py",
    "yacctab.py",
}

# A category module references an inst/ file either as a quoted string
# literal (the (filename, source_dir, ...) list pattern) or as
# `INST_DIR / "filename.py"` (the appended Test(...) pattern). Either way the
# filename appears as a double-quoted string somewhere in the module source.
_QUOTED_PY_FILENAME_RE = re.compile(r'"([A-Za-z0-9_]+\.py)"')


def _registered_filenames() -> set:
    registered = set()
    for module_name in CATEGORY_MODULES:
        path = os.path.join(PYPELINE_TESTS_DIR, module_name)
        with open(path) as f:
            source = f.read()
        registered.update(_QUOTED_PY_FILENAME_RE.findall(source))
    return registered


def test_every_test_file_is_registered_somewhere():
    registered = _registered_filenames()
    all_test_files = {
        f
        for f in os.listdir(INST_DIR)
        if f.endswith("_test.py") and f not in EXEMPT_FILENAMES
    }
    unregistered = sorted(all_test_files - registered)
    assert not unregistered, (
        f"{len(unregistered)} inst/*_test.py file(s) are not registered in any "
        f"category module: {unregistered}. Either register them (add to the "
        f"appropriate category's list/get_tests()) or, if they're actually a "
        f"fixture another test builds, rename to *_design.py or move them up "
        f"into src/tests/pypeline_tests/ instead."
    )


def test_registered_filenames_actually_exist():
    # Most registrations live in inst/, but some (dsp/examples designs)
    # reference EXAMPLES_PYPELINE_DIR and its subdirectories instead, and some
    # (qor/ AUTOFSM/AUTOPIPELINE comparison fixtures) reference QOR_DIR and
    # its per-design subdirectories -- a filename is fine as long as it exists
    # SOMEWHERE plausible, since this check only exists to catch stale
    # references, not to enforce a directory layout the category modules
    # already encode explicitly via their own source_dir.
    registered = _registered_filenames()
    missing = []
    for f in registered:
        in_inst = os.path.isfile(os.path.join(INST_DIR, f))
        in_examples = any(
            f == name
            for _, _, names in os.walk(EXAMPLES_PYPELINE_DIR)
            for name in names
        )
        in_qor = any(
            f == name for _, _, names in os.walk(QOR_DIR) for name in names
        )
        if not (in_inst or in_examples or in_qor):
            missing.append(f)
    missing.sort()
    assert not missing, (
        f"{len(missing)} filename(s) referenced by a category module don't "
        f"exist in inst/, under examples/pypeline/, or under qor/ (stale "
        f"registration after a rename/delete?): {missing}"
    )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
