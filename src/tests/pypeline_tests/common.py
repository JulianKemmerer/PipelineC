#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared infra for sim_tests.py / elab_tests.py / synth_tests.py / run_all.py."""

import argparse
import dataclasses
import os
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
assert (REPO_ROOT / "src" / "pipelinec").is_file(), (
    f"Could not locate src/pipelinec relative to {__file__}; "
    f"computed REPO_ROOT={REPO_ROOT} looks wrong"
)

PIPELINEC = REPO_ROOT / "src" / "pipelinec"
PYPELINE_SIM = REPO_ROOT / "src" / "pypeline_sim.py"
INST_DIR = REPO_ROOT / "src" / "tests" / "pypeline_tests" / "inst"
EXAMPLES_PYPELINE_DIR = REPO_ROOT / "examples" / "pypeline"


@dataclasses.dataclass
class Test:
    name: str
    category: str  # "sim" | "elab" | "synth"
    cmd: list  # argv, without python interpreter or --out_dir
    needs_out_dir: bool = False


@dataclasses.dataclass
class TestResult:
    test: Test
    returncode: int
    duration: float
    test_dir: Path

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def make_tmp_root() -> Path:
    tmp_root = Path(tempfile.mkdtemp(prefix="pypeline_run_all_"))
    print(f"Test output directory: {tmp_root}")
    return tmp_root


def run_test(test: Test, tmp_root: Path) -> TestResult:
    test_dir = tmp_root / test.category / test.name
    test_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = test_dir / "stdout.log"
    stderr_log = test_dir / "stderr.log"

    cmd = [sys.executable] + [str(c) for c in test.cmd]
    if test.needs_out_dir:
        cmd += ["--out_dir", str(test_dir)]

    _log(f"[RUN ] {test.category:6s} {test.name}  log: {stdout_log}")

    start = time.monotonic()
    # Hand the log files directly to the child process so output is written
    # (and visible via e.g. `tail -f`) as the test runs, not just on completion.
    with open(stdout_log, "w") as out_f, open(stderr_log, "w") as err_f:
        proc = subprocess.Popen(
            cmd, cwd=REPO_ROOT, stdout=out_f, stderr=err_f, text=True
        )
        _register_proc(proc)
        try:
            returncode = proc.wait()
        finally:
            _unregister_proc(proc)
    duration = time.monotonic() - start

    result = TestResult(test, returncode, duration, test_dir)
    status = "PASS" if result.passed else "FAIL"
    _log(
        f"[{status}] {test.category:6s} {test.name}  ({duration:.1f}s)  log: {stdout_log}"
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
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(
            f"[{status}] {r.test.category:6s} {r.test.name:{name_width}s} ({r.duration:.1f}s)"
        )
        if not r.passed:
            failed.append(r)

    num_passed = len(results) - len(failed)
    print(f"\n{num_passed}/{len(results)} tests passed.")

    if failed:
        print("\nFailed test output directories:")
        for r in failed:
            print(f"  {r.test.name}: {r.test_dir}")

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
    return parser


def main(get_tests, description: str) -> int:
    parser = make_arg_parser(description)
    args = parser.parse_args()

    tests = get_tests()
    tmp_root = make_tmp_root()
    results = run_tests(tests, args.jobs, tmp_root)
    return print_summary(results)
