Where this stands
=================

2026-10-29. This page says what is in place for Zynthian today and what is still incomplete, why, and what closes it.
The pages it links are the detail.

In place
--------

- **plugin-hostd 0.14.0** ([release](https://github.com/FreeMixer/plugin-hostd/releases/tag/v0.14.0)): the daemon
  that hosts LV2 and CLAP plugins behind mod-host's protocol.
- **omx-clap-core 0.24.0** ([release](https://github.com/FreeMixer/omx-clap-core/releases/tag/v0.24.0)), with the
  CLAP thread pool, so a plugin that asks for helper threads gets them ([instruments](instruments.md)).
- **plugin-qualify 0.17.2** ([release](https://github.com/FreeMixer/plugin-qualify/releases/tag/v0.17.2)): the records
  of latency, real-time safety and cost that the menus read.
- **omx-plugins 0.16.0** ([release](https://github.com/FreeMixer/omx-plugins/releases/tag/v0.16.0)) and **omx-panel
  0.6.0** ([release](https://github.com/FreeMixer/omx-panel/releases/tag/v0.6.0)): our plugins, their panels and their
  MOD GUIs.
- **The zynthian-ui fork at
  [745f100e](https://github.com/FreeMixer/zynthian-ui/commit/745f100ecc71f736f28e0baef5b1771fbf13150b)**: the
  plugin-hostd engine, plugin menus built from the records, the chain estimate footer, the X-Touch Plugin mode, and
  controller screens named by their content.
- **The pipeline page**: [from a plugin file to a page on the screen](../from-file-to-page.md), the five stages.
- **The captures** of the menus, the controller pages and the MOD GUIs on the Pi 5 ([captures](captures.md)).
- **The omx-eq8 pages**: every controller page of omx eq8, retaken on omx-plugins 0.16.0
  ([captures, omx-eq8](captures.md#omx-eq8-retaken-on-omx-plugins-0-16-0)).

Still incomplete
----------------

- **Menu rows read "latency unknown", "not qualified" or "refused".** Cause: the records on the Pi predate the full
  grid of rates and quantums. What closes it: the full re-qualification, running on the Pi since 12:05 CET today;
  every capture is retaken when it ends ([captures](captures.md)).
- **The shipped MOD GUI screenshots carry no text.** Cause: the generator drew shapes only. What closes it: omx-panel
  [#81](https://github.com/FreeMixer/omx-panel/pull/81) (landed) and its release 0.7.0
  ([#82](https://github.com/FreeMixer/omx-panel/pull/82)), then omx-plugins regenerated against it
  ([captures](captures.md)).
- **Instruments with their voices across the cores are not measured yet.** Cause: the worker does not yet receive the
  pin's thread-pool verdict. What closes it: plugin-hostd
  [#236](https://github.com/FreeMixer/plugin-hostd/issues/236), then Surge XT on the Pi after the re-qualification
  ([instruments](instruments.md)).
- **The benchmark matrix is partial: 21 cells.** Cause: it pauses while the re-qualification holds the Pi. What
  closes it: the matrix resumes when the re-qualification ends
  ([benchmarks, the matrix](benchmarks.md#the-matrix-every-rate-and-quantum-single-and-grouped)).
- **Presets cannot be browsed yet.** Cause: omx-clap-host does not answer `preset_list` and `preset_get`
  ([omx-clap-core#383](https://github.com/FreeMixer/omx-clap-core/issues/383)), so the menu of a plugin-hostd chain
  shows no presets, and an LV2 plugin on mod-host gets no list either. What closes it:
  [plugin-hostd#269](https://github.com/FreeMixer/plugin-hostd/issues/269), factory and user presets listed, loaded and
  saved on the Pi ([captures](captures.md)).
- **The upstream patch series is at step 1.** Cause: step 1 is open upstream
  ([zynthian/zynthian-sys#228](https://github.com/zynthian/zynthian-sys/pull/228)); steps 2 to 7 are cut on the forks
  but not offered yet, several with a check on the device still owed. What closes it: those device checks, then each
  step offered in order ([the upstream patch series](upstream-series.md)).
