plugin-hostd
============

A supervisor for plugin host processes. It speaks mod-host's socket protocol
on the way up and runs one worker process per plugin (or per named pool of
plugins) on the way down, so that a plugin that crashes takes down its own
worker and nothing else, and the daemon puts it back.

    controller ── mod-host protocol ──> plugin-hostd ──> mod-host -n -p <port>      (lv2)
       (unchanged)                          │        └─> omx-clap-host -n -p <port> (clap)
                                            └ ledger, placement, respawn, checkpoints

Audio never passes through the daemon. Every worker is a jack client named
`effect_<instance>` exactly as in mod-host, whichever worker holds it, and
links are made in the graph. The daemon loads no plugin code: no lilv world,
no CLAP entry point. It can only die of its own bugs, and it holds nothing a
controller cannot re-lay.

A controller that talks to mod-host talks to the daemon unchanged: same
ports (command `-p`, feedback `-f`), same NUL-terminated messages, same
`resp <code>` replies, the same readiness line.

The protocol surface the daemon owns (the verbs it adds, the placement syntax, the error codes, the feedback events,
the settings, the readiness line) is declared once, in `include/plugin-hostd/protocol.h`, which the daemon compiles
against. The tables below, the key list of the man page and `protocol/plugin-hostd.json` are generated from that
header (`make gen`; `make check-generated` fails on any drift). A C consumer includes the installed header
(`pkg-config --cflags plugin-hostd`, package `plugin-hostd-devel` or `plugin-hostd-dev`); anything else reads
`/usr/share/plugin-hostd/protocol.json`, described by `protocol/plugin-hostd.schema.json` (`/usr/share/plugin-hostd/protocol.schema.json`, in the development package).

Building
--------

    make [MOD_HOST_DIR=<mod-host checkout>]

The protocol is mod-host's `libmod-host-protocol.so`, from `pkg-config
mod-host-protocol` when it is installed (mod-host's `make install-lib`),
otherwise from `MOD_HOST_DIR`, a mod-host tree where the library is built if
missing. The daemon needs libc and that library and nothing else.

Running
-------

    plugin-hostd -n -p <port> [-f <port>] [-c plugin-hostd.conf]

<!-- BEGIN GENERATED protocol:readiness -->
It prints `plugin-hostd ready!` once both ports accept.
<!-- END GENERATED protocol:readiness -->

No worker exists until the first `add`. `quit` or SIGTERM stops every worker and the daemon;
after a SIGKILL the workers notice the parent gone (`PR_SET_PDEATHSIG`) and exit.

The settings live in a file, `-c`, `$PLUGIN_HOSTD_CONF` or
`~/.config/plugin-hostd.conf`, one `key value` per line:

<!-- BEGIN GENERATED protocol:config -->
| key | default | meaning |
|---|---|---|
| `mod_host` | `mod-host` | worker for lv2 (a name on PATH or a path) |
| `clap_host` | `omx-clap-host` | worker for clap |
| `lv2_path` | `$LV2_PATH`, else `/usr/lib64/lv2:/usr/lib/lv2:/usr/local/lib/lv2` | where bundles are searched |
| `state_root` | `$XDG_RUNTIME_DIR`, else `/tmp` | the daemon's checkpoints and worker logs |
| `ready_timeout_ms` | 5000 ms | a worker that does not accept in this long is a failed spawn |
| `rpc_timeout_ms` | 5000 ms | a worker that does not answer in this long is killed |
| `backoff_base_ms` | 250 ms | respawn backoff, doubling per death in the window |
| `backoff_max_ms` | 5000 ms | the most a respawn backoff grows to |
| `storm_deaths` | 5 deaths | deaths inside the window that end respawning of a placement |
| `storm_window_ms` | 60000 ms | the window storm_deaths are counted in |
| `suspect_window_ms` | 500 ms | a worker that dies this soon after a reply drops the verb it answered; 0 turns it off |
| `checkpoint_ms` | 5000 ms | a quiet interval with a changed ledger writes a checkpoint |
| `idle_ms` | 25 ms | the period of the idle tick: reap, respawn, checkpoint |
| `pool_max` | 8 instances | instances in a pool before a sibling opens |
| `require_pins` | 1  | 1: add admits only a plugin pin_set pinned, its files hashed before any worker sees it; 0: no pin is checked |
<!-- END GENERATED protocol:config -->

<!-- BEGIN GENERATED protocol:constants -->
| name | value | meaning |
|---|---|---|
| `default_command_port` | 5555 port | the command port without -p; the feedback port is the next one, unless -n is given |
| `connect_retry_ms` | 5000 ms | how long the idle tick asks again for a connect a respawned worker could not make yet |
<!-- END GENERATED protocol:constants -->

Placement
---------

<!-- BEGIN GENERATED protocol:placement -->
The placement of an `add` is `own | pool:<name> | default`. `own` is a worker for that instance alone; `pool:<name>` is the pool's worker, opened on first use and capped by `pool_config`, and a full pool opens `<name>#2`, `<name>#3`, and so on; `default` is the policy of `policy_set`. A pool name matches `^[A-Za-z0-9_-]{1,32}$`.
<!-- END GENERATED protocol:placement -->

