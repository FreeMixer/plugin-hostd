Benchmarks
==========

`bench/run.sh` runs the same plugins under four hosts on one machine and writes one JSON document per run, in the
`omx-bench/1` format of `schema/omx-bench.v1.schema.json`.

| Host | Program | How it runs the plugins |
|------|---------|-------------------------|
| H1 | `omx-clap-host -n -p P` | every plugin in the one host process, driven over the mod-host protocol |
| H2 | `plugin-hostd -n -p P -c <conf>` | each plugin in a worker of its own, or a chain in one worker; omx-clap-host is the worker; the conf says `require_pins 0` |
| H3 | `mod-host -n -p P` | every plugin in the one host process; LV2 only |
| H4 | `jalv -i -n <name> <uri>` | one process per plugin; LV2 only |

Run it
------

It needs the OpenMixer channel's `plugin-hostd`, `omx-clap-host`, `omx-plugins-clap` and `omx-plugins-lv2`, plus
`jackd2`, `jack-example-tools`, `jalv`, `calf-plugins` and `python3` (on Fedora: `jack-audio-connection-kit`,
`jack-examples`, `jack-tools`, `jalv`, `lv2-calf-plugins`). `mod-host` runs H3 where it is installed.

    bench/run.sh --class rpi5 --out results/ --rates 48000,96000 --frames 128,256

| Option | Meaning |
|--------|---------|
| `--class rpi5\|desk\|ci` | the machine class; it starts the document id, `<class>-<yyyymmdd>-<seq>` |
| `--out DIR` | where the document goes |
| `--rates`, `--frames` | the matrix; the default is 48000,96000 and 128,256 |
| `--scenarios a,b` | only these scenarios |
| `--hosts H1,H2` | only these hosts |
| `--window S` | seconds of measurement per row, 10 by default |
| `--repeats N` | runs of each row, 3 by default; the document holds the median and the spread. 1 is a quick look; a document that is to say anything needs 3 or more |
| `--stress none\|on\|both` | scenarios that declare stress run without it, with it, or both (the default) |
| `--pianoteq-dir DIR` | the directory of Pianoteq's LV2 bundle; the `pianoteq` scenario runs only with it |
| `--qualify` | also time `plugin-qualify --all --isolate` at the first rate and frame count |
| `--keep-governor` | leave the CPU governor alone |
| `--logs DIR` | keep every program's output there |

By default the run sets the CPU governor to `performance` and puts the old one back at the end, which needs root or
`sudo`. Every rate and frame count gets a private JACK server, `jackd -n bench<pid> -d dummy -r <rate> -p <frames>`, and
every program of the run talks to that server only, so a JACK server already running on the machine is never touched.
Each row starts its host fresh on a port of its own and stops it after. The run ends by checking that no process it
started is left, whatever happened, and exits 3 if one was.

`bench/validate.sh <file>...` checks documents against the schema; a problem prints the file, the row and the rule,
and the exit is 1. `bench/lib/send.sh <port> <line>...` sends protocol lines to a host by hand.
`bench/table.sh <file>...` writes the chains and grouping rows as markdown: the figures with their spread, the ratios of
one process per plugin to one chain, and the xruns summed per mode, with and without stress. A table of grouped against
one process per plugin is made by running the `cvp3,cvp8,cvp16` scenarios on the machine and handing the document to it.

Scenarios
---------

The table is `scenarios.json`. The source is `jack_simple_client`'s sine, or `jack_midiseq` playing five-note chords
for an instrument, wired through the plugins in series into the playback ports.

| Id | What runs |
|----|-----------|
| `idle` | the host with no plugin |
| `clap1` | omx-comp as CLAP |
| `lv2-1` | Calf Compressor (LV2) |
| `chain3` | omx-comp, Calf Compressor, omx-delay; a chain under H2, three instances in series elsewhere |
| `clap16` | 16 instances of omx-comp |
| `pianoteq` | Pianoteq 9 playing chords |
| `kill1` | omx-comp, then `kill -9` of the process that holds it |
| `cvp3`, `cvp8`, `cvp16` | chains vs processes: N plugins cycling omx-comp, Calf Compressor, omx-delay, omx-drive |
| `grp8`, `grp16` | grouping vs processes: N CLAP plugins cycling omx-comp, omx-drive, omx-delay, omx-drive, omx-comp, where omx-drive is pinned `isolated` |

H1 and H2 take our plugins as CLAP and Calf through the LV2 adapter. H3 and H4 take the LV2 builds of our plugins,
and the row's note says so.

Chains vs processes runs the same N plugins in each of these modes, one row per mode for each N, rate and frame count:

| Mode | Host | Processes |
|------|------|-----------|
| `individual` | H2, no chain declared | the daemon and N workers |
| `chain` | H2, `chain 1 <ids>` | the daemon and one worker |
| `shared-process` | H1 | one omx-clap-host |
| `shared-process` | H3 | one mod-host |
| `individual` | H4 | N jalv processes |

