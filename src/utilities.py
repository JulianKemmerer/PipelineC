"""Small helpers every compiler module may import (tool lookup, shell commands, repo
paths, version string, regex matching). They import nothing from the compiler, so any
module can use them without joining an import cycle. No design doc of its own.
"""

import os
import re
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


def INDEX_BIT_WIDTH(num_elements: int) -> int:
    # Unsigned bits to index 0..num_elements-1, never 0 (no uint0_t for 1-element arrays)
    # Integer math, math.log(2**29, 2) float rounding would give 30
    return max(1, (num_elements - 1).bit_length())


_REPO_ABS_DIR = None


def REPO_ABS_DIR():
    global _REPO_ABS_DIR
    if _REPO_ABS_DIR:
        return _REPO_ABS_DIR
    _REPO_ABS_DIR = os.path.abspath(
        os.path.dirname(os.path.realpath(__file__)) + "/../"
    )
    return _REPO_ABS_DIR


def DISPLAY_SOURCE(source):
    """Portable source paths in generated HDL; absolute paths remain in index."""
    # abspath (not REPO_ABS_DIR's realpath): design paths are compared unresolved
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if source.startswith(root + os.sep):
        return os.path.relpath(source, root)
    # Synthetic sources and external designs do not embed the scratch root.
    return os.path.basename(source)


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


def GET_SHELL_CMD_OUTPUT(cmd_str, cwd="."):
    # Kill pid after
    process = subprocess.Popen(
        cmd_str, shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd
    )
    # print("Reading from ",cmd_str, flush=True)
    outs, errs = process.communicate()
    output_text = str(outs.decode(encoding="utf-8", errors="replace"))
    err_text = str(errs.decode(encoding="utf-8", errors="replace"))
    # output_text = str(process.stdout.read().decode(encoding="utf-8",errors="replace"))
    # err_text = str(process.stderr.read().decode(encoding="utf-8",errors="replace"))
    # For some reason vivado likes to stay alive? Be sure to kill?
    # os.kill(process.pid, signal.SIGTERM)
    # process.wait()
    if process.returncode != 0:
        e_text = ""
        e_text += "Command failed:" + "\n"
        e_text += cmd_str + "\n"
        e_text += err_text + "\n"
        e_text += output_text + "\n"
        raise Exception(e_text)
    # print("Reading DONE ",cmd_str, flush=True)
    return output_text


# Cached absolute path of the src/ directory holding the compiler modules
_EXE_ABS_DIR = None


def EXE_ABS_DIR():
    global _EXE_ABS_DIR
    if _EXE_ABS_DIR:
        return _EXE_ABS_DIR
    _EXE_ABS_DIR = os.path.dirname(os.path.realpath(__file__))
    return _EXE_ABS_DIR


def FIND_REGEX_MATCHES(regex, text):
    p = re.compile(regex)
    matches = p.findall(text)
    matches = list(set(matches))
    return matches
