Core placement: the workers on the audio cores, the daemon off them
===================================================================

plugin-hostd runs each chain (and each plugin that may not share) in a worker process of its own. On a small machine,
a Raspberry Pi 5 with four cores, the kernel and the JACK server decide where those processes run unless someone pins
them. A plugin's own threads do not help: Surge XT 1.4.0 and the other plugins measured on the Pi 5 ignore CLAP's
thread-pool extension, so one instrument is one audio thread. Several instruments use several cores only when each
runs in a worker of its own on cores the daemon, the UI and the system are kept off.

The setting `placement` does that.

The policy
----------

- **Audio cores.** `audio_cores` is a cpu list (`1-3`, `2,3`). Empty, the default, is every cpu the daemon may run on
  when it starts (its affinity, so a `taskset` or a cgroup is honoured) except one: the cpu of least capacity, the
  lowest of a tie. A list that names a cpu outside that set refuses the start.
- **The reserved cores** are the daemon's cpus that are not audio cores: by default the one of least capacity
  (below). The daemon pins itself and all its threads there at start. The processes it starts that are not workers,
  the descriptor scans and probes, are forked from it and inherit that mask. The UI is the system's to pin there (`taskset -c <cpu>`, or
  `CPUAffinity=<cpu>` in its unit; stderr names the cpu at start). With no reserved core left (`audio_cores` names
  every cpu) the daemon is not pinned, and stderr says so.
- **Each new worker** is pinned (`sched_setaffinity`, in the child before it runs the worker program, so every thread
  it creates, its JACK or PipeWire thread included, inherits the mask) to all the audio cores, never to one core of
  them. The kernel then places the threads: workers that run side by side spread over the audio cores, and workers
  linked in series stay where the last one woke them. A respawned worker, and one made anew (a chain formed, a group
  split by a death, a quarantined member moved out), gets the same mask.
- **Chains and isolated plugins.** A chain, whether declared by `chain` or a segment of a `plan`, is one worker. A
  plugin the planner leaves alone, an `isolated` verdict among them, gets a worker of its own, on the
  audio cores as every other. Zynthian still sees one chain.
- **`worker_env`.** A format whose workers were given a cpu list by `worker_env` keeps that list: the policy does not
  move those workers, and they report no core.
- **`placement none`** pins nothing. Nothing is pinned, the workers inherit the daemon's mask,
  and the reports say `-`.

The configuration
-----------------

In the settings file (`-c`, or `$XDG_CONFIG_HOME/plugin-hostd.conf`):

    placement spread        # or none
    audio_cores 1-3         # empty: every cpu the daemon may use but the one of least capacity

and on the command line, over the file: `plugin-hostd --placement=none`.

Why not one core per worker
---------------------------

The first `spread` pinned each new worker to one audio core of its own, the least loaded: by the sum of the
qualification costs of the workers on it, or by their count when a cost was unknown, so with no records the workers went
round the cores. That is what a series chain of workers cannot take. JACK wakes the clients of a chain one after the
other within each period; each worker on a core of its own is woken on a core that was idle, so every hop pays an
interrupt to another core and the exit from its idle state, and a 48-worker chain pays it 48 times a period.

The desk benchmark of plugin-hostd 0.16.0 (Intel Core Ultra 9 275HX, 24 cpus, governor performance, JACK2 at 96 kHz and
64 frames, 0.67 ms periods, three repeats; the `chains-vs-processes` scenarios, every plugin a worker of its own, linked
in series) measured it. Each row is the DSP load and xruns at 48 plugins with no other load, then with all cores kept
busy:

| 48 plugins in series | DSP, idle cores | xruns | DSP, busy cores | xruns |
|---|---|---|---|---|
| plugin-hostd, one worker each, one core each (CLAP) | 69.3 % | 491 | 41.1 % | 128 |
| jalv, one process each, no pinning (LV2) | 31.5 % | 0 | 39.0 % | 0 |
| omx-clap-host, one process (CLAP) | 25.3 % | 0 | 39.4 % | 0 |
| plugin-hostd, one worker for the chain (CLAP) | 13.6 % | 0 | 15.2 % | 0 |

