# SPDX-License-Identifier: GPL-3.0-or-later
# The verbs plugin-hostd declares (data/verbs.json) and the ones omx-clap-core declares for both hosts, held to the
# daemon on its socket:
#   - every verb the declarations give plugin-hostd as required or optional answers a well-formed line, one that its
#     declared format takes, with its declared reply (an optional one may refuse with a code it declares), and a
#     malformed line with a code it declares;
#   - the verbs the daemon answers itself are the declared ones and mod-host's: a word of the binary that the daemon
#     answers without relaying it to its worker, and that no declaration and no mod-host command holds, is red;
#   - a verb both hosts owe answers the same line in the same shape from the daemon and from a worker that speaks for
#     omx-clap-host (tests/fake-host, the worker every test of this tree runs);
#   - one name per number: no refusal number is named by two codes, and each number protocol.h answers is named by a
#     code of plugin-hostd or of omx-clap-core, whose HOST_REPLY_CODES name the numbers both hosts answer.
# omx-clap-core's declarations are read from its package in the contract directory: the first of OMX_CONTRACT_PATH
# (directories that stand where contractdir stands) that holds 3/omx-clap-core, else pkg-config's contractdir. Without
# one the run fails: data/verbs.json requires it. The run names which source it read.
# Usage: verbs_declared.py (PLUGIN_HOSTD, FAKE_HOST, PROTOCOL from the environment, or the tree's own).
import json, os, re, socket, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
import scan_fixture
from harness import Daemon, Fail, check, wait_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.abspath(os.environ.get("PLUGIN_HOSTD", os.path.join(ROOT, "plugin-hostd")))
FAKE = os.path.abspath(os.environ.get("FAKE_HOST", os.path.join(ROOT, "tests", "fake-host")))
OWN = os.environ.get("PLUGIN_HOSTD_VERBS", os.path.join(ROOT, "data", "verbs.json"))
MAJOR = "3"
HOSTD, CLAP_HOST = "plugin-hostd", "omx-clap-host"
failures = []


def fail(what):
    failures.append(what)
    print("FAIL " + what)


# ---------------------------------------------------------------- the declarations

def codes_of(docs):
    """{ITEM.name: (code, resp)} of every codes item of docs"""
    codes = {}
    for doc in docs:
        for name, item in doc.items():
            if isinstance(item, dict) and item.get("kind") == "codes":
                for key, c in item["codes"].items():
                    codes["%s.%s" % (name, key)] = (c["code"], c.get("resp"))
    return codes


def verbs_of(docs, refs):
    """{word: {format, reply, codes: [resp], implementedBy}} of every verbs item of docs, each code resolved over the
    codes items of refs"""
    codes = codes_of(refs)
    out = {}
    for doc in docs:
        for item in doc.values():
            if isinstance(item, dict) and item.get("kind") == "verbs":
                for v in item["verbs"].values():
                    out[v["verb"]] = dict(v, codes=[codes[c["ref"]][1] for c in v.get("codes", [])])
    return out


