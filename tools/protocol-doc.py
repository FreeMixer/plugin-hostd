#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# docs/protocol.md, the wire protocol as a reader outside this tree reads it, written from the data the tree already
# holds and checks: protocol/plugin-hostd.json and protocol/mod-host.json (generated, check-generated), data/verbs.json
# and the headers omx-contract renders from it and from omx-clap-core's package (check-rendered), the three schemas, the
# install rule of the Makefile, the README's generated host-verbs region, and the Path A evidence of
# docs/zynthian/verbs.tsv. Nothing in the page is typed here but headings and sentences that name where a fact comes
# from; a fact that moves in the data moves the page, and `make check-protocol-doc` is red until it is written again.
#
#   tools/protocol-doc.py            prints docs/protocol.md
#   tools/protocol-doc.py --check    exits 1 when docs/protocol.md is not what it prints
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "docs/protocol.md"


def fail(msg):
    sys.exit(f"protocol-doc: {msg}")


def read(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        fail(f"{rel}: {e.strerror}")


def load(rel):
    try:
        return json.loads(read(rel))
    except ValueError as e:
        fail(f"{rel}: {e}")


PHD = load("protocol/plugin-hostd.json")
MOD = load("protocol/mod-host.json")
VERBS = load("data/verbs.json")
SCHEMAS = ["protocol/plugin-hostd.schema.json", "protocol/probe-output.schema.json", "protocol/preset.schema.json"]
VOCAB_H = "include/plugin-hostd/omx_clap_core_vocabulary.h"
SHARED_H = "include/plugin-hostd/omx_clap_core_host_verbs.h"
EVIDENCE = "docs/zynthian/verbs.tsv"


def cell(text):
    """a markdown table cell: pipes escaped, no line break"""
    return str(text).replace("|", "\\|").replace("\n", " ")


def code(text):
    return "`" + cell(text) + "`" if text != "" else "none"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


# ---- reply codes: one name and meaning per number, from the declarations that own it ----

def host_codes():
    """omx-clap-core's HOST_REPLY_CODES as rendered: camel name -> (resp, code word, meaning)"""
    text = read(VOCAB_H)
    out = {}
    for m in re.finditer(r'#define OMX_REPLY_HOST_([A-Z0-9_]+) "([^"]+)"(?: ///< (.*))?\n#define OMX_REPLY_HOST_\1_RESP \((-?\d+)\)',
                         text):
        snake, word, meaning, resp = m.groups()
        parts = snake.lower().split("_")
        camel = parts[0] + "".join(x.capitalize() for x in parts[1:])
        out[camel] = (int(resp), word, meaning or "")
    if not out:
        fail(f"{VOCAB_H}: no HOST_REPLY_CODES")
    return out


HOST_CODES = host_codes()
PHD_CODES = VERBS["PLUGIN_HOSTD_REPLY_CODES"]["codes"]
PHD_ERRORS = {e["code"]: e for e in PHD["errors"]}


def code_name(resp):
    """the name a number is declared under"""
    if resp in PHD_ERRORS:
        return PHD_ERRORS[resp]["name"]
    for camel, (r, word, _) in HOST_CODES.items():
        if r == resp:
            return word
    names = [e["name"] for e in MOD["host_errors"] if e["value"] == resp]
    if names:
        return names[0]
    fail(f"reply code {resp} is declared nowhere")


def resolve(ref):
    group, name = ref.split(".", 1)
    if group == "PLUGIN_HOSTD_REPLY_CODES":
        if name not in PHD_CODES:
            fail(f"data/verbs.json: no {ref}")
        return PHD_CODES[name]["resp"]
    if group == "HOST_REPLY_CODES":
        if name not in HOST_CODES:
            fail(f"{VOCAB_H}: no {ref}")
        return HOST_CODES[name][0]
    fail(f"data/verbs.json: a code ref of an unknown group, {ref}")


def codes_cell(resps):
    return "; ".join(f"{r} {code_name(r)}" for r in resps) if resps else "-"


# ---- the verbs each declaration holds ----

def shared_verbs():
    """omx-clap-core's verbs as rendered: word -> {format, codes, levels by host}"""
    text = read(SHARED_H)
    hosts = re.search(r"#define OMX_HOST_VERB_HOSTS_INIT \{ (.*) \}", text)
    if not hosts:
        fail(f"{SHARED_H}: no OMX_HOST_VERB_HOSTS_INIT")
    hosts = re.findall(r'"([^"]+)"', hosts.group(1))
    macro = {}
    for m in re.finditer(r'#define OMX_VERB_([A-Z0-9_]+) "([^"]*)"', text):
        macro[m.group(1)] = m.group(2)
    out = {}
    for m in re.finditer(r"\{ OMX_VERB_([A-Z0-9_]+), OMX_VERB_\1_FMT, OMX_VERB_\1_REPLY, \{ ([A-Z_, ]+) \} \}", text):
        key = m.group(1)
        levels = [l.strip().replace("OMX_HOST_VERB_", "").lower() for l in m.group(2).split(",")]
        codes = re.search(rf"#define OMX_VERB_{key}_CODES_INIT \{{ ([-0-9, ]*) \}}", text)
        out[macro[key]] = {
            "format": macro.get(f"{key}_FMT", ""),
            "codes": [int(c) for c in codes.group(1).split(",")] if codes else [],
            "hosts": dict(zip(hosts, levels)),
        }
    if not out:
        fail(f"{SHARED_H}: no verb table")
    return out


SHARED = shared_verbs()
DECLARED = {v["verb"]: v for v in VERBS["PLUGIN_HOSTD_VERBS"]["verbs"].values()}
SINCE = VERBS["PLUGIN_HOSTD_VERBS"].get("since", "")
DAEMON_VERBS = {v["name"]: v for v in PHD["verbs"]}
INSTANCE_VERBS = {v["name"]: v for v in PHD["instance_verbs"]}
HOST_VERBS = {v["name"]: v for v in PHD["host_verbs"]}
PROFILES = [p["name"] for p in PHD["host_profiles"]]
MOD_COMMANDS = {c["verb"]: c for c in MOD["commands"]}
MOD_FEEDBACK = {c["verb"]: c for c in MOD["feedback"]}

TYPE = {"%i": "int", "%s": "word", "%f": "float", "...": "..."}


def types_of(fmt):
    """the words after the verb of a format line, as types"""
    words = fmt.split()[1:]
    for w in words:
        if w not in TYPE:
            fail(f'a format word "{w}" that is not %i, %s, %f or ...')
    return " ".join(TYPE[w] for w in words) or "none"


def mod_types(c):
    return " ".join(TYPE[a] for a in c["args"] + (["..."] if c["optional_tail"] else [])) or "none"


def codes_of(verb):
    if verb in DECLARED:
        return [resolve(c["ref"]) for c in DECLARED[verb].get("codes", [])]
    if verb in SHARED:
        return SHARED[verb]["codes"]
    return []


def hosts_of(verb):
    if verb in DECLARED:
        return DECLARED[verb].get("implementedBy", {})
    if verb in SHARED:
        return SHARED[verb]["hosts"]
    return {}


def format_of(verb):
    if verb in DECLARED:
        return DECLARED[verb]["format"]
    if verb in SHARED:
        return SHARED[verb]["format"]
    return ""


def levels_cell(verb):
    row = HOST_VERBS.get(verb)
    if not row:
        return "-"
    levels = [row["levels"][p] for p in PROFILES]
    if len(set(levels)) == 1:
        return f"{levels[0]} (every profile)"
    return ", ".join(f"{p} {l}" for p, l in zip(PROFILES, levels))


# ---- the Path A evidence: mod-ui's verbs on mod-host against plugin-hostd ----

def evidence():
    text = read(EVIDENCE)
    lines = [l for l in text.split("\n") if l]
    head = lines[0].split("\t")
    if len(head) != 6 or head[0] != "verb":
        fail(f"{EVIDENCE}: the header is not verb and five columns")
    rows = {}
    for l in lines[1:]:
        f = l.split("\t")
        if len(f) != 6:
            fail(f"{EVIDENCE}: a row of {len(f)} columns: {f[0]}")
        rows[f[0]] = dict(zip(["verb", "sent", "lv2", "clap", "difference", "fix"], f))
    return head, rows


EVIDENCE_HEAD, EVIDENCE_ROWS = evidence()


def lv2_differs(row):
    """the evidence names a difference on the LV2 worker: its difference column has an LV2: clause"""
    return "LV2:" in row["difference"]


FEEDBACK_WORDS = set(MOD_FEEDBACK) | {e["name"] for e in PHD["events"]}


def rule_notes(verb):
    """the relay rules and host settings whose text names the verb as a command: a word that is also a feedback line
    (param_set) is named by the relay rules as that line, so no relay rule is read for it"""
    out = []
    pat = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(verb)}(?![A-Za-z0-9_])")
    if verb not in FEEDBACK_WORDS:
        for r in PHD["relay"]["rules"]:
            if pat.search(r["meaning"]):
                out.append(f"relay rule {r['name']}: {r['meaning']}")
    for r in PHD["host_settings"]:
        if pat.search(r["meaning"]):
            out.append(f"a host setting ({r['name']}), kept and handed to every new worker: [Host settings](#host-settings)")
    return out


