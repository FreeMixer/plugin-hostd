The three hosts on the Pi 5, 48000 Hz, 256 frames
=================================================

`bench/run.sh --class rpi5 --rates 48000 --frames 256 --scenarios cvp24,cvp24-lv2,tp10 --stress none --repeats 3`, a private
JACK server on the dummy driver, the CPU governor at performance. Every figure is the median of three repeats.

- `rpi5-20261102-1.json`, `run.log`: every host, omx-clap-core 0.26.3. H1 is omx-clap-host, one process; H3 is the stock
  mod-host (`/usr/local/bin/mod-host`, v0.10.6-595-g6c1cdd8); H2 is plugin-hostd 0.15.9. Its chain rows did not form: see
  below.
- `h2-occ-0.26.4/`: the plugin-hostd rows again on omx-clap-core 0.26.4 (`s6.sh`, `s6.log`), and the check made before
  them (`calf-chain.py`, `guard.log`): 24 Calf Compressors added into one chain form it, 24 of 24, on one worker, and no
  plugin says `abi_clobber`.

Why the chain rows failed on 0.26.3
-----------------------------------

Calf Compressor and the DPF plugins (3BandEQ, MVerb, ZamComp, ZamEQ2, ZamDelay) set FPCR's flush-to-zero bit when their
library is opened: they are built with `-ffast-math`, and its start-up code (`crtfastmath`) writes FPCR. omx-clap-core
0.26.3's register guard read the change as the plugin's, said `abi_clobber 1 0x40000`, and plugin-hostd moved each such
plugin to a worker of its own, so no chain holding one formed. `fpcr-init.c` shows FPCR before and after opening the
library; `calf-clobber.py` loads one plugin and prints what the guard says. An x86-64 desk does not show it. omx-clap-core
0.26.4 logs a change of FPCR or MXCSR alone and does not isolate the plugin for it.

xruns
-----

0 in every row except plugin-hostd with one worker per plugin on 0.26.3: cvp24 had 0, 6 and 59 xruns over its three
repeats, cvp24-lv2 0, 0 and 117. That is the cost of 24 workers and 24 JACK clients on four cores. On 0.26.4 the same rows
had a median of 0, with cvp24 reaching 21 in one repeat; every chain row had 0.
