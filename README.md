plugin-hostd
============

plugin-hostd runs your LV2 and CLAP audio plugins, each in a worker process of its own, and
puts back any worker that dies. A plugin that crashes takes down its own worker and nothing
else. It is for anyone who runs plugins live on Linux, on a mixing console, a stage rig or a
Raspberry Pi, and cannot let one bad plugin stop the show.

- A crash stays small: the plugin's worker is respawned with its settings put back.
- Nothing to change in your controller: it speaks mod-host's socket protocol, same ports, same replies.
- LV2 through omx-clap-host's adapter, with mod-host for the plugins the adapter refuses, and CLAP through omx-clap-host, side by side.
- Audio never passes through the daemon; every worker is a JACK client, as in mod-host.
- A plugin that keeps crashing is singled out and given up on without touching its neighbours.

Install
-------

Fedora:

    sudo dnf install https://www.openmixer.org/rpm/openmixer-release.noarch.rpm
    sudo dnf install plugin-hostd omx-clap-host

Debian bookworm and trixie and Raspberry Pi OS (amd64 and arm64):

    curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb && sudo apt install ./openmixer-release.deb
    sudo apt update && sudo apt install plugin-hostd omx-clap-host

The LV2 worker is mod-host, which Debian does not package; without it CLAP plugins still work.

Status
------

What the continuous integration runs on every push:

- The daemon against stand-in workers that die on cue: placement, forwarding, the ledger, replay,
  attribution and the bound on a respawn storm. No JACK and no plugin are needed for this.
- The generated protocol files, README tables and man page checked against `protocol.h`, and
  every guard broken on purpose to see its test go red.
- The daemon with a real CLAP worker (omx-clap-host) over PipeWire's JACK and over JACK2's `jackd`,
  including meters reaching the controller.
- RPMs (Fedora 44) and DEBs (bookworm and trixie) built and installed in a clean environment.

The LV2 worker (mod-host) is not run in CI; those steps stay in the Makefile for a machine that has
mod-host and an LV2 bundle.

Try it
------

Start the daemon, with pin checking off for a first try (it says when both ports accept):

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

Using it from your own host (Zynthian, a Raspberry Pi, any Debian): [docs/own-host.md](docs/own-host.md), nine commands from
nothing to a plugin running.

Under Zynthian on a Raspberry Pi 5: the measurements are [docs/zynthian/benchmarks.md](docs/zynthian/benchmarks.md), the
pros and cons for a reviewer [docs/zynthian/tradeoffs.md](docs/zynthian/tradeoffs.md), and the acceptance report
[docs/zynthian/acceptance-report.md](docs/zynthian/acceptance-report.md).

Building from source: see [BUILDING.md](BUILDING.md). More about FreeMixer at <https://www.openmixer.org>.

Protocol
--------

