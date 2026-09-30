plugin-hostd
============

plugin-hostd runs your LV2 and CLAP audio plugins, each in a worker process of its own, and
puts back any worker that dies. A plugin that crashes takes down its own worker and nothing
else. It is for anyone who runs plugins live on Linux, on a mixing console, a stage rig or a
Raspberry Pi, and cannot let one bad plugin stop the show.

- A crash stays small: the plugin's worker is respawned with its settings put back.
- Nothing to change in your controller: it speaks mod-host's socket protocol, same ports, same replies.
- LV2 (through mod-host) and CLAP (through omx-clap-host) side by side.
- Audio never passes through the daemon; every worker is a JACK client, as in mod-host.
- A plugin that keeps crashing is singled out and given up on without touching its neighbours.

Install
-------

Fedora:

    sudo dnf config-manager addrepo --from-repofile=https://freemixer.github.io/rpm/freemixer.repo
    sudo dnf install plugin-hostd omx-clap-host

Debian and Raspberry Pi OS: add the apt line from <https://freemixer.github.io>, then

    sudo apt install plugin-hostd omx-clap-host

The LV2 worker is mod-host, which Debian does not package; without it CLAP plugins still work.

Try it
------

Start the daemon (it prints `plugin-hostd ready!`), with pin checking off for a first try:

    echo 'require_pins 0' > plugin-hostd.conf
    plugin-hostd -n -p 5555 -c plugin-hostd.conf

In another terminal, add an LV2 plugin, set its gain and ask where it runs
(messages end in a NUL byte, which `printf` adds):

    send() { printf '%s\0' "$1" | nc -w3 127.0.0.1 5555 | tr '\0' '\n'; }
    send "add http://plugin.org.uk/swh-plugins/amp 0"      # resp 0
    send "param_set 0 gain 6"                              # resp 0
    send "param_get 0 gain"                                # resp 0 6.0000
    send "worker_list"                                     # resp 1 w1:<pid>:lv2:up:own:0

The plugin now runs as JACK client `effect_0` in its own process. Link it in your graph as
you would a mod-host plugin. `man plugin-hostd` has the options; the full protocol is below.

Building from source: see [BUILDING.md](BUILDING.md). More about FreeMixer at <https://freemixer.github.io>.

Protocol
--------

The verbs the daemon adds, the placement syntax, the error codes, the feedback events and the
settings are declared once in `include/plugin-hostd/protocol.h`; the tables here, the man page's
key list and `protocol/plugin-hostd.json` are generated from it. A C program includes the installed
header (`pkg-config --cflags plugin-hostd`, package `plugin-hostd-devel` or `plugin-hostd-dev`); anything
else reads `/usr/share/plugin-hostd/protocol.json`.

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
| `require_pins` | 1  | 1: add admits only a plugin pin_set pinned, its files hashed before any worker sees it, and an lv2 plugin gets a worker of its own, its world the one bundle the pin holds (a default that resolves to a pool is placed own); 0: no pin is checked |
<!-- END GENERATED protocol:config -->

<!-- BEGIN GENERATED protocol:constants -->
| name | value | meaning |
|---|---|---|
| `default_command_port` | 5555 port | the command port without -p; the feedback port is the next one, unless -n is given |
| `connect_retry_ms` | 5000 ms | how long the idle tick asks again for a connect a respawned worker could not make yet |
| `line_max` | 4096 bytes | the protocol socket's buffer: the longest pin_set line the daemon takes |
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
| `pin_expect` | `<instance> <scheme>:<sha256>` | `resp 0` | sent by the daemon to a clap worker just before the instance's add: the layout pin that add checks after init and before activate; any other reply than resp 0 refuses the add with that code, and the add is never forwarded |

A `<state>` is `up` (accepting commands), `starting` (spawned, not yet accepting), `backoff` (dead, waiting to be respawned), `given-up` (the storm bound is spent for its placement).
<!-- END GENERATED protocol:verbs -->

A record's place holds a colon (`pool:p`), so a `worker_list` record is read from both ends: four fields on the
left, the instance list on the right, the place in between.

Verbs a worker answers, by instance
-----------------------------------

What a host knows of a strip and of a plugin's controls. For a CLAP instance the daemon routes them like mod-host's
instance verbs and passes the worker's reply through; the worker answers them from the plugin (`clap.track-info`,
`clap.remote-controls`, `clap.params`). For an LV2 instance the daemon answers them itself, never forwarding them, so
mod-host learns none of them: `track_info` is kept and answered `resp 0`, an LV2 plugin has no remote pages, and
`param_info` answers `-511` until the daemon reads the bundle's port data. When a CLAP plugin changes its pages, its
worker writes `remote_pages_changed <instance>` on its feedback port and the daemon relays it.

