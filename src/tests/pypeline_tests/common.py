#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared infra for every category module (native_sim_tests.py,
native_vs_vhdl_sim_tests.py, elab_tests.py, elab_introspect_tests.py,
unit_tests.py, synth_tests.py, build_report_tests.py, known_issues_tests.py)
and run_all.py. See docs/pypeline_TESTS.md for what belongs in each."""

import argparse
import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import (
    CancelledError,
    ThreadPoolExecutor,
    as_completed,
    wait as wait_futures,
)
from pathlib import Path

_PRINT_LOCK = threading.Lock()


def _log(msg: str) -> None:
    with _PRINT_LOCK:
        print(msg, flush=True)


_ACTIVE_PROCS_LOCK = threading.Lock()
_ACTIVE_PROCS = set()


def _register_proc(proc: subprocess.Popen) -> None:
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.add(proc)


def _unregister_proc(proc: subprocess.Popen) -> None:
    with _ACTIVE_PROCS_LOCK:
        _ACTIVE_PROCS.discard(proc)


def _kill_active_procs() -> None:
    with _ACTIVE_PROCS_LOCK:
        procs = list(_ACTIVE_PROCS)
    for proc in procs:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


REPO_ROOT = Path(__file__).resolve().parents[3]
assert (REPO_ROOT / "src" / "pypelinec").is_file(), (
    f"Could not locate src/pypelinec relative to {__file__}; "
    f"computed REPO_ROOT={REPO_ROOT} looks wrong"
)

PYPELINEC = REPO_ROOT / "src" / "pypelinec"
PYPELINE_SIM = REPO_ROOT / "src" / "pypeline_sim.py"
PYPELINE_SIM_DEBUG = REPO_ROOT / "src" / "pypeline_sim_debug.py"
INST_DIR = REPO_ROOT / "src" / "tests" / "pypeline_tests" / "inst"
EXAMPLES_PYPELINE_DIR = REPO_ROOT / "examples" / "pypeline"

# Per-category fallback timeout (seconds), used when a Test doesn't set its
# own. None of these are precise -- they only exist so a hung GHDL/synthesis
# subprocess can't block the whole suite forever. Override per-Test via
# timeout= for anything known to legitimately run longer/shorter.
DEFAULT_CATEGORY_TIMEOUT_S = {
    "native_sim": 300,
    "native_vs_vhdl_sim": 900,
    "vhdl_sim": 900,
    "elab": 120,
    "elab_introspect": 120,
    "unit": 120,
    "synth": 1800,
    "build_report": 1800,
    "known_issues": 300,
}
FALLBACK_TIMEOUT_S = 1800

_TOOL_WHICH_CACHE = {}


def _tool_available(tool: str) -> bool:
    if tool not in _TOOL_WHICH_CACHE:
        _TOOL_WHICH_CACHE[tool] = shutil.which(tool) is not None
    return _TOOL_WHICH_CACHE[tool]


@dataclasses.dataclass
class Test:
    name: str
    category: str  # "native_sim" | "native_vs_vhdl_sim" | "elab" | "synth" | ...
    cmd: list  # argv, without python interpreter or --out_dir
    needs_out_dir: bool = False
    expect_fail: bool = False  # this test documents a known, unfixed bug
    timeout: float = None  # seconds; None = DEFAULT_CATEGORY_TIMEOUT_S[category]
    requires: list = dataclasses.field(
        default_factory=list
    )  # external tool names (shutil.which) needed to run at all


@dataclasses.dataclass
class TestResult:
    test: Test
    returncode: int  # None if skipped or timed out
    duration: float
    test_dir: Path
    timed_out: bool = False
    skip_reason: str = None

    @property
    def skipped(self) -> bool:
        return self.skip_reason is not None

    @property
    def passed(self) -> bool:
        if self.skipped:
            return True  # SKIP does not fail the suite
        if self.timed_out:
            return False
        ran_ok = self.returncode == 0
        return ran_ok != self.test.expect_fail  # XOR: expect_fail flips the verdict

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        if self.timed_out:
            return "TIMEOUT"
        ran_ok = self.returncode == 0
        if self.test.expect_fail:
            return "XFAIL" if not ran_ok else "XPASS"
        return "PASS" if ran_ok else "FAIL"


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def make_tmp_root() -> Path:
    tmp_root = Path(tempfile.mkdtemp(prefix="pypeline_run_all_"))
    print(f"Test output directory: {tmp_root}")
    return tmp_root


def run_test(test: Test, tmp_root: Path) -> TestResult:
    test_dir = tmp_root / test.category / test.name
    test_dir.mkdir(parents=True, exist_ok=True)
    out_log = test_dir / "out.log"

    missing = [t for t in test.requires if not _tool_available(t)]
    if missing:
        reason = f"missing tool(s): {', '.join(missing)}"
        _log(f"[SKIP] {test.category:10s} {test.name}  ({reason})")
        return TestResult(test, None, 0.0, test_dir, skip_reason=reason)

    cmd = [sys.executable] + [str(c) for c in test.cmd]
    if test.needs_out_dir:
        cmd += ["--out_dir", str(test_dir)]

    timeout = test.timeout
    if timeout is None:
        timeout = DEFAULT_CATEGORY_TIMEOUT_S.get(test.category, FALLBACK_TIMEOUT_S)

    _log(f"[RUN ] {test.category:10s} {test.name}  log: {out_log}")

    start = time.monotonic()
    timed_out = False
    # Hand the log file directly to the child process so output is written
    # (and visible via e.g. `tail -f`) as the test runs, not just on completion.
    # stdout and stderr are combined into one stream so interleaved output
    # (e.g. a traceback next to the print that triggered it) stays readable.
    with open(out_log, "w") as out_f:
        proc = subprocess.Popen(
            cmd, cwd=REPO_ROOT, stdout=out_f, stderr=subprocess.STDOUT, text=True
        )
        _register_proc(proc)
        try:
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                returncode = proc.wait()
        finally:
            _unregister_proc(proc)
    duration = time.monotonic() - start

    result = TestResult(test, returncode, duration, test_dir, timed_out=timed_out)
    _log(
        f"[{result.status}] {test.category:10s} {test.name}  ({duration:.1f}s)  log: {out_log}"
    )
    return result


def run_tests(tests: list, jobs: int, tmp_root: Path) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_test, test, tmp_root) for test in tests]
        try:
            for future in as_completed(futures):
                results.append(future.result())
        except KeyboardInterrupt:
            _log("\nCTRL-C received - killing running tests...")
            for future in futures:
                future.cancel()
            _kill_active_procs()
            # Tests already in flight were just killed and will resolve almost
            # immediately; collect their results so the summary reflects them.
            done, _ = wait_futures(futures, timeout=10)
            for future in done:
                try:
                    results.append(future.result())
                except CancelledError:
                    pass
            print_summary(results)
            sys.exit(130)
    return results


def print_summary(results: list) -> int:
    results = sorted(results, key=lambda r: (r.test.category, r.test.name))
    name_width = max((len(r.test.name) for r in results), default=4)

    print()
    print("================== Test Summary ==================")
    failed = []
    skipped = []
    for r in results:
        print(
            f"[{r.status}] {r.test.category:10s} {r.test.name:{name_width}s} ({r.duration:.1f}s)"
        )
        if r.skipped:
            skipped.append(r)
        elif not r.passed:
            failed.append(r)

    num_passed = len(results) - len(failed) - len(skipped)
    print(f"\n{num_passed}/{len(results)} tests passed", end="")
    if skipped:
        print(f" ({len(skipped)} skipped)", end="")
    print(".")

    if failed:
        print("\nFailed test output directories:")
        for r in failed:
            tag = " [XPASS: bug appears fixed -- promote out of known_issues]" if r.status == "XPASS" else ""
            print(f"  {r.test.name}: {r.test_dir}{tag}")

    return 0 if not failed else 1


def make_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=default_jobs(),
        help=f"Number of tests to run in parallel. Default = (cpu count / 2) = {default_jobs()}.",
    )
    parser.add_argument(
        "--test",
        "-t",
        default=None,
        metavar="INDEX_OR_NAME",
        help="Run only one test: either its position in the list (0-based, see "
        "--list) or its exact name.",
    )
    parser.add_argument(
        "-k",
        default=None,
        metavar="SUBSTRING",
        help="Run only tests whose name contains SUBSTRING (may match several).",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="Print the numbered list of tests and exit without running anything.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Override every test's timeout (seconds). Takes precedence over "
        "both the test's own timeout and the category default.",
    )
    parser.add_argument(
        "--no_timeout",
        action="store_true",
        help="Disable timeouts entirely (equivalent to a very large --timeout).",
    )
    return parser


def filter_tests(tests: list, args) -> list:
    if args.list:
        for i, t in enumerate(tests):
            print(f"  {i:3d}  [{t.category}]  {t.name}")
        sys.exit(0)
    if args.test is not None:
        by_name = {t.name: t for t in tests}
        if args.test in by_name:
            tests = [by_name[args.test]]
        else:
            try:
                idx = int(args.test)
            except ValueError:
                print(
                    f"Error: --test {args.test!r} matches no test name and is not "
                    f"a valid index",
                    file=sys.stderr,
                )
                sys.exit(1)
            if idx < 0 or idx >= len(tests):
                print(
                    f"Error: --test {idx} out of range (0-{len(tests) - 1})",
                    file=sys.stderr,
                )
                sys.exit(1)
            tests = [tests[idx]]
    if getattr(args, "k", None):
        tests = [t for t in tests if args.k in t.name]
        if not tests:
            print(f"Error: -k {args.k!r} matched no tests", file=sys.stderr)
            sys.exit(1)
    if getattr(args, "no_timeout", False):
        tests = [dataclasses.replace(t, timeout=10**9) for t in tests]
    elif getattr(args, "timeout", None) is not None:
        tests = [dataclasses.replace(t, timeout=args.timeout) for t in tests]
    return tests


def main(get_tests, description: str) -> int:
    parser = make_arg_parser(description)
    args = parser.parse_args()

    tests = filter_tests(get_tests(), args)
    tmp_root = make_tmp_root()
    results = run_tests(tests, args.jobs, tmp_root)
    return print_summary(results)