The verbs the daemon adds are declared once in omx-contract's contract directory, with their formats, their replies,
their refusal codes and what each host owes them: `/usr/share/omx-contract/contract.d/3/plugin-hostd/verbs.json`,
package `plugin-hostd-contract`, beside the format tables. A refusal number omx-clap-host answers too carries
omx-clap-core's `reply.host.*` code (package `omx-clap-core-contract`), the others plugin-hostd's
`reply.plugin-hostd.*`: one name per number. The placement syntax, the error codes, the feedback events
and the settings are declared once in `include/plugin-hostd/protocol.h`, which includes the verbs as
`plugin_hostd_host_verbs.h` renders them; the tables here, the man page's key list and `protocol/plugin-hostd.json`
are generated from both. A C program includes the installed header (`pkg-config --cflags plugin-hostd`, package
`plugin-hostd-devel` or `plugin-hostd-dev`); anything else reads `/usr/share/plugin-hostd/protocol.json`. mod-host's own protocol, which the LV2 workers speak
(its command and feedback templates, its parse refusals and its reply codes), is installed beside it as
`/usr/share/plugin-hostd/mod-host.json`, written from the mod-host headers the daemon is built against.
The development package installs the schemas beside them: `protocol.schema.json` for the protocol JSON,
`probe-output.schema.json` for the probe's document and `preset.schema.json` for the org.openmixer.preset file
(`protocoldir` in the pkg-config file is that directory).

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
| `lv2_worker` | `auto` | who runs an LV2 plugin: mod-host (the mod_host program), omx-clap-host (the clap_host program, through its LV2 adapter, a plugin it cannot run refused with a code) or auto (the adapter first, mod-host for what it refuses, each such plugin in a worker of its own unless its add names a placement); lv2_worker_set overrides it for one plugin |
| `lv2_path` | `$LV2_PATH`, else `/usr/lib64/lv2:/usr/lib/lv2:/usr/local/lib/lv2` | where bundles are searched |
| `state_root` | `$XDG_RUNTIME_DIR`, else `/tmp` | the daemon's checkpoints and worker logs |
| `pin_mode` | `first-use` | strict or first-use, while require_pins is 1: first-use records the pin of a plugin on its first add, strict admits only a plugin a controller, a pin_file or pins_dir pinned |
| `grouping` | `off` | off or on: whether plan applies its plan (a run of consecutive members that may share a worker is declared as a chain), or only answers it; the default stays off until the benchmark has published a win |
| `pin_store` | `` | the file first-use pins are kept in; empty is $XDG_STATE_HOME/plugin-hostd/pins, else $HOME/.local/state/plugin-hostd/pins |
| `pin_file` | `` | a file of pin lines loaded at start, as plugin-qualify --all --pins writes it; empty is none |
| `pins_dir` | `/usr/share/plugin-hostd/pins.d` | the read-only pins of packages: every file in it whose name ends in .pins, read at start in name order, under the store, the pin_file and pin_set, except that a pin of verdict=refused there always holds; empty is none |
| `descriptor_dir` | `$OMX_DESCRIPTOR_DIR`, else `` | the scanned descriptors, one file per plugin binary (<id>@<version>-<hash>.json, the hash the binary's SHA-256), written by the scan of an add and read by descriptor_get; empty is $XDG_STATE_HOME/omx/descriptors, else /var/lib/omx/descriptors run as root (a system service), else $HOME/.local/state/omx/descriptors; its variable is for tests only |
| `qualification_dir` | `$OMX_QUALIFICATION_DIR`, else `` | plugin-qualify's qualification records (verdict, cost, version tested), kept apart from the descriptors; empty is $XDG_STATE_HOME/omx/qualification, else /var/lib/omx/qualification run as root (a system service), else $HOME/.local/state/omx/qualification; its variable is for tests only |
| `probe` | `plugin-hostd-probe` | the scanner an add runs, as <probe> describe <target>, in a child of its own once per plugin binary; its stdout is the descriptor |
| `history_file` | `` | the running history: what each plugin did on this machine, kept per plugin, binary and host class; empty is $XDG_STATE_HOME/plugin-hostd/history, else $HOME/.local/state/plugin-hostd/history; local to this machine, mode 0600, written by the daemon alone, and deleted by history_clear |
| `host_class` | `` | the host class the history is kept under, as arch/cores/clock (x86_64/5-8/2.5-3.5GHz); empty is the class of this machine, as the probe writes it; no white space |
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
| `history_window_s` | 60 s | the length of one history window: a worker's CPU and memory are read and folded into the history of its plugins once per window, and a window the plugin was up less than half of is not counted; 0 keeps no history |
| `history_save_s` | 300 s | the history is written at most once this often when it changed, and at quit |
| `history_regroup_s` | 600 s | a plan whose group was split by a death that named no culprit is made again after this many seconds without another death of its members, and the members that share are gathered in a worker again; 0 never makes it again by itself |
| `group_max` | 8 instances | most members of one segment of a plan; 0 sets no limit |
| `group_cost_max` | 60 percent of a core | most the costs of the members of one segment of a plan add to, each a member's coreFractionP95 of its qualification record at group_rate and group_quantum; a member over it alone stays alone; 0 sets no limit |
| `group_rate` | 48000 Hz | the sample rate the cost of a member is read at |
| `group_quantum` | 128 frames | the quantum the cost of a member is read at |
| `require_pins` | 1  | 1: add admits only a plugin that has a pin (see pin_mode), its files hashed before any worker sees it, and a plugin of a format whose pin holds only in a world of its own gets a worker of its own, its world the plugin's files (a default that resolves to a pool is placed own); 0: no pin is checked |
<!-- END GENERATED protocol:config -->

<!-- BEGIN GENERATED protocol:constants -->
| name | value | meaning |
|---|---|---|
| `default_command_port` | 5555 port | the command port without -p; the feedback port is the next one, unless -n is given |
| `connect_retry_ms` | 5000 ms | how long the idle tick asks again for a connect a respawned worker could not make yet |
| `line_max` | 4096 bytes | the protocol socket's buffer: the longest pin_set line the daemon takes |
| `line_words_max` | 64 words | the words of one command line the daemon reads, the verb included; a word past them is not read |
| `chain_members_min` | 1 instances | the fewest members of a chain: a chain of one is valid, so one isolated plugin is a chain like any other |
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

Grouped workers against one process per plugin
----------------------------------------------

A chain runs its plugins in one worker; the other way is one process per plugin. One measurement of the two, with
16 plugins, with the numbers of the page at <https://www.openmixer.org/docs/grouped-vs-processes>:

| | grouped | one process per plugin | |
|---|---|---|---|
| resident memory (RSS), 48 kHz | 125.4 MB | 1764.6 MB | 14x smaller grouped |
| proportional memory (PSS), 48 kHz | 42.9 MB | 118.2 MB | 2.8x smaller grouped |

- RSS counts a shared library once for every process that maps it, so a design with many processes looks larger than
  it is. PSS divides shared pages between the processes that use them, so it is the honest figure. Do not read the RSS
  ratio as the saving in real memory.
- CPU: 1.2 to 1.9x less when grouped, across 3, 8 and 16 plugins at 48 and 96 kHz.
- Context switches: up to about 14x fewer when grouped, 13.9x at 48 kHz and 14.8x at 96 kHz with 16 plugins.
- Xruns over the 12 runs of each mode: 10 grouped against 41 with one process per plugin. Each run is one window of
  10 seconds and the xruns in it are few and unevenly spread, so the 10 against 41 is suggestive and not proof.

How: a Raspberry Pi 5 with 4 cores, CPU governor on performance during the runs, plugin-hostd 0.12.0 with
omx-clap-host 0.22.1 as the worker, N omx plugins in series, 256 frames, on a private JACK server.

Not measured: only 256 frames; only plugin-hostd, with omx plugins; the grouping planner is not part of the result and
no default has been changed because of the numbers; DSP load and xruns are those of the JACK dummy driver, so no claim
about real audio hardware is made.

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
| `policy_set` | `<format \| *> own \| pool:<name>` | `resp 0` | the placement of an add that says default |
| `pool_config` | `<name> <max_instances>` | `resp 0` | the instances a pool holds before a sibling opens |
| `worker_env` | `<format \| *> <cpu-list\|-> <nice\|->` | `resp 0` | the cpu list and the nice value of the workers of a format, at spawn and on the ones running |
| `pin_set` | `<uri> <path>=<sha256>[,<path>=<sha256>...] <scheme>:<sha256> [verdict=<verdict>]` | `resp 0` | the pin of one plugin: the SHA-256 of every file the host loads for it, a path relative to the bundle (the directory of a single-file format's file), its layout fingerprint and, when it is known, the verdict of its qualification; it replaces an earlier pin of the uri; -516 for a plugin whose pins_dir pin carries verdict=refused, which nothing overrides. The pin store, a pin_file and a pins_dir file hold the same line, with or without the verb |
| `pin_clear` | `<uri> \| all` | `resp 0` | forget the pin of one plugin, or of every one; a pins_dir pin is read-only and holds again |
| `lv2_worker_set` | `<uri> <mod-host \| omx-clap-host \| auto \| ->` | `resp 0` | the worker of one LV2 plugin, for its adds from now on: it overrides the lv2_worker setting, - takes the override back; -902 for a word that is none of these. Like policy_set it is the controller's, not in the ledger, gone with the daemon |
| `pin_accept` | `<uri>` | `resp 0` | pin_mode first-use only: take the plugin's files as they are now as its pin, after a pin_changed event; the layout is learned again by the next add and the verdict is dropped; -508 when the plugin has no pin, -509 when its files cannot be collected, -516 when its pins_dir pin carries verdict=refused, -902 under pin_mode strict |
| `pin_layout` | `<instance>` | `resp 0 <scheme>:<sha256>` | sent by the daemon to a worker of a format that checks layouts, after it accepted the add of a plugin whose layout pin is still unknown: the layout the worker found after init, which the daemon records in the pin |
| `pin_expect` | `<instance> <scheme>:<sha256>` | `resp 0` | sent by the daemon to a worker of a format that checks layouts, just before the instance's add: the layout pin that add checks after init and before activate; any other reply than resp 0 refuses the add with that code, and the add is never forwarded |
| `chain` | `<chain> <instance> [<instance> ...]` | `resp 0` | the instances, in this order, are one chain, run in one worker of place chain:<chain>: each member's state is saved, it is removed from the worker it was in and replayed in the chain's. A chain already declared takes the new order, and a member left out of it goes back to a worker of its own; while its worker is up that worker is kept: a new member joins it (its add, the order, its state, its ledger, its connections) and no other member is restarted, unless the new member's format narrows the worker's world, which forms the chain again. Members of clap and lv2-clap form one chain. A worker that runs chains in one client (clap, lv2-clap) is sent this line, with the members it holds, after the adds of its replay; one that does not (mod-host) never is, and a refusal of it is written to stderr and is no failure. Every instance verb still names one member by its own number. A member that crashes the worker is quarantined to a worker of its own and the chain goes on without it; quarantine_clear puts it back. -518 for an instance no add made, -519 for one named twice, -520 for one in another chain, -521 for members no one worker program runs together, -501 for a plugin that may not share a worker while require_pins is on (a CLAP plugin whose first-use pin is not in-process; an LV2 member whose bundle is not found, since a chain's worker sees a world narrowed to the union of its members' bundles), -902 for a chain or an instance that is not a number, or fewer than chain_members_min (1) instances |
| `chain_clear` | `<chain>` | `resp 0` | forget the chain: each member goes to a worker of its own; -522 for a chain no chain declared |
| `chain_get` | `<chain>` | `resp 0 <worker> <instance>,... <instance>,...` | read a chain back: its worker (- when it has none), its members in the declared order, and the members its worker runs now in their order (- for none); a quarantined member is declared and not running; -522 for a chain no chain declared, -902 for a chain that is not a number |
| `plan` | `<chain> <instance> [<instance> ...]` | `resp 0 <instance>,...;<instance>,...;...` | the instances, in signal order, are planned (the grouping-planner design note): the daemon decides, from the pin and the cost of each, which runs of consecutive members share a worker. A run of two or more is declared as a chain of place chain:<chain>.<k>, k counting segments from 0; a member that shares with no neighbour is placed own. The reply names the segments in order, the members of one joined by commas and the segments by semicolons. A chain planned again keeps the running worker of every segment that did not change, and the daemon plans it again by itself when a member is quarantined and, history_regroup_s after a death that split its group, to gather it. The plan numbers are its own, apart from chain's. While the setting grouping is off the plan is answered and kept for plan_get and nothing moves. A segment that cannot be formed refuses the whole plan with its own code, moves nothing and is told by plan_get as plan-refused:<code>. -518 for an instance no add made, -519 for one named twice, -520 for one in a chain or in the plan of another chain, -501 for a segment no world can be built for, -902 for a chain or an instance that is not a number, or fewer than chain_members_min (1) instances |
| `plan_get` | `<chain>` | `resp 0 <instance>,...;<instance>,...;... <instance>:<reason>,...` | read the last plan of a chain back: its segments as plan answered them, then the members that have a reason, instance:reason joined by commas (- for none); the reasons are the words of PLUGIN_HOSTD_GROUPING_REASONS (data/grouping.json); -532 for a chain no plan planned, -902 for a chain that is not a number |
| `plan_clear` | `<chain>` | `resp 0` | forget the plan: each member goes to a worker of its own; -532 for a chain no plan planned |
| `descriptor_get` | `<uri>` | `resp 0 "<path>"` | the scanned descriptor of the plugin, answered from descriptor_dir: the file named for its binary as it is now (<id>@<version>-<hash>.json), written by the scan the plugin's add ran. -529 when there is none, -530 while its scan runs, -531 when its last scan wrote nothing, -528 when the directory could not be written |
| `panel_get` | `<uri>` | `resp 0 "<path>"` | the panel the plugin publishes (org.openmixer.panel-description/1), answered from descriptor_dir: the file panels/<id>@<version>-<hash>.json, named as its descriptor, which the same scan writes once the descriptor is in place, {"plugin": {"format", "id"}, "panel": <the panel object omx-clap-scan --json prints for the plugin, null when it serves none>}; an LV2 plugin's panel is null. The codes are descriptor_get's: -529 when there is none, -530 while its scan runs, -531 when its last scan wrote nothing, -528 when the directory could not be written |
| `history_get` | `<uri>` | `resp 0 <history>` | what the daemon kept of the plugin on this host class, for the binary its pin holds now (the running history: the windows it ran alone and in a group, its crashes, restarts and quarantines): one word of comma-joined digest=<sha256>, class=<host class>, crashed=<0\|1>, raises_xruns=<0\|1> and then every key=value of the record (data/history.json); - when the plugin has no pin or no record, unavailable while the history file is blocked or history_window_s is 0, -902 for a line that is not one word |
| `history_clear` | `<uri> \| all` | `resp 0` | delete the history of one plugin (every binary and host class of it), or all of it, from memory and from the file at once; -902 while the history is blocked or off, or for a line that is not one word |

A `<state>` is `up` (accepting commands), `starting` (spawned, not yet accepting), `backoff` (dead, waiting to be respawned), `given-up` (the storm bound is spent for its placement).
<!-- END GENERATED protocol:verbs -->

A record's place holds a colon (`pool:p`), so a `worker_list` record is read from both ends: four fields on the
left, the instance list on the right, the place in between.

`panel_get` gives a host that draws a plugin's panel itself (Zynthian's engine, a console) the panel the plugin
publishes, as the scan of its add read it: sections, controls with their widget and visibility rule, roles, displays
and placement defaults. A renderer takes the panel for the structure, `param_info` for each control's unit and scale,
and `remote_page_get` for the pages of 8: [docs/panel.md](docs/panel.md).

Verbs a worker answers, by instance
-----------------------------------

What a host knows of a strip and of a plugin's controls. For a CLAP instance the daemon routes them like mod-host's
instance verbs and passes the worker's reply through; the worker answers them from the plugin (`clap.track-info`,
`clap.remote-controls`, `clap.params`), except `param_info`: omx-clap-host answers it from the param contract (`org.openmixer.param-contract/1`), and
`-511` for a parameter the worker holds no checked contract for (and `-103` for a symbol that is no parameter). `-511`
is the stable answer to read as "no contract; fall back to the layout from `omx-clap-scan`"; the daemon passes it through
and drops nothing. For an LV2 instance the daemon answers them itself, never forwarding them, so
mod-host learns none of them: `track_info` is kept and answered `resp 0`, an LV2 plugin has no remote pages, and
`param_info` answers `-511` until the daemon reads the bundle's port data. When a CLAP plugin changes its pages, its
worker writes `remote_pages_changed <instance>` on its feedback port and the daemon relays it.

