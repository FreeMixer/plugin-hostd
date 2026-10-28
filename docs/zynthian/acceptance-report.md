<!-- Written by bench/report/make_report.py on 2026-10-28 from: the omx-bench/1 run rpi5-20261027-1
(evidence/pi5-bench-2026-10-27/rpi5-20261027-1.json), the device notes of evidence/pi5-bench-2026-10-27/
(grouped-vs-processes.md, earlier/), the 1823 qualification documents of the Pi 5 run of 2026-10-28
(/root/omx-deep-20261028/records/ on the device, sha256 of the files concatenated in name order
7bbfca1313b8875bc6b59f68412fd8483cc612d538032832b5a063848b22e126), the LV2 coverage summary of a Fedora 44 desktop
(evidence/desk-lv2-coverage-2026-10-26/summary.txt) and the pull request states of evidence/prs-2026-10-28.json.
Not --strict: the run of 2026-10-27 has no 128-frame rows and no xrun or latency figures, and every section without
data says "not measured yet". Section 4 counts verdicts, one per host profile, not plugins; the LV2 coverage is of
the desktop's 979 plugins, not of the Pi's. The command is in benchmarks.md, "Reproducing". -->

> Read with [benchmarks.md](benchmarks.md). Section 4 counts the records' own ratings, written before the ruling of
> plugin-qualify#196 and plugin-hostd#231: a plugin that fails the RT-safety sweep is isolated (a worker of its own,
> never grouped), not unsuitable. benchmarks.md gives the same records in the three classes.

# plugin-hostd, the PH engine, qualified menus and OpenMixer by default in Zynthian

This report is built from a partial run: 224 reasons, the first 20 listed.

- chain3 H1: no row at 48000/128, 96000/128
- chain3 H2: no row at 48000/128, 96000/128
- chain3 H3: no row at 48000/128, 96000/128
- chain3 H4: no row at 48000/128, 96000/128
- clap1 H1: no row at 48000/128, 96000/128
- clap1 H2: no row at 48000/128, 96000/128
- clap1 H3: no row at 48000/128, 96000/128
- clap1 H4: no row at 48000/128, 96000/128
- clap16 H1: no row at 48000/128, 96000/128
- clap16 H2: no row at 48000/128, 96000/128
- clap16 H3: no row at 48000/128, 96000/128
- clap16 H4: no row at 48000/128, 96000/128
- cvp16 H1 shared-process: no row at 48000/128, 96000/128
- cvp16 H1 shared-process under stress: no row at 48000/128, 48000/256, 96000/128, 96000/256
- cvp16 H2 chain: no row at 48000/128, 96000/128
- cvp16 H2 chain under stress: no row at 48000/128, 48000/256, 96000/128, 96000/256
- cvp16 H2 individual: no row at 48000/128, 96000/128
- cvp16 H2 individual under stress: no row at 48000/128, 48000/256, 96000/128, 96000/256
- cvp16 H3 shared-process: no row at 48000/128, 96000/128
- cvp16 H3 shared-process under stress: no row at 48000/128, 48000/256, 96000/128, 96000/256

## 1. What we change

Sections 1, 2, 5 and 6 restate what the pull requests below say; each line names its pull request. They are not measurements. Sections 3 and 4 hold the measurements, every number read from the files named in the tool's help.