<!-- BEGIN GENERATED protocol:instance-verbs -->
| verb | arguments | reply | meaning |
|---|---|---|---|
| `track_info` | `<instance> <name> <#RRGGBB \| -> [bus \| return \| master]` | `resp 0` | the strip's name ("" for none), colour and kind, absent for an input channel; a clap plugin reads them through clap.track-info; any other word is -902 |
| `remote_pages` | `<instance>` | `resp <count>` | the plugin's remote-control pages, from clap.remote-controls; 0 for an lv2 instance |
| `remote_page_get` | `<instance> <page>` | `resp 0 <page_id> <section> <page_name> <s1> <s2> <s3> <s4> <s5> <s6> <s7> <s8>` | one page, 0 to count - 1: each slot the symbol param_set takes, - for an empty one; -902 for a page that is not one |
| `param_info` | `<instance> <symbol>` | `resp 0 <unit> <scale> <min> <max> <default> <step> <stable_symbol>` | what a parameter's value means: its unit, its scale, and the symbol it keeps across hosts and versions; -103 for a symbol that is not a parameter, the plugin's own bypass and :bypass included |

The ledger keeps the latest `track_info` of an instance and replays it after the add; the others are queries. A `<scale>` is `linear` (the value is linear in position), `log` (the value is geometric in position; both bounds are positive), `stepped` (the whole numbers from min to max, step 1). A string word is at most 255 bytes of UTF-8 with no control character.
<!-- END GENERATED protocol:instance-verbs -->

Error codes the daemon adds to mod-host's:

<!-- BEGIN GENERATED protocol:errors -->
| code | name | meaning |
|---|---|---|
| `-501` | `PHD_ERR_PLACEMENT_INVALID` | placement invalid: not a placement, or not valid here, as a pool:<name> for an lv2 plugin while require_pins is on |
| `-502` | `PHD_ERR_NO_BACKEND` | no worker program for the scheme |
| `-503` | `PHD_ERR_WORKER_SPAWN` | the worker is not up: the spawn failed, or it is in backoff; ask again after instance_restored |
| `-504` | `PHD_ERR_REPLAY` | the name of a refused replay, never a reply: a replayed add that its pin or the worker refuses is announced by the instance_replay_refused event with the refusal's own code, and written to stderr with this one and the step that refused it |
| `-505` | `PHD_ERR_GAVE_UP` | the storm bound is spent for that placement |
| `-506` | `PHD_ERR_NO_SUCH_WORKER` | no such worker |
| `-507` | `PHD_ERR_VERB_DROPPED` | the worker died on this very command and the daemon dropped it: it is not replayed, and the instance_verb_dropped event names it; or it died on, or did not answer in rpc_timeout_ms, the pin_expect of an add, which is then never forwarded |
| `-508` | `PHD_ERR_PIN_ABSENT` | require_pins is on and the plugin has no pin, or its layout pin is in a scheme this version does not know: add is refused and no worker sees it |
| `-509` | `PHD_ERR_PIN_BINARY_MISMATCH` | a pinned file is missing or its SHA-256 differs, or the plugin's manifest names a file the pin does not hold: add is refused and no worker sees it |
| `-510` | `PHD_ERR_PIN_LAYOUT_MISMATCH` | the worker found the parameter layout after init differs from the layout pin: the instance is destroyed before activate |
| `-511` | `PHD_ERR_NO_PARAM_CONTRACT` | the host holds no checked unit and scale for this parameter: fall back to qualification |
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
| `instance_verb_dropped` | `<instance> <the command as sent>` | the command a worker died on, dropped from the ledger, or the pin_expect of an add it died on |
| `instance_verb_dropped` | `<instance> suspect:<ms> <the command as sent>` | the last verb a worker answered when it died inside suspect_window_ms, <ms> the age of the reply |
| `worker_backoff` | `<worker> <ms>` | the respawn waits this long |
| `worker_respawned` | `<worker> <pid> <replayed_count> <ms>` | a worker is back and its ledger replayed |
| `instance_restored` | `<instance> <worker>` | an instance is back in a worker |
| `instance_replay_refused` | `<instance> <code>` | a replayed add was refused, by its pin or by the worker, <code> the refusal's own: no worker holds the instance until the next replay |
| `instance_quarantined` | `<instance> <worker>` | the culprit of a pool death, placed own until cleared |
| `supervisor_gave_up` | `<worker> <deaths> <window_ms>` | the storm bound is spent; respawning ends |
| `remote_pages_changed` | `<instance>` | relayed from a clap worker: the plugin changed its remote pages; read them again |
<!-- END GENERATED protocol:events -->

The workers' own feedback
-------------------------

What a worker reports on its feedback port (the `output_set` of a monitored output, the `param_set` of a parameter the
plugin moved, `data_finish`, the log lines) reaches the controller on the daemon's feedback port, among the events
above:

