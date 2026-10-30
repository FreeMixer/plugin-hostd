Placement on the Pi 5
=====================

`placement none` against `placement spread` (docs/placement.md), two and then three instruments, each in a worker of
its own, a held chord of four notes on each, 60 s per run. The daemon is this branch's, built on the device; the
workers are the device's omx-clap-host 0.23.2 (its LV2 adapter, row `lv2-clap`), in the device's own jackd 1.9.22
(dummy driver, 48 kHz, 256 frames, 2 periods). Device facts: `device.txt` (Pi 5, kernel 6.18, governor powersave).

    DAEMON=./plugin-hostd OUT=out PYTHON=/zynthian/venv/bin/python3 sh run.sh

The instruments alternate Obxd (`https://obxd.wordpress.com`) and Monique (`https://surge-synthesizer.github.io/lv2/MoniqueMonosynth`).
OB-Xf, which the run was meant to use, has no LV2 bundle installed on the device (only a `dsp.ttl`), and the CLAP
Surge XT is installed at a path with a space, which a protocol word cannot carry.

Each directory holds `cores.tsv` (busy percent per core per second, from `/proc/stat`), `summary.json` (the window's
per-core busy percent and the JACK server's xruns, counted by a JACK client of the script's own), `workers.txt`
(`worker_list`, each worker's `Cpus_allowed_list`, the daemon's, and the threads' last cpu) and `daemon.log`.

| run | core 0 | core 1 | core 2 | core 3 | sum | xruns |
|---|---|---|---|---|---|---|
| 2 instruments, none | 6.9 | 9.4 | 7.1 | 7.4 | 30.8 | 0 |
| 2 instruments, spread | 1.5 | 1.3 | 23.6 | 1.7 | 28.1 | 0 |
| 3 instruments, none | 8.7 | 4.3 | 9.5 | 8.8 | 31.3 | 0 |
| 3 instruments, spread | 1.6 | 1.7 | 23.8 | 2.1 | 29.2 | 0 |

(busy percent of each core over the 60 s window)

What it shows:

- The policy does what it says: under `spread` the workers are pinned to cores 1, 2 and 3 and the daemon to core 0
  (`workers.txt`); under `none` every process may run on 0-3 and the scheduler moves the audio threads across all
  four, core 0 included.
- Core 0, the one kept for the daemon, the UI and the system, falls from 6.9-8.7 % busy to 1.5-1.6 %.
- The sum over the four cores is 2-3 points lower under `spread` (fewer migrations), within what one run can tell.
- No xrun in any run, so this load shows no xrun gain. It is a light load: Monique's audio thread is about 17 % of one
  core, Obxd's a few percent. A load that fills a core, or more instruments than audio cores, is where the placement
  is meant to matter, and this run does not measure it.
