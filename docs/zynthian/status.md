Where this stands
=================

This page says what is proven on the Zynthian Pi 5, what is released but not proven on the device yet, and what is
still open, why, and what closes it. The pages it links are the detail. What the work is and how little it changes in
Zynthian: [the Zynthian page](README.md).

On the Pi now
-------------

The Pi 5 runs plugin-hostd 0.15.7, plugin-qualify 0.18.4, omx-clap-host 0.25.4, omx-panel 0.7.2, omx-plugins 0.16.0 and the
zynthian-ui fork at [f864d294](https://github.com/FreeMixer/zynthian-ui/commit/f864d29), which it keeps for the benchmark queue:
it is behind the tip of `vangelis` and does not have the grouping fixes. jackd runs on an RME Babyface Pro at 48000 Hz, 256
frames, 3 periods; the governor is on `performance`. The figures below name their versions, and the earlier ones were taken
with a Digidesign Mbox 2 (`hw:M2`) or the dummy card.

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
  thread, 26 % of a core at 64 voices at 48000 Hz and 256 frames. Every level and count here is measured digitally at the
  JACK ports ([digital proofs](digital-proofs.md)).
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
  On plugin-hostd 0.15.5, 24 LV2 plugins, three repeats: 2 processes, one JACK client, JACK DSP 13.51 %, 61.1 MB PSS, against
  jalv's 24 processes, 19.23 % and 993.6 MB, and mod-host's one process, 15.51 % and 112.1 MB
  ([benchmarks](benchmarks.md#current-versions-chains-up-to-24-plugins)). These figures measure the daemon directly, on a private graph;
  zynthian-ui gained the fix that reads the plan in [zynthian-ui#53](https://github.com/FreeMixer/zynthian-ui/pull/53),
  and a run through Zynthian's own engine is next.
- **Grouping through Zynthian's own engine, on its proof.** On plugin-hostd 0.15.7, omx-clap-host 0.25.4 and zynthian-ui
  [76b5e106](https://github.com/FreeMixer/zynthian-ui/commit/76b5e106) with `grouping on`, `tools/ph_signal_path_proof.py` passes
  10 of 10 on the Pi, read digitally at JACK ports: a run in series groups as one client, a parallel slot, the strip or another
  client ends it, `grouping off` leaves each on its own, an edit elsewhere keeps the worker's pid, a note reaches a member that is
  not the head. Zynthian came up with 0 Tracebacks and all its clients. The checkout then went back to f864d294
  ([log](evidence/pi5-claims-2026-10-31/engine-proof/proof.log)).
- **Values and presets on omx-clap-host 0.25.4, at the daemon.** omx-comp's ratio set to 7.5 reads 7.5 after a chain forms and
  after `kill -9` of the chain's worker; a factory preset on a running CLAP omx eq8 changes 4 of 47 parameters and holds
  ([log](evidence/pi5-claims-2026-10-31/engine-proof/proof.log)).
- **At the daemon, a lost worker comes back.** After `kill -9` of the process holding one plugin, plugin-hostd 0.12.0 put the
  worker back and re-wired the links it made itself in 347 ms at 48000 Hz (`kill1`,
  [benchmarks](benchmarks.md#the-four-hosts-one-plugin-and-short-chains)). The daemon replays only those links: links made
  from outside are not restored, one run stayed silent for that reason, and Zynthian's routing is made from outside. A
  run through Zynthian's own engine says what a crash does there; until then these pages claim nothing for it.
  A plugin that crashes a chain's worker is quarantined and the others go on in order: proven in the CI round trip,
  not yet on the Pi ([chain profile](chain-profile.md)).
- **One panel for both surfaces**: the engine's controller pages and the MOD GUIs are drawn from the same layout
  ([the pipeline page](../from-file-to-page.md)).

Released, not proven on the device yet
--------------------------------------

The Pi runs these or newer releases, so they are installed there; what is owed is the check of each on the device.

- **Time to add, measured on builds that 0.15.8 carries.** Like for like, 24 plugins on the LV2 builds on every host (Pi 5,
  48000 Hz, 256 frames, three repeats): grouped plugin-hostd adds them in 530 ms with one JACK client and 63 MB, against
  mod-host's 733 ms, 26 clients and 112 MB, which is 28 % faster; from a cold host a snapshot of the 24 loads in 541 ms
  against mod-host's 1683 ms, 3.1 times faster. On the CLAP builds, where only our hosts can run them, grouped adds in 428 ms;
  that row is not comparable with mod-host. On a third-party set of ten, all LV2, mod-host still adds faster warm (306 ms
  against 501 ms) for the reason in the open list below ([rows](benchmarks.md#time-to-add-and-the-same-chain-with-the-add-into-the-chain)).
- **Through Zynthian's update.** The signed tags are zynthian-ui `omx-track/2026103102` at ee76d0ce and zynthian-sys
  `omx-track/2026110101` at c34723a; the update now moves zynthian-ui, zynthian-sys, zynthian-webconf and the packages together.
- **plugin-hostd 0.15.7** ([release](https://github.com/FreeMixer/plugin-hostd/releases/tag/v0.15.7)): `chain` answers the
  worker's refusal, and a refused chain ends.
- **plugin-qualify 0.18.4** ([release](https://github.com/FreeMixer/plugin-qualify/releases/tag/v0.18.4)): the adapter pass and
  the isolated step play an instrument a wide range of keys, so a drum kit that answers only some keys is heard.
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

- **Next: chains from the menu with grouping on.** The proof above drives the engine. What closes it: chains built from the menu
  on the Pi with the fork's tip, `worker_list` showing what shares a worker, and the same figures taken that way, and what a crash
  does there.
- **Ten third-party plugins in a group.** Since [plugin-hostd#339](https://github.com/FreeMixer/plugin-hostd/pull/339) they run,
  single and grouped. With the add into the chain, six stereo members form one chain and the four mono ones each have a worker of
  their own: five clients, and 501 ms to add against mod-host's 306 ms ([rows](benchmarks.md#time-to-add-and-the-same-chain-with-the-add-into-the-chain)).
  What closes it: a mono plugin run inside a stereo chain ([omx-clap-core#447](https://github.com/FreeMixer/omx-clap-core/issues/447)),
  then the rows again.
- **A chain that does not form.** On plugin-hostd 0.15.4 a grouped chain did not form within 20 s in one of four cells at 18
  plugins and on one repeat at 32 and at 48. On 0.15.5 it formed in all six cells at 18 and every repeat up to 24. What closes
  it: rows at 32 and 48 on current versions.
- **The chain of all 19.** On omx-clap-host 0.25.3 the worker refused a chain holding omx keyed-gate, so those matrix rows are one
  worker and many JACK clients. omx-clap-host 0.25.4 forms it. What closes it: the chain of all 19 run again.
- **The isolated step is owed.** `verdict=isolated` should mean a plugin was seen running alone. On plugin-qualify 0.18.2
  the step ran for 1 plugin of 152. What closes it: `--isolated-only` on a plugin-qualify that carries the fix, then `--rejudge`.
- **Presets in the menu: mda Piano and Odin 2, and loading on CLAP.** The Factory and User banks, the listing and the
  save are proven for omx eq8 in the menu. Loading on a running CLAP instance works on the daemon on omx-clap-host 0.25.4, and has not been retried from the menu.
  Open: mda Piano was refused from the menu (-509, see below) and has not been tried there since the fix; Odin 2 was refused
  by its pin, which now says `isolated` and has not been tried again. What closes it: a preset loaded from the menu on a running instance, mda Piano tried again from the menu, and captures on all three
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
- **Next: a listening test through the audio interface.** The figures are read digitally at the JACK ports; the next step
  takes mda Piano and Surge XT through the interface's outputs.
- **zynthian-ui#42 and #44 on the device.** The fork on the Pi does not have them; the unmodified fork reproduces both
  (an empty chain per refused add, `AttributeError ... 'setup'` on `CHAIN_OPTIONS`). What closes it: the fork switched to
  the pull request branches and the two behaviours tried ([digital proofs](digital-proofs.md)).
- **Mixbus chains and parallel slots on the device.** A chain now groups only plugins in series, and leaves a parallel
  slot, the mixer strip and a jalv plugin in the signal's way: measured at JACK ports, in a container and with the engine's proof on the Pi, without a Mixbus in Zynthian's own mixer. What
  closes it: the UI steps of [mixbus chains](mixbus.md#steps-for-the-pi).
- **Pin refresh on a plugin upgrade, on the device.** Proven in CI; what closes it: a plugin upgraded on the Pi and
  added again without restarting the daemon.
- **The captures are from before the new set.** What closes it: every capture retaken after the re-qualification
  ([captures](captures.md)).
- **The MOD GUIs on the device show no text.** The Pi runs omx-plugins 0.16.0, whose screenshots predate omx-panel
  0.7.1. What closes it: omx-plugins 0.17.0, regenerated against omx-panel 0.7.2, after its Debian build is fixed
  ([omx-plugins#276](https://github.com/FreeMixer/omx-plugins/issues/276)).
- **openmixer does not build against plugin-hostd 0.14.0 or later.** Two reply codes it reads moved into the
  contract's generated list. What closes it: the fix in openmixer, proven against plugin-hostd 0.15.1, landing.
- **The benchmark matrix is on hold.** Its chain cells were taken on current versions, and the single-plugin cells wait while
  the device runs other measurements. The rows in use are in [benchmarks](benchmarks.md#current-versions-chains-up-to-24-plugins).
  What closes it: the single-plugin cells taken and published.
- **The upstream patch series is at step 1.** Step 1 is open upstream
  ([zynthian/zynthian-sys#228](https://github.com/zynthian/zynthian-sys/pull/228)); steps 2 to 8 are cut on the forks
  but not offered yet, several with a check on the device still owed
  ([the upstream patch series](upstream-series.md)).
