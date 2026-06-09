# Thanks Claude
import hashlib
import os
import ast as python_ast

# pycparser imported lazily / optionally since not needed for Pypeline frontend
try:
    from pycparser import c_ast

    HAS_PYCPARSER = True
except ImportError:
    HAS_PYCPARSER = False

import C_TO_LOGIC

# ─────────────────────────────────────────────
# Base class
# ─────────────────────────────────────────────


class ASTNode:
    """Frontend-agnostic wrapper around a raw AST node.
    Each frontend subclass implements the interface methods
    so that elaboration code (AST_TO_LOGIC.py someday) never
    needs to know which frontend produced the node.
    """

    def __init__(self, node, src_file):
        self.node = node  # raw frontend AST node
        self.src_file = src_file

    '''
    def get_input_names(self, parser_state):
        """Return ordered list of input port names for this node.
        e.g. ["expr"] for unary op, ["left", "right"] for binary op,
        or the callee's input list for a function call.
        """
        raise NotImplementedError
    '''


# ─────────────────────────────────────────────
# PipelineC frontend (pycparser)
# ─────────────────────────────────────────────


class PipelineC_ASTNode(ASTNode):
    """Wraps a pycparser c_ast node from the C frontend."""

    """
    def get_input_names(self, parser_state):
        node = self.node

        if not HAS_PYCPARSER:
            raise RuntimeError("pycparser not available")

        # pycparser: children() returns [(name, child), ...]
        # for unary/binary ops and function calls the child names
        # are the port names directly
        input_names = []
        for child in node.children():
            name = child[0]
            input_names.append(name)
        return input_names
    """
    pass


# ─────────────────────────────────────────────
# Pypeline frontend (python ast)
# ─────────────────────────────────────────────


class Pypeline_ASTNode(ASTNode):
    """Wraps a python ast node from the Pypeline frontend."""

    """
    def get_input_names(self, parser_state):
        node = self.node

        if isinstance(node, python_ast.UnaryOp):
            # ~x, -x, not x  ->  single input port named "expr"
            return ["expr"]

        elif isinstance(node, (python_ast.BinOp, python_ast.Compare)):
            # a + b, a > b etc  ->  two input ports named "left", "right"
            return ["left", "right"]

        elif isinstance(node, python_ast.Call):
            # user function call: input names come from the callee's Logic()
            callee_name  = node.func.id
            callee_logic = parser_state.FuncLogicLookupTable[callee_name]
            return list(callee_logic.inputs)

        else:
            raise NotImplementedError(
                f"Pypeline_ASTNode.get_input_names: unsupported node type {type(node)}"
            )
    """

    def coord_str(self):
        node = self.node
        loc_str = f"l{node.lineno}_c{node.col_offset}"
        return loc_str

    def coord_file_str(self):
        file_base = os.path.basename(self.src_file).replace(".", "_")
        return f"{file_base}_{self.coord_str()}"

    # def op_str(self):
    #    node = self.node
