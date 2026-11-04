# SPDX-License-Identifier: GPL-3.0-or-later
# Where the declared protocol is read from. It is plugin-hostd-protocol's (0.3.0 or later, before 0.4), never this tree's: the
# headers through pkg-config's Cflags of plugin-hostd-protocol, the JSON documents through its variables, and the
# daemon's verbs (verbs.json) from its package of omx-contract's contract directory. Without an installed
# plugin-hostd-protocol, a checkout of it at PROTOCOL_DIR (default ../plugin-hostd-protocol) stands in, as the Makefile
# does. A tree's own include/plugin-hostd/ comes first, so a scratch tree that holds a changed copy of the headers
# (tests/sabotage.py, tests/perturbation.py) is read before the installed ones, as the compiler reads them.
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTOCOL_DIR = os.path.abspath(os.environ.get("PROTOCOL_DIR", os.path.join(ROOT, "..", "plugin-hostd-protocol")))
PACKAGE = "plugin-hostd-protocol"
PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")

# the files of the checkout that stand in for each pkg-config variable
CHECKOUT = {
    "protocoljson": "protocol/plugin-hostd.json",
    "modhostjson": "protocol/mod-host.json",
    "protocolschema": "protocol/plugin-hostd.schema.json",
    "table": "protocol/plugin-hostd-protocol.json",
    "grammar": "grammar/plugin-hostd-protocol.abnf",
    "protocoldoc": "doc/protocol.md",
    "protocolgen": "tools/protocol-gen.c",
}


def _pkg(*args):
    p = subprocess.run([PKG_CONFIG] + list(args) + [PACKAGE], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def installed():
    return _pkg("--exists") is not None


def variable(name):
    """the installed file a variable of plugin-hostd-protocol.pc names, or the checkout's"""
    if installed():
        v = _pkg("--variable=" + name)
        if v:
            return v
    return os.path.join(PROTOCOL_DIR, CHECKOUT[name])


def include_dir():
    """the directory that holds plugin-hostd/protocol.h and mod-host.h, as the compiler finds them"""
    if installed():
        for flag in (_pkg("--cflags-only-I") or "").split():
            if os.path.exists(os.path.join(flag[2:], "plugin-hostd", "protocol.h")):
                return flag[2:]
    return os.path.join(PROTOCOL_DIR, "include")


def header(name, tree=ROOT):
    """plugin-hostd/<name>: the tree's own copy when it holds one, else the library's"""
    own = os.path.join(tree, "include", "plugin-hostd", name)
    return own if os.path.exists(own) else os.path.join(include_dir(), "plugin-hostd", name)


def read_header(name, tree=ROOT):
    with open(header(name, tree)) as f:
        return f.read()


def headers():
    """the library's plugin-hostd/ headers: {name: path}"""
    d = os.path.join(include_dir(), "plugin-hostd")
    return {f: os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".h")}


def contract_dirs():
    dirs = [d for d in os.environ.get("OMX_CONTRACT_PATH", "").split(":") if d]
    p = subprocess.run([PKG_CONFIG, "--variable=contractdir", "omx-contract"], capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        dirs.append(p.stdout.strip())
    return dirs


def verbs_json():
    """the daemon's verbs: PLUGIN_HOSTD_VERBS, else plugin-hostd-protocol's package of the contract directory, else the
    checkout's data/verbs.json"""
    if os.environ.get("PLUGIN_HOSTD_VERBS"):
        return os.environ["PLUGIN_HOSTD_VERBS"]
    for d in contract_dirs():
        f = os.path.join(d, "3", PACKAGE, "verbs.json")
        if os.path.exists(f):
            return f
    return os.path.join(PROTOCOL_DIR, "data", "verbs.json")


def overlay(tree):
    """copy the library's plugin-hostd/ headers into tree/include/plugin-hostd/, where -Iinclude finds them before the
    installed ones; protocol.h includes its rendered headers by quotes, so it reads the copies beside it"""
    dest = os.path.join(tree, "include", "plugin-hostd")
    os.makedirs(dest, exist_ok=True)
    for name, path in headers().items():
        with open(path) as src, open(os.path.join(dest, name), "w") as out:
            out.write(src.read())
    return dest


def render_overlay(tree, verbs):
    """the daemon's verbs of a changed copy (verbs, a verbs.json) rendered as omx-contract renders them for
    plugin-hostd-protocol, into the overlay of tree (overlay() first): the headers the daemon is then built against"""
    import shutil
    import tempfile
    datadir = subprocess.run([PKG_CONFIG, "--variable=datadir", "omx-contract"], capture_output=True, text=True,
                             check=True).stdout.strip()
    work = tempfile.mkdtemp(prefix="plugin-hostd-render.")
    try:
        os.makedirs(os.path.join(work, "data"))
        shutil.copy(verbs, os.path.join(work, "data", "verbs.json"))
        subprocess.run(["sh", os.path.join(datadir, "install-contract-dir.sh"), PACKAGE, "0.0.0", "3", "data",
                        os.path.join(work, "stage"), "data"], cwd=work, check=True, stdout=subprocess.DEVNULL)
        # the installed package of the same name is left out: the staged one replaces it
        others = os.path.join(work, "others", "3")
        os.makedirs(others)
        for d in contract_dirs():
            base = os.path.join(d, "3")
            for pkg in sorted(os.listdir(base)) if os.path.isdir(base) else []:
                if pkg != PACKAGE and not os.path.exists(os.path.join(others, pkg)):
                    shutil.copytree(os.path.join(base, pkg), os.path.join(others, pkg))
        env = dict(os.environ, OMX_CONTRACT_PATH=os.path.join(work, "stage") + ":" + os.path.join(work, "others"))
        subprocess.run([os.environ.get("OMX_CONTRACT", "omx-contract"), "render", "--target", "c", "--package", PACKAGE,
                        "--installed", "--out", os.path.join(tree, "include", "plugin-hostd")], env=env, check=True,
                       stdout=subprocess.DEVNULL)
    finally:
        shutil.rmtree(work, ignore_errors=True)
