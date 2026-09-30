# mod-host's protocol as its headers declare it, for the tests that must not spell it: where the build takes the
# headers from (pkg-config when mod-host-protocol is installed, a mod-host checkout otherwise, as the Makefile does),
# the verb of every command of mod-host.h and the codes of host-errors.h.
import os, re, subprocess


def include_dir(mod_host_dir):
    p = subprocess.run([os.environ.get("PKG_CONFIG", "pkg-config"), "--cflags-only-I", "mod-host-protocol"],
                       capture_output=True, text=True)
    if p.returncode == 0:
        for flag in p.stdout.split():
            if os.path.exists(os.path.join(flag[2:], "mod-host.h")):
                return flag[2:]
    return os.path.join(mod_host_dir, "src")


def formats(directory):
    """{macro: format} for every command of mod-host.h"""
    with open(os.path.join(directory, "mod-host.h")) as f:
        return dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', f.read(), re.M))


def commands(directory):
    """{macro: verb} for every command of mod-host.h, the verb being the first word of its format"""
    return {name: fmt.split()[0] for name, fmt in formats(directory).items()}


def errors(directory):
    """{name: code} of host-errors.h"""
    with open(os.path.join(directory, "host-errors.h")) as f:
        return {name: int(code) for name, code in re.findall(r"\b(\w+) = (-?\d+)", f.read())}
