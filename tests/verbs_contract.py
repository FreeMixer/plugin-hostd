# The daemon routes by instance the verbs whose first argument is an instance number. That list is mod-host's
# grammar, not ours: every "<verb> <instance_number>" line of mod-host's README must be in verbs.c's table.
import os, re, sys

readme = os.path.join(os.environ.get("MOD_HOST_DIR", "../mod-host"), "README.md")
if not os.path.exists(readme):
    print("skip verbs contract: no mod-host README at " + readme)
    sys.exit(0)
verbs = set(re.findall(r"^\s{4}(\w+) <instance_number>", open(readme).read(), re.M))
table = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "verbs.c")).read()
table = table[table.index("g_instance_verbs[]"):table.index("};", table.index("g_instance_verbs[]"))]
have = set(re.findall(r'"(\w+)"', table))
handled = {"add", "remove"}
missing = verbs - handled - have
if len(verbs) < 15:
    print("FAIL verbs contract: found only %d verbs in %s" % (len(verbs), readme))
    sys.exit(1)
if missing:
    print("FAIL verbs contract: not routed by instance: %s" % sorted(missing))
    sys.exit(1)
print("ok   verbs contract: %d instance verbs of mod-host's README, all routed" % len(verbs))
