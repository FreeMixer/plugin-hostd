# SPDX-License-Identifier: GPL-3.0-or-later
# What plugin-hostd shares with omx-contract is read from omx-contract, never typed again here: the probe runner's
# default rates are ORACLE_FLOOR_RATES, and the parameter scales of the protocol are PARAM_SCALES, the same words in
# the same order. Checked twice: against the installed contract (its data and its C header), and against a scratch
# copy of the header with the values changed, where the runner must follow and the generator must refuse to build.
# Usage: contract_derived.py (run from the tree; CC, PKG_CONFIG and PROBE from the environment, or their defaults).
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CC = os.environ.get("CC", "cc")
PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
PROBE = os.path.abspath(os.environ.get("PROBE", os.path.join(ROOT, "plugin-hostd-probe")))
failures = 0


def check(cond, what):
    global failures
    if not cond:
        failures += 1
        print("FAIL contract: " + what)


def pkg(*args):
    return subprocess.run([PKG_CONFIG] + list(args) + ["omx-contract"], capture_output=True, text=True, check=True).stdout.strip()


def contract_data(name):
    """an item of omx-contract's own data, as the installed package lays it out (contract.d/<major>/omx-contract)"""
    base = pkg("--variable=contractdir")
    for major in sorted(os.listdir(base), reverse=True):
        for f in sorted(os.listdir(os.path.join(base, major, "omx-contract"))):
            if f.endswith(".json") and f != "MANIFEST.json":
                with open(os.path.join(base, major, "omx-contract", f)) as fh:
                    data = json.load(fh)
                if name in data:
                    return data[name]
    raise SystemExit("omx-contract declares no %s" % name)


def header():
    for flag in pkg("--cflags").split() + ["-I/usr/include"]:
        if flag.startswith("-I"):
            path = os.path.join(flag[2:], "omxcontract", "omx_contract_limits.h")
            if os.path.exists(path):
                return path
    raise SystemExit("omx-contract's C header is not installed")


def child_rates(probe, tmp):
    """the --rates the runner hands its child when it is given none"""
    seen = os.path.join(tmp, "argv")
    child = os.path.join(tmp, "child.sh")
    with open(child, "w") as f:
        f.write('#!/bin/sh\nprintf "%%s\\n" "$@" > %s\n' % seen)
    os.chmod(child, 0o755)
    plugin = os.path.join(tmp, "x.clap")
    open(plugin, "w").close()
    subprocess.run([probe, "run", "--child", child, "--wall-s", "5", "--out", os.path.join(tmp, "doc.json"), plugin],
                   capture_output=True, text=True, timeout=60)
    args = open(seen).read().split("\n") if os.path.exists(seen) else []
    return args[args.index("--rates") + 1] if "--rates" in args else None


def help_rates(probe):
    p = subprocess.run([probe], capture_output=True, text=True, timeout=10)
    m = re.search(r"--rates R,R,\.\.\.\s+sample rates \(default ([0-9,]+)\)", p.stderr)
    return m.group(1) if m else None


def build_probe(include_first, out):
    cmd = [CC, "-I" + include_first, "-I" + os.path.join(ROOT, "include")] + pkg("--cflags").split() + \
          ["-O2", "-std=gnu99", "-D_GNU_SOURCE", "-DPROBE_VERSION=\"0\"", "-o", out, os.path.join(ROOT, "src", "probe.c")]
    return subprocess.run(cmd, capture_output=True, text=True)


def build_gen(include_first, out):
    cmd = [CC, "-I" + include_first, "-I" + os.path.join(ROOT, "include")] + pkg("--cflags").split() + \
          ["-std=gnu99", "-o", out, os.path.join(ROOT, "tools", "protocol-gen.c")]
    return subprocess.run(cmd, capture_output=True, text=True)


