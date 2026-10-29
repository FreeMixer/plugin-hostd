Where this stands
=================

2026-10-29, evening. This page says what is in place for Zynthian today and what is still incomplete, why, and what
closes it. The pages it links are the detail.

In place
--------

- **omx-clap-core 0.24.2** ([release](https://github.com/FreeMixer/omx-clap-core/releases/tag/v0.24.2)): the CLAP
  host lists, loads and saves presets, and keeps the CLAP thread pool, so a plugin that asks for helper threads gets
  them ([instruments](instruments.md)).
- **omx-panel 0.7.1** ([release](https://github.com/FreeMixer/omx-panel/releases/tag/v0.7.1)): the MOD GUI
  screenshots carry the control names, set in Inter.
- **plugin-qualify 0.17.2** ([release](https://github.com/FreeMixer/plugin-qualify/releases/tag/v0.17.2)): the records
  of latency, real-time safety and cost that the menus read. 0.17.3 follows.
- **plugin-hostd 0.14.0** ([release](https://github.com/FreeMixer/plugin-hostd/releases/tag/v0.14.0)): the daemon
  that hosts LV2 and CLAP plugins behind mod-host's protocol. 0.15.0 follows
  ([release PR #282](https://github.com/FreeMixer/plugin-hostd/pull/282)): the thread pool started from the pins, the
  pins reloaded while the daemon runs, and complete plugin search paths.
- **The zynthian-ui fork at
  [a136591b](https://github.com/FreeMixer/zynthian-ui/commit/a136591bdfacf804f3936fa7155488668fc03711)**, the tip the
  Pi runs: the plugin-hostd engine, plugin menus built from the records, the chain estimate footer, the X-Touch Plugin
  mode, controller screens named by their content, and a Factory and a User preset bank for every plugin, CLAP or LV2.
- **The pipeline page**: [from a plugin file to a page on the screen](../from-file-to-page.md), the five stages.
- **The captures** of the menus, the controller pages and the MOD GUIs on the Pi 5 ([captures](captures.md)).
- **The omx-eq8 pages**: every controller page of omx eq8, retaken on omx-plugins 0.16.0
  ([captures, omx-eq8](captures.md#omx-eq8-retaken-on-omx-plugins-0-16-0)).

Still incomplete
----------------

- **The LV2 records are not redone yet.** The CLAP part of the re-qualification finished today. Cause: the LV2 part
  was stopped at 13:20, because the mod-host probe could not see the plugin folders of the device and refused plugins
  Zynthian runs every day ([plugin-qualify#224](https://github.com/FreeMixer/plugin-qualify/issues/224), fixed in
  plugin-qualify). What closes it: the LV2 part restarts on plugin-qualify 0.17.3, then every capture is retaken
  ([captures](captures.md)).
- **LV2 plugins that ship presets are refused with -509.** Cause: the pin plugin-qualify writes holds the plugin's
  files but not the preset files its manifest names, and the daemon checks those too. What closes it:
  [plugin-qualify#228](https://github.com/FreeMixer/plugin-qualify/issues/228), the pin takes its file list from
  plugin-hostd ([#231](https://github.com/FreeMixer/plugin-qualify/pull/231)), after plugin-hostd 0.15.0.
- **The MOD GUIs on the device still show no text.** Cause: the Pi runs omx-plugins 0.16.0, whose screenshots were
  made before omx-panel 0.7.1. What closes it: omx-plugins 0.17.0, regenerated against omx-panel 0.7.1, after its
  Debian build is fixed ([omx-plugins#276](https://github.com/FreeMixer/omx-plugins/issues/276)).
- **Instruments with their voices across the cores are not measured yet.** Cause: the switch that starts a worker
  with the thread pool is in plugin-hostd 0.15.0, not yet on the Pi, and Surge XT ships its CLAP as
  `Surge XT.clap`, a name with a space the daemon cannot add yet
  ([plugin-hostd#240](https://github.com/FreeMixer/plugin-hostd/issues/240),
  [#276](https://github.com/FreeMixer/plugin-hostd/pull/276)). What closes it: both on the Pi, then Surge XT measured
  ([instruments](instruments.md)).
- **The benchmark matrix is partial: 287 cells so far** (682 rows, 639 ok and 43 failed). Cause: it paused while the
  re-qualification held the Pi. What closes it: it is running again and fills the rest
  ([benchmarks, the matrix](benchmarks.md#the-matrix-every-rate-and-quantum-single-and-grouped)).
- **The upstream patch series is at step 1.** Cause: step 1 is open upstream
  ([zynthian/zynthian-sys#228](https://github.com/zynthian/zynthian-sys/pull/228)); steps 2 to 7 are cut on the forks
  but not offered yet, several with a check on the device still owed. What closes it: those device checks, then each
  step offered in order ([the upstream patch series](upstream-series.md)).