Notes are played the same way, by a controller that is not a jack client (a web console, a test, a MIDI surface on the
network): `note_input` says whether an instance takes notes, and `note_on`, `note_off` and `all_notes_off` reach its
worker unchanged once the daemon has checked their words. A worker answers them from the plugin's note input. mod-host
takes no notes on its socket, so for an LV2 instance on mod-host the daemon answers all four `-514`, and the plugin is
played through its jack MIDI input with `connect`. omx-clap-host does not answer them yet (FreeMixer/omx-clap-core#122).

`preset_list` and `preset_get` list a plugin's presets the way `remote_pages` and `remote_page_get` list its pages; the
key `preset_get` gives is the one `preset_load` takes. mod-host cannot list presets, so for an LV2 instance on mod-host
the daemon answers both `-515`. omx-clap-host lists them with `preset_list` and `preset_get`.

A plugin with a window or a surface of its own tells its host when the user takes hold of one of its knobs and lets go,
moves values by itself, and suggests a remote page. Its worker writes `param_gesture`, mod-host's `param_set` and
`remote_page_suggest` on its feedback port, and the daemon relays them as written, in order (events below). If the
worker dies, or the instance is removed, while a gesture is held, the daemon ends the gesture itself, so no control
stays held at the controller. omx-clap-host writes these lines from FreeMixer/omx-clap-core#87 on.

<!-- BEGIN GENERATED protocol:instance-verbs -->
| verb | arguments | reply | meaning |
|---|---|---|---|
| `track_info` | `<instance> <name> <#RRGGBB \| -> [bus \| return \| master]` | `resp 0` | the strip's name ("" for none), colour and kind, absent for an input channel; a worker whose plugin format has a track-info extension passes them on; any other word is -902 |
| `remote_pages` | `<instance>` | `resp <count>` | the plugin's remote-control pages, from clap.remote-controls; 0 for an instance of a format whose worker has none |
| `remote_page_get` | `<instance> <page>` | `resp 0 <page_id> <section> <page_name> <s1> <s2> <s3> <s4> <s5> <s6> <s7> <s8>` | one page, 0 to count - 1: each slot the symbol param_set takes, - for an empty one; -902 for a page that is not one |
| `param_info` | `<instance> <symbol>` | `resp 0 <unit> <scale> <min> <max> <default> <step> <stable_symbol>` | what a parameter's value means: its unit, its scale, and the symbol it keeps across hosts and versions; -103 for a symbol that is not a parameter, the plugin's own bypass and :bypass included; -511 for a parameter whose unit and scale the worker holds no checked contract for |
| `preset_list` | `<instance>` | `resp <count>` | the plugin's presets, the ones its preset discovery or its bundle lists; (-515) for an instance of a worker that cannot list them |
| `preset_get` | `<instance> <index>` | `resp 0 <load_key> <name>` | one preset, 0 to count - 1: the key preset_load takes for it, and its name; -902 for an index that is not one |
| `note_input` | `<instance>` | `resp 0 <port \| ->` | whether the instance takes notes: the name of its note input on its worker's jack client, - for a plugin that takes none; (-514) for an instance of a worker that cannot say |
| `note_on` | `<instance> <channel> <key> <velocity>` | `resp 0` | play a key: channel 0 to 15, key 0 to 127, velocity 1 to 127, a MIDI note on at the start of the worker's next cycle; (-513) for a plugin that takes no notes, (-514) for an instance of a worker that takes none on its socket, -902 for a word out of its range |
| `note_off` | `<instance> <channel> <key> <velocity>` | `resp 0` | release a key, velocity 0 to 127, a MIDI note off; answered as note_on is |
| `all_notes_off` | `<instance>` | `resp 0` | release every key of every channel, MIDI's all notes off (controller 123) on each; answered as note_on is |

The ledger keeps the latest `track_info` of an instance and replays it after the add; the others are never replayed. A `<scale>` is `linear` (the value is linear in position), `log` (the value is geometric in position; both bounds are positive), `stepped` (the whole numbers from min to max, step 1). A string word is at most 255 bytes of UTF-8 with no control character.
<!-- END GENERATED protocol:instance-verbs -->

What each host profile owes every verb a controller sends: mod-host's commands, the two that Zynthian's mod-ui still
names, and the verbs the daemon adds. A verb has a row here before the daemon serves it. The daemon relays a worker's
verb, an instance verb to the worker that holds the instance and any other to every worker, and passes its answer
back: a required verb (presets and bundles for the CLAP worker and Zynthian, by the rulings of 2026-10-22) answers -902
only while the worker does. MIDI learn and CV addressing are policy of the surfaces: the host answers them only as the
mechanism, and they stay optional. The preset verbs and the preset file are [docs/presets.md](docs/presets.md).

<!-- BEGIN GENERATED protocol:host-verbs -->
| verb | sent by | lv2-worker | clap-worker | console | zynthian |
|---|---|---|---|---|---|
| `add` | mod-ui | required | required | required | required |
| `remove` | mod-ui | required | required | required | required |
| `bypass` | mod-ui | required | required | required | required |
| `connect` | mod-ui | required | required | required | required |
| `param_set` | mod-ui | required | required | required | required |
| `state_load` | mod-ui | required | required | required | required |
| `state_save` | mod-ui | required | required | required | required |
| `state_tmpdir` | mod-ui | required | required | required | required |
| `feature_enable` | mod-ui | required | required | required | required |
| `bundle_add` | mod-ui | required | required | required | required |
| `bundle_remove` | mod-ui | required | required | required | required |
| `preset_load` | mod-ui | required | required | required | required |
| `preset_save` | mod-ui | required | required | required | required |
| `preset_show` | mod-ui | required | required | required | required |
| `transport` | mod-ui | required | required | required | required |
| `transport_sync` | mod-ui | required | required | required | required |
| `cpu_load` | mod-ui | required | required | required | required |
| `midi_learn` | mod-ui | optional | optional | optional | optional |
| `midi_map` | mod-ui | optional | optional | optional | optional |
| `midi_unmap` | mod-ui | optional | optional | optional | optional |
| `cv_map` | mod-ui | optional | optional | optional | optional |
| `cv_unmap` | mod-ui | optional | optional | optional | optional |
| `monitor_midi_program` | mod-ui | optional | optional | optional | optional |
| `monitor_output` | mod-ui | optional | optional | optional | optional |
| `output_data_ready` | mod-ui | optional | optional | optional | optional |
| `patch_get` | mod-ui | optional | optional | optional | optional |
| `patch_set` | mod-ui | optional | optional | optional | optional |
| `cc_map` | mod-ui | absent | absent | absent | absent |
| `cc_value_set` | mod-ui | absent | absent | absent | absent |
| `cc_unmap` | mod-ui | absent | absent | absent | absent |
| `hmi_map` | mod-ui | absent | absent | absent | absent |
| `hmi_unmap` | mod-ui | absent | absent | absent | absent |
| `show_external_ui` | mod-ui | absent | absent | absent | absent |
| `set_midi_program_change_pedalboard_bank_channel` | mod-ui | absent | absent | absent | absent |
| `set_midi_program_change_pedalboard_snapshot_channel` | mod-ui | absent | absent | absent | absent |
| `disconnect` | mod-host | required | required | required | required |
| `set_bpm` | mod-host | required | required | required | required |
| `set_bpb` | mod-host | required | required | required | required |
| `quit` | mod-host | required | required | required | required |
| `param_get` | mod-host | optional | optional | optional | optional |
| `param_monitor` | mod-host | optional | optional | optional | optional |
| `licensee` | mod-host | optional | optional | optional | optional |
| `monitor` | mod-host | optional | optional | optional | optional |
| `load` | mod-host | optional | optional | optional | optional |
| `save` | mod-host | optional | optional | optional | optional |
| `help` | mod-host | optional | optional | optional | optional |
| `track_info` | mod-host | optional | optional | optional | optional |
| `remote_pages` | mod-host | optional | optional | optional | optional |
| `remote_page_get` | mod-host | optional | optional | optional | optional |
| `param_info` | mod-host | optional | optional | optional | optional |
| `preset_list` | daemon | optional | optional | optional | optional |
| `preset_get` | daemon | optional | optional | optional | optional |
| `note_input` | daemon | optional | optional | optional | optional |
| `note_on` | daemon | optional | optional | optional | optional |
| `note_off` | daemon | optional | optional | optional | optional |
| `all_notes_off` | daemon | optional | optional | optional | optional |
| `worker_list` | daemon | required | required | required | required |
| `instance_info` | daemon | required | required | required | required |
| `supervisor_reset` | daemon | required | required | required | required |
| `quarantine_clear` | daemon | required | required | required | required |
| `policy_set` | daemon | required | required | required | required |
| `pool_config` | daemon | required | required | required | required |
| `worker_env` | daemon | required | required | required | required |
| `pin_set` | daemon | required | required | required | required |
| `pin_clear` | daemon | required | required | required | required |
| `pin_accept` | daemon | required | required | required | required |
| `lv2_worker_set` | daemon | required | required | required | required |
| `chain` | daemon | required | required | required | required |
| `chain_clear` | daemon | required | required | required | required |
| `chain_get` | daemon | required | required | required | required |
| `plan` | daemon | required | required | required | required |
| `plan_get` | daemon | required | required | required | required |
| `plan_clear` | daemon | required | required | required | required |
| `descriptor_get` | daemon | required | required | required | required |
| `panel_get` | daemon | required | required | required | required |
| `history_get` | daemon | required | required | required | required |
| `history_clear` | daemon | required | required | required | required |

The profiles: `lv2-worker`, an LV2 plugin's worker: mod-host, or omx-clap-host's LV2 adapter; `clap-worker`, a CLAP plugin's worker, omx-clap-host; `console`, the openmixer console as a controller of the daemon; `zynthian`, Zynthian's mod-ui and its plugind engine as a controller of the daemon. `required` is answered as its grammar says; `optional` is answered, or refused with -902, and never misread; `absent` is refused on purpose, and no client of the profile may need it.
<!-- END GENERATED protocol:host-verbs -->

Error codes the daemon adds to mod-host's:

<!-- BEGIN GENERATED protocol:errors -->
| code | name | meaning |
|---|---|---|
| `-501` | `OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID_RESP` | placement invalid: not a placement, or not valid here, as a pool:<name> for a plugin of a format whose pin holds only in a world of the plugin's own, while require_pins is on |
| `-502` | `OMX_REPLY_PLUGIN_HOSTD_NO_BACKEND_RESP` | no worker program for the scheme |
| `-503` | `OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN_RESP` | the worker is not up: the spawn failed, or it is in backoff; ask again after instance_restored |
| `-504` | `OMX_REPLY_PLUGIN_HOSTD_REPLAY_RESP` | the name of a refused replay, never a reply: a replayed add that its pin or the worker refuses is announced by the instance_replay_refused event with the refusal's own code, and written to stderr with this one and the step that refused it |
| `-505` | `OMX_REPLY_PLUGIN_HOSTD_GAVE_UP_RESP` | the storm bound is spent for that placement |
| `-506` | `OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_WORKER_RESP` | no such worker |
| `-507` | `OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED_RESP` | the worker died on this very command and the daemon dropped it: it is not replayed, and the instance_verb_dropped event names it; or it died on, or did not answer in rpc_timeout_ms, the pin_expect of an add, which is then never forwarded |
| `-508` | `OMX_REPLY_HOST_PIN_ABSENT_RESP` | pin_mode strict and the plugin has no pin, or its layout pin is in a scheme this version does not know: add is refused and no worker sees it |
| `-509` | `OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP` | a pinned file is missing or its SHA-256 differs, or the plugin's manifest names a file the pin does not hold: add is refused and no worker sees it |
| `-510` | `OMX_REPLY_HOST_PIN_LAYOUT_MISMATCH_RESP` | the worker found the parameter layout after init differs from the layout pin: the instance is destroyed before activate |
| `-511` | `OMX_REPLY_HOST_NO_PARAM_CONTRACT_RESP` | the host holds no checked unit and scale for this parameter: fall back to qualification |
| `-512` | `OMX_REPLY_PLUGIN_HOSTD_LV2_ADAPTER_REFUSED_RESP` | the lv2-clap worker's LV2 adapter cannot run this plugin (MIDI it does not feed, a required feature it lacks, a layout it does not take): the worker answered the add -102, the lv2_adapter_refused event carries the hosting.* code of that reply, and under lv2_worker auto the plugin is run by the lv2 row instead and this code is never answered; a plugin no bundle of the worker's world holds is no refusal: the worker's -101 is answered |
| `-513` | `OMX_REPLY_HOST_NO_NOTE_INPUT_RESP` | the instance's plugin takes no notes (an effect): its worker answers note_on, note_off and all_notes_off with this code |
| `-514` | `OMX_REPLY_HOST_NOTES_BY_JACK_RESP` | the instance's worker takes no notes on its socket (mod-host): the daemon answers the note verbs and note_input with this code, and the plugin is played through its jack MIDI input with connect |
| `-515` | `OMX_REPLY_PLUGIN_HOSTD_NO_PRESET_LIST_RESP` | the instance's worker cannot list the plugin's presets (mod-host): the daemon answers preset_list and preset_get with this code; preset_load still takes a preset the controller knows |
| `-516` | `OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED_RESP` | the plugin's pin carries verdict=refused: its files are the ones that failed qualification, so add is refused and no worker sees it, and a replayed add is refused the same way; files that differ from the pin answer (-509) first. A pins_dir pin of that verdict is never overridden: pin_set and pin_accept of its plugin answer this code |
| `-517` | `OMX_REPLY_HOST_NOTE_QUEUE_FULL_RESP` | the instance's worker has no room for this note_on, note_off or all_notes_off before its next block: the line was not taken and nothing of it is kept; the controller may send it again |
| `-518` | `OMX_REPLY_PLUGIN_HOSTD_CHAIN_UNKNOWN_INSTANCE_RESP` | a member of chain is an instance no add made: the chain is not declared |
| `-519` | `OMX_REPLY_PLUGIN_HOSTD_CHAIN_DUPLICATE_RESP` | an instance is named twice in one chain: the chain is not declared |
| `-520` | `OMX_REPLY_PLUGIN_HOSTD_CHAIN_INSTANCE_BUSY_RESP` | a member of chain is already in another chain: the chain is not declared; chain_clear of the other chain frees it |
| `-521` | `OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT_RESP` | the members of chain are not all run by one worker program, or are of two rows of one program and a row does not run chains in one client, so no one worker runs them: the chain is not declared |
| `-522` | `OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_CHAIN_RESP` | chain_clear or chain_get of a chain no chain declared |
| `-523` | `OMX_REPLY_PLUGIN_HOSTD_PRESET_NOT_OFFERED_RESP` | the worker: preset_load or preset_show of a stable name the plugin does not offer, or of a plugin with no preset system and no state |
| `-524` | `OMX_REPLY_PLUGIN_HOSTD_PRESET_INVALID_RESP` | preset_save with a file path that is not absolute or with no name, or preset_load or preset_show of a file that cannot be read, is no JSON, is of a format version other than org.openmixer.preset/1 and org.openmixer.preset/2, or breaks the format (docs/presets.md): the daemon answers it and no worker sees the file |
| `-525` | `OMX_REPLY_PLUGIN_HOSTD_PRESET_NEEDS_STATE_RESP` | the worker: a preset file that carries state for a worker that cannot take state yet |
| `-526` | `OMX_REPLY_PLUGIN_HOSTD_PRESET_PLUGIN_CHANGED_RESP` | the worker: the preset file's plugin id, version or fingerprint is not the instance's; nothing of it is applied |
| `-527` | `OMX_REPLY_PLUGIN_HOSTD_LOAD_REFUSED_RESP` | the worker: the plugin refused the preset or the state its file carries |
| `-528` | `OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE_RESP` | descriptor_dir or qualification_dir cannot be made or written: the daemon does not start, and says which key and which path on stderr with this code; a directory that turns read-only later makes the scan of an add write nothing, and descriptor_get and panel_get of that plugin answer this code |
| `-529` | `OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT_RESP` | descriptor_get (panel_get) of a plugin that has no descriptor (panel) in descriptor_dir for its binary as it is now, and none being written: no add since it changed, or a binary that cannot be found |
| `-530` | `OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_PENDING_RESP` | descriptor_get (panel_get) of a plugin whose scan, started by its add, has not written its descriptor (panel) yet: ask again |
| `-531` | `OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED_RESP` | descriptor_get (panel_get) of a plugin whose last scan wrote no descriptor (panel): the scanner refused the plugin, made no dump or no panel, or is not installed; the add it ran for stands, and stderr and the scan's log say why. The next add scans again |
| `-532` | `OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_PLAN_RESP` | plan_get or plan_clear of a chain no plan planned |
<!-- END GENERATED protocol:errors -->

A worker's own refusal is returned as it said it. An `add` that killed its worker answers mod-host's `-102`.

`worker_env` offers no real-time priority: a worker's audio thread is set by the jack client library (under a SCHED_FIFO 60
driver it ran at 55, unasked), and a FIFO priority given to the whole process puts the plugin's own threads above
it, where a busy thread starves the graph.