def verdict(verb):
    """same, differs or refused, and the facts that say so"""
    notes = []
    row = HOST_VERBS.get(verb)
    if row and all(row["levels"][p] == "absent" for p in PROFILES):
        kind = "refused"
        notes.append("absent of every profile: refused on purpose")
    elif verb in DAEMON_VERBS or verb in INSTANCE_VERBS:
        kind = "differs"
        decl = DAEMON_VERBS.get(verb) or INSTANCE_VERBS[verb]
        notes.append(f"plugin-hostd declares it: `{decl['arguments']}` → `{decl['reply']}`; {decl['meaning']}")
    elif verb in EVIDENCE_ROWS and lv2_differs(EVIDENCE_ROWS[verb]):
        kind = "differs"
    else:
        kind = "same"
    if verb in EVIDENCE_ROWS:
        notes.append(f"Path A: {EVIDENCE_ROWS[verb]['difference']}")
    if verb not in DAEMON_VERBS and verb not in INSTANCE_VERBS:
        notes += rule_notes(verb)
    return kind, notes


# ---- the groups of the verbs mod-host does not have ----

OURS_GROUPS = [
    ("Placement and supervision", r"^(worker_|instance_info$|supervisor_|quarantine_|policy_set$|pool_|lv2_worker_set$)"),
    ("Pins and qualification", r"^(pin_|estimate$)"),
    ("Chains and plans", r"^(chain|plan)(_|$)"),
    ("Descriptors, panels and the running history", r"^(descriptor_|panel_|history_)"),
    ("Presets and notes, by instance", r"^(preset_|note_|all_notes_off$)"),
]

