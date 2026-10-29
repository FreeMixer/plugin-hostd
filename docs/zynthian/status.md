Where this stands
=================

2026-10-29, night. This page says what is in place for Zynthian today and what is still incomplete, why, and what
closes it. The pages it links are the detail.

In place
--------

- **plugin-hostd 0.15.0** ([release](https://github.com/FreeMixer/plugin-hostd/releases/tag/v0.15.0)): the daemon
  that hosts LV2 and CLAP plugins behind mod-host's protocol. New in this release: a plugin whose pin asks for the
  thread pool gets a worker started with it, the pins are read again while the daemon runs, and the plugin search
  paths are complete for a Zynthian Pi.
- **plugin-qualify 0.17.3** ([release](https://github.com/FreeMixer/plugin-qualify/releases/tag/v0.17.3)): the records
  of latency, real-time safety and cost that the menus read. A pin now holds every file plugin-hostd collects for the
  plugin, preset files included, so LV2 plugins that ship presets are no longer refused with -509
  ([plugin-qualify#228](https://github.com/FreeMixer/plugin-qualify/issues/228)). The mod-host probe looks in the
  device's LV2 folders ([plugin-qualify#224](https://github.com/FreeMixer/plugin-qualify/issues/224)).
- **omx-clap-core 0.24.2** ([release](https://github.com/FreeMixer/omx-clap-core/releases/tag/v0.24.2)): the CLAP
  host lists, loads and saves presets, and keeps the CLAP thread pool, so a plugin that asks for helper threads gets
  them ([instruments](instruments.md)).
- **omx-panel 0.7.1** ([release](https://github.com/FreeMixer/omx-panel/releases/tag/v0.7.1)): the MOD GUI
  screenshots carry the control names, set in Inter.
- **The zynthian-ui fork at
  [a136591b](https://github.com/FreeMixer/zynthian-ui/commit/a136591bdfacf804f3936fa7155488668fc03711)**, the tip the
  Pi runs: the plugin-hostd engine, plugin menus built from the records, the chain estimate footer, the X-Touch Plugin
  mode, controller screens named by their content, and a Factory and a User preset bank for every plugin, CLAP or LV2.
- **A release gate**: a library's release is tested in the projects that use it, from its own packages, before it is
  tagged.
- **The pipeline page**: [from a plugin file to a page on the screen](../from-file-to-page.md), the five stages.
- **The captures** of the menus, the controller pages and the MOD GUIs on the Pi 5 ([captures](captures.md)).
- **The omx-eq8 pages**: every controller page of omx eq8, retaken on omx-plugins 0.16.0
  ([captures, omx-eq8](captures.md#omx-eq8-retaken-on-omx-plugins-0-16-0)).

Still incomplete
----------------

- **The LV2 records are not redone yet.** The CLAP part of the re-qualification finished today. Cause: the LV2 part
  was stopped at 13:20, because the mod-host probe could not see the device's plugin folders. What closes it: the LV2
  re-qualification, running since 23:57 CET on the new set, which the Pi now runs: plugin-hostd 0.15.0,
  plugin-qualify 0.17.3, omx-clap-host 0.24.2 and omx-panel 0.7.1.
- **The captures are from before the new set.** What closes it: every capture retaken when the LV2 re-qualification
  ends, presets and the Factory and User banks included ([captures](captures.md)).
- **Instruments with their voices across the cores are not measured yet.** Cause: the thread pool switch is on
  the Pi with plugin-hostd 0.15.0, but Surge XT ships its CLAP as `Surge XT.clap`, a name with a space the daemon
  cannot add yet ([plugin-hostd#240](https://github.com/FreeMixer/plugin-hostd/issues/240),
  [#276](https://github.com/FreeMixer/plugin-hostd/pull/276)). What closes it: #276 on the Pi, then Surge XT measured
  after the re-qualification ([instruments](instruments.md)).
- **The snapshot round trip is not proven on the device.** What closes it: a Zynthian snapshot holding plugin-hostd
  chains saved and loaded back on the Pi, the plugins and their settings as they were.
- **The MOD GUIs on the device still show no text.** Cause: the Pi runs omx-plugins 0.16.0, whose screenshots were
  made before omx-panel 0.7.1. What closes it: omx-plugins 0.17.0, regenerated against omx-panel 0.7.1, after its
  Debian build is fixed ([omx-plugins#276](https://github.com/FreeMixer/omx-plugins/issues/276)).
- **openmixer does not build against plugin-hostd 0.14.0 or later.** Cause: two reply codes it reads moved into the
  contract's generated list. What closes it: the fix in openmixer, being landed at the desk.
- **The benchmark matrix is partial: 287 cells so far** (682 rows, 639 ok and 43 failed). What closes it: it is
  running again and fills the rest
  ([benchmarks, the matrix](benchmarks.md#the-matrix-every-rate-and-quantum-single-and-grouped)).
- **The upstream patch series is at step 1.** Cause: step 1 is open upstream
  ([zynthian/zynthian-sys#228](https://github.com/zynthian/zynthian-sys/pull/228)); steps 2 to 7 are cut on the forks
  but not offered yet, several with a check on the device still owed. What closes it: those device checks, then each
  step offered in order ([the upstream patch series](upstream-series.md)).