A daemon without privilege cannot give a worker a nice lower than the worker has (a new worker has the daemon's own). The
verb still answers `resp 0`, the worker keeps its nice, and the daemon logs `worker_env: worker <pid> keeps nice <n>, the
nice <m> was not applied` on stderr.

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
| `instance_verb_dropped` | `<instance> <the command as sent>` | the command a worker died on, dropped from the ledger; or the add it died on, the add as the worker was given it, which names the plugin, or the pin_expect of that add |
| `instance_verb_dropped` | `<instance> suspect:<ms> <the command as sent>` | the last verb a worker answered when it died inside suspect_window_ms, <ms> the age of the reply |
| `worker_backoff` | `<worker> <ms>` | the respawn waits this long |
| `worker_respawned` | `<worker> <pid> <replayed_count> <ms>` | a worker is back and its ledger replayed |
| `instance_restored` | `<instance> <worker>` | an instance is back in a worker |
| `instance_replay_refused` | `<instance> <code>` | a replayed add was refused, by its pin or by the worker, <code> the refusal's own: no worker holds the instance until the next replay |
| `instance_quarantined` | `<instance> <worker>` | the culprit of a pool or a chain death, placed own until cleared; a chain goes on without it |
| `chain_formed` | `<chain> <worker> <instance>,...` | a chain's worker is up with these members, in this order, after its declaration, a respawn or a member's quarantine; - for none. <chain> is the number chain declared, or <plan>.<k> for segment k of a plan |
| `plan_reason` | `<chain> <instance>:<reason>,...` | a plan of the chain changed: what plan_get answers now after the segments, - for none |
| `supervisor_gave_up` | `<worker> <deaths> <window_ms>` | the storm bound is spent; respawning ends |
| `pin_changed` | `<uri> files \| layout` | an add or a replay of a plugin was refused because its files, or the layout the worker found, differ from its pin; the pin is as it was until pin_accept or pin_set |
| `lv2_adapter_refused` | `<uri> <reason> auto \| omx-clap-host` | the LV2 adapter of the lv2-clap worker refused a plugin: <reason> is the hosting.* code after -102 on the worker's reply to that add (- when it named none); the last word is the lv2_worker in force, auto for a plugin the lv2 row runs from now on, omx-clap-host for an add answered (-512) |
| `remote_pages_changed` | `<instance>` | relayed from a worker: the plugin changed its remote pages; read them again |
| `remote_page_suggest` | `<instance> <page_id>` | relayed from a worker: the plugin suggests the remote page of that id (a page_id of remote_page_get); a surface may follow it |
| `param_gesture` | `<instance> <symbol> begin \| end` | relayed from a worker: the user took hold of a control of the plugin's own, or let it go; a controller writes no automation of that parameter in between. The values the plugin moves meanwhile, or at any time by itself, are mod-host's param_set feedback lines, relayed as written. A gesture whose worker died, or whose instance was removed, before its end is ended by the daemon, before the worker_died event |
| `xruns` | `<count>` | relayed from a worker, and read by the daemon: the JACK xruns the worker has counted since it started, written when the count changes and at most once a second; a worker that never writes it counted none. The daemon takes the first count of a worker as its baseline and, at the close of each history window, adds the window to xrun_windows_solo or xrun_windows_grouped of every member of the worker when the count rose in it; a line that is not the word and one whole number is not a count |
| `param_set` | `<instance> <symbol> <value>` | relayed from a worker: parameter feedback, a value the plugin moved by itself (its automation, an LFO, a preset load, a MIDI map, the user's knob of the plugin's own), as mod-host writes it; a controller updates its control to it. A worker never writes it for a value a controller's param_set gave it, and a worker that writes none changes nothing: the daemon adds no line of its own |
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

A synced delay or an arpeggiator comes back at the right tempo after a crash. What the daemon keeps of the commands
every worker shares:

<!-- BEGIN GENERATED protocol:host-settings -->
- the tempo, the metre and the transport a controller sets (mod-host's set_bpm, set_bpb, transport and transport_sync) are kept, the latest line of each as it was sent, in the order they were last sent.
- a worker is handed them before anything else: a respawned one before its first add, and a worker started later, of a new placement, as well; a worker's refusal of one is written to stderr and is no failure.
- a line whose words are not that command's grammar is passed on and not kept.
<!-- END GENERATED protocol:host-settings -->

Probing a plugin
----------------

`plugin-hostd-probe run` loads a plugin in a child process under limits and writes down what happened, as facts only: no
verdict. The child is clap-qualify for a CLAP plugin. For an LV2 plugin, named `lv2:<uri>`, the child is plugin-qualify's
`lv2_measure`, found at run time in `/usr/libexec/plugin-qualify` (plugin-qualify is not a dependency of this package).
The runner never loads plugin code itself.

    plugin-hostd-probe run --out probe.json --log probe.stderr.log /usr/lib64/clap/plate.clap org.example.plate
    plugin-hostd-probe run --out probe.json lv2:http://example.org/plate

A CLAP instrument is timed holding notes down: as many as the voice capacity it declares, or, when it declares none,
the count `--probe-notes N` gives; `--hold N` holds that count whatever it declares. Both are passed to clap-qualify.
Each rate's grid point carries the cost clap-qualify timed at that rate, in nanoseconds per sample, and for an instrument
`voices`, the notes it held and why that many (`declared` or `probe`). A rate it did not time has no cost. An instrument has
no input for the impulse, so its latency is measured from a note (`method: note-onset`), with `heard: false` at a rate
where the note did not sound.

clap-qualify runs under plugin-qualify's interposer, `rt_interpose.so` beside the child. A bare `--child` is found as execvp
finds it; name the child by path when PATH is unset or holds a directory of its name. The measured child gets the interposer
and nothing else: an `LD_PRELOAD` the runner was started with is dropped for the measurement, named in `run.tools.droppedPreload`
and in the `rt-safety` step, and put back in the runner's environment after the child. The first grid point carries what process() did under it, and an instrument's
note sweep carries what process() did while notes played. `run.tools.interposer` names it once the child says it counted
under it. With no interposer beside the child, or one that did not load, no count is written: rtSafety says
`interposer: false`, and the `rt-safety` and `note-sweep` steps are `probe.not-attempted` and say why.

An LV2 plugin is measured the way plugin-qualify's LV2 hosting pass measures it today, in two children under the same
limits and the same wall clock. The first child (`lv2_measure --pin`) pins the bundle's files without instantiating the
plugin. The second measures at the highest of `--rates`, in blocks of `--quantum`, with 30 instantiate and destroy cycles
and 3 swept rt-safety runs. It runs under plugin-qualify's interposer (`rt_interpose.so` beside the child, found and with any
other preload dropped as for clap-qualify) and the noise stimulus. The document's binary is the plugin's library, with every pinned file of the bundle listed. The rate's grid
point carries what run() did under the interposer and, for a plugin with a MIDI input, its note sweep (what run() did
while notes played), and `behaviour` carries the lifecycles, the threads and the features
the plugin requires. A plugin no bundle holds exits 3 with no document. A plugin of which nothing could be pinned exits 2
with no document, because the document has no binary to name. Its refusal is a code on stderr: `<plugin>: <code>: <why>`,
`probe.unpinnable` for a bundle the pin cannot cover. Version 1 runs the quick measurement only: the deep lifecycle pass
and the soak stay plugin-qualify's until the probe protocol says which plugins get them and for how long.

The runner kills the whole process tree of the child at its wall clock, and again when the child is done, so a process a
plugin started in a session of its own does not outlive the run. It applies these limits on every Linux: the wall clock,
the CPU time, the data size, the open files, the file size, no core dump, no real-time priority, no new privileges, the
child dying with the runner, and the cpus the child may use (`--cpus`). A limit the set asks for and this version does not
apply (the number of tasks, namespaces, Landlock, seccomp) is listed in the document under `limits.unavailable` with its
code, and `--require tasks` makes the run refuse instead.

A crash, a hang and a timeout are outcomes in the document, never a missing document: the steps the child finished before
dying stay in it. The exit status says whether there is one: 0 a complete run, 1 a document with some step that ended
otherwise, 2 no document, 3 no such plugin. The document is described by `probe-output.schema.json`, generated from the
codes in `protocol.h`, and installed with the protocol.

Pins
----

Why: a plugin is checked before the console trusts it. We measure one build of it for crashes, real-time safety and
its parameters. The pin makes sure the bytes that load are the bytes that were checked, so an update or a swapped
file cannot slip in unchecked. The layout pin also protects the controls: presets, surfaces and the REST rows are
mapped to the plugin's parameters, and a changed layout would send values to the wrong ones. It also leaves a record
you can audit: the exact plugin build that processed the audio.

With `require_pins` on, the default, `add` admits only a plugin that has a pin: the SHA-256 of
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

Where the pin comes from is `pin_mode`. `strict` takes it from `pin_set` or from a `pin_file` loaded at start, and a
plugin with no pin is refused. `first-use`, the default, records it: the first `add` of a plugin with no pin hashes its
files, keeps the pin in the pin store (`$XDG_STATE_HOME/plugin-hostd/pins`) and places the instance `own`; the layout is
asked of the worker after the add (`pin_layout`) and recorded too. A host that pins by itself sets `pin_mode strict`.
The store, a `pin_file` and `pin_set` carry one line format, `pin_set <uri> <files> <layout> [verdict=<word>]` with the
verb optional in a file. In `first-use` only a pin with `verdict=in-process`, which plugin-qualify writes, lets a plugin
share a worker. A pin with `verdict=refused` names files that failed qualification. Their `add` answers `-516`
(`PIN_REFUSED`), no worker sees it, and a replay is refused with the same code. A pin that changes to `refused` while
the instance runs takes effect at its next replay. Files that differ from the pin answer `-509` first, because the
verdict was given for the pinned files only. A plugin that changed since it was pinned is refused (-509, or -510 from the worker), the
`pin_changed <uri> files|layout` event names what changed, and `pin_accept <uri>` takes the new pin.

Pins that ship with packages live in a read-only layer of their own, under the host's. At start the daemon reads
every `*.pins` file of `pins_dir` (`/usr/share/plugin-hostd/pins.d` by default; empty is none), in byte order of
their names, in the same line format. A package drops its own file there, so its plugins and their pins are replaced
in one transaction and removed together; plugin-hostd owns the directory and another package may co-own it. The
daemon never writes it. A pin from this layer is trusted as it is, in both pin modes. The rules:

- A pins.d pin with `verdict=refused` always holds. The pin store, a `pin_file` and `pin_set` never override it:
  `pin_set` and `pin_accept` of its uri answer `-516` (`PIN_REFUSED`), and a line of the store or of the `pin_file`
  for it is kept but has no effect, which stderr says at start.
- Any other pins.d pin is under the host's layer. A pin of the same uri in the store, the `pin_file` or from
  `pin_set` holds over it, and `pin_accept` of a plugin whose files differ from its package pin records the new files
  in the store, which then hold. `pin_clear` forgets the host's pin only: the package pin holds again.
- When two pins.d files hold the same uri, a refusal wins; otherwise the file last in name order wins. Two lines of
  one file follow the same rule, the later line in place of the later file.
- A line outside the grammar, or longer than a pin line can be, is skipped and named on stderr; the rest of the file
  is read. A file that cannot be read is named on stderr and skipped. A directory that is missing or empty holds no
  pins and is no error.

What cannot be pinned:

<!-- BEGIN GENERATED protocol:pin-limits -->
- a path holding ',', '=' or whitespace cannot be pinned: they are the separators of pin_set's words, and pin_set refuses it as a token outside its grammar.
- a pin_set line is at most line_max, 4096 bytes, the protocol socket's buffer; a longer one is refused as outside the grammar.
- a manifest that uses @base, or names a file of the plugin by a percent-encoded IRI, makes add answer OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP (-509): the daemon does not resolve either, so it cannot know the file the host would load.
<!-- END GENERATED protocol:pin-limits -->

Pins are the controller's policy, like `policy_set`: not in the ledger, gone with the daemon, set again by a controller
that reconnects. A replayed `add` is checked again, so a file swapped while a worker was down is refused on respawn:
the daemon emits `instance_replay_refused <instance> <code>` with the refusal's own code (the pin's, or the worker's
when it refuses the replayed `pin_expect` or `add`), writes `PHD_ERR_REPLAY`, the step and that code to stderr, and
the worker does not hold that instance until a later replay passes. The hashing and the layout serialisation are `include/plugin-hostd/pin.h`, installed beside the
protocol header for the hosts that check a layout.

