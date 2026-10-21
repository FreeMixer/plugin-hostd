# SPDX-License-Identifier: GPL-3.0-or-later
# The answers the daemon serves to the verbs mod-ui sends match the declared host verb table (host_verbs of
# protocol/plugin-hostd.json): a verb required in a profile is never refused, an absent one always is, an optional one
# is answered either way. One daemon per profile, its workers tests/fake-host: as mod-host (FAKE_WORKER=mod-host) for
# the lv2 row, as omx-clap-host (FAKE_WORKER=omx-clap-host) for the clap row, which refuses what omx-clap-host leaves
# to the daemon; the console runs both rows at once. Every row of the table is sent, a line built from the command's
# format in protocol/mod-host.json, so no verb is left out and none is spelled here. A positive control first: the
# checker must find a verb the table calls absent that was answered.
# Usage: host_verbs_contract.py (PLUGIN_HOSTD, FAKE_HOST, PLUGIN_HOSTD_PROTOCOL and ONLY from the environment).
import json, os, stat, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import DECLARED, Daemon, Fail, check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", os.path.join(ROOT, "plugin-hostd")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))
ONLY = os.environ.get("ONLY")
with open(os.path.join(ROOT, "protocol", "mod-host.json")) as f:
    FORMATS = {c["verb"]: c["args"] for c in json.load(f)["commands"]}
TABLE = DECLARED["host_verbs"]
WORDS = {w["name"] for w in DECLARED["host_verb_words"]}
REQUIRED, OPTIONAL, ABSENT = (w["name"] for w in DECLARED["host_verb_words"])
PROFILES = ("lv2", "clap", "console")
# the instances of a profile: (instance, uri, the jack client the fake names it); the console holds both
INSTANCES = {"lv2": [(0, "urn:fake:lv2", "effect_0")], "clap": [(0, "clap:fake#a", "effect_0")],
             "console": [(0, "urn:fake:lv2", "effect_0"), (1, "clap:fake#a", "effect_1")]}
failed = 0


def code(reply):
    words = reply.split()
    return int(words[1]) if len(words) > 1 and words[0] == "resp" and words[1].lstrip("-").isdigit() else None


def line(verb, inst, client, tmp):
    """a line of the verb by its format: the instance for a number first, a port of the instance and one of the system
    for two words, the feature and its value for a word and a number, a directory for any other first word, 0.5 for a
    float"""
    args = FORMATS.get(verb, [])
    if args == ["%s", "%s"]:
        return "%s %s:in_1 system:capture_1" % (verb, client)
    if args == ["%s", "%i"]:
        return "%s processing 1" % verb
    words = [str(inst) if a == "%i" and n == 0 else "1" if a == "%i" else "0.5" if a == "%f" else tmp if n == 0 else "x"
             for n, a in enumerate(args)]
    return " ".join([verb] + words)


def judged(profile, answers, table):
    """the rows the answers break: (verb, word, reply)"""
    bad = []
    for row in table:
        word = row[profile]
        for reply in answers[row["name"]]:
            c = code(reply)
            if c is None or (word == REQUIRED and c < 0) or (word == ABSENT and c >= 0):
                bad.append((row["name"], word, reply))
    return bad


def wrapper(tmp, worker):
    path = os.path.join(tmp, worker)
    with open(path, "w") as f:
        f.write('#!/bin/sh\nFAKE_WORKER=%s exec %s "$@"\n' % (worker, FAKE))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def serve(profile, tmp):
    """every row of the table sent to a daemon of the profile: verb -> the replies, one per instance it names"""
    d = Daemon(EXE, wrapper(tmp, "mod-host"), clap_worker=wrapper(tmp, "omx-clap-host"))
    try:
        for inst, uri, client in INSTANCES[profile]:
            d.ok("add %s %d" % (uri, inst), "resp %d" % inst)
        answers = {}
        for row in TABLE:
            verb = row["name"]
            # a verb that takes a number or two words first is sent once for each instance, any other once
            targets = INSTANCES[profile] if FORMATS.get(verb, [None])[:1] == ["%i"] or FORMATS.get(verb) == ["%s", "%s"] \
                else INSTANCES[profile][:1]
            answers[verb] = []
            for inst, uri, client in targets:
                if verb in ("add", "remove"):
                    continue
                answers[verb].append(d.send(line(verb, inst, client, tmp)))
        # add and remove last: an instance added again, then removed
        answers["add"] = [d.send("add %s %d" % (INSTANCES[profile][0][1], 7))]
        answers["remove"] = [d.send("remove 7")]
        return answers
    finally:
        d.close()


for profile in PROFILES:
    check_name = "served_host_verbs_match_the_table_" + profile
    if ONLY and ONLY != check_name:
        continue
    try:
        check({r[profile] for r in TABLE} <= WORDS, "%s: a word that is not declared" % profile)
        check(len(TABLE) == len({r["name"] for r in TABLE}), "a verb is in the table twice")
        with tempfile.TemporaryDirectory(prefix="host-verbs.") as tmp:
            answers = serve(profile, tmp)
        # positive control: the first required verb called absent must be found
        first = next(r["name"] for r in TABLE if r[profile] == REQUIRED)
        flipped = [dict(r, **{profile: ABSENT}) if r["name"] == first else r for r in TABLE]
        check(any(b[0] == first for b in judged(profile, answers, flipped) + judged(profile, answers, TABLE)),
              "the checker does not find %s answered while the table calls it absent" % first)
        bad = judged(profile, answers, TABLE)
        check(not bad, "%d served answers break the table: %s" % (len(bad), "; ".join(
            "%s is %s, answered %r" % b for b in bad)))
        print("ok   %s (%d verbs, %d required, %d absent)" % (check_name, len(TABLE),
              sum(r[profile] == REQUIRED for r in TABLE), sum(r[profile] == ABSENT for r in TABLE)))
    except Fail as e:
        failed += 1
        print("FAIL %s: %s" % (check_name, e))

print("host verbs contract FAILED (%d)" % failed if failed else "host verbs contract ok")
sys.exit(1 if failed else 0)