# the values the example sessions put in place of a word of the grammar; a word not here stays as the grammar says it
SAMPLE = {
    "<instance>": ["0", "1", "2"],
    "<chain>": ["1"],
    "<uri>": ["clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp"],
    "<worker>": ["w1"],
    "<name>": ["fx"],
    "<max_instances>": ["4"],
    "<index>": ["0"],
    "<channel>": ["0"],
    "<key>": ["60"],
    "<velocity>": ["100"],
    "<format>": ["clap"],
    "<cpu-list>": ["-"],
    "<nice>": ["-"],
}

# a verb whose words take other values than SAMPLE's
SAMPLE_BY_VERB = {
    "lv2_worker_set": {"<uri>": ["lv2:urn:openmixer:comp"], "<mod-host>": ["omx-clap-host"]},
}


def first_alternative(text):
    """the grammar with each [optional] part dropped and each a | b | ... reduced to its first alternative"""
    text = re.sub(r"\s*\[[^\[\]]*\]", "", text)
    out = []
    for word in re.split(r"\s+(?![^<]*>)", text.strip()):
        out.append(word)
    s = " ".join(out)
    s = re.sub(r"<([^<>|]+?)\s*\|[^<>]*>", r"<\1>", s)  # <a | b> inside one placeholder
    parts = [p.strip() for p in re.split(r"\s+\|\s+(?![^<]*>)", s)]
    return parts[0] if parts else ""


def example(verb, decl):
    args = first_alternative(decl["arguments"]) if decl["arguments"] else ""
    used = {}

    def take(m):
        w = m.group(0)
        vals = SAMPLE_BY_VERB.get(verb, {}).get(w) or SAMPLE.get(w)
        if not vals:
            return w
        i = used.get(w, 0)
        used[w] = i + 1
        return vals[min(i, len(vals) - 1)]

    line = (verb + " " + re.sub(r"<[^<>]+>", take, args)).strip()
    if verb in ("chain", "plan"):
        line += " 1"
    return line, decl["reply"]