plugin-hostd and jalv ran the same number of processes, JACK clients and context switches (820 000 to 880 000 a run); the
difference is the pinning. It is about 5 µs a hop with idle cores and disappears when every core is kept busy, which is
what a wakeup on a cold core costs. Over every chain length the one-core-per-worker rule had 1100
xruns, 967 of them at 48 plugins, 110 at 32 and 16 at 24; jalv had 3. On a Pi 5 with three audio cores and 16 plugins
or fewer the hops were too few to show.

With the whole audio set the kernel may keep a series chain on the core that woke it, and still spreads workers that run
side by side. A chain declared as one worker is the cheapest of all and stays the way to run many plugins in series.

Which core is reserved
----------------------

The daemon and the UI need little, so the core kept for them is the weakest one, and the audio keeps the strong ones.
The capacity of each cpu is read from `/sys/devices/system/cpu/cpu<n>/cpu_capacity`, which the kernel writes on hybrid
and big.LITTLE machines; where a cpu lacks it, from `cpufreq/cpuinfo_max_freq`; where both are missing, nothing is
known. The reserved core is the cpu of least capacity, the lowest of a tie, so a machine whose cpus are all alike (a
Raspberry Pi 5) keeps cpu 0 as before.

Reserving cpu 0 on a hybrid cpu takes a performance core from the audio. On the Intel Core Ultra 9 275HX of the desk
benchmark, cpus 0-7 are performance cores (`cpu_capacity` 1000) and 8-23 efficiency cores (765): with cpu 0 reserved,
48 workers had 7 performance cores where `placement none` gave them 8, and `none` had fewer xruns in three of four
cells at 96 kHz/64. Now the daemon sits on cpu 8 and the workers keep all eight performance cores.

What reports the core
---------------------

- `worker_list`: each record is `<worker>:<pid>:<format>:<state>:<core>:<pool>:<place>:<instances>`. `<core>` is
  always `-`: no worker is pinned to one core of its own. `<pool>` is `on` or `qualified` (below). The place still holds
  colons, so a record is read from both ends: six fields on the left, the instances on the right.
- `plan` answers `resp 0 <segments> <cores>` and `plan_get` `resp 0 <segments> <reasons> <cores>`: `<cores>` has the
  shape of `<segments>` with each member replaced by `-`, so `1,2;3` reads `-,-;-`.

The CLAP thread pool
--------------------

omx-clap-host's pool of helper threads (`--thread-pool=qualified|off|on`, omx-clap-core#395) sizes itself from the
worker's affinity mask: N cores, N - 1 helpers. Under `spread` that mask is the audio cores, so a Pi 5 with three audio
cores gives a pool two helpers. The pool is the plugin's qualification's to give, never a global switch,
and it travels in the plugin's pin as the word `pool=cores` (or `pool=off`) after the verdict:

    pin_set <uri> <files> <layout> verdict=isolated pool=cores

A CLAP or lv2-clap worker of a plugin whose pin says `pool=cores` (and is not a refusal) is started with
`--thread-pool=on`, after the cpus above are set, so the mask it sizes the pool from is the one the policy gave it. The
plugin runs in a worker of its own: the planner leaves it alone (`verdict-isolated`), a `pool:` placement and a chain
are refused for it, and a respawn starts the worker with the option again. Every other worker is started with no
option, the host's `qualified`, which grants the pool to no plugin. The pool's waits past the block are in the worker's
`xruns` line, so they are attributed as any xrun is. Pins are read while `require_pins` is on, so the pool is too.

Measured
--------

On a Pi 5 (docs/evidence/placement-pi5-2026-10-29/): two and three LV2 instruments (Obxd, Monique) in
workers of their own, 60 s each, under the first `spread` (one core each). The workers sat on cores 1-3 and the daemon
on 0, and core 0 fell from 7-9 % busy to under 2 %; the sum over the cores was 2-3 points lower. Neither mode had an
xrun at that load: the instruments use a fraction of one core. Core 0 is the reserved core there still, since the Pi's
cores are all alike. The desk measurement of series chains is above, under Why not one core per worker.