<!-- BEGIN GENERATED protocol:relay -->
Every worker is started as `<program> -n -p <command port> -f <feedback port>`.

- every line a worker writes on its feedback port goes out on the daemon's feedback port as the worker wrote it: output_set, param_set, data_finish and the rest of mod-host's feedback, and a line the daemon does not know.
- the instance number in a relayed line is already the controller's: add hands it to the worker unchanged, so nothing in a line is rewritten.
- a worker's lines go out in the order it wrote them, and what a worker wrote before it died goes out before its worker_died event; an instance lives in one worker at a time, so its lines keep their order across a respawn; the lines of different workers interleave.
- monitor_output is in the ledger, one line per output, and param_monitor as it was sent; a respawn replays them after the add, so a respawned instance reports the same outputs, each once, starting again from its first value.
- output_data_ready names no instance and goes to every worker; each worker's data_finish is relayed.
- with no feedback port, or no controller on it, a line is dropped, as mod-host drops it; the daemon reads every worker's feedback all the time, so no worker waits on it.
<!-- END GENERATED protocol:relay -->

Pins
----

Why: a plugin is checked before the console trusts it. We measure one build of it for crashes, real-time safety and
its parameters. The pin makes sure the bytes that load are the bytes that were checked, so an update or a swapped
file cannot slip in unchecked. The layout pin also protects the controls: presets, surfaces and the REST rows are
mapped to the plugin's parameters, and a changed layout would send values to the wrong ones. It also leaves a record
you can audit: the exact plugin build that processed the audio.

With `require_pins` on, the default, `add` admits only a plugin the controller pinned with `pin_set`: the SHA-256 of
every file the host loads for it, and its parameter layout fingerprint. Before any worker is spawned or sees the
`add`, the daemon hashes each pinned file over one open descriptor: for a CLAP the files beside the `.clap` that
`clap:<path>#<id>` names, the `.clap` itself among them; for an LV2 the files of the bundle whose `manifest.ttl` names
the URI, the manifest among them, and every file the manifest names with `lv2:binary` or `rdfs:seeAlso` for the plugin
must be held by the pin. No pin, or a layout pin in a scheme this version does not know, answers `PHD_ERR_PIN_ABSENT`;
a file missing, changed or not held answers `PHD_ERR_PIN_BINARY_MISMATCH`. For a CLAP the daemon then sends the worker
`pin_expect <instance> <layout pin>` and the `add` unchanged, and the worker answers `PHD_ERR_PIN_LAYOUT_MISMATCH`
when the layout after `init` is not the pinned one; a worker that refuses `pin_expect` gets no `add`, and its refusal
is the reply, and one that dies on it or does not answer it is dropped with `PHD_ERR_VERB_DROPPED`, the
`instance_verb_dropped` event naming the `pin_expect`. An LV2 worker gets no pin verb: its layout is its bundle's TTL,
which the hash covers, in a world of that one bundle; so a pinned LV2 plugin gets a worker of its own, a `default` that
resolves to a pool is placed `own` and an explicit `pool:<name>` answers `PHD_ERR_PLACEMENT_INVALID`.

What cannot be pinned:

<!-- BEGIN GENERATED protocol:pin-limits -->
- a path holding ',', '=' or whitespace cannot be pinned: they are the separators of pin_set's words, and pin_set refuses it as a token outside its grammar.
- a pin_set line is at most line_max, 4096 bytes, the protocol socket's buffer; a longer one is refused as outside the grammar.
- a manifest that uses @base, or names a file of the plugin by a percent-encoded IRI, makes add answer PHD_ERR_PIN_BINARY_MISMATCH (-509): the daemon does not resolve either, so it cannot know the file the host would load.
<!-- END GENERATED protocol:pin-limits -->

Pins are the controller's policy, like `policy_set`: not in the ledger, gone with the daemon, set again by a controller
that reconnects. A replayed `add` is checked again, so a file swapped while a worker was down is refused on respawn:
the daemon emits `instance_replay_refused <instance> <code>` with the refusal's own code (the pin's, or the worker's
when it refuses the replayed `pin_expect` or `add`), writes `PHD_ERR_REPLAY`, the step and that code to stderr, and
the worker does not hold that instance until a later replay passes. The hashing and the layout serialisation are `include/plugin-hostd/pin.h`, installed beside the
protocol header for the hosts that check a layout.

What a worker must do
---------------------

- answer mod-host's protocol on `-n -p <port> -f <port>`, the feedback port opened by the daemon right after the
  command port;
<!-- BEGIN GENERATED protocol:worker-ready -->
- print a line ending `ready!` on stdout once its socket accepts;
<!-- END GENERATED protocol:worker-ready -->
- write, for `state_save <dir>`, files whose names begin `effect_<instance>` and read them back on
  `state_load <dir>`, skipping an instance with no file.

`mod-host` and `omx-clap-host` do.
