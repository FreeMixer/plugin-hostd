Digital proofs on the Pi 5
==========================

What was measured on the Zynthian Pi 5 with the Digidesign Mbox 2 (`hw:M2`) under jackd at 48000 Hz, 256 frames, 3
periods, with plugin-hostd 0.15.3, omx-clap-host 0.25.1, plugin-qualify 0.18.0, omx-panel 0.7.2, omx-plugins 0.16.0 and
the zynthian-ui fork at `f864d294` (the tip of `vangelis`). Every level and count below is read at a JACK port or in a
journal: these are **digital** measurements, and each figure is one at the JACK ports. Where a failure below has since been fixed, the
section says on which release; the Pi now runs plugin-hostd 0.15.4 and omx-clap-host 0.25.2.

Nothing was downloaded or built on the Pi except the two probes `tools/zynthian/` names (`jack-instrument-probe`,
`jack-note-meter`, compiled with the gcc and `jack.h` that are already on the image). Every run is a script in
[tools/zynthian/](../../tools/zynthian/) or a protocol line, and the raw tables are in
[evidence/pi-digital-proofs/logs/](evidence/pi-digital-proofs/logs/).

The figures are what they are: measured on this Pi at 48000 Hz and 256 frames, on digital output, over windows of a few
seconds each. They are not a rating and not a benchmark.

Proven digitally
----------------

### mda Piano through the plugin-hostd engine