`<uri>` is `lv2:<uri>` or a bare URI for an LV2 plugin, `clap:<path>#<id>`
for a CLAP one. The instance number is the controller's and reaches the
worker unchanged. A worker holds one format. An own LV2 worker sees one
bundle: `LV2_PATH` is a directory of the daemon's holding a link to the bundle
whose `manifest.ttl` names the URI.

A token after the instance that is not a placement is the fork's optional
jack client name, passed on. An instance that crashed in a pool is placed
`own` whatever the hint until `quarantine_clear`.

Verbs the daemon adds
---------------------

<!-- BEGIN GENERATED protocol:verbs -->
| verb | arguments | reply | meaning |
|---|---|---|---|
| `add` | `<uri> <instance> [own \| pool:<name> \| default] [client_name]` | `resp <instance>` | mod-host's add with a placement; a token after the instance that is not a placement is the jack client name |
| `worker_list` | none | `resp <n> <worker>:<pid>:<format>:<state>:<place>:<i>,<i>,...` | the workers, one record each |
| `instance_info` | `<instance>` | `resp 0 <worker> <pid> <state> <crashes> <quarantined>` | where an instance lives and what it has cost |
| `supervisor_reset` | `[<worker> \| all]` | `resp 0` | re-arm the storm bound and the backoff of a given-up placement |
| `quarantine_clear` | `<instance> \| all` | `resp 0` | let a quarantined instance go back where its placement says |
| `policy_set` | `<lv2 \| clap \| *> own \| pool:<name>` | `resp 0` | the placement of an add that says default |
| `pool_config` | `<name> <max_instances>` | `resp 0` | the instances a pool holds before a sibling opens |
| `worker_env` | `<lv2 \| clap \| *> <cpu-list\|-> <nice\|->` | `resp 0` | the cpu list and the nice value of the workers of a format, at spawn and on the ones running |
| `pin_set` | `<uri> <path>=<sha256>[,<path>=<sha256>...] <scheme>:<sha256>` | `resp 0` | the pin of one plugin: the SHA-256 of every file the host loads for it, a path relative to the bundle (the .clap's directory for a CLAP), and its layout fingerprint; it replaces an earlier pin of the uri |
| `pin_clear` | `<uri> \| all` | `resp 0` | forget the pin of one plugin, or of every one |
| `pin_expect` | `<instance> <scheme>:<sha256>` | `resp 0` | sent by the daemon to a clap worker just before the instance's add: the layout pin that add checks after init and before activate |

A `<state>` is `up` (accepting commands), `starting` (spawned, not yet accepting), `backoff` (dead, waiting to be respawned), `given-up` (the storm bound is spent for its placement).
<!-- END GENERATED protocol:verbs -->

A record's place holds a colon (`pool:p`), so a `worker_list` record is read from both ends: four fields on the
left, the instance list on the right, the place in between.

Error codes the daemon adds to mod-host's:

<!-- BEGIN GENERATED protocol:errors -->
| code | name | meaning |
|---|---|---|
| `-501` | `PHD_ERR_PLACEMENT_INVALID` | placement invalid |
| `-502` | `PHD_ERR_NO_BACKEND` | no worker program for the scheme |
| `-503` | `PHD_ERR_WORKER_SPAWN` | the worker is not up: the spawn failed, or it is in backoff; ask again after instance_restored |
| `-504` | `PHD_ERR_REPLAY` | reserved: not returned as a reply by this version; a replayed add its pin refuses is written to stderr with it and the pin's code |
| `-505` | `PHD_ERR_GAVE_UP` | the storm bound is spent for that placement |
| `-506` | `PHD_ERR_NO_SUCH_WORKER` | no such worker |
| `-507` | `PHD_ERR_VERB_DROPPED` | the worker died on this very command and the daemon dropped it: it is not replayed, and the instance_verb_dropped event names it |
| `-508` | `PHD_ERR_PIN_ABSENT` | require_pins is on and the plugin has no pin, or its layout pin is in a scheme this version does not know: add is refused and no worker sees it |
| `-509` | `PHD_ERR_PIN_BINARY_MISMATCH` | a pinned file is missing or its SHA-256 differs, or the plugin's manifest names a file the pin does not hold: add is refused and no worker sees it |
| `-510` | `PHD_ERR_PIN_LAYOUT_MISMATCH` | the worker found the parameter layout after init differs from the layout pin: the instance is destroyed before activate |
<!-- END GENERATED protocol:errors -->

A worker's own refusal is returned as it said it. An `add` that killed its worker answers mod-host's `-102`.

`worker_env` offers no real-time priority: a worker's audio thread is set by the jack client library (under a SCHED_FIFO 60
driver it ran at 55, unasked), and a FIFO priority given to the whole process puts the plugin's own threads above
it, where a busy thread starves the graph.

