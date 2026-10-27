# Grouping: the fewest workers the pins and the history allow

Status: proposed 2026-10-27, for plugin-hostd#182, plugin-qualify#157 and openmixer#2263. No code in this note's pull
request. Operator priority of 2026-10-27: use plugin-hostd's ability to run many plugins in one process to save CPU and
RAM, on Zynthian first and then wherever the host runs. A grouping that does not win in the benchmark is not the
default.

## What exists today (read from the code, 2026-10-27)

- **Pins and verdicts.** A pin is `pin_set <uri> <path>=<sha256>[,...] <scheme>:<sha256> [verdict=<word>]`
  (`src/pins.h`). The verdict is `in-process`, `isolated` or `refused`. The pin carries nothing else: the cost, the
  memory and the latency of a plugin are in plugin-qualify's qualification record, not in the pin.
- **Who may share a worker.** With `require_pins` on and `pin_mode first-use`, a CLAP plugin shares a worker only if its
  pin says `in-process` (`pins_in_process`); a learned pin has no verdict, so the instance is placed `own`. An explicit
  `pool:<name>` for such a plugin answers -501 (`PLACEMENT_INVALID`). A format whose pin holds only in a world of the
  plugin's own (LV2: `pinned_own_only`) is never pooled, and always answers -501 for a pool. A pin with
  `verdict=refused` answers -516 at `add` and at every replay.
- **Chains.** `chain <chain> <instance>...` puts the members in one worker, `chain:<chain>`, that omx-clap-host runs as one
  JACK client and one process callback, in the declared order (`docs/design/notes/2026-10-21-chains.md`). A member that
  `must_run_own` (require_pins, first-use, no `in-process` verdict, not an LV2 member) makes `chain` answer -501. An LV2
  member is accepted because the chain's world is the union of its members' bundles. Rows of two programs answer -521. A
  member that crashes the worker is quarantined and moved to a worker of its own; a death that names no culprit splits the
  members and the one that dies alone is quarantined. A chain is declared and read back with `chain_get`; `chain_formed`
  and `instance_quarantined` are the events.
- **Pools.** `pool:<name>` shares one worker among instances, each its own JACK client, capped by `pool_config` and
  `pool_max` (8); a full pool opens `<name>#2`.
- **What the host measures of a running plugin.** `instance_info` gives the worker, the pid, the state, the crash count and
  the quarantine flag. `worker_list` gives workers and members. `src/proc.c` reads `/proc/<pid>/task`. The daemon counts
  no CPU time, no resident memory and no xrun of a worker or an instance, and writes no history. JACK xruns are seen by
  omx-clap-core's bench probe (`bench/probe.c`, `jack_set_xrun_callback`), not by the daemon.
- **plugin-qualify.** `--pins <file>` writes the pin lines with the verdict of the first `--host-profile`. The profiles are
  `openmixer-console`, `jalv`, `mod-host` and `omx-clap-host` (isolation: in-process, per-process, shared-process,
  shared-process); a verdict is `suitable` (`in-process`), `conditional` (`isolated`), `unsuitable` (`refused`) or
  `unknown`. The qualification record holds the verdict, the deciding reason code and the cost at the profile's rate and
  quantum (`nsPerSampleP95`, `coreFractionP95`), and the machine class (`machine.class`). Plugin-hostd's `probe.c` writes
  that class as arch plus a core band and a clock band.
- **Zynthian.** The PH engine (branch `feat/ph-default-and-qualified-menus` of FreeMixer/zynthian-ui,
  `zyngine/zynthian_engine_plugin_hostd.py`) adds each plugin with `add <uri> <n>` and no placement, so each lands `own`
  or by `policy_set`. `sync_chain` runs after every graph rebuild and sends `chain <zynthian chain id> <members>` for the
  members of ONE Zynthian chain, when there are two or more. A refusal in `CHAIN_FALLBACK_CODES` (`PLACEMENT_INVALID`,
  `CHAIN_DUPLICATE`, `CHAIN_INSTANCE_BUSY`, `CHAIN_MIXED_FORMAT`) leaves every member alone, with one log line, and the chain
  is not tried again until its members change. So one plugin that may not share makes the whole Zynthian chain run one
  process per plugin. `zynthian_plugin_qualification.py` already reads the pin verdicts for the menus.
