# SPDX-License-Identifier: GPL-3.0-or-later
# The README sells the packages and BUILDING.md carries the build: no command of the README, in a code block or a
# code span, runs a build tool, and BUILDING.md runs a plain make. Prose ("make sure") is not a command and is not read.
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# a command whose first word is one of these, or whose first two are one of the pairs, is a build
TOOLS = {"make", "gmake", "meson", "cmake", "ninja", "rpmbuild", "dpkg-buildpackage", "debuild", "cc", "gcc", "clang",
         "./configure"}
PAIRS = {("pnpm", "build"), ("npm", "build"), ("yarn", "build"), ("cargo", "build"), ("go", "build")}


def commands(text):
    """(line number, command) for every line of an indented or fenced code block and every code span"""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.startswith(("    ", "\t")):
            yield n, line.strip()
        else:
            for span in re.findall(r"`([^`]+)`", line):
                yield n, span.strip()


def words(cmd):
    """the words of a command without a prompt, sudo, run, VAR=value or an [optional] group"""
    cmd = re.sub(r"\[[^]]*\]", " ", cmd)
    return [w for w in cmd.split() if w not in ("$", "sudo", "run") and not re.match(r"^[A-Z_][A-Z0-9_]*=", w)]


def is_build(cmd):
    w = words(cmd)
    return bool(w) and (w[0] in TOOLS or tuple(w[:2]) in PAIRS)


def main():
    failed = 0
    readme = open(os.path.join(ROOT, "README.md")).read()
    for n, cmd in commands(readme):
        if is_build(cmd):
            print("FAIL README.md:%d runs a build: %s (the build steps belong in BUILDING.md)" % (n, cmd))
            failed += 1
    path = os.path.join(ROOT, "BUILDING.md")
    building = open(path).read() if os.path.exists(path) else ""
    # the build itself, make with no target; make test or make gen alone does not say how to build
    if not any(words(cmd) == ["make"] for _, cmd in commands(building)):
        print("FAIL BUILDING.md carries no plain make: the build steps are documented nowhere")
        failed += 1
    if not failed:
        print("ok   README.md runs no build tool and BUILDING.md carries the build")
    return 1 if failed else 0


sys.exit(main())
