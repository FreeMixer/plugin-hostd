Where this stands
=================

This page says what is proven on the Zynthian Pi 5, what is released but not proven on the device yet, and what is
still open, why, and what closes it. The pages it links are the detail. What the work is and how little it changes in
Zynthian: [the Zynthian page](README.md).

On the Pi now
-------------

The Pi 5 runs plugin-hostd 0.15.4, plugin-qualify 0.18.2, omx-clap-host 0.25.2, omx-panel 0.7.2, omx-plugins 0.16.0
and the zynthian-ui fork at
[f864d294](https://github.com/FreeMixer/zynthian-ui/commit/f864d29), the tip of `vangelis`. jackd runs on a Digidesign
Mbox 2 (`hw:M2`) at 48000 Hz, 256 frames, 3 periods, with no xruns at idle. The benchmark matrix is running on these
versions, with the CPU governor on `performance`, on a private dummy JACK server. The figures below name their versions,
because the earlier ones were taken on older releases.

Proven on the device
--------------------

- **The plugin-hostd engine runs Zynthian chains**, LV2 and CLAP side by side, with the plugin menus built from the
  qualification records ([captures](captures.md)).
- **Controller pages follow the plugin's own sections** and are named by what they hold: every page of omx eq8,
  retaken on omx-plugins 0.16.0 ([captures, omx-eq8](captures.md#omx-eq8-retaken-on-omx-plugins-0-16-0)).
- **Instruments and effects play through the engine, digitally.** mda Piano, Surge XT as CLAP (through the engine) and
  as LV2 (through jalv) give a signal at their JACK output ports at the right pitch with 0 xruns; omx eq8 shows Factory
  and User preset banks in the menu and saves a user preset; omx eq8 (LV2), mda Piano and Odin 2 load factory presets
  and user presets by value on the daemon. Surge XT as CLAP gives the same load with the thread pool off and on: one busy
  thread, 26 % of a core at 64 voices at 48000 Hz and 256 frames. Everything is measured at JACK ports, none of it at the
  analog outputs ([digital proofs](digital-proofs.md)).
- **Surge XT through plugin-hostd, in both formats, digitally.** On plugin-hostd 0.15.4 and omx-clap-host 0.25.2, as LV2
  through the adapter and as CLAP with its own file name, `Surge%20XT.clap`: -13.5 dBFS at C4 at the JACK ports, run by
  hand with a `HOME` set. Without a `HOME` it is silent under jalv and the adapter and its CLAP answers -503.
- **The chains come back at boot.** The engine reaches the daemon on loopback, and the boot load has no -509.
- **The adapter pass ran.** Each LV2 plugin is started under omx-clap-host's adapter and given a note. Its counts: 1216
  admitted, 16 silent, 6 refused, 2 not started. With `lv2_worker auto` a plugin the adapter does not admit goes to
  mod-host.
- **A chain in one worker costs less than one process per plugin.** 16 plugins at 48000 Hz and 256 frames, plugin-hostd
  0.12.0 (run `rpi5-20261027-1`): 2 processes, 10.16 % of a core and 66.1 MB PSS, against jalv's 16 processes, 11.39 %
  and 215.0 MB. Stock mod-host, one process, is a little cheaper in CPU (9.54 %) and a little heavier in PSS (76.4 MB),
  so the gain is over one process per plugin, not over mod-host ([benchmarks](benchmarks.md#grouped-versus-alone-plugin-hostd-jalv-mod-host)).
  At 16 chains of four, plugin-hostd 0.13.1, all at 1500 MHz: 70.6 % of a core and 224.2 MB for 60 plugins grouped,
  82.3 % and 2745.6 MB for 64 plugins under jalv, which stopped there on memory with 2 xruns ([stress run](stress.md)).
- **A lost worker comes back.** After `kill -9` of the process holding one plugin, plugin-hostd 0.12.0 put the worker back
  and re-wired it in 347 ms at 48000 Hz (`kill1`, [benchmarks](benchmarks.md#the-four-hosts-one-plugin-and-short-chains)).
  A plugin that crashes a chain's worker is quarantined and the others go on in order: proven in the CI round trip,
  not yet on the Pi ([chain profile](chain-profile.md)).
- **One panel for both surfaces**: the engine's controller pages and the MOD GUIs are drawn from the same layout
  ([the pipeline page](../from-file-to-page.md)).

Released, not proven on the device yet
--------------------------------------

The Pi runs newer releases than most of these, so they are installed there, except plugin-qualify 0.18.3; what is owed is
the check of each on the device.

- **plugin-qualify 0.18.3** ([release](https://github.com/FreeMixer/plugin-qualify/releases/tag/v0.18.3)): the isolated
  step runs for every plugin of a pass, and again after it could not run; the sync's unit gives the plugins a `HOME`.
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

- **A third-party chain does not run under plugin-hostd yet.** In the new matrix the chain of ten third-party LV2
  effects fails in every cell, single and grouped: `add lv2:http://gareus.org/oss/lv2/fil4#stereo` answers -101, although
  the plugin's pin says in-process and the adapter pass admitted it. So no grouped figure exists yet for other projects'
  plugins on current versions. What closes it: the cause found and fixed, then those cells run again.
- **JACK clients of a grouped chain.** The earlier run on plugin-hostd 0.12.0 counted one JACK client for a chain of our
  plugins ([grouped-vs-processes](evidence/pi5-bench-2026-10-27/grouped-vs-processes.md)); the new matrix on 0.15.4 notes
  one worker and 19 JACK clients for a chain of 19. What closes it: the reason, and the figure in the published matrix.
- **The isolated step is owed.** `verdict=isolated` should mean a plugin was seen running alone. On plugin-qualify 0.18.2
  the step ran for 1 plugin of 152. What closes it: plugin-qualify 0.18.3 on the Pi, `--isolated-only`, then `--rejudge`.
- **Presets in the menu: mda Piano and Odin 2, and loading on CLAP.** The Factory and User banks, the listing and the
  save are proven for omx eq8 in the menu. Open: loading a preset on a running CLAP instance does nothing (omx eq8 reads
  a preset file only while it is not processing, so the menu names the preset and every control stays where it was);
  mda Piano was refused from the menu (-509, see below) and has not been tried there since the fix; Odin 2 was refused
  by its pin, which now says `isolated` and has not been tried again. What closes it: omx-plugins
  and omx-clap-core load a preset on a running instance, mda Piano tried again from the menu, and captures on all three
  ([plugin-hostd#269](https://github.com/FreeMixer/plugin-hostd/issues/269), [digital proofs](digital-proofs.md)).
- **The snapshot round trip.** A snapshot holding mda Piano did not load: the add answered -509, because the daemon did not
  find a bundle whose manifest names the plugin by a prefixed name (`mda:Piano`). plugin-hostd 0.15.4 finds it, and the
  boot load has no -509. What closes it: a snapshot of plugin-hostd chains saved and loaded back with its plugins and
  settings as they were, by value.
- **Surge XT has no record.** It plays in both formats by hand, but no qualification record holds it in either, so the menu
  does not build from a measurement of it. What closes it: a sync on plugin-qualify 0.18.3, with its `HOME`, then Surge XT
  played in both formats through the menu ([instruments](instruments.md), [digital proofs](digital-proofs.md)).
- **Surge XT voices across the cores.** Measured with the thread pool off and on: the same one thread at 26 % of a core
  at 64 voices. Four instances at 16 voices each, in four workers, ran on cpu1, cpu2, cpu3 and cpu1, 0 xruns: what spreads
  today is instances across workers. Surge XT 1.4 declares no thread pool, so the pool does not spread one instance's
  voices. No instrument that takes the pool has been measured yet (omx-clap-core#395).
- **What is heard.** Nothing has gone through the analog outputs: the figures are at JACK ports. What closes it: a person
  listening to mda Piano and Surge XT through the Mbox 2 outputs, with a speaker or a loop cable.
- **zynthian-ui#42 and #44 on the device.** The fork on the Pi does not have them; the unmodified fork reproduces both
  (an empty chain per refused add, `AttributeError ... 'setup'` on `CHAIN_OPTIONS`). What closes it: the fork switched to
  the pull request branches and the two behaviours tried ([digital proofs](digital-proofs.md)).
- **Pin refresh on a plugin upgrade, on the device.** Proven in CI; what closes it: a plugin upgraded on the Pi and
  added again without restarting the daemon.
- **The captures are from before the new set.** What closes it: every capture retaken after the re-qualification
  ([captures](captures.md)).
- **The MOD GUIs on the device show no text.** The Pi runs omx-plugins 0.16.0, whose screenshots predate omx-panel
  0.7.1. What closes it: omx-plugins 0.17.0, regenerated against omx-panel 0.7.2, after its Debian build is fixed
  ([omx-plugins#276](https://github.com/FreeMixer/omx-plugins/issues/276)).
- **openmixer does not build against plugin-hostd 0.14.0 or later.** Two reply codes it reads moved into the
  contract's generated list. What closes it: the fix in openmixer, proven against plugin-hostd 0.15.1, landing.
- **The benchmark matrix is being taken again.** The published figures come from an earlier run with the governor on
  `powersave`, which Zynthian's power save can switch to, and mixed versions. What closes it: the new run published
  ([benchmarks, the matrix](benchmarks.md#the-matrix-every-rate-and-quantum-single-and-grouped)).
- **The upstream patch series is at step 1.** Step 1 is open upstream
  ([zynthian/zynthian-sys#228](https://github.com/zynthian/zynthian-sys/pull/228)); steps 2 to 8 are cut on the forks
  but not offered yet, several with a check on the device still owed
  ([the upstream patch series](upstream-series.md)).
