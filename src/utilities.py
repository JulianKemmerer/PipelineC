import os
from shutil import which
from typing import Optional


def GET_TOOL_PATH(tool_exe_name: str) -> Optional[str]:
    w = which(tool_exe_name)
    if w is not None:
        return str(w)
    return None


_REPO_SRC_ABS_DIR = None


def SRC_ABS_DIR():
    # This is the directory for python source files
    # aka site-packages when installed
    global _REPO_SRC_ABS_DIR
    if _REPO_SRC_ABS_DIR:
        return _REPO_SRC_ABS_DIR
    _REPO_SRC_ABS_DIR = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
    return _REPO_SRC_ABS_DIR


_C_INCLUDE_DIR = None


def C_INCLUDE_ABS_DIR():
    global _C_INCLUDE_DIR
    if _C_INCLUDE_DIR:
        return _C_INCLUDE_DIR
    # Default to repo files if running from there
    repo_abs_dir = os.path.abspath(SRC_ABS_DIR() + "/../")
    _C_INCLUDE_DIR = repo_abs_dir + "/include"
    if not os.path.exists(_C_INCLUDE_DIR):
        # Then fall back to include directory on the system
        _C_INCLUDE_DIR = "/usr/include/pipelinec"
        # Error if not found
        if not os.path.exists(_C_INCLUDE_DIR):
            _C_INCLUDE_DIR = None
            raise Exception("Could not find pipelinec include directory!")
    return _C_INCLUDE_DIR