The running history
-------------------

The daemon keeps what each plugin did on this machine, per plugin, per binary and per host class: the file named by
`history_file`, else `$XDG_STATE_HOME/plugin-hostd/history`, else `$HOME/.local/state/plugin-hostd/history`. It is
local: it holds URIs, digests and counters, no audio, no path, no user, session or preset name, the daemon sends it
nowhere and no verb writes it from outside; `history_clear <uri | all>` deletes it. Only the daemon writes it, mode
0600 in a directory of mode 0700, to a temporary file that is renamed over it, at most once per `history_save_s` and
at quit. `history_window_s` 0 keeps none.

The first line is `# plugin-hostd history/1`, then one line per key, `history <uri> <binary digest> <host class>
key=value ...`. The binary digest is the SHA-256 of the first file the plugin's pin holds, so a plugin with no pin has
no history and a changed plugin starts a record of its own, the old one kept and not read. The host class is
`arch/cores/clock` as the probe writes it (`x86_64/5-8/2.5-3.5GHz`), or the `host_class` setting. The keys are the
words of `PLUGIN_HOSTD_HISTORY_KEYS` in [data/history.json](data/history.json): `first`, `last`, `windows_solo`,
`windows_grouped`, `cpu_p95_solo`, `cpu_max_solo`, `pss_mb_solo`, `xrun_windows_solo`, `xrun_windows_grouped`,
`crashes_solo`, `crashes_grouped`, `restarts_grouped`, `quarantines`, `last_crash`, `last_crash_grouped`.