def gen_json(gen):
    p = subprocess.run([gen, "json"], capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout, p.stderr


def main():
    floor = ",".join(str(r) for r in contract_data("ORACLE_FLOOR_RATES")["values"])
    scales = contract_data("PARAM_SCALES")["ids"]
    with open(os.path.join(ROOT, "protocol", "plugin-hostd.json")) as f:
        declared = [s["name"] for s in json.load(f)["param_scales"]]
    check(declared == scales, "the protocol's parameter scales %s are omx-contract's PARAM_SCALES %s" % (declared, scales))

    tmp = tempfile.mkdtemp(prefix="plugin-hostd-contract.")
    try:
        check(child_rates(PROBE, tmp) == floor, "the runner's child gets omx-contract's ORACLE_FLOOR_RATES %s by default, "
              "not %s" % (floor, child_rates(PROBE, tmp)))
        check(help_rates(PROBE) == floor, "the runner's usage names the same default: %s" % help_rates(PROBE))

        # a scratch contract whose floor is other rates: the runner built against it follows, with no edit of its own
        scratch = os.path.join(tmp, "include")
        os.makedirs(os.path.join(scratch, "omxcontract"))
        text = open(header()).read()
        moved = re.sub(r"(#define OMX_ORACLE_FLOOR_RATES_INIT )\{[^}]*\}", r"\1{ 32000, 88200 }", text)
        check(moved != text, "positive control: the scratch header's floor was changed")
        with open(os.path.join(scratch, "omxcontract", "omx_contract_limits.h"), "w") as f:
            f.write(moved.replace("#define OMX_ORACLE_FLOOR_RATES_COUNT 4u", "#define OMX_ORACLE_FLOOR_RATES_COUNT 2u"))
        built = build_probe(scratch, os.path.join(tmp, "probe"))
        check(built.returncode == 0, "the runner builds against the scratch contract: %s" % built.stderr[-400:])
        if built.returncode == 0:
            check(child_rates(os.path.join(tmp, "probe"), tmp) == "32000,88200",
                  "a moved floor moves the runner's default: %s" % child_rates(os.path.join(tmp, "probe"), tmp))

        # the generator builds against the contract as it is and writes its scales; it refuses a word of the
        # protocol's own that is not the contract's, and a contract whose scales are in another order
        built = build_gen(os.path.dirname(os.path.dirname(header())), os.path.join(tmp, "gen"))
        check(built.returncode == 0, "positive control: the generator builds against the contract: %s" % built.stderr[-400:])
        if built.returncode == 0:
            rc, out, err = gen_json(os.path.join(tmp, "gen"))
            check(rc == 0 and [x["name"] for x in json.loads(out)["param_scales"]] == scales,
                  "positive control: the generator writes the contract's scales: rc %d %s" % (rc, err[-200:]))
        own = os.path.join(tmp, "own")
        shutil.copytree(os.path.join(ROOT, "include"), own)
        proto = os.path.join(own, "plugin-hostd", "protocol.h")
        ptext = open(proto).read()
        renamed = ptext.replace('X(LOG, "log", ', 'X(LOG, "logarithmic", ')
        check(renamed != ptext, "positive control: the scratch protocol.h's word was changed")
        with open(proto, "w") as f:
            f.write(renamed)
        built = build_gen(own, os.path.join(tmp, "gen-renamed"))
        if built.returncode == 0:
            rc, out, err = gen_json(os.path.join(tmp, "gen-renamed"))
            check(rc != 0 and "PARAM_SCALES" in err and out == "",
                  "the generator writes nothing for a scale word that is not the contract's: rc %d %r" % (rc, err[-200:]))
        else:
            check(0, "the generator builds with a renamed word, to refuse it when it runs: %s" % built.stderr[-300:])
        swapped = text.replace("OMX_PARAM_SCALES_LOG = 1", "OMX_PARAM_SCALES_LOG = 2").replace(
            "OMX_PARAM_SCALES_STEPPED = 2", "OMX_PARAM_SCALES_STEPPED = 1")
        check(swapped != text, "positive control: the scratch header's scales were swapped")
        with open(os.path.join(scratch, "omxcontract", "omx_contract_limits.h"), "w") as f:
            f.write(swapped)
        built = build_gen(scratch, os.path.join(tmp, "gen-swapped"))
        check(built.returncode != 0 and "PARAM_SCALES" in built.stderr,
              "the generator refuses scales the contract orders otherwise: rc %d %s" % (built.returncode, built.stderr[-300:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("contract: %s" % ("FAILED (%d)" % failures if failures else "ok"))
    return 1 if failures else 0


sys.exit(main())
