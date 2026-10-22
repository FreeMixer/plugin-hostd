# SPDX-License-Identifier: GPL-3.0-or-later
# The host verb table (protocol.h's PHD_HOST_VERBS) has a row for every verb a controller sends the daemon, no more and
# no fewer: every command of mod-host's protocol (protocol/mod-host.json, written from mod-host.h), every verb of
# PHD_VERBS a controller sends, and every one of PHD_INSTANCE_VERBS. A row for a verb that none of them declares is a
# verb of Zynthian's mod-ui that mod-host never had, and it is absent from every profile. A verb the daemon answers
# itself is required of every profile, since no worker can take it away. The table is read as the compiler sees it: a
# small program built against the header prints it.
#
#   python3 tests/verb_table.py [<tree>]     the tree whose include/ is read (default: this one)
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ROOT
CC = os.environ.get("CC", "cc")

DUMP = r'''
#include <stdio.h>
#include <string.h>
#include <plugin-hostd/protocol.h>

int main(void)
{
#define X(id, name, meaning) printf("profile\t%s\n", name);
    PHD_HOST_PROFILES(X)
#undef X
#define X(name, source, lv2, clap, console, zynthian) \
    printf("row\t%s\t%s\t%s\t%s\t%s\t%s\n", name, PHD_VERB_SOURCE_##source, PHD_LEVEL_##lv2, PHD_LEVEL_##clap, \
           PHD_LEVEL_##console, PHD_LEVEL_##zynthian);
    PHD_HOST_VERBS(X)
#undef X
#define X(id, name, args, reply, meaning) \
    printf("verb\t%s\t%s\n", name, strstr(meaning, "sent by the daemon") ? "daemon-sends" : "controller-sends");
    PHD_VERBS(X)
#undef X
#define X(id, name, args, reply, ledger, meaning) printf("instance\t%s\n", name);
    PHD_INSTANCE_VERBS(X)
#undef X
    return 0;
}
'''

failed = 0


def fail(what):
    global failed
    print("FAIL verb table: " + what)
    failed += 1


def dump(tree):
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = os.path.join(tmp, "dump.c"), os.path.join(tmp, "dump")
        with open(src, "w") as f:
            f.write(DUMP)
        subprocess.run([CC, "-std=gnu99", "-Wall", "-Werror", "-I" + os.path.join(tree, "include"), "-o", exe, src],
                       check=True)
        return subprocess.run([exe], check=True, capture_output=True, text=True).stdout


profiles, rows, own, instance = [], [], {}, set()
for line in dump(TREE).splitlines():
    f = line.split("\t")
    if f[0] == "profile":
        profiles.append(f[1])
    elif f[0] == "row":
        rows.append((f[1], f[2], dict(zip(profiles, f[3:]))))
    elif f[0] == "verb":
        own[f[1]] = f[2]
    elif f[0] == "instance":
        instance.add(f[1])

with open(os.path.join(ROOT, "protocol", "mod-host.json")) as f:
    commands = {c["verb"] for c in json.load(f)["commands"]}
controller = {v for v, who in own.items() if who == "controller-sends"}
daemon_answers = controller - commands
universe = commands | controller | instance

if len(profiles) != 4 or len(rows) < 60 or len(commands) < 40 or len(controller) < 10 or len(instance) < 8:
    fail("read %d profiles, %d rows, %d mod-host commands, %d controller verbs and %d instance verbs"
         % (len(profiles), len(rows), len(commands), len(controller), len(instance)))

names = [r[0] for r in rows]
for n in sorted({n for n in names if names.count(n) > 1}):
    fail("%s has more than one row" % n)
for n in sorted(universe - set(names)):
    fail("%s is a verb the daemon is sent, with no row in PHD_HOST_VERBS" % n)
for name, source, levels in rows:
    if len(levels) != len(profiles) or set(levels.values()) - {"required", "optional", "absent"}:
        fail("%s: levels %s are not one of required, optional, absent per profile" % (name, levels))
    if name not in universe and (source != "mod-ui" or set(levels.values()) != {"absent"}):
        fail("%s is declared by neither mod-host.h nor protocol.h, so it is a mod-ui verb absent from every profile, "
             "not %s %s" % (name, source, levels))
    if source == "daemon" and name in commands:
        fail("%s is a command of mod-host.h, so the daemon is not its only source" % name)
    if source != "daemon" and name in universe and name not in commands:
        fail("%s is declared by protocol.h alone, so its source is the daemon, not %s" % (name, source))
    if name in daemon_answers and set(levels.values()) != {"required"}:
        fail("%s is answered by the daemon itself, so it is required of every profile, not %s" % (name, levels))

if failed:
    sys.exit(1)
print("ok   verb table: %d rows over %d profiles cover %d mod-host commands, %d controller verbs and %d instance verbs"
      % (len(rows), len(profiles), len(commands), len(controller), len(instance)))