- An apt repository for OpenMixer and a recipe that installs plugin-hostd, omx-clap-host, omx-plugins and omx-panel (FreeMixer/zynthian-sys#1)
- ZYNTHIAN_MODHOST_BACKEND picks what answers MOD-UI on port 5555: jack_load, or plugin-hostd (FreeMixer/zynthian-sys#2)
- A plugin that ships no MOD GUI gets one made by omx-panel modgui from its descriptor (FreeMixer/zynthian-sys#3)
- OpenMixer is installed by default on new images and by update_zynthian_sys.sh and update_system_image.sh (FreeMixer/zynthian-sys#4)
- A new engine, PH, runs LV2 and CLAP plugins in one plugin-hostd daemon per Zynthian, on port 5570, and declares the members of a Zynthian chain to the daemon as a chain (FreeMixer/zynthian-ui#1)
- plugin-hostd is the default engine, and the plugin menus are built from plugin-qualify records (FreeMixer/zynthian-ui#2)

## 2. What the user gets

- The plugin controller pages come from omx-panel's layout of the plugin descriptor, eight controls to a page (FreeMixer/zynthian-ui#1)
- Each plugin entry carries a tag such as 'live, 1.2 ms, RT'; live means real-time safe with a measured latency of at most ZYNTHIAN_PLUGIN_LIVE_MS (5) at the worst measured rate (FreeMixer/zynthian-ui#2)
- Plugins that are pinned refused, or that crashed or hung during qualification, are hidden; ZYNTHIAN_PLUGIN_SHOW_HIDDEN=1 lists them last, greyed, with the reason (FreeMixer/zynthian-ui#2)

## 3. Measurements

DSP load is the JACK DSP load read with jack_cpu_load; memory is resident (RSS) and proportional (PSS) from /proc.

Run rpi5-20261027-1 on Raspberry Pi 5 Model B Rev 1.0 (Cortex-A76, 4 cores, 4045 MB RAM, Debian 13, kernel 6.18.50+rpt-rpi-2712), governor performance. Software: plugin-hostd 0.12.0, omx-clap-host 0.22.1, mod-host 0.10.6-595-g6c1cdd8 (not packaged), jalv 1.6.9 (not packaged), jack 1.9.22~dfsg-4, omx-plugins-clap 0.13.0, omx-plugins-lv2 0.13.0, calf-plugins 5:0.90.3-1kxstudio3.

### The four hosts

### CPU: DSP load, average (maximum), percent

| scenario | rate | frames | omx-clap-host alone | plugin-hostd | mod-host | jalv |
|---|---|---|---|---|---|---|
| the host running, no plugin | 48000 | 256 | 0.13 (0.13) | 0.15 (0.16) | 0.19 (0.19) | unsupported (jalv runs one plugin per process; it has no host without a plugin) |
| the host running, no plugin | 96000 | 256 | 0.26 (0.26) | 0.27 (0.30) | 0.34 (0.36) | unsupported (jalv runs one plugin per process; it has no host without a plugin) |
| one CLAP plugin, sine in | 48000 | 256 | 0.57 (0.60) | 0.55 (0.56) | unsupported (mod-host runs LV2 only) | unsupported (jalv runs LV2 only) |
| one CLAP plugin, sine in | 96000 | 256 | 1.13 (1.48) | 1.01 (1.01) | unsupported (mod-host runs LV2 only) | unsupported (jalv runs LV2 only) |
| one LV2 plugin, sine in | 48000 | 256 | 0.70 (0.72) | 0.70 (0.73) | 0.72 (0.73) | 0.72 (0.86) |
| one LV2 plugin, sine in | 96000 | 256 | 1.27 (1.30) | 1.27 (1.28) | 1.38 (1.39) | 1.33 (1.38) |
| three plugins in a chain, sine in | 48000 | 256 | 1.31 (1.45) | 1.33 (1.57) | 1.17 (1.19) | 1.29 (1.35) |
| three plugins in a chain, sine in | 96000 | 256 | 2.37 (2.42) | 2.36 (2.37) | 2.23 (2.30) | 2.33 (2.36) |
| 16 instances of one CLAP plugin, sine in | 48000 | 256 | 6.08 (6.19) | 7.19 (7.23) | 5.32 (5.34) | 6.69 (6.84) |
| 16 instances of one CLAP plugin, sine in | 96000 | 256 | 12.25 (12.35) | 13.78 (15.36) | 10.41 (10.93) | 15.16 (34.53) |

### RAM: resident memory of the host processes, MB (PSS in brackets when measured)

| scenario | rate | frames | omx-clap-host alone | plugin-hostd | mod-host | jalv |
|---|---|---|---|---|---|---|
| the host running, no plugin | 48000 | 256 | 107.6 (36.6) | 1.1 (0.6) | 121.7 (51.0) | unsupported (jalv runs one plugin per process; it has no host without a plugin) |
| the host running, no plugin | 96000 | 256 | 107.6 (36.6) | 1.1 (0.6) | 122.2 (51.0) | unsupported (jalv runs one plugin per process; it has no host without a plugin) |
| one CLAP plugin, sine in | 48000 | 256 | 108.7 (37.2) | 110.8 (38.0) | unsupported (mod-host runs LV2 only) | unsupported (jalv runs LV2 only) |
| one CLAP plugin, sine in | 96000 | 256 | 108.7 (37.2) | 110.3 (37.9) | unsupported (mod-host runs LV2 only) | unsupported (jalv runs LV2 only) |
| one LV2 plugin, sine in | 48000 | 256 | 115.7 (45.2) | 118.9 (46.0) | 125.2 (53.8) | 115.8 (44.2) |
| one LV2 plugin, sine in | 96000 | 256 | 117.3 (45.2) | 118.3 (46.0) | 124.3 (53.2) | 115.8 (44.2) |
| three plugins in a chain, sine in | 48000 | 256 | 120.4 (49.0) | 122.5 (50.0) | 129.2 (58.3) | 345.1 (88.6) |
| three plugins in a chain, sine in | 96000 | 256 | 119.9 (49.0) | 121.9 (49.9) | 127.8 (56.8) | 345.0 (88.6) |
| 16 instances of one CLAP plugin, sine in | 48000 | 256 | 112.7 (41.4) | 1736.5 (116.2) | 132.7 (62.5) | 1813.3 (199.6) |
| 16 instances of one CLAP plugin, sine in | 96000 | 256 | 111.2 (41.4) | 1736.8 (116.1) | 123.7 (53.6) | 1811.8 (199.5) |

### Processes

| scenario | rate | frames | omx-clap-host alone | plugin-hostd | mod-host | jalv |
|---|---|---|---|---|---|---|
| the host running, no plugin | 48000 | 256 | 1 | 1 | 1 | unsupported (jalv runs one plugin per process; it has no host without a plugin) |
| the host running, no plugin | 96000 | 256 | 1 | 1 | 1 | unsupported (jalv runs one plugin per process; it has no host without a plugin) |
| one CLAP plugin, sine in | 48000 | 256 | 1 | 2 | unsupported (mod-host runs LV2 only) | unsupported (jalv runs LV2 only) |
| one CLAP plugin, sine in | 96000 | 256 | 1 | 2 | unsupported (mod-host runs LV2 only) | unsupported (jalv runs LV2 only) |
| one LV2 plugin, sine in | 48000 | 256 | 1 | 2 | 1 | 1 |
| one LV2 plugin, sine in | 96000 | 256 | 1 | 2 | 1 | 1 |
| three plugins in a chain, sine in | 48000 | 256 | 1 | 2 | 1 | 3 |
| three plugins in a chain, sine in | 96000 | 256 | 1 | 2 | 1 | 3 |
| 16 instances of one CLAP plugin, sine in | 48000 | 256 | 1 | 17 | 1 | 16 |
| 16 instances of one CLAP plugin, sine in | 96000 | 256 | 1 | 17 | 1 | 16 |

- idle, 48000 Hz/256, omx-clap-host alone: 0.13%
- idle, 48000 Hz/256, plugin-hostd: 0.15%
- idle, 48000 Hz/256, mod-host: 0.19%
- idle, 96000 Hz/256, omx-clap-host alone: 0.26%
- idle, 96000 Hz/256, plugin-hostd: 0.27%
- idle, 96000 Hz/256, mod-host: 0.34%
- clap1, 48000 Hz/256, omx-clap-host alone: 0.57%
- clap1, 48000 Hz/256, plugin-hostd: 0.55%
- clap1, 96000 Hz/256, omx-clap-host alone: 1.13%
- clap1, 96000 Hz/256, plugin-hostd: 1.01%
- lv2-1, 48000 Hz/256, omx-clap-host alone: 0.70%
- lv2-1, 48000 Hz/256, plugin-hostd: 0.70%
- lv2-1, 48000 Hz/256, mod-host: 0.72%
- lv2-1, 48000 Hz/256, jalv: 0.72%
- lv2-1, 96000 Hz/256, omx-clap-host alone: 1.27%
- lv2-1, 96000 Hz/256, plugin-hostd: 1.27%
- lv2-1, 96000 Hz/256, mod-host: 1.38%
- lv2-1, 96000 Hz/256, jalv: 1.33%
- chain3, 48000 Hz/256, omx-clap-host alone: 1.31%
- chain3, 48000 Hz/256, plugin-hostd: 1.33%
- chain3, 48000 Hz/256, mod-host: 1.17%
- chain3, 48000 Hz/256, jalv: 1.29%
- chain3, 96000 Hz/256, omx-clap-host alone: 2.37%
- chain3, 96000 Hz/256, plugin-hostd: 2.36%
- chain3, 96000 Hz/256, mod-host: 2.23%
- chain3, 96000 Hz/256, jalv: 2.33%
- clap16, 48000 Hz/256, omx-clap-host alone: 6.08%
- clap16, 48000 Hz/256, plugin-hostd: 7.19%
- clap16, 48000 Hz/256, mod-host: 5.32%
- clap16, 48000 Hz/256, jalv: 6.69%
- clap16, 96000 Hz/256, omx-clap-host alone: 12.25%
- clap16, 96000 Hz/256, plugin-hostd: 13.78%
- clap16, 96000 Hz/256, mod-host: 10.41%
- clap16, 96000 Hz/256, jalv: 15.16%

### Recovery after kill -9 of the process holding one plugin

| host | rate | frames | recover ms | status | note |
|---|---|---|---|---|---|
| omx-clap-host alone | 48000 | 256 | n/a | failed | host process lost |
| plugin-hostd | 48000 | 256 | 347 | ok |  |
| mod-host | 48000 | 256 | n/a | failed | LV2 builds of omx-comp; host process lost |
| jalv | 48000 | 256 | n/a | failed | LV2 builds of omx-comp; host process lost |
| omx-clap-host alone | 96000 | 256 | n/a | failed | host process lost |
| plugin-hostd | 96000 | 256 | 336 | ok |  |
| mod-host | 96000 | 256 | n/a | failed | LV2 builds of omx-comp; host process lost |
| jalv | 96000 | 256 | n/a | failed | LV2 builds of omx-comp; host process lost |

### Xruns and latency

*xruns per host: not measured yet.*

*declared latency to system:playback_1 per host: not measured yet.*

### One worker for a chain against one process per plugin

| set | stress | rate | frames | mode | processes | RSS MB | PSS MB | CPU % of a core | DSP load % | add ms |
|---|---|---|---|---|---|---|---|---|---|---|
| chains vs processes, 3 plugins | not recorded | 48000 | 256 | H1 shared-process | 1 | 119.2 | 48.9 | 1.24 | 1.47 | 189 |
| chains vs processes, 3 plugins | not recorded | 48000 | 256 | H2 chain | 2 | 121.7 | 50.0 | 1.50 | 1.30 | 595 |
| chains vs processes, 3 plugins | not recorded | 48000 | 256 | H2 individual | 4 | 337.6 | 80.0 | 1.86 | 1.33 | 292 |
| chains vs processes, 3 plugins | not recorded | 48000 | 256 | H3 shared-process | 1 | 128.7 | 58.3 | 1.15 | 1.17 | 82 |
| chains vs processes, 3 plugins | not recorded | 48000 | 256 | H4 individual | 3 | 345.0 | 88.6 | 1.06 | 1.26 | 416 |
| chains vs processes, 3 plugins | not recorded | 96000 | 256 | H1 shared-process | 1 | 120.5 | 49.0 | 2.39 | 2.34 | 162 |
| chains vs processes, 3 plugins | not recorded | 96000 | 256 | H2 chain | 2 | 122.0 | 49.9 | 2.39 | 2.39 | 550 |
| chains vs processes, 3 plugins | not recorded | 96000 | 256 | H2 individual | 4 | 337.3 | 79.9 | 2.74 | 2.47 | 270 |
| chains vs processes, 3 plugins | not recorded | 96000 | 256 | H3 shared-process | 1 | 127.8 | 56.7 | 2.30 | 2.28 | 69 |
| chains vs processes, 3 plugins | not recorded | 96000 | 256 | H4 individual | 3 | 345.0 | 88.6 | 2.39 | 2.33 | 387 |
| chains vs processes, 8 plugins | not recorded | 48000 | 256 | H1 shared-process | 1 | 127.3 | 56.4 | 5.21 | 5.07 | 324 |
| chains vs processes, 8 plugins | not recorded | 48000 | 256 | H2 chain | 2 | 129.0 | 57.2 | 5.39 | 5.11 | 1279 |
| chains vs processes, 8 plugins | not recorded | 48000 | 256 | H2 individual | 9 | 890.1 | 117.1 | 6.89 | 5.35 | 687 |
| chains vs processes, 8 plugins | not recorded | 48000 | 256 | H3 shared-process | 1 | 134.7 | 64.8 | 4.86 | 4.79 | 204 |
| chains vs processes, 8 plugins | not recorded | 48000 | 256 | H4 individual | 8 | 917.9 | 146.3 | 5.57 | 5.36 | 1158 |
| chains vs processes, 8 plugins | not recorded | 96000 | 256 | H1 shared-process | 1 | 127.5 | 56.4 | 9.90 | 9.74 | 272 |
| chains vs processes, 8 plugins | not recorded | 96000 | 256 | H2 chain | 2 | 128.2 | 57.1 | 9.99 | 9.73 | 1187 |
| chains vs processes, 8 plugins | not recorded | 96000 | 256 | H2 individual | 9 | 889.0 | 117.1 | 11.84 | 10.29 | 631 |
| chains vs processes, 8 plugins | not recorded | 96000 | 256 | H3 shared-process | 1 | 131.3 | 60.6 | 9.63 | 9.39 | 172 |
| chains vs processes, 8 plugins | not recorded | 96000 | 256 | H4 individual | 8 | 915.8 | 146.2 | 10.34 | 10.44 | 1051 |
| chains vs processes, 16 plugins | not recorded | 48000 | 256 | H1 shared-process | 1 | 137.0 | 65.4 | 9.99 | 9.71 | 559 |
| chains vs processes, 16 plugins | not recorded | 48000 | 256 | H2 chain | 2 | 138.1 | 66.1 | 10.16 | 9.76 | 2507 |
| chains vs processes, 16 plugins | not recorded | 48000 | 256 | H2 individual | 17 | 1782.8 | 155.6 | 14.75 | 10.90 | 1435 |
| chains vs processes, 16 plugins | not recorded | 48000 | 256 | H3 shared-process | 1 | 147.1 | 76.4 | 9.54 | 9.40 | 434 |
| chains vs processes, 16 plugins | not recorded | 48000 | 256 | H4 individual | 16 | 1834.9 | 215.0 | 11.39 | 11.01 | 2417 |
| chains vs processes, 16 plugins | not recorded | 96000 | 256 | H1 shared-process | 1 | 135.9 | 65.4 | 19.44 | 18.83 | 489 |
| chains vs processes, 16 plugins | not recorded | 96000 | 256 | H2 chain | 2 | 136.5 | 66.1 | 19.62 | 18.91 | 2338 |
| chains vs processes, 16 plugins | not recorded | 96000 | 256 | H2 individual | 17 | 1779.1 | 155.5 | 25.17 | 21.78 | 1320 |
| chains vs processes, 16 plugins | not recorded | 96000 | 256 | H3 shared-process | 1 | 138.8 | 67.8 | 18.82 | 18.27 | 362 |
| chains vs processes, 16 plugins | not recorded | 96000 | 256 | H4 individual | 16 | 1835.9 | 215.0 | 21.82 | 20.99 | 2206 |

### Under stress

*grouped against individual processes under stress: not measured yet.*

chains vs processes, 16 plugins at 48000 Hz, 256 frames, stress not recorded: the chain runs in 2 processes against 17, and uses 0.42 times the proportional memory of the individual mode.

chains vs processes, 16 plugins at 96000 Hz, 256 frames, stress not recorded: the chain runs in 2 processes against 17, and uses 0.43 times the proportional memory of the individual mode.

chains vs processes, 3 plugins at 48000 Hz, 256 frames, stress not recorded: the chain runs in 2 processes against 4, and uses 0.62 times the proportional memory of the individual mode.

chains vs processes, 3 plugins at 96000 Hz, 256 frames, stress not recorded: the chain runs in 2 processes against 4, and uses 0.62 times the proportional memory of the individual mode.

chains vs processes, 8 plugins at 48000 Hz, 256 frames, stress not recorded: the chain runs in 2 processes against 9, and uses 0.49 times the proportional memory of the individual mode.

chains vs processes, 8 plugins at 96000 Hz, 256 frames, stress not recorded: the chain runs in 2 processes against 9, and uses 0.49 times the proportional memory of the individual mode.

Device notes, read as written from grouped-vs-processes.md:

> # Grouped (one worker per chain) vs one process per plugin
> 
> Raspberry Pi 5, Zynthian vangelis-2610.1 (Debian 13 arm64, kernel 6.18), governor performance during the run (powersave restored after), 4 cores.
> plugin-hostd 0.12.0 with omx-clap-host 0.22.1 as the worker, `require_pins 1` with the pin file written by plugin-qualify-sync (every plugin used carries verdict=in-process).
> Plugins: N instances in series, cycling omx-chorus, omx-comp, omx-deesser, omx-delay, omx-drive, omx-eq8, omx-flanger, omx-geq (omx-plugins 0.13.0). Sine in, 256 frames, private JACK server (`jackd -n gvp<rate> -d dummy`), the live JACK untouched.
> Window 10 s after a 1 s warm-up. Processes: plugin-hostd plus its workers. RSS and PSS summed over those processes. cpu_pct: utime+stime of those processes over the window, percent of one core. ctx: voluntary plus involuntary context switches of all their threads over the window. DSP: `jack_cpu_load` once a second (avg / max). xruns: JACK xrun callbacks during the window. Stress: 8 busy-loop python processes on the 4 cores.
> Outputs of both modes carry the same signal (peak equal within 1%).
> 
> | rate | N | stress | mode | procs | JACK clients | RSS MB | PSS MB | cpu_pct | ctx | DSP avg/max % | xruns |
> |---|---|---|---|---|---|---|---|---|---|---|---|
> | 48000 | 3 | no | grouped | 2 | 1 | 113.4 | 31.0 | 2.1 | 2795 | 2.1 / 2.27 | 0 |
> | 48000 | 3 | no | individual | 4 | 3 | 331.0 | 59.0 | 2.6 | 7579 | 2.34 / 2.37 | 0 |
> | 48000 | 3 | yes | grouped | 2 | 1 | 113.4 | 30.9 | 2.4 | 2838 | 2.11 / 2.23 | 0 |
> | 48000 | 3 | yes | individual | 4 | 3 | 330.9 | 58.9 | 2.7 | 7616 | 2.4 / 2.45 | 0 |
> | 48000 | 8 | no | grouped | 2 | 1 | 118.1 | 35.6 | 3.9 | 2793 | 3.86 / 3.88 | 0 |
> | 48000 | 8 | no | individual | 9 | 8 | 881.6 | 92.7 | 6.3 | 19612 | 4.86 / 4.9 | 0 |
> | 48000 | 8 | yes | grouped | 2 | 1 | 118.1 | 35.6 | 4.0 | 2809 | 3.89 / 3.99 | 0 |
> | 48000 | 8 | yes | individual | 9 | 8 | 881.7 | 92.6 | 6.49 | 19820 | 4.92 / 5.33 | 0 |
> | 48000 | 16 | no | grouped | 2 | 1 | 125.4 | 42.9 | 7.2 | 2801 | 7.25 / 7.29 | 0 |
> | 48000 | 16 | no | individual | 17 | 16 | 1764.6 | 118.2 | 13.39 | 38985 | 9.83 / 9.98 | 0 |
> | 48000 | 16 | yes | grouped | 2 | 1 | 125.4 | 42.9 | 7.3 | 2795 | 7.24 / 7.31 | 0 |
> | 48000 | 16 | yes | individual | 17 | 16 | 1764.5 | 118.0 | 13.15 | 39219 | 9.94 / 12.49 | 18 |
> | 96000 | 3 | no | grouped | 2 | 1 | 113.4 | 31.0 | 3.8 | 4678 | 4.05 / 4.11 | 0 |
> | 96000 | 3 | no | individual | 4 | 3 | 330.9 | 59.0 | 4.6 | 13233 | 4.52 / 4.57 | 0 |
> | 96000 | 3 | yes | grouped | 2 | 1 | 113.4 | 30.9 | 3.9 | 4749 | 4.16 / 4.26 | 0 |
> | 96000 | 3 | yes | individual | 4 | 3 | 330.9 | 59.0 | 4.8 | 13397 | 4.62 / 4.82 | 0 |
> | 96000 | 8 | no | grouped | 2 | 1 | 118.1 | 35.6 | 7.5 | 4679 | 7.62 / 7.79 | 2 |
> | 96000 | 8 | no | individual | 9 | 8 | 881.5 | 92.7 | 10.69 | 34674 | 9.38 / 9.45 | 0 |
> | 96000 | 8 | yes | grouped | 2 | 1 | 118.1 | 35.6 | 7.4 | 4696 | 7.59 / 7.76 | 3 |
> | 96000 | 8 | yes | individual | 9 | 8 | 881.7 | 92.6 | 11.38 | 34875 | 9.53 / 10.15 | 10 |
> | 96000 | 16 | no | grouped | 2 | 1 | 125.4 | 42.9 | 14.2 | 4700 | 14.41 / 14.79 | 0 |
> | 96000 | 16 | no | individual | 17 | 16 | 1764.5 | 118.2 | 22.68 | 69466 | 19.16 / 22.33 | 13 |
> | 96000 | 16 | yes | grouped | 2 | 1 | 125.4 | 42.9 | 14.2 | 4717 | 14.37 / 14.61 | 5 |
> | 96000 | 16 | yes | individual | 17 | 16 | 1764.4 | 118.0 | 23.33 | 76520 | 19.52 / 19.94 | 0 |
> 
> ## Ratios, individual / grouped (no stress)
> 
> | rate | N | processes | RSS | PSS | cpu_pct | ctx | DSP avg |
> |---|---|---|---|---|---|---|---|
> | 48000 | 3 | 4 vs 2 | 2.92x | 1.90x | 1.24x | 2.71x | 1.11x |
> | 48000 | 8 | 9 vs 2 | 7.46x | 2.60x | 1.62x | 7.02x | 1.26x |
> | 48000 | 16 | 17 vs 2 | 14.07x | 2.76x | 1.86x | 13.92x | 1.36x |
> | 96000 | 3 | 4 vs 2 | 2.92x | 1.90x | 1.21x | 2.83x | 1.12x |
> | 96000 | 8 | 9 vs 2 | 7.46x | 2.60x | 1.43x | 7.41x | 1.23x |
> | 96000 | 16 | 17 vs 2 | 14.07x | 2.76x | 1.60x | 14.78x | 1.33x |
> 
> Xruns summed over the 12 runs of each mode: grouped 10, individual 41.
> The runs are single 10 s windows; xruns are few and unevenly spread (grouped 96 kHz N=8: 2 and 3, N=16 stressed: 5; individual 96 kHz N=16: 13, N=8 stressed: 10, 48 kHz N=16 stressed: 18), so read them as a count, not as a rate. No hardware claim is made from any of it: DSP load and xruns are the JACK dummy driver's.
> 
> Finding: a chain of CLAP members is one JACK client (the head's `effect_<n>` carries the chain's ports); the FreeMixer/zynthian-ui engine still names each processor `effect_<instance>` (open).

### Pianoteq 9 at 48 and 96 kHz

| rate | frames | host | DSP load avg % | max % | samples | source |
|---|---|---|---|---|---|---|
| 48000 | 256 | omx-clap-host alone | 14.4 | 15.7 | 10 | rpi5-20261027-1 |
| 48000 | 256 | plugin-hostd | 14.3 | 14.9 | 10 | rpi5-20261027-1 |
| 48000 | 256 | mod-host | 14.1 | 15.1 | 10 | rpi5-20261027-1 |
| 48000 | 256 | jalv | 14.4 | 15.8 | 10 | rpi5-20261027-1 |
| 96000 | 256 | omx-clap-host alone | 21.6 | 22.5 | 10 | rpi5-20261027-1 |
| 96000 | 256 | plugin-hostd | 21.6 | 22.9 | 10 | rpi5-20261027-1 |
| 96000 | 256 | mod-host | 21.4 | 22.4 | 10 | rpi5-20261027-1 |
| 96000 | 256 | jalv | 20.9 | 22.1 | 10 | rpi5-20261027-1 |

## 4. Qualification coverage

Source: plugin-qualify documents (6304 verdicts). 6304 verdicts in 1823 documents, one per host profile (jalv, mod-host, omx-clap-host, openmixer-console).

| verdict | verdicts | share |
|---|---|---|
| suitable | 4375 | 69.4% |
| unsuitable | 1009 | 16.0% |
| unknown | 920 | 14.6% |

### Refused, with reasons

| deciding reason | verdicts |
|---|---|
| hosting.rt-safety.violations-in-run | 1006 |
| hosting.clap.format-not-hosted | 408 |
| probe.crashed | 328 |
| probe.timeout | 156 |
| hosting.rt-safety.unmeasured | 24 |
| probe.refused-instantiation | 4 |
| mod-host.signal-SIGABRT | 2 |
| mod-host.no-answer | 1 |

### LV2 hosting coverage of the installed set

| host | hosted | of |
|---|---|---|
| jalv | 977 | 979 |
| mod-host | 975 | 979 |
| omx-clap-core | 979 | 979 |

## 5. Risk and how to revert

- sbin/set_modhost_backend.sh jack_load|plugin-hostd switches the mod-host backend and restarts mod-ui (FreeMixer/zynthian-sys#2)
- ZYNTHIAN_PLUGIN_ENGINE=jalv switches the plugin menus back to jalv; the jalv entries stay in the engine list, so a snapshot that holds a JV processor loads as saved (FreeMixer/zynthian-ui#2)
- tools/convert_snapshots_to_ph.py is run once by hand and writes foo.ph.zss beside foo.zss, never overwriting (FreeMixer/zynthian-ui#2)
- Each default step runs once and is recorded in /zynthian/config/openmixer-defaults; the recipe starts and restarts nothing (FreeMixer/zynthian-sys#4)
- MOD-UI chains keep the MD engine and MIDI tools stay with jalv (FreeMixer/zynthian-ui#2)

## 6. How to try it

- curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb, then sudo apt install ./openmixer-release.deb and sudo apt install plugin-hostd omx-clap-host omx-clap-scan omx-panel (FreeMixer/zynthian-ui#1)
- Check out the zynthian-ui branch in /zynthian/zynthian-ui and restart zynthian; enable one LV2 effect in webconf so its (PH) entry shows up (FreeMixer/zynthian-ui#1)
- On an existing Zynthian run scripts/update_zynthian_sys.sh from the zynthian-sys branch and read the 'OpenMixer defaults' report; apply with sbin/set_modhost_backend.sh plugin-hostd or reboot (FreeMixer/zynthian-sys#4)
- For a new image run setup_zynthian.sh, then scripts/omx_prequalify_image.sh natively on arm64 before taking the image; the package's timer runs the qualification sync two minutes after every boot (FreeMixer/zynthian-sys#4)

## 7. The pull requests

| repository | PR | what | state | base |
|---|---|---|---|---|
| FreeMixer/zynthian-sys | #1 | OpenMixer apt repository and install recipe | merged | vangelis |
| FreeMixer/zynthian-sys | #2 | plugin-hostd as the mod-host of MOD-UI, one switch | merged | vangelis |
| FreeMixer/zynthian-sys | #3 | MOD GUIs generated from the plugin descriptions | merged | vangelis |
| FreeMixer/zynthian-sys | #4 | OpenMixer in the default install and the update path | merged | vangelis |
| FreeMixer/zynthian-ui | #1 | PH engine for LV2 and CLAP plugins | merged | vangelis |
| FreeMixer/zynthian-ui | #2 | PH as default engine, snapshot converter, menus from qualification | merged | feat/engine-plugin-hostd |

States as fetched at 2026-10-28T22:00:19Z.
