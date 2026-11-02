Qualification on the Pi 5, 2026-11-02
=====================================

A Raspberry Pi 5 running Zynthian (zynthian-ui 369f4fc4), plugin-qualify 0.18.5, omx-clap-host 0.26.3, the records
package omx-qualification-rpi5-zynthian-vangelis 2026110101. Read from the device's own state; nothing was measured
for this page.

- `qualify-sync.json`: the sync's state as the device holds it (`/var/lib/omx/qualify-sync.json`): every plugin, its
  outcome, its record and its pin.
- `qualification-2026-11-02.json`: one row per plugin, with its class, and the totals: 1602 plugins (1341 LV2, 261
  CLAP); 1079 qualified in-process, 306 qualified isolated; 93 crashed, 46 hung, 13 refused; 27 unmeasured; 38 rated
  suitable with no pin.
- `records/`: the qualification records of the plugins that are neither qualified with a pin nor unsuitable, by group,
  and `records/index.json`, which names each one's URI, outcome, code and record file:

| group | plugins | code |
|---|---|---|
| `silent-under-note` | 11 | `omx-clap-host.silent-under-note`: an instrument that makes no sound under a note until it is given content (a soundfont, a kit, samples, a ROM) |
| `probe-oom` | 9 | `probe.oom`: a cell went past the probe's memory bound, half of the RAM |
| `rt-safety-unmeasured` | 6 | `hosting.rt-safety.unmeasured` |
| `refused-instantiation` | 1 | `probe.refused-instantiation` |
| `memory-unmeasured` | 38 | rated suitable for omx-clap-host, with no pin: the console's verdict reads `hosting.memory.unmeasured` |