def check_one_name(own_docs, shared_docs):
    """one name per number: no resp is named by two codes, of one package or of both, and each number protocol.h's
    PHD_ERRORS answers is named by one code of the two packages; the lower package, omx-clap-core, owns the numbers
    both hosts answer and plugin-hostd names only its own"""
    named = {}
    for pkg, docs in (("plugin-hostd", own_docs), ("omx-clap-core", shared_docs)):
        for ref, (code, resp) in codes_of(docs).items():
            if resp is not None:
                named.setdefault(resp, []).append("%s %s (%s)" % (pkg, code, ref))
    for resp, names in sorted(named.items()):
        if len(names) > 1:
            fail("%d has %d names: %s" % (resp, len(names), ", ".join(names)))
    with open(os.path.join(ROOT, "include", "plugin-hostd", "protocol.h")) as f:
        header = f.read()
    # the numbers PHD_ERRORS answers are the rendered OMX_REPLY_*_RESP macros it names; the header defines none of its own
    rendered = {}
    for name in ("omx_clap_core_vocabulary.h", "plugin_hostd_vocabulary.h"):
        with open(os.path.join(ROOT, "include", "plugin-hostd", name)) as f:
            rendered.update({m: int(n) for m, n in re.findall(r"^#define\s+(OMX_REPLY_\w+_RESP)\s+\((-[0-9]+)\)", f.read(), re.M)})
    if re.search(r"^#define\s+PHD_ERR_", header, re.M):
        fail("protocol.h defines a PHD_ERR_ number of its own")
    block = header[header.index("#define PHD_ERRORS(X)"):header.index("/* ---------------------------------------------------------------- verbs */")]
    names = re.findall(r"X\([A-Z0-9_]+, (OMX_REPLY_\w+_RESP), ", block)
    absent = [n for n in names if n not in rendered]
    if absent:
        fail("PHD_ERRORS names %s, which no rendered vocabulary header defines" % absent)
    # the daemon is compiled against the rendered numbers: one that is not the declared resp of its code is a stale render
    for pkg, docs in (("plugin-hostd", own_docs), ("omx-clap-core", shared_docs)):
        for ref, (code, resp) in codes_of(docs).items():
            macro = "OMX_" + re.sub(r"[^A-Za-z0-9]+", "_", code).upper() + "_RESP"
            if resp is not None and macro in rendered and rendered[macro] != resp:
                fail("%s is %d in the rendered header and %d in %s (%s): render again" % (macro, rendered[macro], resp, pkg, ref))
    errors = {rendered[n] for n in names}
    if len(errors) < 20:
        fail("found only %d numbers in protocol.h's PHD_ERRORS" % len(errors))
    unnamed = sorted(errors - set(named))
    if unnamed:
        fail("protocol.h answers %s, which no code of plugin-hostd or omx-clap-core names" % unnamed)
    print("ok   one name per number: %d numbers, %d of protocol.h's, %d of them named by omx-clap-core"
          % (len(named), len(errors), len([r for r in errors if any(n.startswith("omx-clap-core") for n in named.get(r, []))])))