- **The benchmark.** `bench/` (plugin-hostd PR #179, branch `feat/bench-harness`) runs four hosts and writes `omx-bench/1`.
  Its chains-vs-processes family (`cvp3`, `cvp8`, `cvp16`) has the modes `individual` and `chain` for plugin-hostd, one
  omx-clap-host, one mod-host, and one jalv per plugin. It reports `processes`, `rss_mb_total`, `pss_mb_total`, `cpu_pct`,
  `ctx_switches`, `ctx_involuntary` and JACK `dsp_load_*`. It has no xrun field and no stress load.

The gaps this note closes: the chain is all-or-nothing, only a chain of one Zynthian strip is ever grouped, nothing is
learned from what a plugin did on this machine, and the benchmark cannot yet show xruns or stress.

## The three-line gate

1. **Which primitive?** The chain verb and its worker (`chain:<n>`), the pool, the quarantine, the pin line and its
   verdict, the qualification record, the `omx-bench/1` document. All exist. The planner chooses among them; it adds no
   new way to run a plugin.
2. **Extend the vocabulary first?** Yes, in plugin-hostd: the plan, the reason codes, the history line. The reason codes
   and the history keys are declared in `data/` and rendered like the verbs, never retyped in plugin-qualify or the
   Zynthian engine (the engine reads the daemon's declaration, as it does for reply codes today).
3. **Why isn't a plan a chain?** A chain is the controller's statement: these run together in this order. A plan is the
   daemon's answer to: given these in this order, which of them may run together. The plan ends in `chain` and `add`
   calls the daemon already has.

## The planner

A pure function in plugin-hostd. Same inputs, same plan, byte for byte; it reads no clock and no file while it decides.

**Inputs**

1. The members, in signal order: instance number, uri, format row.
2. For each: its pin (files held, layout, verdict or none) and, from the qualification record when there is one, its cost
   (`coreFractionP95` at the daemon's rate and quantum) and latency.
3. For each: its history on this host class (below), already summarised to the fields the rules read.
4. The host class, the settings (`group_max`, `group_cost_max`, `grouping`), `require_pins`, `pin_mode`.

**Output**

A list of segments in signal order. A segment is a run of consecutive members that share one worker, or one member alone.
Each segment of two or more is declared as a daemon chain; a segment of one is placed `own`. For every member that sits in
a segment of one, or whose segment ended before the next member, one reason code.

Segments are runs of consecutive members, because a chain is one callback in the declared order and a member left out of
the middle must keep its place in the signal path. So `A B C D E` with `C` unfit becomes `[A B] [C] [D E]`.

**Rules, in this order. The first rule that matches a member decides it.**

| reason | when | member goes |
|---|---|---|
| `refused` | pin verdict `refused` | not added at all (-516), as today |
| `no-pin` | no pin, `pin_mode strict` | not added (-508), as today |
| `no-verdict` | pin without a verdict (a learned pin) | alone |
| `verdict-isolated` | verdict `isolated` | alone |
| `format-world` | format pins only in a world of its own, and the chain's union world cannot be built (`chain_world_found`) | alone |
| `history-crashed` | the history marks it crashed (below) | alone |
| `history-xruns` | the history marks it as raising xruns when grouped | alone |
| `cost-over` | a cost is known and one member alone is over `group_cost_max` | alone |
| `format-mixed` | its row's program differs from the open segment's and the two rows do not both run chains in one client | starts a new segment |
| `group-full` | the open segment holds `group_max` members | starts a new segment |
| `group-cost` | adding its cost takes the open segment over `group_cost_max` | starts a new segment |

A member no rule matches joins the open segment. A plugin with no history is judged by its pin and its cost alone: no
history is neutral, otherwise a plugin could never earn one. `group_cost_max` is a fraction of one core at the daemon's
rate and quantum; a segment is one callback, so its members' costs add. Its default and `group_max`'s are set by the
benchmark (acceptance, below), not by this note. A member with no known cost counts as the median of the segment's
known costs, and as zero when none is known; the reason list says so (`cost-assumed`).

**Cross-chain leftovers.** A segment of one that passed every rule above except being alone (it was only a neighbour of an
unfit member) may share a pool with such members of other chains, `pool:g<n>` named by the daemon, up to `pool_max`. A pool
saves resident memory, not wake-ups: each member stays a JACK client. A worker that holds one chain cannot hold another
(omx-clap-host takes one `chain` line), so two chains never share a chain worker. Whether the pool is worth having is
decided by the benchmark's `pool` mode; until the numbers say so, leftovers stay alone.

**Where the plan runs.** In the daemon. Zynthian's engine is a Python controller that talks the socket and must not
carry the rules; openmixer's console must reach the same answer. Two verbs, declared in `data/verbs.json` by the first
planner lane:

- `plan <chain> <instance> [<instance> ...]`: applies the plan for this chain. The segments become the daemon's chains and
  the lone members stay or become `own`. Reply `resp 0 <segments>` with the segments as `i,i,i;i;i,i`. A chain planned
  again keeps the running workers of segments that did not change (the in-place rule of the chains note).
- `plan_get <chain>`: reads back the last plan and the reason of each member left alone, `instance:reason` joined by `,`
  (`-` for none); a `plan_reason` event carries the same when a plan changes.

`plan_clear <chain>` gives every member a worker of its own and forgets the plan, as `chain_clear` does. The place of a
segment's worker is `chain:<chain>.<k>`; the lane that declares the verbs also amends the placement grammar for it. The
existing `chain` verb stays as the controller's own statement and is not planned over.

`grouping` is a setting: `off` (today: a plan is one segment per `chain` the controller sends, nothing more), `on`.
`plan` under `off` answers the plan without applying it, with the reason `grouping-off`. The shipped default stays `off`
until the benchmark has published a win (acceptance).

## The history record

**What it is.** What each plugin did on this machine, kept per plugin, per binary and per host class. The key is
`<uri> <binary digest> <host class>`. The binary digest is the first pinned file's SHA-256 as the pin holds it, so a
changed plugin starts a fresh record and the old one is kept, not read. The host class is the machine class the daemon's
own probe writes (arch, core band, clock band), as one string, `arch/cores/clock`; the benchmark's `rpi5`, `desk` and `ci`
are labels for those classes, set by a `host_class_label` setting for the page only.

**Fields**

| key | meaning |
|---|---|
| `first`, `last` | UTC seconds of the first and the last window |
| `windows_solo`, `windows_grouped` | windows the plugin ran in a worker of its own, or in a worker of two or more |
| `cpu_p95_solo`, `cpu_max_solo` | percent of one core, worker utime plus stime over a window, windows run alone only |
| `pss_mb_solo` | `Pss` of the worker's `smaps_rollup`, MiB, largest window run alone |
| `xrun_windows_solo`, `xrun_windows_grouped` | windows in which JACK counted at least one xrun |
| `crashes_solo`, `crashes_grouped` | worker deaths the daemon attributed to the plugin (culprit named) |
| `restarts_grouped` | worker deaths while it was a member and it was not the culprit |
| `quarantines` | times the supervisor quarantined it |
| `last_crash` | UTC seconds, and `last_crash_grouped` when it was in a group |

Per-plugin CPU is kept only for windows run alone: a group's worker time cannot be split among its members honestly. For a
member of a group the planner's cost is the larger of the qualification cost and `cpu_p95_solo`. A window is
`history_window_s` seconds (60); a window with the plugin up less than half of it is not counted.

**Where it is stored.** `$XDG_STATE_HOME/plugin-hostd/history`, else `$HOME/.local/state/plugin-hostd/history`, mode 0600,
written to a temporary file in the same directory and renamed, as the pin store is. `history_file` in the settings names
another. One line per key, `history <uri> <digest> <host class> key=value ...`, a header line `# plugin-hostd history/1`; a
line with a version or a key it does not know is kept verbatim by every save and not read, as a bad pin store line is.

**Who writes.** Only the daemon, from the idle tick: it closes a window per worker, reads `/proc/<pid>/stat` and
`smaps_rollup`, reads the worker's xrun count (below), folds the window into the lines of the instances the worker holds
and saves at most once per `history_save_s` (300) and at quit. The supervisor adds a crash, a restart and a quarantine at
the moment it attributes the death. No other process writes it.

**Who reads.** The planner, through a summary: `crashed` when `crashes_*` > 0 within `history_keep_days` (30) of
`last_crash`; `raises-xruns` when `windows_grouped` >= `history_min_windows` (30) and the share of xrun windows grouped
exceeds the share solo by `history_xrun_margin` (0.05), or exceeds 0.05 when the plugin has no solo windows. plugin-qualify
reads the file directly (it runs without a daemon), so the line grammar is declared once in plugin-hostd and rendered for
the TypeScript reader, as the pin line is today. The daemon also answers `history_get <uri>` with the summary, for a
controller that has no access to the file.

**Privacy.** The history is local. It holds URIs, digests and counters only, no audio, no path outside the plugin's own
files' digest, no user name, no session or preset name. The daemon never sends it anywhere and no verb writes it from
outside; `history_clear <uri|all>` deletes it. The benchmark and plugin-qualify copy figures out of it only when the
operator runs them and names the file.

**The xrun.** JACK reports an xrun to a client, not to a plugin, and the daemon holds no JACK client (no `jack` include in `src/` or `include/`). The worker is one
(omx-clap-host). The worker therefore reports to the daemon on its feedback port a line `xruns <count>`, the count since
its start, when it changes and at most once a second. The daemon attributes a window's xruns to every member of that
worker. A group's xrun window is a suspicion of each member, not proof against one; that is why the planner compares the
grouped share with the solo share of the same plugin rather than reading an absolute count, and why a plugin that has
never run alone is not marked `raises-xruns` by anything but a large share. This line is owed to omx-clap-core and does
not exist today.

## How plugin-qualify uses it

A new step, `plugin-qualify adjust --history <file> --qualification-dir <dir>`, after `judge`. It never changes the
measurement or the first verdict; it writes a second verdict beside it, for the host class of the history, with the
reason. `--pins` writes the adjusted verdict when `--history` is given, and the measured one otherwise.

| move | when | result |
|---|---|---|
| demote `in-process` to `isolated` | `crashed`, or `raises-xruns`, on this class | reason `history.crashed` or `history.xruns-grouped` |
| demote `isolated` to `refused` | three or more solo crashes on this binary and class within `history_keep_days` | reason `history.crashed-alone` |
| promote `isolated` to `in-process` | the measured verdict is `conditional` and every deciding reason is a cost reason (`hosting.cost.*`), `windows_solo` >= 360 (six hours at 60 s), no crash, no restart, `cpu_p95_solo` under the profile's budget | reason `history.steady` |
| nothing | every other case | the measured verdict stands |

A promotion never lifts a verdict decided by real-time safety (`hosting.rt-safety.*`), a missing feature, a crash in the
prober or an `unknown`; those are measurements of the plugin, not of this machine. A `refused` verdict is never promoted
by history. The numbers above are starting values, set in `data/` of plugin-qualify and tuned only with benchmark rows.
The record gets a `history` block per host class (the applied move or `none`, the reason code, the windows read), so a
verdict can be audited: measured, adjusted, and why. Same plugin, different host class, different history, different
adjusted verdict; the measured verdict does not change.

When plugin-hostd and plugin-qualify disagree, the pin file wins at the daemon, as today: the daemon reads the pin, the
planner reads the pin and the history, and the history can only make the planner more careful than the pin, never less.

## Zynthian

`sync_chain` stops sending `chain` and sends `plan <zynthian chain id> <members>` instead, when the daemon declares the
`plan` verb; against an older daemon it keeps today's behaviour. Four consequences:

1. One plugin that may not share no longer ungroups the strip: `A B C D E` is `[A B] [C] [D E]`.
2. The engine stores the daemon's reply (`plan_get`) and shows the reason of a plugin left alone in the chain's plugin
   menu, next to the verdict tag the qualified menus already draw.
3. The strip still replays on a daemon restart: the plan is made again from the same inputs and comes out the same,
   except where the history changed.
4. `CHAIN_FALLBACK_CODES` and the per-chain `chain_refused` bookkeeping go away; the daemon's reason replaces them.

The engine carries no rule of the planner. The default placement of a lone `add` stays the daemon's.

## The benchmark

The instrument is the existing `omx-bench/1` chains-vs-processes family (`bench/`, plugin-hostd#179), extended, and run on
the Pi 5 and on the desk. The extension is its own lane because it is the only way the claim is tested.

**Modes**, same plugins, same chains, same rates and quanta, one row each:

1. `individual`: one process per plugin (daemon with no chain).
2. `chain`: the whole strip declared as one chain (today's best case, all plugins fit).
3. `plan`: the strip through the planner with `grouping on`, with at least one plugin in each strip that the pins refuse to
   share (a `no-verdict` or `isolated` one), so the plan has more than one segment.
4. `pool`: leftovers in pools, once the planner has the cross-chain step.

**Fields.** The existing ones, `processes`, `rss_mb_total`, `pss_mb_total`, `cpu_pct`, `ctx_switches`, `ctx_involuntary`,
`dsp_load_avg`, `dsp_load_max`, `add_ms`, `recover_ms`; and the new `xruns` (JACK's count over the window, from the
probe's callback) and `stress` (the load profile, or none). The schema grows by these two fields, in `omx-bench/1`
because it adds fields only; the page at openmixer-www reads them.

**Stress.** A fixed load run beside the host on the same machine for the whole window: N busy processes pinned to the
cores the host uses, N from the machine's core count, plus a memory touch of a fixed size, so that the same document on
the same class is comparable. A run with the stress and a run without are two rows of one scenario.

**Acceptance.** For each of the Pi 5 and the desk, at each rate and quantum the page already lists, at N of 8 and 16:

1. Without stress: `plan` has fewer `processes` than `individual`, `pss_mb_total` not higher, `cpu_pct` not higher, and no
   more `xruns` than `individual`.
2. With stress: `xruns` of `plan` are fewer than or equal to `individual`'s, and fewer in the sum over the matrix.
3. `plan` has no more `xruns` than `chain` where `chain` is possible, and `recover_ms` after a `kill -9` no worse than
   `chain`'s by more than the document's own noise (the run repeated three times, the spread stated).
4. Each row repeated at least three times; the page shows the median and the spread; a row that fails 1 to 3 is shown, not
   dropped.
5. Class `ci` shows the format only and is never used for acceptance (the harness's own note).

`grouping` turns `on` by default in a release only when the page carries documents that meet 1 to 3 for both classes,
and the release's notes link them. If the numbers lose, `grouping` stays `off`, the numbers are published anyway, and
`group_max` and `group_cost_max` are tuned until they win or the feature stays optional. The defaults of those two
settings are the values the winning run used.

## Failure modes

- **A member crashes.** The supervisor's rules stand: a named culprit is quarantined and moved to a worker of its own, the
  group is respawned without it and `chain_formed` names what runs (chains note). New: the crash goes into the history
  (`crashes_grouped`, `last_crash_grouped`), the planner is run again for that chain, the culprit comes out
  `history-crashed` and stays alone, and the reason is in `plan_get`. A death that names no culprit splits the members as
  today, each member is run alone, and the plan is made again after `history_regroup_s` (600) of steady running; a member
  that crashes alone is quarantined and counted as `crashes_solo`.
- **Xruns in a group.** The window is recorded against every member. If the share exceeds the margin after
  `history_min_windows` windows, the next plan leaves the highest-cost members alone (`history-xruns`) and the group is
  rebuilt in place. Nothing is changed during a window in which the worker is running a chain: a plan applies at the next
  declaration, a quarantine, or a controller's `plan` call, never by itself mid-cycle.
- **History unreadable or wrong.** A file that cannot be read, or has an unknown version, blocks reading and saving it
  (stderr says so) and the planner runs on pins and costs alone, `history-unavailable` in the reason list. A history never
  makes a plugin less safe than the pin: with no history the plan is the pin's.
- **Pin changes.** A changed file is a new digest, so a new history; the old record is kept for the old digest. A pin that
  goes to `refused` is applied at the next replay, as today.
- **The worker does not report xruns** (an older omx-clap-host, mod-host): the windows count, `xrun_windows_*` stay zero
  and the planner never marks `raises-xruns`; the plan is the pins'.
- **The daemon restarts.** The controller sends the same `plan` and gets the same segments from the same history. No state
  is needed beyond the file.
- **A plan the daemon cannot make.** Any member's `add` or `chain` refused leaves the members as they were and answers the
  refusal's own code; the plan reason is `plan-refused:<code>`.

## Lanes

Each lane is one repo and a small change, with its own test and the sabotage that reds it. They land in this order;
lanes with no arrow can run in parallel.

| lane | repo | what | needs |
|---|---|---|---|
| L1 | plugin-hostd | history record: line grammar in `data/`, reader and writer, windows from `/proc`, crash, restart and quarantine counts, `history_get`, `history_clear`, settings; no planner | |
| L2 | plugin-hostd | the planner as a pure function and the `plan`, `plan_get`, `plan_clear` verbs, the reason codes, the chain place `chain:<n>.<k>`; rules from pins and costs; `grouping off` by default; determinism test (same inputs, same bytes); one test per reason | |
| L3 | plugin-hostd | planner reads the history summary, re-plans on a quarantine, the regroup timer; the failure-mode tests | L1, L2 |
| L4 | omx-clap-core | the worker writes `xruns <count>` on its feedback port | |
| L5 | plugin-hostd | the daemon reads `xruns` into the windows | L1, L4 |
| L6 | plugin-hostd | bench: the `plan` and `pool` modes, the `xruns` and `stress` fields in the schema, the stress load, three repeats and the spread | L2, L4; PR #179 |
| L7 | plugin-qualify | `adjust --history`, the `history` block in the record, `--pins` writes the adjusted verdict, the table above in `data/` | L1 |
| L8 | zynthian-ui | `sync_chain` through `plan`, the reason in the plugin menu, the old fallback removed | L2 |
| L9 | openmixer-www | the benchmark page reads the new fields and shows medians, spreads and the stress rows | L6 |
| L10 | openmixer (#2263) | run the family on the Pi 5 and the desk, publish the documents | L6, L8, L9 |
| L11 | plugin-hostd | turn `grouping` on by default, with the winning `group_max` and `group_cost_max`; a conformance test that reads the published documents and refuses the flip without them | L10 |

The default does not flip before L11, and L11 does not start before L10 has published numbers that meet the acceptance.

## Not decided here

- Packing independent chains into one worker. omx-clap-host takes one `chain` line per worker; running several in one
  client is omx-clap-core's decision. Until then two chains never share a chain worker, and a pool is the only way to share
  a process across chains.
- The values of `group_max`, `group_cost_max`, `history_min_windows` and the promotion threshold. They are starting values
  and the benchmark sets them.
- Instruments (a plugin with a note input) in a group. They are judged like any other member by pin and cost; if the
  benchmark's `pianoteq` row says otherwise, a rule is added then.
