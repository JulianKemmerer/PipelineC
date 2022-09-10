import os
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
