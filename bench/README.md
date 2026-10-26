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
`jackd2`, `jack-example-tools`, `jalv`, `calf-plugins` and `python3`. `mod-host` runs H3 where it is installed.

    bench/run.sh --class rpi5 --out results/ --rates 48000,96000 --frames 128,256

| Option | Meaning |
|--------|---------|
| `--class rpi5\|desk\|ci` | the machine class; it starts the document id, `<class>-<yyyymmdd>-<seq>` |
| `--out DIR` | where the document goes |
| `--rates`, `--frames` | the matrix; the default is 48000,96000 and 128,256 |
| `--scenarios a,b` | only these scenarios |
| `--hosts H1,H2` | only these hosts |
| `--window S` | seconds of measurement per row, 10 by default |
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

Reading the numbers
-------------------

| Field | Meaning |
|-------|---------|
| `dsp_load_avg`, `dsp_load_max` | JACK's DSP load in percent, one `jack_cpu_load` reading a second over the window, the first dropped |
| `samples` | how many readings |
| `rss_mb`, `rss_mb_total` | resident memory summed over the host's processes at the end of the window |
| `pss_mb_total` | proportional memory (`Pss` of `smaps_rollup`) summed the same way: shared libraries counted once across the processes |
| `processes` | the host's processes: itself and every descendant, the workers of plugin-hostd included |
| `cpu_pct` | utime plus stime of those processes over the window, in percent of one core |
| `ctx_switches`, `ctx_involuntary` | context switches of all their threads over the window, and how many of them were involuntary |
| `add_ms` | from the first `add` to the last reply; for H2 `chain` until the chain runs; for H4 until the last client is in the graph |
| `recover_ms` | from `kill -9` of the worker until its client is back and wired as before |
| `status` | `ok`; `unsupported` when the host cannot run the scenario; `failed` when it ran and broke; the note says why |

Under H1, H3 and H4 the killed process is the host itself, so `kill1` ends `failed` with the note `host process lost`.

`qualification` is written with `--qualify`: the CLAP plugins on the machine, the seconds `plugin-qualify` took, and how
many it rated suitable.

The DSP load of class `ci` comes from a container on a shared machine and tells nothing about a device; it is there to
show the format. Compare rows of one document, or of documents of one class.
