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
`resp <code>` replies, the same `ready!` line.

Building
--------

    make [MOD_HOST_DIR=<mod-host checkout>]

The protocol is mod-host's `libmod-host-protocol.so`, from `pkg-config
mod-host-protocol` when it is installed (mod-host's `make install-lib`),
otherwise from `MOD_HOST_DIR`, a mod-host tree where the library is built if
missing. The daemon needs libc and that library and nothing else.

Running
-------

    plugin-hostd -n -p 5555 [-f 5556] [-c plugin-hostd.conf]

It prints `plugin-hostd ready!` once both ports accept. No worker exists
until the first `add`. `quit` or SIGTERM stops every worker and the daemon;
after a SIGKILL the workers notice the parent gone (`PR_SET_PDEATHSIG`) and
exit.

The settings live in a file, `-c`, `$PLUGIN_HOSTD_CONF` or
`~/.config/plugin-hostd.conf`, one `key value` per line:

    mod_host          mod-host          worker for lv2 (a name on PATH or a path)
    clap_host         omx-clap-host     worker for clap
    lv2_path          $LV2_PATH         where bundles are searched
    state_root        $XDG_RUNTIME_DIR  the daemon's checkpoints and worker logs
    ready_timeout_ms  5000              a worker that does not accept in this long is a failed spawn
    rpc_timeout_ms    5000              a worker that does not answer in this long is killed
    backoff_base_ms   250               respawn backoff, doubling per death in the window
    backoff_max_ms    5000
    storm_deaths      5                 deaths inside the window that end respawning of a placement
    storm_window_ms   60000
    suspect_window_ms 500               a worker that dies this soon after a reply drops the verb it answered; 0 turns it off
    checkpoint_ms     5000              a quiet interval with a changed ledger writes a checkpoint
    pool_max          8                 instances in a pool before a sibling opens

Placement
---------

    add <uri> <instance> [own | pool:<name> | default] [client_name]

`<uri>` is `lv2:<uri>` or a bare URI for an LV2 plugin, `clap:<path>#<id>`
for a CLAP one. The instance number is the controller's and reaches the
worker unchanged. A worker holds one format. `own` is a worker for that
instance alone; its death is the plugin's. `pool:<name>` is the pool's
worker, opened on first use and capped by `pool_config`; a full pool opens
`<name>#2`. `default` is the policy of `policy_set` (built in: `own`). An
own LV2 worker sees one bundle: `LV2_PATH` is a directory of the daemon's
holding a link to the bundle whose `manifest.ttl` names the URI.

A token after the instance that is not a placement is the fork's optional
jack client name, passed on. An instance that crashed in a pool is placed
`own` whatever the hint until `quarantine_clear`.

Verbs the daemon adds
---------------------

    worker_list                              resp <n> <worker>:<pid>:<format>:<state>:<place>:<i>,<i>,...
    instance_info <instance>                 resp 0 <worker> <pid> <state> <crashes> <quarantined>
    supervisor_reset [<worker> | all]        re-arm the storm bound and the backoff of a given-up placement
    quarantine_clear <instance> | all
    policy_set <lv2 | clap | *> <own | pool:<name>>
    pool_config <name> <max_instances>
    worker_env <lv2 | clap | *> <cpu-list|-> <nice|->

`<state>` is `up`, `starting`, `backoff` or `given-up`. A record's place holds
a colon (`pool:p`), so a record is read from both ends: four fields on the
left, the instance list on the right, the place in between.

Codes: `-501` placement invalid, `-502` no worker program for the scheme,
`-503` the worker is not up (spawn failed, or it is in backoff), `-505` the
storm bound is spent for that placement, `-506` no such worker, `-507` the worker died on this very command and the
daemon dropped it (it is not replayed; the `instance_verb_dropped` event names it), and the same event names the
last verb a worker answered when it died inside the suspect window (below). A worker's own
refusal is returned as it said it. An `add` that killed its worker answers
`-102`.

`worker_env` sets the cpu list and the nice value of the workers of a format, at spawn and on the ones running.
It offers no real-time priority: a worker's audio thread is set by the jack client library (under a SCHED_FIFO 60
driver it ran at 55, unasked), and a FIFO priority given to the whole process puts the plugin's own threads above
it, where a busy thread starves the graph.

Like mod-host, the daemon serves one controller at a time, and `remove` of an instance it does not hold answers
`resp 0`. With `-n` and no `-f` there is no feedback port (mod-host's own rule), and a controller need not open
one; without `-n`, or with `-f`, the daemon waits for the controller to open both. A command that finds its
worker gone answers `-503`: the worker is not up, ask again after `instance_restored`. A command that
kills its worker answers `-507`.

Events on the feedback port, one NUL-terminated line each:

    worker_died <worker> <pid> <exit:N | signal:N> <instance>,...
    instance_verb_dropped <instance> <the command as sent>
    instance_verb_dropped <instance> suspect:<ms> <the command as sent>
    worker_backoff <worker> <ms>
    worker_respawned <worker> <pid> <replayed_count> <ms>
    instance_restored <instance> <worker>
    instance_quarantined <instance> <worker>
    supervisor_gave_up <worker> <deaths> <window_ms>

The last verb is a suspect
--------------------------

A plugin that aborts in a callback dies after it answered `resp 0`, so the verb that killed it is in the ledger and
the respawn would play it again until the storm bound ends it. For `suspect_window_ms` after a reply (default 500: the
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
the idle tick for five seconds). What a plugin held in RAM and exposed through no verb (a
reverb tail) is lost.

Who is blamed: a death with a command on the wire names that command's
instance. A death in a callback of a pool cannot be named from outside, so
the pool is split, each member into a worker of its own, and the one that
dies again is named (`instance_quarantined`) and stays own. In a worker of
one instance the death is that instance's. Five deaths inside a minute end
respawning for that placement only (`supervisor_gave_up`); its neighbours are
not touched.

What a worker must do
---------------------

Answer mod-host's protocol on `-n -p <port>`; print a line ending `ready!` on
stdout once its socket accepts; write, for `state_save <dir>`, files whose
names begin `effect_<instance>` and read them back on `state_load <dir>`,
skipping an instance with no file. `mod-host` and `omx-clap-host` do.

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
