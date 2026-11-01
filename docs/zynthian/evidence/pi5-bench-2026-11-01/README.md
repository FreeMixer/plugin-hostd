Pi 5 rows on omx-clap-core 0.26.1, 2026-11-01
=============================================

A Raspberry Pi 5 running Zynthian, 48000 Hz, 256 frames. Measurement builds: omx-clap-core 0.26.1 (omx-clap-host) and
plugin-hostd 0.15.8~meas, against Zynthian's own mod-host (September 2024 build). Read digitally at JACK ports. 0 xruns
in every row.

The run's own files are here: [rpi5-20261101-1.json](rpi5-20261101-1.json) (every row), [run.log](run.log) (the
summary lines) and [versions.txt](versions.txt) (what was installed). The earlier rows are in
[../../benchmarks.md](../../benchmarks.md).

cvp24: 24 plugins, CLAP builds
------------------------------

| host | DSP % | RSS MB | add ms |
|---|---|---|---|
| mod-host | 14.47 | 192 | 717 |
| omx-clap-host, shared process | 15.12 | 145 | 886 |
| plugin-hostd, added into a chain | 12.37 | 147 | 422 |
| plugin-hostd, individual workers | 17.34 | 2684 | 1933 |
| plugin-hostd, chain (added, then moved) | 12.32 | | 4586 |

tp10: ten third-party LV2 plugins
---------------------------------

| host | DSP % | RSS MB | add ms |
|---|---|---|---|
| mod-host | 6.34 | 174 | 317 |
| omx-clap-host, shared process | 6.67 | 125 | 437 |
| plugin-hostd, added into a chain | 5.57 | 128 | 256 |

cvp24-lv2: 24 plugins, LV2 builds (to be measured again)
--------------------------------------------------------

This scenario may have overlapped a build on the Pi. Read the rows as provisional and draw nothing from them.

| host | DSP % | RSS MB | add ms |
|---|---|---|---|
| mod-host | 15.74 | 193 | 754 |
| omx-clap-host, shared process | 16.87 | 144 | 1132 |
| plugin-hostd, added into a chain | 14.13 | 145 | 555 |

Qualification on the Pi
-----------------------

1403 plugins qualified, 93 crashed, 45 hung, 28 unmeasured. 59 of the crashes are LSP plugins (55 CLAP, 4 LV2); they are
being qualified again under the register guard (omx-clap-core 0.26.2, plugin-hostd 0.15.9). calf Wavetable and dexed
crash for a reason that is not the register guard; it is still being looked into.