def contract_dirs():
    dirs = [d for d in os.environ.get("OMX_CONTRACT_PATH", "").split(":") if d]
    p = subprocess.run([os.environ.get("PKG_CONFIG", "pkg-config"), "--variable=contractdir", "omx-contract"],
                       capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        dirs.append(p.stdout.strip())
    return dirs


def package(name):
    """the files of a package of the contract directory, and where they were read, or (None, None)"""
    for d in contract_dirs():
        base = os.path.join(d, MAJOR, name)
        manifest = os.path.join(base, "MANIFEST.json")
        if os.path.exists(manifest):
            with open(manifest) as f:
                m = json.load(f)
            docs = []
            for rel in m["files"]:
                with open(os.path.join(base, rel)) as f:
                    docs.append(json.load(f))
            return docs, "%s %s from %s" % (name, m["version"], base)
    return None, None


def owes(verb, host):
    return verb["implementedBy"].get(host) in ("required", "optional")


# ---------------------------------------------------------------- a reply and its declared shape

WORD = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')


def words(line):
    return WORD.findall(line)


def token_rx(token):
    if "..." in token:
        return r"\S+"
    if token.startswith('"') and token.endswith('"'):
        return r'"(?:[^"\\]|\\.)*"'
    parts = re.split(r"(<[^>]+>)", token)
    return "".join(r'(?:"(?:[^"\\]|\\.)*"|[^\s"]+?)' if p.startswith("<") else re.escape(p) for p in parts if p)


def shaped(reply, declared):
    """whether reply is declared's shape: its literal words, one word per placeholder; a count in second place
    (resp <n> or resp <count>) is a whole number and the words after it are that many records"""
    got, want = words(reply), declared.split()
    if len(got) < 2 or got[0] != want[0]:
        return False
    if want[1].startswith("<"):
        if not re.fullmatch(r"[0-9]+", got[1]):
            return False
        rest = want[2:]
        want = want[:2] + rest * int(got[1]) if rest else want
    if len(got) != len(want):
        return False
    return all(re.fullmatch(token_rx(w), g) for g, w in zip(got[1:], want[1:]))


def takes(fmt, line):
    """whether the declared format takes the line: the verb, then a word per conversion, %i a whole number, and more
    words only where it ends in ..."""
    want, got = fmt.split(), words(line)
    if got[0] != want[0]:
        return False
    open_end = want[-1] == "..."
    conv = [w for w in want[1:] if w != "..."]
    if len(got) - 1 < len(conv) or (not open_end and len(got) - 1 != len(conv)):
        return False
    return all(c != "%i" or re.fullmatch(r"-?[0-9]+", g) for c, g in zip(conv, got[1:]))


def code(reply):
    m = re.fullmatch(r"resp (-[0-9]+)", reply)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- the lines

# For each verb plugin-hostd owes, in the order they run: the arguments of a well-formed line, of a malformed one, and
# of lines the verb refuses by its meaning, each of which must answer a code the verb declares. {uri} is the CLAP
# fixture's uri (an add made 1 and 2 of it, and its scan wrote its descriptor and its panel; their first-use pins are
# recorded), 3 is an LV2 instance on mod-host's row, {layout} the fake's layout pin, {sha} the CLAP file's SHA-256.
# pin_accept takes the first-use pin before pin_set replaces it with one of verdict in-process, which lets the members
# share the chain's worker; chain_get and chain_clear read and forget what chain declared; pin_clear runs last.
LINES = {
    "pin_accept": ("{uri}", "", ()),
    "pin_set": ("{uri} controls.clap={sha} {layout} verdict=in-process", "{uri}", ()),
    "worker_list": ("", "x", ()),
    "instance_info": ("1", "1 x", ("99",)),
    "supervisor_reset": ("all", "all x", ("w99",)),
    "quarantine_clear": ("all", "", ("99",)),
    "policy_set": ("clap own", "clap", ("clap pool:",)),
    "pool_config": ("p 4", "p x", ()),
    "worker_env": ("clap - -", "clap", ()),
    "lv2_worker_set": ("urn:example:other auto", "urn:example:other", ()),
    "descriptor_get": ("{uri}", "{uri} x", ("clap:/nowhere.clap#x",)),
    "panel_get": ("{uri}", "", ("clap:/nowhere.clap#x",)),
    "preset_list": ("1", "", ("99", "3")),
    "preset_get": ("1 0", "1", ("99 0", "3 0")),
    "track_info": ('1 "Lead" #112233', "1", ("99 x -",)),
    "remote_pages": ("1", "", ("99",)),
    "remote_page_get": ("1 0", "1", ("99 0",)),
    "param_info": ("1 0", "1", ("99 x",)),
    "note_input": ("1", "", ("99",)),
    "note_on": ("1 0 60 100", "1 0 60", ("99 0 60 100",)),
    "note_off": ("1 0 60 0", "1 0 60", ("99 0 60 0",)),
    "all_notes_off": ("1", "", ("99",)),
    "chain": ("7 1 2", "7", ("8 99", "8 1 1")),
    "chain_get": ("7", "x", ("9",)),
    "chain_clear": ("7", "x", ("7",)),
    "pin_clear": ("all", "", ()),
}
ORDER = list(LINES)


def line(verb, args, ctx):
    return (verb + " " + args.format(**ctx)).strip()


def setup(s):
    """a daemon in front of the fake worker under pin_mode first-use, with two CLAP instances whose scan is done and
    an LV2 one; the first-use pins of the CLAP adds are recorded, so pin_accept takes them"""
    lay = subprocess.check_output([FAKE, "-L"], text=True).strip()
    d = s.daemon(conf={"require_pins": 1, "pin_mode": "first-use"})
    for n in (1, 2):
        d.expect("add %s %d" % (s.clap_uri, n), "resp %d" % n)
    d.expect("add lv2:%s 3" % scan_fixture.LV2_COMPRESSOR, "resp 3")
    wait_for(lambda: d.send("panel_get %s" % s.clap_uri).startswith("resp 0 "), "the scan's descriptor and panel")
    return d, {"uri": s.clap_uri, "layout": lay, "sha": scan_fixture.sha(s.clap)}


def check_verbs(declared):
    s = scan_fixture.Scan(lambda **kw: Daemon(EXE, FAKE, **kw))
    d = None
    try:
        d, ctx = setup(s)
        owed = [v for v in declared if owes(declared[v], HOSTD)]
        missing = [v for v in owed if v not in LINES]
        if missing:
            fail("no well-formed line for %s, which the declarations give plugin-hostd" % missing)
        for verb in sorted((v for v in owed if v in LINES), key=ORDER.index):
            decl = declared[verb]
            good, bad = (line(verb, a, ctx) for a in LINES[verb][:2])
            if not takes(decl["format"], good):
                fail("%s: the well-formed line %r is not what its declared format %r takes" % (verb, good, decl["format"]))
                continue
            r = d.send(good)
            optional = decl["implementedBy"][HOSTD] == "optional"
            if shaped(r, decl["reply"]):
                print("ok   %-16s %-40s -> %s" % (verb, good[:40], r[:60]))
            elif optional and code(r) in decl["codes"]:
                print("ok   %-16s %-40s -> %s (optional: a declared refusal)" % (verb, good[:40], r))
            else:
                fail("%s: %r answers %r, not the declared %r%s" % (verb, good, r, decl["reply"],
                     " or one of %s" % decl["codes"] if optional else ""))
            # a format that ends in ... takes any words past its conversions: the grammar past them is the verb's own
            if not decl["format"].endswith("...") and takes(decl["format"], bad):
                fail("%s: the malformed line %r is one its declared format %r takes" % (verb, bad, decl["format"]))
            for kind, refused in [("malformed", bad)] + [("refused", line(verb, a, ctx)) for a in LINES[verb][2]]:
                r = d.send(refused)
                if code(r) is not None and code(r) in decl["codes"]:
                    print("ok   %-16s %-40s -> %s (declared)" % (verb, refused[:40], r))
                else:
                    fail("%s: the %s %r answers %r, which is none of its declared codes %s"
                         % (verb, kind, refused, r, decl["codes"]))
    except Fail as e:
        fail(str(e))
    finally:
        if d:
            d.close()
        s.close()


# ---------------------------------------------------------------- what the daemon answers itself

def binary_words(exe):
    """every lower-case word the binary holds as a C string: each word the daemon compares a verb with is one"""
    with open(exe, "rb") as f:
        data = f.read()
    return sorted({w.decode() for w in re.findall(rb"(?<=\x00)([a-z][a-z0-9_]{2,40})(?=\x00)", data)})


def answered_by_daemon(candidates):
    """the words whose line the daemon answers without relaying it: a line of eleven words no verb takes, sent with one
    worker up, that never reaches the worker"""
    log = tempfile.mktemp(prefix="plugin-hostd-verbs-log.")
    s = scan_fixture.Scan(lambda **kw: Daemon(EXE, FAKE, **kw))
    d = s.daemon(env={"FAKE_LOG": log})
    try:
        d.expect("add %s 1" % s.clap_uri, "resp 1")
        junk = " ~" * 11
        for w in candidates:
            d.send(w + junk)
        d.send("worker_list")
        with open(log) as f:
            relayed = {l.split(" ", 2)[1] for l in f if l.endswith(junk + "\n")}
        return {w for w in candidates if w not in relayed}
    finally:
        d.close()
        s.close()
        if os.path.exists(log):
            os.unlink(log)


def check_answered(declared):
    with open(os.path.join(ROOT, "protocol", "mod-host.json")) as f:
        modhost = {c["verb"] for c in json.load(f)["commands"]}
    candidates = binary_words(EXE)
    ours = {v for v in declared if owes(declared[v], HOSTD)}
    unseen = ours - set(candidates)
    if unseen:
        fail("positive control: the scan of the binary does not see the declared %s" % sorted(unseen))
    answered = answered_by_daemon(candidates)
    extra = answered - ours - modhost
    if extra:
        fail("the daemon answers %s itself, which no declaration and no mod-host command holds" % sorted(extra))
    relayed = ours - answered
    if relayed:
        fail("declared for plugin-hostd, but the daemon relays them and never answers them: %s" % sorted(relayed))
    if not extra and not relayed:
        print("ok   the daemon answers %d words of its %d itself: the %d declared for it and %d of mod-host's"
              % (len(answered), len(candidates), len(ours), len(answered - ours)))


# ---------------------------------------------------------------- the same line to both hosts

class Worker:
    """tests/fake-host on ports of its own, as a daemon starts it; it answers once a controller holds both"""

    def __init__(self):
        self.port, fb = harness.port_pair()
        self.proc = subprocess.Popen([FAKE, "-p", str(self.port), "-f", str(fb)], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        end = time.monotonic() + 10
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
                self.fb = socket.create_connection(("127.0.0.1", fb), timeout=10)
                break
            except OSError:
                if time.monotonic() > end:
                    raise Fail("the fake worker does not listen on %d and %d" % (self.port, fb))
                time.sleep(0.02)

    def send(self, msg):
        self.sock.sendall(msg.encode() + b"\0")
        buf = b""
        while not buf.endswith(b"\0"):
            c = self.sock.recv(65536)
            if not c:
                raise Fail("the fake worker closed on " + msg)
            buf += c
        return buf[:-1].decode()

    def close(self):
        self.proc.kill()
        self.proc.wait()


def check_both(declared):
    both = [v for v in declared if owes(declared[v], HOSTD) and owes(declared[v], CLAP_HOST) and v in LINES]
    s = scan_fixture.Scan(lambda **kw: Daemon(EXE, FAKE, **kw))
    d = w = None
    try:
        d, ctx = setup(s)
        # the members share a worker under a pin of verdict in-process, as in check_verbs
        d.expect(line("pin_set", LINES["pin_set"][0], ctx), "resp 0")
        w = Worker()
        for n in (1, 2):
            w.send("add %s %d" % (s.clap_uri, n))
        for verb in sorted(both, key=ORDER.index):
            decl = declared[verb]
            good = line(verb, LINES[verb][0], ctx)
            a, b = d.send(good), w.send(good)
            same = (shaped(a, decl["reply"]) and shaped(b, decl["reply"])) or (code(a) is not None and code(a) == code(b))
            if same:
                print("ok   %-16s the same shape from both hosts: %s | %s" % (verb, a[:40], b[:40]))
            else:
                fail("%s: %r answers %r from plugin-hostd and %r from the worker, not one declared shape" % (verb, good, a, b))
    except Fail as e:
        fail(str(e))
    finally:
        if w:
            w.close()
        if d:
            d.close()
        s.close()


def main():
    with open(OWN) as f:
        own_docs = [json.load(f)]
    docs, source = package("omx-clap-core")
    if not docs:
        fail("no omx-clap-core package in OMX_CONTRACT_PATH or the contract directory: data/verbs.json requires it "
             "(%s), its verbs refuse with its HOST_REPLY_CODES" % own_docs[0]["requires"].get("omx-clap-core"))
        return 1
    own = verbs_of(own_docs, own_docs + docs)
    shared = verbs_of(docs, docs)
    print("ok   the shared verbs and codes are read from %s" % source)
    dup = set(shared) & set(own)
    if dup:
        fail("declared by plugin-hostd and by omx-clap-core: %s" % sorted(dup))
    declared = dict(shared, **own)
    check_one_name(own_docs, docs)
    # the words and the formats protocol.h still names for both hosts are omx-clap-core's declarations
    with open(os.path.join(ROOT, "include", "plugin-hostd", "protocol.h")) as f:
        header = f.read()
    word = dict(re.findall(r'^#define\s+(PHD_VERB_\w+)\s+"(\w+)"', header, re.M))
    named = 0
    for macro, verb_macro, rest in re.findall(r'^#define\s+(PHD_VERB_\w+)_FMT\s+(PHD_VERB_\w+) "([^"]*)"', header, re.M):
        verb = word[verb_macro]
        if verb in shared:
            named += 1
            if verb + rest != shared[verb]["format"]:
                fail("protocol.h's %s_FMT is %r, omx-clap-core declares %r" % (macro, verb + rest, shared[verb]["format"]))
    print("ok   protocol.h names %d formats of the shared verbs, as omx-clap-core declares them" % named)
    print("plugin-hostd declares %d verbs, %d of them owed by plugin-hostd" %
          (len(own), len([v for v in own if owes(own[v], HOSTD)])))

    check_verbs(declared)
    check_answered(dict(shared, **declared))
    check_both(declared)

    # positive controls of the shape and the format: a reply or a line that is not the declared one is seen
    for reply, decl, want in (("resp 0", "resp 0", True), ("resp 1", "resp 0", False),
                              ('resp 0 "/x"', 'resp 0 "<path>"', True), ("resp 0 /x", 'resp 0 "<path>"', False),
                              ("resp 2 a:1 b:2", "resp <n> <w>:<p>", True), ("resp 2 a:1", "resp <n> <w>:<p>", False),
                              ("resp 0 w4 1 1,2", "resp 0 <worker> <instance>,... <instance>,...", True)):
        if shaped(reply, decl) != want:
            fail("positive control: %r against %r is %s" % (reply, decl, not want))
    for fmt, l, want in (("chain %i %i ...", "chain 7 1 2", True), ("chain %i %i ...", "chain x 1", False),
                         ("chain_get %i", "chain_get 7 8", False), ("worker_list", "worker_list", True)):
        if takes(fmt, l) != want:
            fail("positive control: %r against %r is %s" % (l, fmt, not want))

    print("verbs declared: %s" % ("FAILED (%d)" % len(failures) if failures else "ok"))
    return 1 if failures else 0


sys.exit(main())