A window is `history_window_s` seconds of one worker: its utime plus stime from `/proc/<pid>/stat` as percent of one
core, and the `Pss` of its `smaps_rollup`. A worker of its own gives a window to the plugin it holds; a worker of two
or more gives one to each member, counted in `windows_grouped` and nowhere else, because a group's CPU cannot be split
among its members. `cpu_p95_solo` is an estimate that needs no list of windows: each window above it moves it up
by 0.95 of 2 percent of itself and each one not above moves it down by 0.05 of that. A window in which the members of
the worker changed is dropped, and a worker that died is counted if it had been up for half the window. A crash is
counted when the daemon names a culprit (`crashes_solo` in a worker of its own, `crashes_grouped` in a group), the
members that went down with it and were not the culprit get `restarts_grouped`, and a quarantine counts in
`quarantines`. A worker writes `xruns <count>` on its feedback port, the JACK xruns it has counted since it started,
when the count changes. The daemon takes the first count of a process as its baseline, never as xruns of the window it
arrives in, and at the close of a window adds one to `xrun_windows_solo` or `xrun_windows_grouped` of every member of
the worker when the count rose in it, however many xruns it rose by. A worker that wrote no count counted none; a
restarted worker counts from zero and its first count is a baseline again; a line that is not the word and one whole
number is not a count.