def ours_group(verb):
    for title, pat in OURS_GROUPS:
        if re.search(pat, verb):
            return title
    fail(f"{verb}: in no group of OURS_GROUPS; give it one")


# ---- the page ----

def install_names():
    """protocol/<file> -> the installed path, from the Makefile's install_protocol rule"""
    out = {}
    for m in re.finditer(r"install -m 644 (protocol/\S+) \$\(DESTDIR\)\$\(DATADIR\)/(\S+)", read("Makefile")):
        out[m.group(1)] = "/usr/share/" + m.group(2)
    return out


def host_verbs_levels():
    """the definition of required, optional and absent, as the README's generated host-verbs region states it"""
    region = re.search(r"<!-- BEGIN GENERATED protocol:host-verbs -->(.*?)<!-- END GENERATED protocol:host-verbs -->",
                       read("README.md"), re.S)
    if not region:
        fail("README.md: no protocol:host-verbs region")
    m = re.search(r"(`required` is answered.*?)$", region.group(1), re.M)
    if not m:
        fail("README.md: the host-verbs region does not define its levels")
    return m.group(1).strip()


def constant(name):
    for c in PHD["constants"]:
        if c["name"] == name:
            return c
    fail(f"protocol/plugin-hostd.json: no constant {name}")


def page():
    o = []
    w = o.append
    w("<!-- GENERATED by tools/protocol-doc.py from protocol/*.json, data/verbs.json, include/plugin-hostd/omx_clap_core_*.h,")
    w("     the Makefile, README.md and docs/zynthian/verbs.tsv. Do not edit: `make protocol-doc` writes it, and")
    w("     `make check-protocol-doc` fails when it differs. -->")
    w("")
    w("The plugin-hostd wire protocol")
    w("==============================")
    w("")
    w(f"Protocol `{PHD['protocol']}`, version {PHD['version']} of its JSON declaration (`protocol/plugin-hostd.json`); "
      f"mod-host's protocol as the daemon models it is `protocol/{MOD['protocol']}.json`, version {MOD['version']}, written "
      f"from the mod-host headers {', '.join('`' + h + '`' for h in MOD['headers'])} the daemon is built against. "
      f"The verbs the daemon adds are declared in `data/verbs.json` (since {SINCE}, requiring "
      + ", ".join(f"{k} {v}" for k, v in VERBS["requires"].items()) + ").")
    w("")

    # 1. transport
    port = constant("default_command_port")
    w("1. Transport")
    w("------------")
    w("")
    rows = [
        ["command port", f"TCP, {port['value']} without `-p`", port["meaning"]],
        ["feedback port", "TCP", "the next port after the command port, unless -n is given; `-f <port>` names it"],
        ["daemon ready", code(PHD["readiness"]["daemon_line"]), "printed on stdout once both ports accept"],
        ["worker ready", code(PHD["readiness"]["worker_marker"]), "the end of the line a worker prints once its socket accepts"],
        ["worker command line", code(PHD["relay"]["worker_arguments"]), "how the daemon starts every worker"],
    ]
    for name in ("line_max", "line_words_max"):
        c = constant(name)
        rows.append([name, f"{c['value']} {c['unit']}", c["meaning"]])
    rows.append(["string_max", f"{PHD['string_max']} bytes", "the longest string word"])
    w("\n".join(table(["what", "value", "meaning"], [[cell(a), cell(b), cell(c)] for a, b, c in rows])))
    w("")
    w("A command is one line of words, the verb first; a reply is `resp <code> [...]`: the words after the code are the "
      "verb's reply grammar below, and a negative code is a refusal, named in [Reply codes](#reply-codes). Events go out "
      "on the feedback port, one line each (README.md, Events).")
    w("")
    w("Discovery: the daemon declares itself in files, not on the socket. The verb tables below are installed as:")
    w("")
    names = install_names()
    w("\n".join(table(["file in this tree", "installed as"],
                      [[code(k), code(v)] for k, v in sorted(names.items())])))
    w("")
    w("`pkg-config --variable=protocoldir plugin-hostd` names that directory. The `protocol` and `version` keys of the "
      "protocol JSON identify it; " + ("no verb below answers a version." if not any(
          "version" == v for v in list(DAEMON_VERBS) + list(MOD_COMMANDS)) else "the version verb answers it."))
    w("")

    # 2. mod-host's verbs
    w("2. mod-host's verbs on plugin-hostd")
    w("-----------------------------------")
    w("")
    w(host_verbs_levels())
    w("")
    w("Answer: `same` is relayed to the worker that holds the instance (any other verb to every worker) and answered as "
      "that worker answers it; `differs` is a verb plugin-hostd declares a grammar or a behaviour of its own for, or one "
      "the Path A run observed answered otherwise on the LV2 worker; `refused` is absent of every profile. The argument "
      "types are mod-host's templates (`int` %i, `word` %s, `float` %f, `...` an optional tail); the declarations carry "
      "no unit per argument, and a range or a unit a verb has is in its meaning.")
    w("")
    relayed = [PHD_ERRORS[resolve("PLUGIN_HOSTD_REPLY_CODES." + n)] for n in ("workerSpawn", "verbDropped")]
    w("mod-host's templates name no reply codes per verb: a relayed verb answers what its worker answers, or one of "
      + " or ".join(f"{e['code']} {e['name']} ({e['meaning']})" for e in relayed) + ".")
    w("")
    counts = {"same": 0, "differs": 0, "refused": 0}
    by_level = {}
    for c in MOD["commands"]:
        row = HOST_VERBS.get(c["verb"])
        lvl = row["levels"][PROFILES[0]] if row else "-"
        by_level.setdefault(lvl, []).append(c)
    titles = {"required": "Required of every profile", "optional": "Optional", "absent": "Absent: refused on purpose",
              "-": "Not in the host verb table"}
    for lvl in ("required", "optional", "absent", "-"):
        if lvl not in by_level:
            continue
        w(f"### {titles[lvl]}")
        w("")
        rows = []
        for c in by_level[lvl]:
            kind, notes = verdict(c["verb"])
            counts[kind] += 1
            rows.append([code(c["verb"]), cell(mod_types(c)), cell(levels_cell(c["verb"])), kind,
                         cell("<br>".join(notes) if notes else "-")])
        w("\n".join(table(["verb", "mod-host arguments", "levels", "answer", "what the data says"], rows)))
        w("")
    extra = [v for v in HOST_VERBS.values() if v["source"] == "mod-ui" and v["name"] not in MOD_COMMANDS]
    if extra:
        w("Verbs of Zynthian's mod-ui that are no mod-host command, each refused:")
        w("")
        w("\n".join(table(["verb", "levels", "Path A"],
                          [[code(v["name"]), cell(levels_cell(v["name"])),
                            cell(EVIDENCE_ROWS[v["name"]]["difference"] if v["name"] in EVIDENCE_ROWS else "-")]
                           for v in extra])))
        w("")
    w("### The Path A evidence")
    w("")
    w(f"`{EVIDENCE}`: every verb Zynthian's mod-ui sends, replayed against mod-host and against plugin-hostd. The column "
      "heads name the versions that ran; the rows are what was observed then, not run again by this page.")
    w("")
    w("\n".join(table([cell(h) for h in EVIDENCE_HEAD[:5]],
                      [[code(r["verb"]), cell(r["sent"]), cell(r["lv2"]), cell(r["clap"]), cell(r["difference"])]
                       for r in EVIDENCE_ROWS.values()])))
    w("")

    # 3. ours only
    w("3. Verbs mod-host does not have")
    w("-------------------------------")
    w("")
    w("Each is declared in `protocol/plugin-hostd.json`; the formats, codes and hosts come from `data/verbs.json`, or "
      "from omx-clap-core's verb table for a verb the two hosts share. A verb whose meaning begins \"sent by the daemon "
      "to a worker\" is the daemon's to a worker, never a controller's.")
    w("")
    ours = [v for v in list(PHD["verbs"]) + list(PHD["instance_verbs"]) if v["name"] not in MOD_COMMANDS]
    groups = {}
    for v in ours:
        groups.setdefault(ours_group(v["name"]), []).append(v)
    for title, _ in OURS_GROUPS:
        if title not in groups:
            continue
        w(f"### {title}")
        w("")
        rows = []
        for v in groups[title]:
            hosts = ", ".join(f"{h} {l}" for h, l in hosts_of(v["name"]).items()) or "-"
            fmt = format_of(v["name"])
            rows.append([code(v["name"]), code(v["arguments"]), cell(types_of(fmt) if fmt else "-"), code(v["reply"]),
                         cell(codes_cell(codes_of(v["name"]))), cell(SINCE if v["name"] in DECLARED else "-"),
                         cell(hosts), cell(v["meaning"])])
        w("\n".join(table(["verb", "arguments", "types", "reply", "codes", "since (the group's)", "hosts", "meaning"], rows)))
        w("")
        for v in groups[title]:
            line, reply = example(v["name"], v)
            w(f"`{v['name']}`:")
            w("")
            w("```")
            w(f"> {line}")
            w(f"< {reply}")
            w("```")
            w("")

    # events
    w("4. Events and feedback")
    w("----------------------")
    w("")
    w("mod-host's feedback lines, relayed as the worker wrote them:")
    w("")
    w("\n".join(table(["line", "arguments"], [[code(f["verb"]), cell(mod_types(f))] for f in MOD["feedback"]])))
    w("")
    w("The daemon's events and the worker lines it relays:")
    w("")
    w("\n".join(table(["event", "fields", "meaning"],
                      [[code(e["name"]), code(e["fields"]), cell(e["meaning"])] for e in PHD["events"]])))
    w("")
    w("The relay rules:")
    w("")
    for r in PHD["relay"]["rules"]:
        w(f"- {r['name']}: {r['meaning']}")
    w("")
    w("### Host settings")
    w("")
    for r in PHD["host_settings"]:
        w(f"- {r['name']}: {r['meaning']}")
    w("")

    # codes
    w("Reply codes")
    w("-----------")
    w("")
    w("mod-host's parse refusals (`protocol.h`): " + "; ".join(
        f"{e['code']} {e['name']} ({e['message']})" for e in MOD["protocol_errors"]) + ".")
    w("")
    w("mod-host's reply codes (`host-errors.h`): " + "; ".join(
        f"{e['value']} {e['name']}" for e in MOD["host_errors"]) + ".")
    w("")
    w("The codes omx-clap-host answers too (omx-clap-core's `reply.host.*`):")
    w("")
    w("\n".join(table(["resp", "code", "meaning"],
                      [[str(r), code(word), cell(meaning)] for r, word, meaning in sorted(HOST_CODES.values(),
                                                                                         key=lambda x: -x[0])])))
    w("")
    w("The codes the daemon adds:")
    w("")
    w("\n".join(table(["resp", "name", "meaning"],
                      [[str(e["code"]), code(e["name"]), cell(e["meaning"])] for e in PHD["errors"]])))
    w("")

    # documents
    w("5. JSON documents")
    w("-----------------")
    w("")
    rows = []
    for s in SCHEMAS:
        d = load(s)
        fmt = d.get("properties", {}).get("format", {})
        fmt = fmt.get("const") or ", ".join(fmt.get("enum", [])) or "-"
        rows.append([code(s), code(names.get(s, "-")), code(d.get("$id", "-")), cell(d.get("title", "-")), cell(fmt),
                     cell(d.get("description", "-"))])
    w("\n".join(table(["schema", "installed as", "$id", "title", "format", "description"], rows)))
    w("")
    w(f"Counts: {len(MOD['commands'])} mod-host commands, {counts['same']} same, {counts['differs']} differs, "
      f"{counts['refused']} refused; {len(ours)} verbs mod-host does not have.")
    return "\n".join(o) + "\n", counts, len(ours)


def main():
    text, counts, ours = page()
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        try:
            with open(os.path.join(ROOT, OUT), encoding="utf-8") as f:
                have = f.read()
        except OSError:
            have = None
        if have != text:
            sys.exit(f"{OUT} is not what tools/protocol-doc.py writes: run make protocol-doc")
        print(f"{OUT} is current")
        return
    if len(sys.argv) > 1:
        fail(f"usage: {sys.argv[0]} [--check]")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