`instrument-proof.py` starts a plugin-hostd of its own on a private port (no pins, its own state directory), adds mda
Piano (`http://moddevices.com/plugins/mda/Piano`), links a probe to its note input and measures at the instance's JACK
output ports `effect_1:out_1` and `effect_1:out_2`. The Zynthian UI's own daemon was not the one measured, see
[mda Piano cannot be added from the Zynthian menu](#mda-piano-cannot-be-added-from-the-zynthian-menu).

| Window | Peak | RMS | Pitch | Xruns |
| --- | --- | --- | --- | --- |
| velocity 20 | -34.3 dBFS | -45.1 dBFS | 261.4 Hz | 0 |
| velocity 64 | -16.5 dBFS | -27.4 dBFS | 262.9 Hz | 0 |
| velocity 127 | -5.6 dBFS | -18.7 dBFS | 541.4 Hz | 0 |
| idle | -inf | -inf | | 0 |
| 8 notes held | -4.7 dBFS | -24.5 dBFS | | 0 |

The note is C4 (261.6 Hz) and the level follows the velocity. The add took 182 ms and the ports were up after 330 ms.
Table: [a-mdapiano.tsv](evidence/pi-digital-proofs/logs/a-mdapiano.tsv), protocol:
[a-mdapiano-protocol.log](evidence/pi-digital-proofs/logs/a-mdapiano-protocol.log).

### Surge XT, CLAP, through the engine

The same script with `clap:.../Surge XT.clap#org.surge-synth-team.surge-xt`: 23 windows (start, velocity, polyphony,
pitch bend, sustain, all notes off, MPE), every one with 0 xruns and the note at its pitch (C4 at 261.4 to 262.9 Hz at
every velocity, A4 at 440.0 Hz under bend, 440.0 and 881.0 Hz on the MPE member channel). Peak -13.5 dBFS at every
velocity (Surge XT's default patch ignores velocity). With 8 or more voices held the peak is above 0 dBFS (+1.2 dBFS at 8
voices, +9.6 and +9.7 dBFS at 64 voices in the two pool runs below): this is a float signal, it would clip a converter.
[d-clap-default.tsv](evidence/pi-digital-proofs/logs/d-clap-default.tsv)

The file name has a space, so the daemon takes it as `Surge%20XT.clap`. The run used a symlink without a space,
`/tmp/.../SurgeXT.clap`, because the worker answers -101 to the encoded name, see
[Surge XT as CLAP with the encoded name](#surge-xt-as-clap-with-the-encoded-name).

### Surge XT, LV2, through jalv

The stock Zynthian path (`jalv -n inst_jalv https://surge-synthesizer.github.io/lv2/surge-xt`), the same scenarios, 20
windows, 0 xruns, the same pitches, peak -13.5 dBFS, +5.2 dBFS at 16 voices.
[d-lv2-jalv.tsv](evidence/pi-digital-proofs/logs/d-lv2-jalv.tsv)

### Surge XT voices across the cores, thread pool off and on

64 voices, Surge XT 1.4 as CLAP, one instance, polyphony held for each step, JACK DSP load from the server. Percent of
one core of the thread that carries the work (`omx-clap-host@cpuN`), 0 xruns in every window.

| Voices | Pool off: thread | Pool off: JACK DSP | Pool cores: thread | Pool cores: JACK DSP |
| --- | --- | --- | --- | --- |
| 1 | 2 % | 2.6 % | 2 % | 2.7 % |
| 8 | 4 % | 4.9 % | 4 % | 4.9 % |
| 16 | 7 % | 7.8 % | 6 % | 7.7 % |
| 32 | 13 % | 14.1 % | 13 % | 14.0 % |
| 48 | 19 % | 20.3 % | 19 % | 20.4 % |
| 64 | 26 % | 27.5 % | 25 % | 27.0 % |

Both settings give one busy thread, on cpu1, and the same load. Surge XT 1.4 declares no `clap.thread-pool`, so the
pool has nothing of its to run: **the pool does not spread Surge XT's voices on this Pi**. Four instances of the same
plugin (16 voices each) run in four workers, spread over the cores: 10 %, 10 % and 10 % on cpu1, cpu2 and cpu3 and 8 % on
cpu1 again, JACK DSP 18.8 % without the pool and 18.6 % with it, 0 xruns in both. That is the same 64 voices at a lower
JACK DSP load than one instance's 27.5 %. What spreads is instances across workers, not one instance's voices. Tables:
[pool off](evidence/pi-digital-proofs/logs/d-clap-poly64-pool-off.tsv),
[pool cores](evidence/pi-digital-proofs/logs/d-clap-poly64-pool-cores.tsv),
[four instances](evidence/pi-digital-proofs/logs/d-clap-x4.tsv),
[four instances, pool cores](evidence/pi-digital-proofs/logs/d-clap-x4-pool.tsv).

The per-core numbers in the four-instance rows (cpu0 to cpu3) differ between the two runs (cpu1 24 %, others 2 to 3 %
without the pool, 19 to 24 % on every core with it) while the threads read the same 10 %. They are one-window samples of
`/proc/stat` and are not read here as a difference the pool makes.

### Presets: Factory and User banks

- **omx eq8 (CLAP), in the Zynthian menu.** The preset menu shows two banks, Factory and User
  ([banks](evidence/pi-digital-proofs/captures/b-eq8-banks.png)). Factory lists the plugin's eight presets by name
  ([capture](evidence/pi-digital-proofs/captures/b-eq8-factory.png)). User says `No presets` with no error in the journal
  ([capture](evidence/pi-digital-proofs/captures/b-eq8-user-no-presets.png)). **Save new preset** wrote
  `/zynthian/zynthian-my-data/presets/plugin-hostd/omx_eq8/omxtest.json`
  ([the file](evidence/pi-digital-proofs/logs/b-omx-eq8-clap-user-preset-from-the-ui.json), Band 1 gain 6.0 after six
  encoder steps) and the preset lists again under User
  ([capture](evidence/pi-digital-proofs/captures/b-eq8-user-saved-listed.png)). **Loading a preset does not change a
  value, see [CLAP preset load](#omx-eq8-as-clap-refuses-to-load-a-preset-on-a-running-instance).**
- **omx eq8 (LV2) through plugin-hostd.** Eight presets listed, `eq-601` loaded: Band 1 to 4 gain 0, 0, 0, 0 become
  1.5, -1.5, 2.0, 2.5; `maxer-low` gives 3.0, 0, 0, 0. A user preset saved with Band 3 gain set to 4.5 loads back as 4.5
  after `eq-601` had put it at 2.0 ([log](evidence/pi-digital-proofs/logs/b-omx-eq8-presets.txt)).
- **mda Piano (LV2) through plugin-hostd.** Eight presets (Default and seven named). `Plain Piano` then `Dark Piano`:
  muffling filter 75.1 to 30.4 and stereo width 100 to 130.2. A user preset saved with the muffling filter at 55 loads
  back as 55 after `Plain Piano` put it at 75.1
  ([log](evidence/pi-digital-proofs/logs/b-mda-piano-presets.txt),
  [file](evidence/pi-digital-proofs/logs/b-mda-piano-user-preset.json)). This was done on the private daemon, not in the
  menu.
- **Odin 2 2.3.4 (LV2), on omx-clap-host's adapter, spoken to directly.** The bundle ships one preset
  (`https://thewavewarden.com/odin2#preset001`, with no label), it loads, and none of the 258 control ports it was
  compared on changes. A user preset saved with `osc1_finetune` at 0.8 loads back as 0.8 after the factory preset had
  put it at 0.5 ([log](evidence/pi-digital-proofs/logs/b-odin2-presets.txt)). Odin 2 cannot be added from the Zynthian
  menu or to the device's daemon, see [Odin 2](#odin-2-is-refused-by-its-pin).

Failed or not run
-----------------

### mda Piano cannot be added from the Zynthian menu

Adding mda Piano from the menu, or restoring a snapshot that holds it, answers
`add http://moddevices.com/plugins/mda/Piano 1000 => OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH_RESP (-509)`. mda ePiano
and every plugin of the `mod-mda-*` bundles are refused the same way. The cause is in the daemon: the bundle search
looks for the literal `<http://moddevices.com/plugins/mda/Piano>` in each manifest, and these manifests write
`mda:Piano` under an `@prefix`, so no bundle is found and no pin can be collected.
`plugin-hostd --pin-files http://moddevices.com/plugins/mda/Piano` fails with `manifest.ttl is in no bundle of lv2_path
naming the plugin`. The fix is [plugin-hostd#324](https://github.com/FreeMixer/plugin-hostd/pull/324), in plugin-hostd
0.15.4, which the Pi now runs: the chains load at boot with no -509. Adding mda Piano from the menu has not been tried
again.

Each refused add left an empty chain in the mixer, one per try
([capture](evidence/pi-digital-proofs/captures/b-refused-adds-leave-empty-chains.png)). This is what
zynthian-ui#42 is for; the Pi's fork does not have it (see below).

### The snapshot round trip

Not proven. A snapshot of a mixer holding the empty piano chains and an omx eq8 chain was saved
([capture](evidence/pi-digital-proofs/captures/c-snapshot-saved.png)), all chains were removed with CLEAN_ALL, and
loading it back stopped on the first mda Piano chain with the -509 above:
`zynthian_state_manager.load_snapshot: Invalid snapshot: 'add ... Piano 1000' => ... (-509)`
([journal](evidence/pi-digital-proofs/logs/c-snapshot-load-journal.txt)). No chain came back. The UI then stayed busy
(`Clients have been busy for longer than 30s: add_processor, set_chain_state`) and ignored every CUIA action until its
service is restarted ([capture](evidence/pi-digital-proofs/captures/c-ui-busy-after-failed-snapshot-load.png)); the
service was not restarted from this run. JACK counted one xrun at the moment of the failed load. Plugins and settings as
they were, by value, cannot be compared until mda Piano can be added.

### omx eq8 as CLAP refuses to load a preset on a running instance

In the menu, choosing a Factory preset shows its name in the title bar and leaves every control where it was
([capture](evidence/pi-digital-proofs/captures/b-eq8-factory-load-values-unchanged.png): `Gentle Tilt` with Band 1 gain
0.0, where the LV2 form of the same preset gives 1.5). The journal has
`preset_load 1000 file:/usr/share/omx/presets/org.openmixer.eq8//eq-601.json => ERR_HOST_INVALID_PRESET_URI (-104)`. On
the daemon the same key answers `-104 PRESET_NOT_OFFERED`, a path answers `PRESET_INVALID`, and a user file saved from
the instance answers `LOAD_REFUSED`. The plugin's `clap.preset-load` (and its state load) return false while it is
processing: `plugins/omx-eq8/omx_eq8_clap.c` reads a preset file only `!g->processing`, and an instance on a live JACK
client is always processing. This is read from the source of omx-plugins 0.16.0; the plugin was not rebuilt to confirm it.

### Surge XT as CLAP with the encoded name

`add clap:/usr/local/lib/clap/Surge%20XT.clap#org.surge-synth-team.surge-xt` is accepted by the daemon (0.15.3 decodes
it where it opens and hashes the file) and answers -101 from the worker, which is given the encoded name. A symlink with
no space in its name works: the proofs above used it.

After this run the daemon gives the worker the decoded path, one quoted word. On plugin-hostd 0.15.4 and omx-clap-host
0.25.2 the encoded name reads -13.5 dBFS at C4, run by hand with a `HOME` set: without a `HOME` its CLAP answers -503.

### Surge XT as LV2 through plugin-hostd's adapter

Added with `lv2_worker omx-clap-host`, it runs and takes the notes (JACK DSP 9 % with one note held, 16 % at 8 voices, and a
second busy thread) but **the output ports stay silent: peak -inf dBFS in all 22 windows**, in two runs
([run 1](evidence/pi-digital-proofs/logs/d-lv2-hostd.tsv), [run 2](evidence/pi-digital-proofs/logs/d-lv2-hostd-2.tsv)),
with 0 xruns. The same plugin through jalv, in the same session, gives -13.5 dBFS. With the device's own settings
(`require_pins 1`) the add answers -509: the manifest names the binary `libSurge%20XT.so`, which the daemon does not
decode ([plugin-hostd#239](https://github.com/FreeMixer/plugin-hostd/issues/239)).

The silence was the adapter's: its first block sent every `patch:writable` property at its `lv2:default`, and Surge XT's TTL
says 0 for all 775 of them, the global volume among them, while its real values live in the plugin
([omx-clap-core#433](https://github.com/FreeMixer/omx-clap-core/pull/433)). With a build of that change and of the daemon
that decodes the binary's name, on this Pi, under `require_pins 1`: -13.5 dBFS at C4, as jalv, 0 xruns. A single low note
reads -11.2 dBFS peak, -22.4 dBFS RMS at 65.5 Hz, the row jalv gives, at JACK DSP 3.7 % against 14.3 % before. The released
plugin-hostd 0.15.4 and omx-clap-host 0.25.2 give the same -13.5 dBFS at C4, by hand with a `HOME` set; without a `HOME`
Surge XT is silent, under jalv too. Surge XT still has no qualification record in either form.

### Odin 2 is refused by its pin

In this run the pin of Odin 2 carried `verdict=refused` (its record said `unsuitable`, isolated, from real-time violations
in the sweep), so the daemon answered -516 and the menu listed it as `refused`. Presets were proven by speaking to the
worker directly (above). Since then its record says `isolated` for the same violations, the adapter pass admits it and the
pin carries `verdict=isolated`, which means a worker of its own; adding and playing it has not been tried again.

### zynthian-ui #42 and #44

Not tried. The Pi's fork is at the tip of `vangelis` and neither pull request is merged, so a trial means switching the
fork's checkout to the pull request branches, which this run did not do. What the unmodified fork does is on the record:

- #44: sending `CHAIN_OPTIONS` through the CUIA port (UDP 1370, `/CUIA/CHAIN_OPTIONS`) reproduces the bug at once:
  `AttributeError: 'zynthian_gui_chain_options' object has no attribute 'setup'` in `cuia_chain_options`
  ([journal](evidence/pi-digital-proofs/logs/e-chain-options-journal.txt),
  [capture](evidence/pi-digital-proofs/captures/e-chain-options-no-screen.png): the screen does not change). So the
  trigger works for the trial.
- #42: the empty chains and the stuck busy state above.

How the screens were driven
---------------------------

`xdotool key` on `:0` moves lists (Up, Down, Left and Right change the category, Return selects, Escape goes back); a
bold press is Return held for 1.3 s. The CUIA port takes named actions (`add_chain`, `chain_control`, `bank_preset`,
`screen_snapshot`, `clean_all:CONFIRM`) but its arrow actions did not move a list. The on-screen keyboard of the text
screens takes mouse clicks only and its first layer has no hyphen, so the saved names are `omxtest` and `omxrta`; typing on
a physical keyboard there runs the key bindings instead (`m` started a MIDI recording, stopped again with no file written).
