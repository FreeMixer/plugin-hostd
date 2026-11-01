Zynthian and plugin-hostd: pros and cons
========================================

For a reviewer of the zynthian-ui and zynthian-sys changes. Each point names the measurement in
[benchmarks.md](benchmarks.md) or the public fact it rests on. Where nothing was measured, it says so.

One worker per chain against one process per plugin
---------------------------------------------------

These figures measure the daemon directly, on a private graph; a run through Zynthian's own engine is next
([zynthian-ui#53](https://github.com/FreeMixer/zynthian-ui/pull/53) gives the engine the fix that reads the plan). plugin-hostd runs a chain in one worker process (grouped) or each plugin in a worker of its own (individual);
jalv runs one process per plugin; mod-host runs every plugin in one process. Figures: [Grouped versus
alone](benchmarks.md#grouped-versus-alone-plugin-hostd-jalv-mod-host), Pi 5, 48000 Hz, 256 frames, run `rpi5-20261027-1`
on plugin-hostd 0.12.0. On current versions, up to 24 plugins, the grouped chain has the lowest DSP load: [the
table](benchmarks.md#current-versions-chains-up-to-24-plugins).

| | grouped (plugin-hostd chain) | jalv (one process per plugin) | mod-host (one process) |
|---|---|---|---|
| processes, 16 plugins | 2 | 16 | 1 |
| PSS, 16 plugins | 66.1 MB | 215.0 MB | 76.4 MB |
| CPU, 16 plugins, % of a core | 10.16 | 11.39 | 9.54 |
| add time, 16 plugins | 2507 ms | 2417 ms | 434 ms |
| JACK clients per chain | 1 for an all-CLAP chain (grouped-vs-processes.md); 3 for chain3 with an LV2 member | one per plugin, not counted | not counted |
| a plugin crashes | at the daemon the worker is put back with the links it made itself, 347 ms (`kill1`); in a chain the other members keep playing (round-trip.txt). Not yet measured through Zynthian's engine, whose links come from outside | that plugin's process is lost, nothing restarts it | every plugin of the process is lost |

Pros:

- Memory. A chain of 16 costs 66.1 MB PSS grouped against 215.0 MB under jalv and 155.6 MB as individual workers; RSS
  138.1 MB against 1834.9 MB under jalv. On a 4 GB Pi this is the difference that grows with the chain.
- CPU. Grouped uses less CPU than jalv at 8 and 16 plugins (5.39 against 5.57, 10.16 against 11.39 % of a core) and less
  than plugin-hostd's own individual mode at every N (1.50/5.39/10.16 against 1.86/6.89/14.75).
- Fewer context switches: 2801 grouped against 38985 with one worker per plugin, in 10 s for 16 plugins at 48000 Hz, with
  the chain as one JACK client (grouped-vs-processes.md, plugin-hostd 0.12.0).
- Crash containment by the daemon: a lost worker is restarted, with the links the daemon made itself, in about 340 ms, which
  jalv and mod-host do not do (`kill1`). Links made from outside are not restored, and Zynthian's routing is made from
  outside, so this says nothing yet for a real Zynthian. Inside a chain a member that aborts leaves the others playing (round-trip.txt,
  `a_crashed_member_leaves_the_three_playing`).

Cons:

- A grouped chain shares one process: a plugin that corrupts memory instead of crashing cleanly can take the chain with
  it. The pins are the guard: a plugin that fails the RT-safety sweep is isolated, it runs in a worker of its own and is
  never grouped with RT-safe plugins (plugin-qualify#196, plugin-hostd#231), and an unsuitable one (it crashes, hangs or
  fails to load) is not offered.
- Isolation has a cost: each isolated plugin is one more worker, which is the "plugin-hostd, individual" mode of the
  grouped-versus-alone figure. Per plugin it adds about one process and, from 3 to 16 plugins at 48000 Hz, the
  individual mode costs 80.0 to 155.6 MB PSS against 50.0 to 66.1 MB grouped, and 1.86 to 14.75 % of a core against
  1.50 to 10.16. On the Pi 185 of 1329 LV2 plugins and 133 of 247 CLAP plugins are isolated for plugin-hostd's worker.
- Add time. A chain takes longer to form than the same plugins under mod-host (2507 ms against 434 ms for 16), and the
  same order as jalv. It is paid when a chain is built or changed.
- On 0.12.0, mod-host was the cheapest in CPU at every N (9.54 % for 16) and close in PSS (76.4 MB). On 0.15.4, with the
  chain as one JACK client, the grouped chain reads lower (8.45 % DSP against 9.84 % at 16), on different builds of the
  plugins. Either way plugin-hostd's large gain is over jalv, Zynthian's default engine for LV2, not over mod-host.
- Latency: the bench records only the latency the clients declare (none for these plugins). A measured round-trip
  latency per host is not measured yet (it needs a loopback cable).

CLAP hosting
------------

Zynthian has no CLAP host: jalv and mod-host host LV2 only (every CLAP verdict under jalv and mod-host is
`hosting.clap.format-not-hosted` or a crash, benchmarks.md). plugin-hostd hosts CLAP in its worker, omx-clap-host, and LV2
through the same worker's LV2 adapter.

- Of the 248 CLAP plugins on the Pi, about 189 are offered through plugin-hostd and 59 are not (qualification after the
  rejudge, below). Every one of our 19 omx plugins
  sweeps clean.
- The CLAP and LV2 builds of one plugin are not interchangeable in cost: at 192000 Hz and 512 frames the LV2 build of
  omx-chorus costs 592.2 ns per sample at the median against 0.8496 for the CLAP build (tables.md). The reason is not
  established.
- CLAP behind MOD-UI does not carry over: mod-ui reads LV2 TTL, so CLAP ports, parameters, presets and MIDI maps fail
  behind it (verbs.tsv). The fork's PH engine does not go through MOD-UI.

Qualification and pins
----------------------

Every plugin on the device is measured once by plugin-qualify, and plugin-hostd reads the result as a pin per binary
(`pin_set <id> <file>=<sha256> ... verdict=<v>`): a plugin whose files change is measured again.

- Three classes (plugin-qualify#196, plugin-hostd#231): suitable; isolated, a plugin that fails the RT-safety sweep,
  run in a worker of its own and never grouped; unsuitable, a plugin that crashes, hangs, fails to load or breaks the
  host. For plugin-hostd's worker on the Pi: LV2 1059 suitable, 185 isolated, 79 unsuitable (6 unmeasured); CLAP 71,
  133, 43.
- After the deep run and sync on plugin-qualify 0.16.1, the device's pin file holds 1187 pins `in-process`, 305 `refused` and 81 without a
  verdict. The files predate the decision that a plugin failing the sweep is isolated: of the 172 plugins the sync refused, 170 failed the sweep in the run and 2
  under notes, so all 172 are isolated, not unsuitable; the sync's 4 crashed plugins are the unsuitable ones.
- After the rejudge, the Pi's pin file holds 1516 plugins: 1283 LV2 and 233 CLAP. Of the LV2 ones, 995 may share a worker,
  176 get a worker of their own, 38 have no verdict yet and run in a worker of their own until they are qualified, and 7 are
  refused; that is 1216, and I have not broken down the other 67. The qualification records hold 248 distinct CLAP
  plugins, of which about 189 are offered and 59 are not. Under our host the LV2 set reads 1033 suitable, 177 conditional, 6 unsuitable and 113 unknown; the same
  plugins under mod-host read 781, 174, 279 and 95. 96 records are still owed. 148 records say "probe crashed": that is our
  probe, which reused one instance across four sample rates, and LSP plugins crash when reactivated at a new rate. They are
  being run again with a fresh instance per rate, so no plugin is called broken here. The counts below are from the run before
  the rejudge.
- LV2 suitability is the same under jalv, mod-host and plugin-hostd's worker (1059, 1058, 1059 of 1329): qualification
  does not shrink what Zynthian offers for LV2; it isolates the plugins it found allocating, locking or calling into
  the kernel in the audio thread (183 LV2 records) and leaves out the ones that crash or hang (79).
- A plugin plugin-hostd refuses stays on jalv, listed in its menu (FreeMixer/zynthian-ui#12): nothing the user
  has disappears. An isolated plugin runs in plugin-hostd in a worker of its own instead.
- Cost is not part of any verdict yet: the grid holds 512-frame blocks only, so every cost rating reads unknown
  (plugin-qualify#193). The menus' cost tags are therefore not from Zynthian's quantum.
- The run is long: 6 hours on the Pi 5 for 1823 records (run.log), with the governor at powersave. It runs once per
  plugin set, not at boot.
- Defects the files show: 8 LV2 plugins have no document because a file they load is named by a percent-encoded IRI
  (Pianoteq 9, Surge XT among them); four DISTRHO CLAP files are pinned under one id; the sync timed out writing CLAP
  descriptors (benchmarks.md).

mod-host protocol compatibility
-------------------------------

plugin-hostd speaks mod-host's protocol on its port, so mod-ui and Zynthian code written for mod-host talk to it
unchanged. [verbs.tsv](verbs.tsv) lists the 33 verbs mod-ui sends and what each does under plugin-hostd.

- In the driven session (spike, plugin-hostd 0.6.0) 130 of 135 replies are identical. The 5 that differ:
  `connect` to `mod-monitor` (no worker owns it), `feature_enable aggregated-midi` (a later worker never hears it), and
  `preset_load` of a user preset after a pedalboard reload (the new worker never heard the `bundle_add`).
- Feedback differs by worker: `transport` 6 times against 1.
- Not re-run since 0.6.0; the PH engine of the fork uses the chain verbs (`chain`, `chain_get`, `plan`, `plan_get`,
  `plan_clear`), which mod-host does not have.

Packaging
---------

- The packages come from the OpenMixer apt repository for Debian 13 arm64 (FreeMixer/zynthian-sys#1): plugin-hostd,
  omx-clap-host, omx-plugins and omx-panel. On the Pi of these runs: plugin-hostd 0.13.1, omx-clap-host 0.23.2,
  omx-plugins 0.15.1, plugin-qualify 0.16.1, omx-panel 0.6.0.
- ZynthianOS vangelis ships Python 3.13. mod-ui's install recipe did not build there; FreeMixer/zynthian-sys#6 makes it
  build (pycryptodome, the ssl backport, the interpreter's own version), and the same change is offered upstream as
  zynthian/zynthian-sys#228 (open).
- A second apt source is a cost for the image: a mirror, keys, and a release cadence that is not Zynthian's.

What changes in zynthian-ui and zynthian-sys
--------------------------------------------

FreeMixer/zynthian-ui, branch `vangelis`, merged pull requests:

| # | change |
|---|---|
| 1 | PH engine: LV2 and CLAP plugins in plugin-hostd |
| 2 | plugin-hostd by default, snapshot converter, menus from qualification |
| 3 | a grouped member takes the chain's JACK client |
| 4 | plugin menus read the qualification records, CLAP entries keyed by pin URI |
| 5 | tests: chain JACK-name tests key their CLAP entry by pin URI |
| 6 | a chain on the lv2-clap row is one JACK client too |
| 7 | sync_chain asks the daemon's planner what runs together (plugin-hostd#190) |
| 8 | a CLAP parameter addressed by its number, not by omx-panel's name |
| 11 | tests: one zynthian_lv2 stand-in per process, its registry reset per test |
| 12 | a plugin plugin-hostd refuses stays on jalv, listed in its menu |
| 14 | protocol files read once with a clear refusal; the daemon started by zynthian-sys's one script |

(2, 3, 4 and 6 were merged into feature branches that were then merged to `vangelis`.)

FreeMixer/zynthian-sys, branch `vangelis`, merged pull requests:

| # | change |
|---|---|
| 1 | the OpenMixer repository |
| 2 | plugin-hostd as the mod-host of the MOD-UI engine, switchable (`ZYNTHIAN_MODHOST_BACKEND`, `sbin/set_modhost_backend.sh`) |
| 3 | MOD GUIs from omx-panel |
| 4 | OpenMixer as the default install, on new images and on update |
| 5 | omx-modgui-sync from omx-panel; the image enables it and puts its directory on `LV2_PATH` |
| 6 | install_mod-ui.sh builds the environment on Python 3.13 |
| 7 | plugin-hostd-start.sh: one place starts a plugin-hostd and waits for its declared line |

Upstream: zynthian/zynthian-sys#228 (install_mod-ui.sh on Python 3.13), open.

What is not done
----------------

- A listening test through the audio interface, which is next. Plugins are measured digitally at JACK ports on the Pi
  ([digital proofs](digital-proofs.md)). The sample-by-sample round trip ran in x86_64 containers.
- The cost grid at the hosts' quantums (128, 256, 1024 frames) and LV2 at 44.1, 48 and 96 kHz: plugin-qualify#193.
- A cost estimate at Zynthian's quantum: the `estimate` verb and the fork's menu exist (FreeMixer/zynthian-ui#13), but
  the records' cost comes from 512-frame blocks only (plugin-qualify#193).
- The fork's engine still gives each processor of a CLAP chain the JACK name `effect_<instance>`, although the chain is
  one JACK client whose head carries the chain's ports. Open.
- The MOD-UI engine on plugin-hostd was not measured on the device: until the fork's update script was applied it ran
  the stock mod-host.
- JACK client counts for jalv and mod-host, and xruns over long windows: not measured yet.
