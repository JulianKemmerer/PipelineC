"""The one place this project reaches the Pypeline library from.

Every file here is run directly -- by `pypelinec`, or as a plain script -- and
never imported as part of a package, so each needs `include/pypeline` (and, for
the scripts that call `sim_call` themselves, `src`) on `sys.path` before it can
`from pypeline import ...`. Importing this module is that one line:

    import pdw_paths  # noqa: F401  (sys.path side effect)

Sibling modules need no path work of their own: the directory holding the
script being run is already on `sys.path`, and every module of this project
now lives in that one directory.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# pdw -> dsp -> pypeline -> examples -> repo root
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))

for _d in (os.path.join(ROOT, "src"), os.path.join(ROOT, "include", "pypeline"), HERE):
    if _d not in sys.path:
        sys.path.insert(0, _d)
