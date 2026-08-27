import os
import shlex
import subprocess
import sys
from shutil import which
from typing import Optional


def GET_TOOL_PATH(tool_exe_name: str) -> Optional[str]:
    w = which(tool_exe_name)
    if w is not None:
        return str(w)
    return None


_REPO_ABS_DIR = None


def REPO_ABS_DIR():
    global _REPO_ABS_DIR
    if _REPO_ABS_DIR:
        return _REPO_ABS_DIR
    _REPO_ABS_DIR = os.path.abspath(
        os.path.dirname(os.path.realpath(__file__)) + "/../"
    )
    return _REPO_ABS_DIR


def _GIT(argv) -> Optional[str]:
    try:
        p = subprocess.run(
            ["git"] + argv,
            cwd=REPO_ABS_DIR(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.strip()


_VERSION_STR = None


def GET_VERSION_STR() -> str:
    global _VERSION_STR
    if _VERSION_STR is not None:
        return _VERSION_STR

    toplevel = _GIT(["rev-parse", "--show-toplevel"])
    if toplevel is not None and os.path.realpath(toplevel) == os.path.realpath(
        REPO_ABS_DIR()
    ):
        sha = _GIT(["rev-parse", "--short=7", "HEAD"])
        if sha:
            dirty = _GIT(["status", "--porcelain", "--untracked-files=no"])
            _VERSION_STR = sha + ("-dirty" if dirty else "")
            return _VERSION_STR

    # No usable git repo here (e.g. a pip/nix install) -- fall back to the
    # installed package's version, which poetry-dynamic-versioning already
    # embeds the commit into (see pyproject.toml format-jinja).
    try:
        from importlib import metadata

        for pkg_name in ("pypelinec", "pipelinec"):
            try:
                _VERSION_STR = metadata.version(pkg_name) + " (installed package)"
                return _VERSION_STR
            except Exception:
                continue
    except Exception:
        pass

    _VERSION_STR = "unknown"
    return _VERSION_STR


def GET_COMMAND_LINE_STR() -> str:
    return shlex.join(sys.argv)
