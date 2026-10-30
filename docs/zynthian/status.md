Where this stands
=================

This page says what is proven on the Zynthian Pi 5, what is released but not proven on the device yet, and what is
still open, why, and what closes it. The pages it links are the detail.

On the Pi now
-------------

The Pi 5 runs plugin-hostd 0.15.0, plugin-qualify 0.17.3, omx-clap-host 0.24.2, omx-panel 0.7.1, omx-plugins 0.16.0
and the zynthian-ui fork at
[a136591b](https://github.com/FreeMixer/zynthian-ui/commit/a136591bdfacf804f3936fa7155488668fc03711). The LV2 part of
the re-qualification is running on that set; the CLAP part is done.

Proven on the device
--------------------

- **The plugin-hostd engine runs Zynthian chains**, LV2 and CLAP side by side, with the plugin menus built from the
  qualification records ([captures](captures.md)).
- **Controller pages follow the plugin's own sections** and are named by what they hold: every page of omx eq8,
  retaken on omx-plugins 0.16.0 ([captures, omx-eq8](captures.md#omx-eq8-retaken-on-omx-plugins-0-16-0)).
- **One panel for both surfaces**: the engine's controller pages and the MOD GUIs are drawn from the same layout
  ([the pipeline page](../from-file-to-page.md)).

Released, not proven on the device yet
--------------------------------------

- **plugin-hostd 0.15.1** ([release](https://github.com/FreeMixer/plugin-hostd/releases/tag/v0.15.1)): a plugin whose
  pin asks for the thread pool gets a worker started with it; the pins are read again while the daemon runs, so a
  plugin upgrade needs no restart (proven in CI); the plugin search paths are complete for a Zynthian Pi; an LV2
  plugin's remote pages and `param_info` come from its bundle's ports; an LV2 IRI with percent-encoding finds its
  qualification record; an LV2 toggle stays a toggle.
- **plugin-qualify 0.17.5** ([release](https://github.com/FreeMixer/plugin-qualify/releases/tag/v0.17.5)): a pin
  holds every file plugin-hostd collects for the plugin, preset files included, so an LV2 plugin that ships presets
  is no longer refused with -509 ([plugin-qualify#228](https://github.com/FreeMixer/plugin-qualify/issues/228)); the
  pins on disk are refreshed from plugin-hostd on its upgrade and at every sync start, measuring nothing.
- **omx-clap-core 0.24.3** ([release](https://github.com/FreeMixer/omx-clap-core/releases/tag/v0.24.3)): the CLAP host
  lists, loads and saves presets, answers `pin_layout`, and runs a plugin's helper threads on a pool of real-time threads when its pin asks
  for it ([instruments](instruments.md)).
- **omx-panel 0.7.2** ([release](https://github.com/FreeMixer/omx-panel/releases/tag/v0.7.2)): the MOD GUI screenshots
  carry the control names, and `--per-page 4` gives pages of four controls, one per encoder.
- **The zynthian-ui fork on `vangelis`**, ahead of the Pi: a Factory and a User preset bank for every plugin, CLAP or
  LV2; controller pages that start with the plugin's own remote pages; pages of four when omx-panel offers them;
  the format named in the menu titles, each CLAP plugin listed once; Show and Hide plugin window in the processor
  options. Its tests run in CI on every change.

Still open
----------

- **The LV2 records are not redone yet.** What closes it: the LV2 re-qualification running on the Pi.
- **Presets on the device: the Factory and User banks.** Not proven on the current set. What closes it: captures on
  mda Piano, Odin 2 and omx eq8 after the re-qualification
  ([plugin-hostd#269](https://github.com/FreeMixer/plugin-hostd/issues/269)).
- **The snapshot round trip.** A snapshot holding an mda Piano chain did not load on the earlier pins (-509, the pin
  without the preset files). What closes it: plugin-qualify 0.17.5 on the Pi refreshes the pins, then a snapshot of
  plugin-hostd chains is saved and loaded back on the Pi with its plugins and settings as they were.
- **Surge XT in both formats.** Surge XT ships its CLAP as `Surge XT.clap`, a name with a space the daemon cannot add
  yet ([plugin-hostd#240](https://github.com/FreeMixer/plugin-hostd/issues/240),
  [#276](https://github.com/FreeMixer/plugin-hostd/pull/276)). What closes it: #276 released and on the Pi, then
  Surge XT played as CLAP and as LV2, with its voices across the cores ([instruments](instruments.md)).
- **Pin refresh on a plugin upgrade, on the device.** Proven in CI; what closes it: a plugin upgraded on the Pi and
  added again without restarting the daemon.
- **The captures are from before the new set.** What closes it: every capture retaken after the re-qualification
  ([captures](captures.md)).
- **The MOD GUIs on the device show no text.** The Pi runs omx-plugins 0.16.0, whose screenshots predate omx-panel
  0.7.1. What closes it: omx-plugins 0.17.0, regenerated against omx-panel 0.7.2, after its Debian build is fixed
  ([omx-plugins#276](https://github.com/FreeMixer/omx-plugins/issues/276)).
- **openmixer does not build against plugin-hostd 0.14.0 or later.** Two reply codes it reads moved into the
  contract's generated list. What closes it: the fix in openmixer, proven against plugin-hostd 0.15.1, landing.
- **The benchmark matrix is partial: 287 cells so far** (682 rows, 639 ok and 43 failed). What closes it: the matrix
  fills the rest ([benchmarks, the matrix](benchmarks.md#the-matrix-every-rate-and-quantum-single-and-grouped)).
- **The upstream patch series is at step 1.** Step 1 is open upstream
  ([zynthian/zynthian-sys#228](https://github.com/zynthian/zynthian-sys/pull/228)); steps 2 to 7 are cut on the forks
  but not offered yet, several with a check on the device still owed
  ([the upstream patch series](upstream-series.md)).
