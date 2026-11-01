Add time on the Pi, 2026-11-01
==============================

A Raspberry Pi 5 running Zynthian (Debian 13 arm64, 1336 LV2 plugins on its search path), a private JACK server on the
dummy driver at 48000 Hz and 256 frames, three repeats, medians with the lowest and highest in brackets. The builds of
every host are in `versions.txt`; plugin-hostd is main with #358 and #359, which 0.15.8 carries.

Each row says which builds of the plugins its host ran. The 24 plugins are omx comp, delay and drive in turn, and Calf
Compressor, which has no CLAP build: an "LV2" row runs every plugin's LV2 build on every host (plugin-hostd and
omx-clap-host through the LV2 adapter), a "CLAP" row runs the omx plugins' CLAP builds and Calf's LV2 build, which only
plugin-hostd and omx-clap-host can.

Warm adds
---------

`bench/run.sh --class rpi5 --scenarios cvp24,cvp24-lv2 --hosts H1,H2,H3,H4 --stress none --rates 48000 --frames 256
--repeats 3` (`rpi5-20261101-2-like-for-like.json`), and the ten third-party set, all LV2, from the first run
(`rpi5-20261101-1.json`, scenario tp10). `add_ms` runs from the first add to the last reply, the host already running.

| plugins | builds | host | add ms | JACK clients | PSS MB |
|---------|--------|------|--------|--------------|--------|
| 24 | LV2 | plugin-hostd, added into a chain | 530 [523, 530] | 1 | 63 |
| | LV2 | mod-host | 733 [732, 749] | 26 | 112 |
| | LV2 | omx-clap-host, one process | 944 [944, 949] | 24 | 64 |
| | LV2 | plugin-hostd, a worker each | 2460 [2428, 2471] | 24 | 190 |
| | LV2 | jalv, a process each | 26689 [25756, 27402] | 24 | 1091 |
| 24 | CLAP | plugin-hostd, added into a chain | 428 [425, 434] | 1 | 64 |
| | CLAP | omx-clap-host, one process | 849 [849, 870] | 24 | 64 |
| | CLAP | plugin-hostd, a worker each | 2408 [2375, 2445] | 24 | 183 |
| 10 third-party | LV2 | mod-host | 306 [306, 328] | 12 | 93 |
| | LV2 | omx-clap-host, one process | 441 [436, 442] | 10 | 44 |
| | LV2 | plugin-hostd, added into a chain | 501 [496, 501] | 5 | 90 |
| | LV2 | plugin-hostd, a worker each | 683 [678, 785] | 10 | 111 |
| | LV2 | jalv, a process each | 10454 [10418, 10518] | 10 | 505 |

In the third-party chain four members are mono (gx_flanger, ZamComp, ZamEQ2, ZamDelay) behind a stereo head: the chain
refuses them and they are added in a worker each, as Zynthian adds them. That is the gap to mod-host on this set.

The bench's mode that adds every plugin in a worker of its own and then declares the chain (added, then moved) took 4602
ms on the CLAP row; on the LV2 row its chain did not form within 20 s, a fault of that path that the add into a chain
does not take.

From a cold start to a loaded snapshot
--------------------------------------

`cold-to-snapshot.py` (`cold-to-snapshot.json`): the host started fresh and every plugin of the set added, the time from
the start to the last reply. mod-host reads the whole LV2 world when it starts.

| plugins | builds | host | start to answering ms | cold to loaded ms |
|---------|--------|------|-----------------------|-------------------|
| 24 | LV2 | plugin-hostd, added into a chain | 3 | 541 [538, 546] |
| | LV2 | omx-clap-host | 27 | 975 [955, 979] |
| | LV2 | mod-host | 970 | 1683 [1600, 1701] |
| | LV2 | plugin-hostd, a worker each | 3 | 2522 [2459, 2639] |
| 24 | CLAP | plugin-hostd, added into a chain | 3 | 441 [440, 446] |
| | CLAP | omx-clap-host | 28 | 873 [836, 877] |
| 10 third-party | LV2 | plugin-hostd, added into a chain | 3 | 532 [523, 543] |
| | LV2 | omx-clap-host | 24 | 473 [469, 478] |
| | LV2 | mod-host | 870 | 1204 [1180, 1218] |
| | LV2 | plugin-hostd, a worker each | 3 | 689 [688, 702] |

Measured digitally at JACK ports on the dummy driver; nothing here is a claim about analog audio.
