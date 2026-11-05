# SPDX-License-Identifier: GPL-3.0-or-later
# The JSON string literals of the daemon and the probe are spelled by omx-contract's one writer,
# <omxcontract/omx_json_write.h> (omx_json_escape_byte, omx_json_write_string, omx_json_string; RFC 8259: a quote and a
# backslash backslashed, a byte below 0x20 as \b \t \n \f \r or \u00XX, everything else as it is). No C file of this tree
# carries an escape loop of its own: a `\u%04x` format, a \u00 escape written byte by byte or as a literal, the writer's
# switch copied (a `case '"':` that writes a backslash), or a copy of the writer's functions under their names. A loop that
# comes back drifts from the one rule (src/json.c once escaped 0x7f, src/transforms.c did not).
#
# A quoted word of the text protocol (src/lv2.c's quoted(): a control byte becomes a space, a quote and a backslash take
# a backslash) spells no JSON and is not a mark: it writes no \u escape and no switch; nor is a reader's switch, which
# writes the byte an escape stands for (src/transforms.c's read_string).
#
#   python3 tests/no_json_escape_loop.py [<tree>]     red on any loop in the tree (default: this one)
#   python3 tests/no_json_escape_loop.py --self-test  each shape of loop planted in a scratch tree must be red, and a
#                                                     quoted word of the text protocol must not be
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = "omxcontract/omx_json_write.h"

MARKS = [
    (re.compile(r'\\\\u%0?\d*[xX]'), "a \\u%04x format: a JSON escape spelled with printf"),
    (re.compile(r'"\\\\u00'), "a \\u00 literal: a JSON escape typed by hand"),
    (re.compile(r"'\\\\'[^\n]{0,80}'u'"), "a \\u escape written byte by byte"),
    (re.compile(r"case\s+'\"'\s*:[^\n]{0,80}[=(]\s*'\\\\'"), "the writer's switch copied (case '\"' writing a backslash)"),
    (re.compile(r"\bomx_json_(escape_byte|write_string|string)\s*\([^;]*\)\s*\{"), "a copy of the writer's functions"),
]
# where the marks are looked for: every C file of the tree
SCANNED = ("src", "include", "tools", "fuzz", "tests")
SUFFIXES = (".c", ".h")
SKIP = {os.path.join("tests", "no_json_escape_loop.py")}


def c_files(tree):
    out = []
    for d in SCANNED:
        for base, _, files in os.walk(os.path.join(tree, d)):
            for f in sorted(files):
                rel = os.path.relpath(os.path.join(base, f), tree)
                if rel.endswith(SUFFIXES) and rel not in SKIP and HEADER not in rel:
                    out.append(rel)
    return sorted(out)


def loops(tree):
    """every 'path: what' of a JSON escape loop in the tree"""
    found = []
    for rel in c_files(tree):
        with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as f:
            text = f.read()
        for rx, what in MARKS:
            m = rx.search(text)
            if m:
                found.append("%s:%d: %s" % (rel, text.count("\n", 0, m.start()) + 1, what))
    return found


# the shapes that must be red, each the loop a file of this tree or a sibling once carried, and the one that must not
PLANTS = [
    ("src/old_sb_str.c", "the sb_printf loop src/json.c carried",
     'void sb_str(sb_t *b, const unsigned char *p)\n{\n    for (; *p; p++)\n        if (*p < 0x20 || *p == 0x7f)\n'
     '            sb_printf(b, "\\\\u%04x", *p);\n        else\n            sb_put(b, (const char *)p, 1);\n}\n'),
    ("src/old_put_quoted.c", "the putf loop src/transforms.c carried",
     'static void put_quoted(out_t *o, const char *s, size_t n)\n{\n    size_t i;\n    for (i = 0; i < n; i++)\n'
     '    {\n        unsigned char c = (unsigned char)s[i];\n        if (c == \'"\' || c == \'\\\\\')\n            put(o, "\\\\", 1);\n'
     '        else if (c < 0x20)\n            putf(o, "\\\\u%04X", c);\n        else\n            put(o, s + i, 1);\n    }\n}\n'),
    ("src/by_byte.c", "a \\u escape written byte by byte",
     'static size_t esc(unsigned char c, char *out)\n{\n    out[0] = \'\\\\\'; out[1] = \'u\'; out[2] = \'0\'; out[3] = \'0\';\n    return 6;\n}\n'),
    ("include/literal.h", "a \\u00 literal",
     'static inline void ctl(FILE *f, unsigned c) { fputs("\\\\u00", f); fprintf(f, "%02x", c); }\n'),
    ("src/switch_copy.c", "the writer's switch copied",
     'static size_t esc(unsigned char c, char *out)\n{\n    switch (c)\n    {\n    case \'"\': out[0] = \'\\\\\'; out[1] = \'"\'; return 2;\n'
     '    case \'\\\\\': out[0] = \'\\\\\'; out[1] = \'\\\\\'; return 2;\n    default: out[0] = (char)c; return 1;\n    }\n}\n'),
    ("include/writer_copy.h", "a copy of the writer's functions",
     'static inline int omx_json_write_string(FILE *f, const char *s)\n{\n    return fputs(s, f);\n}\n'),
]
NOT_A_MARK = ("src/quoted_word.c", "a quoted word of the text protocol",
              'static void quoted(char *out, size_t size, const char *text)\n{\n    size_t used = 0;\n    out[used++] = \'"\';\n'
              '    for (; *text && used < size - 2; text++)\n    {\n        unsigned char c = *text;\n        if (c < 0x20 || c == 0x7f)\n'
              '            c = \' \';\n        if ((c == \'"\' || c == \'\\\\\') && used + 2 < size - 1)\n            out[used++] = \'\\\\\';\n'
              '        out[used++] = c;\n    }\n    out[used++] = \'"\';\n    out[used] = 0;\n}\n')


def self_test():
    failed = 0
    work = tempfile.mkdtemp(prefix="no-json-escape-loop.")
    try:
        tree = os.path.join(work, "t")
        for d in SCANNED:
            if os.path.isdir(os.path.join(ROOT, d)):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tree, d),
                                ignore=shutil.ignore_patterns("*.o", "corpus", "__pycache__"))
        if loops(tree):
            print("FAIL self-test: the copy of the tree as it is is red: %s" % loops(tree))
            return 1
        for rel, what, text in PLANTS + [NOT_A_MARK]:
            path = os.path.join(tree, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            hits = [l for l in loops(tree) if l.startswith(rel + ":")]
            want = (rel, what, text) != NOT_A_MARK
            if bool(hits) == want:
                print("ok   self-test: %s planted as %s is %s" % (what, rel, "red" if want else "not a mark"))
            else:
                print("FAIL self-test: %s planted as %s is %s" % (what, rel, "not seen" if want else "red: %s" % hits))
                failed += 1
            os.unlink(path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    tree = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    found = loops(tree)
    for l in found:
        print("FAIL a JSON escape loop of its own, not <%s>: %s" % (HEADER, l))
    if found:
        return 1
    print("ok   every JSON string literal is spelled by <%s>: %d C files carry no escape loop" % (HEADER, len(c_files(tree))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