Grouping vs processes (`grp8`, `grp16`) runs one strip four ways under H2 only:

| Mode | How plugin-hostd runs the strip | Processes |
|------|---------------------------------|-----------|
| `individual` | no chain declared, `require_pins 0` | the daemon and N workers |
| `chain` | `chain 1 <ids>`, `require_pins 0`: the case where every plugin may share | the daemon and one worker |
| `plan` | `grouping on`, `require_pins 1`, a verdict per plugin; `plan 1 <ids>` | the daemon and one worker per segment |
| `pool` | the same plan, then the members it left alone that the pins let share leave for `pool:g1` | the daemon, the chain workers, the isolated ones, one pool worker |

A row of `plan` or `pool` needs a plugin-hostd with the planner (plugin-hostd#185). Without it the daemon refuses the
`grouping` setting and the row says `unsupported`, with that as its note. The runner starts a daemon once to let it learn
each plugin's pin, then writes a verdict on each line of the daemon's own pin store: `isolated` for the plugins the
scenario names under `unshared`, `in-process` for the rest, and starts the row's daemon on that store with the package
pins off. A plan of one segment is a `failed` row (nothing was left for the pins to cut, so it is the `chain` row), and so
is a pool that the daemon did not form from exactly the members the runner moved into it. One strip is one chain, so the
pool holds that strip's leftovers; sharing a pool across chains is the planner's own later step.
Reading the numbers
-------------------

| Field | Meaning |
|-------|---------|
| `dsp_load_avg`, `dsp_load_max` | JACK's DSP load in percent, one `jack_cpu_load` reading a second over the window, the first dropped |
| `samples` | how many readings |
| `xruns` | JACK's xrun callbacks over the window, counted by a client of the run's private server (`libjack` through ctypes, no port and no process callback, so it adds no work to the cycle). If the server's own log names xruns in the window and the probe counted none, the row is `failed`: a deaf probe reads 0 on every row |
| `latency_frames` | the capture latency JACK reports at `system:playback_1`, the longest of its range: what the clients on the path declared, not a measurement of the audio; a host that declares none contributes none |
| `jack_clients` | the JACK clients the host put on the graph: every client with ports there after the plugins are wired that was not there before the host started, the source excepted |
| `stress` | `none`, or `busy<cores>+mem<MiB>`: one busy loop pinned to each core the host may use, and a process that keeps touching 256 MiB, running beside the host for the whole window. The same name on the same machine is the same load. The same scenario with and without stress is two rows |
| `repeats`, `spread` | a row run `repeats` times holds the median of each measure, a count taking the higher middle run so it is never understated, and `spread`: `{measure: [min, max]}`. A repeat that fails fails the row and its note says which; a row that is `unsupported` is not repeated |
| `rss_mb`, `rss_mb_total` | resident memory summed over the host's processes at the end of the window |
| `pss_mb_total` | proportional memory (`Pss` of `smaps_rollup`) summed the same way: shared libraries counted once across the processes |
| `processes` | the host's processes: itself and every descendant, the workers of plugin-hostd included |
| `cpu_pct` | utime plus stime of those processes over the window, in percent of one core |
| `ctx_switches`, `ctx_involuntary` | context switches of all their threads over the window, and how many of them were involuntary |
| `add_ms` | from the first `add` to the last reply; for H2 `chain` until the chain runs; for H4 until the last client is in the graph |
| `recover_ms` | from `kill -9` of the worker until its client is back and wired as before |
| `status` | `ok`; `unsupported` when the host cannot run the scenario; `failed` when it ran and broke; the note says why |

Under H1, H3 and H4 the killed process is the host itself, so `kill1` ends `failed` with the note `host process lost`.

`xruns`, `latency_frames`, `jack_clients`, `stress`, `repeats` and `spread`, and the modes `plan` and `pool`, are additions to
`omx-bench/1`: a document without them is valid, and a reader that ignores them reads the document as before.

`qualification` is written with `--qualify`: the CLAP plugins on the machine, the seconds `plugin-qualify` took, and how
many it rated suitable.

The DSP load of class `ci` comes from a container on a shared machine and tells nothing about a device; it is there to
show the format. Compare rows of one document, or of documents of one class.

Tests
-----

`python3 -I bench/tests/test_bench.py` needs no JACK server and no host: the schema and validator rules, the xrun probe
against a stand-in `libjack`, the stress processes (pinned, resident) on the machine it runs on, the median and spread,
the plan and pool steps against a stand-in daemon on a socket, the pin verdicts, and the tables. `bench/tests/sabotage.sh`
breaks one line behind each of those guards in a copy and requires its test to go red; `--teardown` also runs the hosts.