A line this version cannot read, or with a key it does not know, is kept as it is by every save and is not read. A file
that cannot be read, or whose first line is another version, is neither read nor overwritten: stderr says why, and
`history_get` answers `unavailable` until the operator repairs or removes it.

`history_get <uri>` answers the record of the binary the pin holds now, on this host class, as one word: `digest=`,
`class=`, `crashed=1` when a crash is within 30 days, `raises_xruns=1` when the share of xrun windows in a group
exceeds the share alone by 5 points (from 30 windows in a group), and then every key. `-` is no record.

The planner reads that summary. A plugin the history marks `crashed`, or the daemon has quarantined, is left alone by
the next plan with the reason `history-crashed`; one marked `raises_xruns` with `history-xruns`. Both are judged after
the pin's rules (a history makes a plan more careful than the pin, never less) and before the cost. A plugin's cost is
the larger of its qualification record's and its `cpu_p95_solo` (percent of one core, from the windows it ran alone). A
plugin with no history is judged by its pin and its cost alone. With the history blocked or `history_window_s` 0 the plan
is the pins' and the costs', and every member with nothing harder to say says `history-unavailable`.

A plan is made again by the daemon, never in the middle of a cycle of a worker, when a member of it is quarantined or
its quarantine is cleared, and `history_regroup_s` seconds after a death that named no culprit and split a group, if no
member of the plan has died since: the segments that did not change keep their workers, a group that was split is
gathered, and the member the history marks goes alone. The new reasons come as a `plan_reason` event and in `plan_get`.

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

