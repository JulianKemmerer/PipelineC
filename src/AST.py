import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(eq=False)
class ASTMeta:
    """Frontend-agnostic source location metadata stored on Logic objects.

    Both the C (pycparser) and Pypeline (python ast) frontends populate this.
    coord_str() and location_text() derive uniform strings from the raw fields
    so formatting is defined once regardless of which frontend produced the node.
    """

    src_file: str  # full source file path
    line: int  # 1-based line number
    col: int  # 0-based column offset
    end_col: Optional[int]  # end column if available (Python AST), else None
    hash_suffix: str = ""  # md5 fragment for C-frontend uniqueness; "" for Pypeline
    raw: Any = None  # original node — escape hatch for C-only deep navigation

    def coord_str(self) -> str:
        """Wire-name-safe location tag, e.g. 'myfile_py_l5_c12_a1b2c3d4'"""
        base = os.path.basename(self.src_file).replace(".", "_")
        end = f"_e{self.end_col}" if self.end_col is not None else ""
        return f"{base}_l{self.line}_c{self.col}{end}{self.hash_suffix}"

    def location_text(self) -> str:
        """Human-readable for error messages, e.g. 'myfile.py:5:12'"""
        return f"{self.src_file}:{self.line}:{self.col}"

    def __eq__(self, other):
        if not isinstance(other, ASTMeta):
            return NotImplemented
        return self.coord_str() == other.coord_str()

    def __hash__(self):
        return hash(self.coord_str())
