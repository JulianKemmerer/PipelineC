# Thanks 
# Discord https://github.com/skmp 
# https://eli.thegreenplace.net/2011/07/03/parsing-c-in-python-with-clang and Victor https://github.com/suarezvictor/!

import sys

import clang.cindex
from clang.cindex import *
from clang.cindex import conf, register_function, c_int, c_object_p

def traverse(node, level):
    print('%s %-35s %-20s %-10s %s ' % (' ' * level,
    node.kind, node.spelling, node.type.spelling, node.mangled_name))
    if node.kind == clang.cindex.CursorKind.CALL_EXPR:
        for arg in node.get_arguments():
            print("ARG=%s %s" % (arg.kind, arg.spelling))
    elif node.kind == clang.cindex.CursorKind.INTEGER_LITERAL:
        eval = conf.lib.clang_Cursor_Evaluate(node)
        if (eval):
            eval = EvalResult(eval)
            print(eval.getAsInt())
    #elif node.kind == clang.cindex.CursorKind.VAR_DECL:
    #    print("VAR_DECL",dir(node))
    #    for arg in node.get_arguments():
    #        print("ARG=%s %s" % (arg.kind, arg.spelling))


    for child in node.get_children():
        traverse(child, level+1)

class EvalResult:
    def __init__(self, ptr):
        self.ptr = ptr

    def __del__(self):
        conf.lib.clang_EvalResult_dispose(self)

    def from_param(self):
      return self.ptr

    def getKind(self):
        return conf.lib.clang_EvalResult_getKind(self)

    def getAsInt(self):
        return conf.lib.clang_EvalResult_getAsInt(self)

register_function(conf.lib, ("clang_Cursor_Evaluate", [Cursor], c_object_p), False) # not quite sure why EvalResult won't work here, seems like some issue with ctypes?
register_function(conf.lib, ("clang_EvalResult_getAsInt", [EvalResult],c_int), False)
register_function(conf.lib, ("clang_EvalResult_getKind", [EvalResult],c_int), False)
register_function(conf.lib, ("clang_EvalResult_dispose", [EvalResult]), False)


def PARSE_FILE(file_name):
    index = clang.cindex.Index.create()
    translation_unit = index.parse(file_name, args=['-std=c++17'])

    #ParseFromCursor(translation_unit.cursor)
    traverse(translation_unit.cursor, 0)


def GET_C_FILE_AST_FROM_PREPROCESSED_TEXT(c_text, c_filename):
    index = clang.cindex.Index.create()
    translation_unit = index.parse(c_filename, args=['-std=c++17'],
                                   unsaved_files=[(c_filename, c_text)],  options=0)


    #If you add PARSE_DETAILED_PROCESSING_RECORD as an option to your call to index.parse() you'll get access to the preprocessor nodes.

    #index = clang.cindex.Index.create()                                                                         
    #tu = index.parse(filename, options=clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

    #ParseFromCursor(translation_unit.cursor)
    traverse(translation_unit.cursor, 0)
    #sys.exit(0)
    return translation_unit.cursor