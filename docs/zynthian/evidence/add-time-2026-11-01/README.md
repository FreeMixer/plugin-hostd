Add time on the Pi, 2026-11-01
==============================

A Raspberry Pi 5 running Zynthian (Debian 13 arm64, 1336 LV2 plugins on its search path), a private JACK server on the
dummy driver at 48000 Hz and 256 frames, three repeats, medians with the lowest and highest in brackets. plugin-hostd is a
build of main with #358 and #359 (0.15.8 carries the same code), omx-clap-host 0.26.0 (`versions.txt`).

Warm adds: `bench/run.sh --class rpi5 --scenarios cvp24,tp10 --hosts H1,H2,H3,H4 --stress none --rates 48000 --frames 256
--repeats 3` (`rpi5-20261101-1.json`). `add_ms` runs from the first add to the last reply, the host already running.

| plugins | host | add ms | JACK clients | PSS MB |
|---------|------|--------|--------------|--------|
| 24 (omx comp, delay, drive, Calf Compressor) | plugin-hostd, added into a chain | 435 [433, 436] | 1 | 64 |
| | mod-host | 749 [701, 776] | 26 | 112 |
| | omx-clap-host, one process | 865 [854, 875] | 24 | 64 |
| | plugin-hostd, a worker each | 2466 [2423, 2514] | 24 | 184 |
| | plugin-hostd, added then moved into a chain | 4586 [4538, 4746] | 1 | 65 |
| | jalv, a process each | 26039 [25939, 26615] | 24 | 1092 |
| 10 third-party LV2 | mod-host | 306 [306, 328] | 12 | 93 |
| | omx-clap-host, one process | 441 [436, 442] | 10 | 44 |
| | plugin-hostd, added into a chain | 501 [496, 501] | 5 | 90 |
| | plugin-hostd, a worker each | 683 [678, 785] | 10 | 111 |
| | plugin-hostd, added then moved into a chain | refused: the members are not all one width | | |
| | jalv, a process each | 10454 [10418, 10518] | 10 | 505 |

In the third-party chain four members are mono (gx_flanger, ZamComp, ZamEQ2, ZamDelay) and the head is stereo: the chain
refuses them, and they are added in a worker each, as Zynthian adds them. That is the gap to mod-host on this set.

From a cold start to a loaded snapshot: `cold-to-snapshot.py`, the host started fresh and every plugin of the set added,
the time from the start to the last reply. mod-host reads the whole LV2 world when it starts.

| plugins | host | start to answering ms | cold to loaded ms |
|---------|------|-----------------------|-------------------|
| 24 | plugin-hostd | 3 | 440 [439, 475] |
| | omx-clap-host | 23 | 889 [869, 895] |
| | mod-host | 863 | 1566 [1563, 1599] |
| 10 third-party | plugin-hostd | 3 | 531 [520, 583] |
| | omx-clap-host | 25 | 464 [463, 470] |
| | mod-host | 868 | 1209 [1172, 1251] |

Measured digitally at JACK ports on the dummy driver; nothing here is a claim about analog audio.
