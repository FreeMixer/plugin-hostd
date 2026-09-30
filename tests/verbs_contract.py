# The daemon routes by instance the commands whose first argument is an instance number. That list is mod-host's
# grammar, not ours: every "<verb> <instance_number>" line of mod-host's README must be a command of verbs.c's table,
# whose verbs are read from mod-host.h. And no verb is spelled in the C sources: a verb of mod-host.h or of
# include/plugin-hostd/protocol.h is read from its declaration, so a C string that starts with one is a copy.
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modhost

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_HOST_DIR = os.environ.get("MOD_HOST_DIR", os.path.join(ROOT, "..", "mod-host"))
# the C sources built against the declarations: the daemon, and the worker the tests run it with
SOURCES = [os.path.join("src", f) for f in sorted(os.listdir(os.path.join(ROOT, "src"))) if f.endswith((".c", ".h"))]
SOURCES.append(os.path.join("tests", "fake_host.c"))
failed = 0


def fail(what):
    global failed
    print("FAIL verbs contract: " + what)
    failed += 1


def strings(text):
    """(line, string) of every C string outside comments; a getopt table names options, not verbs"""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    for n, line in enumerate(text.splitlines(), 1):
        if "_argument" in line:
            continue
        for s in re.findall(r'"((?:[^"\\]|\\.)*)"', line):
            yield n, s


def spelled(text, verbs):
    return [(n, s) for n, s in strings(text) if re.split(r"[ \t%]", s, maxsplit=1)[0] in verbs]


include = modhost.include_dir(MOD_HOST_DIR)
if not os.path.exists(os.path.join(include, "mod-host.h")):
    print("FAIL verbs contract: no mod-host.h in " + include)
    sys.exit(1)
commands = modhost.commands(include)
with open(os.path.join(ROOT, "include", "plugin-hostd", "protocol.h")) as f:
    own = set(re.findall(r'^#define\s+PHD_(?:VERB|EVENT)_\w+\s+"(\w+)"', f.read(), re.M))
verbs = set(commands.values()) | own
if len(commands) < 40 or len(own) < 15:
    fail("found only %d commands in %s and %d verbs and events in protocol.h" % (len(commands), include, len(own)))

# positive control: the scan finds a verb where one is spelled
if not spelled('x = strcmp(verb, "%s");' % commands["EFFECT_BYPASS"], verbs):
    fail("the scan does not find a spelled verb")

for path in SOURCES:
    with open(os.path.join(ROOT, path)) as f:
        for n, s in spelled(f.read(), verbs):
            fail('%s:%d spells "%s": read it from its declaration' % (path, n, s))

with open(os.path.join(ROOT, "src", "verbs.c")) as f:
    table = f.read()
table = table[table.index("g_instance_verbs[]"):table.index("};", table.index("g_instance_verbs[]"))]
names = re.findall(r"\b([A-Z][A-Z0-9_]+)\b", table)
unknown = [m for m in names if m not in commands]
if unknown:
    fail("not commands of mod-host.h: %s" % unknown)
routed = {commands[m] for m in names if m in commands}

readme = os.path.join(MOD_HOST_DIR, "README.md")
if not os.path.exists(readme):
    print("skip verbs contract: no mod-host README at " + readme)
else:
    with open(readme) as f:
        grammar = set(re.findall(r"^\s{4}(\w+) <instance_number>", f.read(), re.M))
    handled = {commands["EFFECT_ADD"], commands["EFFECT_REMOVE"]}
    missing = grammar - handled - routed
    if len(grammar) < 15:
        fail("found only %d verbs in %s" % (len(grammar), readme))
    elif missing:
        fail("not routed by instance: %s" % sorted(missing))
    else:
        print("ok   verbs contract: %d instance verbs of mod-host's README, all routed" % len(grammar))

if failed:
    sys.exit(1)
print("ok   verbs contract: %d commands of mod-host.h and %d verbs and events of protocol.h, none spelled in %d sources"
      % (len(commands), len(own), len(SOURCES)))