Formats
-------

The daemon holds its plugin formats in one table, `src/formats.c`, and nothing else in the daemon, the protocol or the
pins names a format. A row says how a uri reaches the format (`prefix`, `strip_prefix`, `fallback`), which program serves
it (`worker`), where its plugins are searched and how a worker's world is narrowed to one plugin (`search`, `world_env`,
`narrow_world`), which files a pin holds (`pin_collect`), whether the worker checks the layout (`layout_check`), whether
a pinned plugin must run in a worker of its own (`pinned_own_only`) and who answers the instance verbs
(`native_instance_verbs`, else `param_info`). Adding a format is a row and its worker; `formats_register` refuses a row
with a capability missing and says which. a test registers a third format in the test and takes it through
`add`, `param_set`, `pin_set` and `remove`.

Who runs an LV2 plugin
----------------------

`lv2_worker` chooses the program that runs LV2 plugins: `auto` (the default: the adapter first, mod-host for a plugin the
adapter refuses, and for every add while omx-clap-host is not installed), `omx-clap-host` (the `clap_host` program, through
its LV2 adapter, a plugin it cannot run refused with a code) or `mod-host` (the `mod_host` program). `lv2_worker_set <uri> <mod-host|omx-clap-host|auto|->` overrides it for one plugin from then on, and `-` takes
the override back. The two programs are two rows of the table, `lv2` and `lv2-clap`, so `policy_set`, `worker_env` and
`worker_list` name them like any format. The adapter row differs from the mod-host row in these ways, each held by a test:

| capability | `lv2` (mod-host) | `lv2-clap` (omx-clap-host) |
|---|---|---|
| `worker` | `mod_host` | `clap_host`, given the uri with its `lv2:` prefix |
| `native_instance_verbs` | no: the daemon answers `track_info`, `remote_pages`, `remote_page_get` and `param_info` | yes: the worker answers them from the plugin, and `track_info` is replayed to it after a respawn |
| `layout_check` | no | no: an LV2 pin holds the layout of the plugin's ports, not of the CLAP parameters the adapter presents, so `pin_expect` would refuse every pin `plugin-qualify` wrote |
| `world_scope` | one bundle, narrowed: `LV2_PATH` holds a link to the plugin's bundle | the same: the adapter opens bundles through the LV2 world |
| `pin_pool` | no: a pinned plugin is placed `own` | the same, for the same reason |

An adapter handles a subset of LV2. When it refuses a plugin, the worker answers the add `resp -102 <hosting code>`
(for instance `hosting.features.midi-in-fed-empty`, `hosting.features.missing`, `hosting.topology.wider-than-strip` or
`hosting.no-realisation`). The add under `omx-clap-host` then answers `-512` (`LV2_ADAPTER_REFUSED`) and the
`lv2_adapter_refused` event carries that code, read from the reply to that add and never from the worker's log, which a
pool worker shares with other plugins (`-` when the reply named none). Under `auto` the add is made again on the `lv2`
row, the plugin stays there, the event is sent once, and the controller never sees `-512`. The daemon remembers the refusal until
the adapter has a reason to take the plugin again: `lv2_worker_set` of that uri (to any word, `-` included) forgets it, and
so does a change of pins (`pin_set`, `pin_accept`, `pin_clear`) for every plugin; the next add under `auto` asks the
adapter once more.

A plugin the adapter refused under `auto` runs on the `lv2` row in a worker of its own, whatever the policy says, unless
its add names a placement. The adapter never ran it, so nothing says it is safe in a shared worker. Some plugins abort
in instantiate: drumkv1, samplv1 and synthv1 do, through Qt, when no display is set. Such a plugin takes down only
its own worker. The add answers `-102`, and an `instance_verb_dropped` event names the add with its uri.

A plugin that no bundle of the worker's world holds is not a refusal: the worker answers `resp -101` with no code. Under
`omx-clap-host` the add answers that `-101`, with no event. Under `auto` the same add is made on the `lv2` row, so mod-host
looks for the plugin; nothing is remembered, and the adapter is asked again on the next add. Under `auto` an
`omx-clap-host` that is not installed is not an error either: the add goes to the `lv2` row.

