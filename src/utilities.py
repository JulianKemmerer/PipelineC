from os.path import abspath, dirname, realpath
from shutil import which
from typing import AnyStr, Optional


def GET_TOOL_PATH(tool_exe_name: str) -> Optional[str]:
    w = which(tool_exe_name)
    if w is not None:
        return str(w)
    return None


def REPO_ABS_DIR() -> AnyStr:
    return abspath(dirname(realpath(__file__)) + "/../")
