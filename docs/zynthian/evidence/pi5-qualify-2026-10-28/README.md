Pi 5 deep qualification, 2026-10-28
===================================

What ran: `plugin-qualify --all --isolate` over every LV2 and CLAP plugin on a Raspberry Pi 5 (4 cores, 4 GB) running
ZynthianOS vangelis, kernel 6.18.50+rpt-rpi-2712 (not PREEMPT_RT), from 2026-10-28T14:51:58Z to 20:51:49Z, then
`plugin-qualify-sync --system --force`. Packages: plugin-qualify 0.16.1, plugin-hostd 0.13.1 (its probe ran every
measurement: `plugin-hostd-probe 0.13.1`), omx-clap-host 0.23.2, omx-plugins 0.15.1; mod-host v0.10.6-595-g6c1cdd8 and
jalv from `/usr/local/bin` as the image ships them. The script is [run.sh](run.sh); `bin-jalv` is the jalv wrapper
it put first on `PATH` (plugin-qualify#187). The CPU governor was `powersave` and the probes were not pinned to a core
(every probe document records `probe.profile.governor` and `probe.profile.not-pinned` as unmet). The device has no sound
card: nothing here is a statement about audio heard.

The full outputs stay on the device; this directory holds the summary and the logs. On the Pi:

| file | bytes | sha256 |
|---|---|---|
| `/root/omx-deep-20261028/qualify.json` (1823 qualification records) | 11824126 | `b9c335c4dc0d8c41ec044da5eada619845aed86441610c6fbcf9b49c8347caf3` |
| `/root/omx-deep-20261028/qualify.err` | 432654 | `7d1ee83e185783b73b56e129abe9ab6afabc2b810d708a388b62c9cb9c94b028` |
| `/root/omx-deep-20261028/qualified.pins` (the run's pins) | 49264 | `dd7c0548c8efec4a079b94386712903c3b1bc8a81912cd03470f63e5bc897513` |
| `/root/omx-deep-20261028/records/` (1823 probe and 1823 qualification documents; sha256 of the files concatenated in name order) | | `7bbfca1313b8875bc6b59f68412fd8483cc612d538032832b5a063848b22e126` |
| `/var/lib/omx/qualified.pins` (the system pins after the sync, 22:08Z) | 593197 | `3bb157e247b15774a4fc1bc648db73d1683a689c2346c90a70f1c5a895aa11f1` |
| `/var/lib/omx/qualification/` (3774 files) | | |
| [run.log](run.log) | 248 | `e50837d0a789d7d832ba79b226ee45e54d25d357521ba2e902b32649efed63e7` |
| [sync.log](sync.log) | 42461 | `adaf85e8f40689199609433265c3f08ef50d5c2bf1bdfea70d698f5c8aa58e1f` |

[summary.json](summary.json) and [tables.md](tables.md) are written from those files by:

    rsync -a root@zynthian.local:/root/omx-deep-20261028/ deep/
    scp root@zynthian.local:/var/lib/omx/qualified.pins system-qualified.pins
    tools/zynthian/qualify-summary.py --qualify deep/qualify.json --records deep/records \
        --pins deep/qualified.pins --system-pins system-qualified.pins --sync-log deep/sync.log --run-log deep/run.log \
        --requested-rates 44100,48000,96000,192000 --requested-quanta 128,256,512,1024 \
        --out summary.json --markdown tables.md

and the figures under [../figures/](../figures/) from the summary by `tools/zynthian/figures.py` (the command is in
[../../benchmarks.md](../../benchmarks.md)).

`run.log` holds `dpkg-query: no packages found matching ${Version}"`: a quoting slip in run.sh's version line, so the
log does not name plugin-qualify's version; it is taken from `dpkg -l` on the device (0.16.1). plugin-qualify exited
with status 2 (run.log).
