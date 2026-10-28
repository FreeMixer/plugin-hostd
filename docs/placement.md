Core placement: one worker per chain, pinned across the audio cores
===================================================================

plugin-hostd runs each chain (and each plugin that may not share) in a worker process of its own. On a small machine,
a Raspberry Pi 5 with four cores, the kernel and the JACK server decide where those processes run unless someone pins
them. A plugin's own threads do not help: Surge XT 1.4.0 and the other plugins measured on the Pi 5 ignore CLAP's
thread-pool extension, so one instrument is one audio thread. Several instruments use several cores only when each
runs in a worker of its own and those workers are spread over the cores, with the daemon, the UI and the system kept
off them.

The setting `placement` does that (plugin-hostd#226).

The policy
----------

- **Audio cores.** `audio_cores` is a cpu list (`1-3`, `2,3`). Empty, the default, is every cpu the daemon may run on
  when it starts (its affinity, so a `taskset` or a cgroup is honoured) except the lowest one. A list that names a cpu
  outside that set refuses the start.
- **The reserved cores** are the daemon's cpus that are not audio cores: the lowest one by default. The daemon pins
  itself and all its threads there at start. The processes it starts that are not workers, the descriptor scans and
  probes, are forked from it and inherit that mask. The UI is the system's to pin there (`taskset -c 0`, or
  `CPUAffinity=0` in its unit). With no reserved core left (`audio_cores` names every cpu) the daemon is not pinned, and stderr says so.
- **Each new worker** is pinned (`sched_setaffinity`, in the child before it runs the worker program, so every thread
  it creates, its JACK or PipeWire thread included, inherits the mask) to one audio core: the one with the least load.
  The load of a core is the sum of the estimated costs of the workers already placed on it, when the cost of every
  placed worker is known. A worker's cost is the sum of its members' `coreFractionP95` from their qualification records
  at `group_rate` and `group_quantum`, as the planner reads it. When any placed worker has a member without a record,
  the load is the number of workers. Ties go to the lowest core. So four workers on four cpus land on cores 1, 2, 3 and
  1, with the daemon on 0.
- **A worker keeps its core** when it is respawned. A worker that is made anew (a chain formed, a group split by a
  death, a quarantined member moved out) is placed again.
- **Chains and isolated plugins.** A chain, whether declared by `chain` or a segment of a `plan`, is one worker, so it
  takes one core. A plugin the planner leaves alone, an `isolated` verdict among them (plugin-hostd#231), gets a worker
  of its own, placed by the same rule. Zynthian still sees one chain.
- **`worker_env`.** A format whose workers were given a cpu list by `worker_env` keeps that list: the policy does not
  move those workers, and they report no core.
- **`placement none`** is the behaviour before this setting. Nothing is pinned, the workers inherit the daemon's mask,
  and the reports say `-`.

The configuration
-----------------

In the settings file (`-c`, or `$XDG_CONFIG_HOME/plugin-hostd.conf`):

    placement spread        # or none
    audio_cores 1-3         # empty: every cpu the daemon may use but the lowest

and on the command line, over the file: `plugin-hostd --placement=none`.

What reports the core
---------------------

- `worker_list`: each record is `<worker>:<pid>:<format>:<state>:<core>:<place>:<instances>`, `<core>` the audio core
  the policy pinned it to, `-` for none. The place still holds colons, so a record is read from both ends: five fields
  on the left, the instances on the right.
- `plan` answers `resp 0 <segments> <cores>` and `plan_get` `resp 0 <segments> <reasons> <cores>`: `<cores>` has the
  shape of `<segments>`, each member replaced by the core of the worker that runs it now (`-` for none), so `1,2;3`
  placed on cores 2 and 1 reads `2,2;1`.

Measured
--------

Not measured yet. The run that measures it, on a Pi 5, is two and then three instruments in separate chains, 60 s per
mode, `placement none` against `placement spread`, with per-core CPU from `mpstat -P ALL 1 60` and the xruns the
workers count over the window; its raw numbers go under `docs/evidence/`.