Like mod-host, the daemon serves one controller at a time, and `remove` of an instance it does not hold answers
`resp 0`. With `-n` and no `-f` there is no feedback port (mod-host's own rule), and a controller need not open
one; without `-n`, or with `-f`, the daemon waits for the controller to open both. A command that finds its
worker gone answers `PHD_ERR_WORKER_SPAWN`: the worker is not up, ask again after `instance_restored`. A command that
kills its worker answers `PHD_ERR_VERB_DROPPED`.

Events on the feedback port, one NUL-terminated line each:

<!-- BEGIN GENERATED protocol:events -->
| event | fields | meaning |
|---|---|---|
| `worker_died` | `<worker> <pid> <exit:N \| signal:N> <instance>,...` | a worker died; the instances it held, or - for none |
| `instance_verb_dropped` | `<instance> <the command as sent>` | the command a worker died on, dropped from the ledger |
| `instance_verb_dropped` | `<instance> suspect:<ms> <the command as sent>` | the last verb a worker answered when it died inside suspect_window_ms, <ms> the age of the reply |
| `worker_backoff` | `<worker> <ms>` | the respawn waits this long |
| `worker_respawned` | `<worker> <pid> <replayed_count> <ms>` | a worker is back and its ledger replayed |
| `instance_restored` | `<instance> <worker>` | an instance is back in a worker |
| `instance_quarantined` | `<instance> <worker>` | the culprit of a pool death, placed own until cleared |
| `supervisor_gave_up` | `<worker> <deaths> <window_ms>` | the storm bound is spent; respawning ends |
<!-- END GENERATED protocol:events -->

The last verb is a suspect
--------------------------

A plugin that aborts in a callback dies after it answered `resp 0`, so the verb that killed it is in the ledger and
the respawn would play it again until the storm bound ends it. For `suspect_window_ms` after a reply (a setting, above: the
test plugins die 30 ms after it, and the daemon sees the death 40 to 100 ms later) the last verb the ledger kept, of
the instances of a worker, is a suspect. A worker that dies inside the window, of a crash or an exit and not of a
SIGKILL or SIGTERM from outside, has that verb taken out of the ledger: the value it replaced comes back, or the
parameter goes to the plugin's own, and the event `instance_verb_dropped <instance> suspect:<ms> <command>` names it,
`<ms>` being the age of the reply when the death was seen. The instance that sent it is blamed like the one whose
command was in flight: its crash is counted, and in a pool it is quarantined and leaves the pool alone. A death
outside the window replays everything, as before.

What it keeps and replays
-------------------------

Per instance, in memory: the `add` line, then the state-changing verbs as
sent, as text (`param_set`, `patch_set`, `preset_load`, `bypass`,
`param_monitor`, the `midi_`, `cc_` and `cv_` maps), a repeat of the same
setting replacing the earlier one, a `preset_load` dropping the parameter
writes before it; and the `connect`s that name the instance's jack client.
After a `preset_load` or `patch_set`, and after a quiet interval, it asks the
worker for `state_save <dir>` into one checkpoint directory of its own and,
for an instance whose state file is there, drops the verbs the state now
holds.

A worker that dies is respawned after a backoff, and each instance is put
back: `add`, one `state_load` of the checkpoint directory, the verb tail,
the connections (a connect the new client cannot make yet, because the peer's port has not reached it, is asked again by
the idle tick for `connect_retry_ms`). What a plugin held in RAM and exposed through no verb (a
reverb tail) is lost.

Who is blamed: a death with a command on the wire names that command's
instance. A death in a callback of a pool cannot be named from outside, so
the pool is split, each member into a worker of its own, and the one that
dies again is named (`instance_quarantined`) and stays own. In a worker of
one instance the death is that instance's. `storm_deaths` deaths inside `storm_window_ms` end
respawning for that placement only (`supervisor_gave_up`); its neighbours are
not touched.

What a worker must do
---------------------

- answer mod-host's protocol on `-n -p <port>`;
<!-- BEGIN GENERATED protocol:worker-ready -->
- print a line ending `ready!` on stdout once its socket accepts;
<!-- END GENERATED protocol:worker-ready -->
- write, for `state_save <dir>`, files whose names begin `effect_<instance>` and read them back on
  `state_load <dir>`, skipping an instance with no file.

`mod-host` and `omx-clap-host` do.

Tests
-----

    make test

runs the daemon against `tests/fake-host`, a worker that speaks the same
protocol and dies, hangs or refuses on cue: placement, forwarding, the
ledger, replay to the byte, attribution, quarantine, the storm bound,
`worker_env`, and the verb table against mod-host's README. No jack, no plugin.

    make test-jack OMX_CLAP_HOST=<omx-clap-host> [MOD_HOST=<mod-host> LV2_DIR=<lv2 path> LV2_URI=<a stereo effect> LV2_BUNDLE=<its bundle dir> LV2_PARAM=<a control taking 0.25>]

runs `tests/jack_e2e.sh`: the real workers behind the daemon, over jack inside
a PipeWire of its own (private user, net and pid namespace, torn down on
exit), with `tests/stress.clap` (a passthrough that crashes on a parameter
write, spins, keeps state). It kills workers and reads the graph and the audio
level of a neighbouring chain across the kill.

`make sabotage` (`tests/sabotage.py`) breaks the daemon on purpose, one guard at a time, and
requires the named test to go red.
