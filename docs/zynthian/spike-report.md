Zynthian spike: plugin-hostd and plugin-qualify in Zynthian
===========================================================

FreeMixer/plugin-hostd#124, run 2026-10-20 in a cluster pod (Fedora 44 container, x86_64, 4 CPUs, no root, no
container runtime, no qemu-system). Nothing was sent to Zynthian and no Zynthian repository was written to. The plan
built on these results is [offer.md](offer.md); the verb table is [verbs.tsv](verbs.tsv); the spike's engine was
a patch against zynthian-ui, since superseded by the FreeMixer/zynthian-ui fork ([README.md](README.md)). Every number below names the file or command it came
from; the raw logs are under [evidence/](evidence/).

What ran, and what did not
--------------------------

| Part | Ran | How |
|---|---|---|
| Zynthian's mod-ui | yes, x86_64 | zynthian/mod-ui `zyn-mod-merge-20230514` @ `817a67234f41` (the branch zynthian-sys `scripts/recipes/install_mod-ui.sh:13` installs), Python 3.11 venv with tornado 4.3 patched as that recipe patches it, `utils/libmod_utils.so` built against JACK2 1.9.22 and lilv 0.26.4 |
| mod-host | yes, x86_64 | moddevices/mod-host @ `12335c265374` (2026-10-19). Zynthian builds upstream mod-host at HEAD, not its own fork: `install_mod-host.sh:13` clones moddevices/mod-host, the sha line is commented out (`:9`; zynthian-sys file:line citations are at `f5e41b3b270a`, the image's commit); zynthian/mod-host has not moved since 2016-11-03 (`d44ae41`). Loaded into jackd as an internal client, as `etc/systemd/mod-host.service:17` does (`jack_load -i 5555 mod-host`) |
| plugin-hostd | yes, x86_64 | this branch's tip built from source (0.6.0), LV2 workers = the mod-host program of the same build, CLAP worker = omx-clap-host 0.12.0 (FreeMixer RPM) |
| JACK | yes | jackd 1.9.22, dummy driver, 48000 Hz, period 256 (the V5/V4 kits' rate and period on a Pi 4, `zynthian-sys config/zynthian_envars_V5.sh:43`) |
| zynthian-ui engine classes | yes, imported | zynthian/zynthian-ui `vangelis` @ `f46b0189b616` (2026-10-19): `zynthian_engine`, `zynthian_engine_jalv_base`, `zynthian_controller`, `zynthian_lv2` are the real modules; `zyncoder` (not vendored), `pyliblo3`, `zynautoconnect` and the state manager are stubs (`tools/zynthian/test-path-b.py`) |
| ZynthianOS image | read, not booted | `2026-10-15-zynthianos-vangelis-2610-stable.img.xz` from os.zynthian.org, sha256 in `evidence/image/sha256.txt`, read without mounting by `tools/zynthian/image-inspect.sh` (debugfs) |
| arm64 userland | **no** | qemu-user-static-aarch64 was fetched but nothing of the image was executed under it; the pod has no binfmt, no root and no qemu-system. Every run above is x86_64 |
| Timing (CPU, latency, xruns) | **no** | emulation and a dummy driver give function, not timing; see OWED |

The image, read (`evidence/image/inspect.txt`): ZynthianOS Vangelis-2610.1, built 2026-10-15 from Raspberry Pi OS
trixie aarch64; Debian 13.7, 2125 packages; Python 3.13.5; jackd2 1.9.22~dfsg-4; liblilv-0-0 0.24.26; kernels
linux-image-rpi-v8 and -2712 6.18.50-1+rpt1 (no PREEMPT_RT package); zynthian-ui `b82dfccf9ba3` (8 commits behind the
pin; the patch applies to it: `git apply --check`), zynthian-sys `f5e41b3b270a`; mod-host at `/usr/local/bin/mod-host`,
jalv at `/usr/local/bin/jalv`, mod-ui under `/zynthian/zynthian-sw/mod-ui`; 262 LV2 bundles in `/usr/lib/lv2`, 50 in
`/usr/local/lib/lv2`, 297 in `/zynthian/zynthian-plugins/lv2`. The shipped `zynthian_envars.sh` leaves `SOUNDCARD_NAME`
and `JACKD_OPTIONS` empty (lines 41, 44): the card is chosen at first boot.

Images and environments (forum and site, checked 2026-10-20): there is no official x86 or VM image (os.zynthian.org
lists only Pi `.img.xz`). The routes the forum knows: a Docker build of the Pi image (thread 2499, posts 2018-12-08 to
2018-12-16); a maintainer saying official images are built in a QEMU ARM VM (thread 3569, 2019-12-20); unofficial
x86_64 attempts (thread 4983, 2020-11-16 to 2023-03-12; thread 12782, 2026-02-05/06); a desktop setup question (thread
11454). zynthian/ZynthianOS (CustomPiOS) last changed 2021-03-22 (`1f71e0b`) and needs root and loop devices; it was
not built here. zynthian-emuface last changed 2018-03-22.

Path A: mod-ui with plugin-hostd as its daemon
----------------------------------------------

Rerun: `tools/zynthian/path-a.sh <out>` (environment in its header). One session per daemon, driven by
`tools/zynthian/modui-drive.py` as the browser page drives mod-ui: two pedalboards built (caps AmpVTS + PlateX2; calf
Monosynth + gareus fil4 stereo + calf Reverb), parameters moved, bypass on and off, factory presets loaded, a user
preset saved, snapshots, transport, both pedalboards saved and loaded back. `tools/zynthian/verb-proxy.py` sits on
5555/5556 and logs every message.

- mod-ui's source sends 33 distinct verbs (`mod/host.py`, `mod/session.py`; send sites in `verbs.tsv`). The two verbs
  of the issue's count missing from `protocol/mod-host.json`, `set_midi_program_change_pedalboard_bank_channel` and
  `..._snapshot_channel`, are commented out (`mod/host.py:4735`, `:4739`): mod-ui never sends them. Every verb mod-ui
  sends is in the table.
- The session sent 135 commands of 16 verbs, the same 135 in the same order against both daemons
  (`evidence/path-a/diff.txt`: 0 unmatched). 5 replies differ:
  1. `connect system:capture_N mod-monitor:in_N` (x2): mod-host 0, plugin-hostd -902. No instance owns either port.
  2. `feature_enable aggregated-midi 1`: mod-host -202 (this pod has no mod-midi-merger internal client), plugin-hostd 0
     (no worker was running; the daemon keeps nothing of it for a later worker).
  3. `preset_load 0 file://.../spike_{a,b}_preset.ttl` (x2): mod-host 0, plugin-hostd -105. The pedalboard reload made a
     new worker, and the daemon replays only `set_bpm`, `set_bpb`, `transport`, `transport_sync` to it
     (`src/supervisor.c:100`), not the earlier `bundle_add` that told mod-host where the user preset is.
  Feedback differs too: `transport` 6 times against 1, `data_finish` 3 against 1 (one per worker).
- mod-monitor (`evidence/path-a/monitor-owner.txt`): mod-host makes the `mod-monitor` JACK client only when its own client
  is named `mod-host` (mod-host `src/effects.c:3922`). Under plugin-hostd the first LV2 worker gets that name and makes
  it; when that one instance is removed, mod-monitor goes and `connect ... mod-monitor:in_1` answers -205. mod-ui
  routes a pedalboard's output through mod-monitor, so the output path hangs on whichever plugin was added first.
- Every verb once (`tools/zynthian/verb-probe.py`, `evidence/path-a/probe.tsv`, 37 lines): with one LV2 instance the
  daemon's replies equal mod-host's on all 37.
- CLAP: the session replayed with each LV2 add turned into omx-comp (`evidence/path-a/clap-replay.tsv`) and the probe on
  a CLAP worker. omx-clap-host answers add, remove, bypass, transport, transport_sync, state_save, cpu_load; param_set
  with mod-ui's LV2 symbols is -103 (40 of 40), connect with mod-ui's port names -205 (22 of 24), presets, bundles,
  MIDI/CV maps, monitor_midi_program, state_tmpdir, output_data_ready are -902, state_load -105. A CLAP plugin cannot
  appear in mod-ui at all today: mod-ui lists plugins and their ports from lilv.
- The fixes, smallest first, and where: `verbs.tsv`, last column. On plugin-hostd: own mod-monitor; replay `bundle_add`
  and `feature_enable` to new workers; relay host-wide feedback once; jack_connect ports no instance owns. On
  omx-clap-host: symbols for parameters, presets, state_load, the -902 verbs that are only acknowledgements. On
  Zynthian's side: `mod-host.service` would start plugin-hostd instead of `jack_load -i 5555 mod-host`.

Path B: a plugind engine
------------------------

Rerun: `tools/zynthian/path-b.sh <zynthian-ui clone> <out>`. The patch adds `zyngine/zynthian_engine_plugind.py` (247
lines; `zynthian_engine_jalv.py` is 1515) and registers it as `PL` (and, with `ZYNTHIAN_PLUGIND=1`, in place of `JV`)
in `zynthian_chain_manager.py`. It subclasses `zynthian_engine_jalv_base`, so the LV2 controllers are built by the
jalv engine's own `get_lv2_controllers_dict` from lilv; CLAP controllers come from `omx-clap-scan --json`. The
engine attaches to plugin-hostd on 5555 or starts it, adds one instance per engine, reports `effect_<n>` as its JACK
client, maps the jalv command lines (`symbol=value`, `preset <uri>`) to `param_set`/`preset_load`, takes meters from
`output_set` feedback (acknowledging `data_finish` as mod-ui does), lists LV2 presets from lilv and CLAP presets with
`preset_list`/`preset_get`. MIDI channels stay with Zynthian's router: `set_midi_chan` is the jalv base's.

`evidence/path-b/test.log`, run on the patch applied to a fresh checkout of the pinned commit: 10 checks pass. Three
engines (calf Monosynth LV2, calf Compressor LV2, omx-comp CLAP) start as effect_0..2; 52 LV2 controllers (cutoff 10
.. 16000) and 11 CLAP controllers (1 = Ratio, 1 .. 20); cutoff set to 2000 reads back 2000.0, Ratio 8 reads back 8.0;
21 presets listed, Barkline loaded; note 60 on MIDI channel 1 through synth, LV2 compressor and CLAP compressor:
peak -inf dBFS before the note, -11.2 dBFS after; the LV2 compressor's meters arrive (compression 0.998, meter_in
0.095). Sabotage: with the engine's `param_set` translation removed, both control checks fail (cutoff reads 33.0,
Ratio 4.0) and the run exits 1.

What the jalv engine does that this one does not: native plugin GUIs (`jalv -s`, jalv.qt5/gtk3) and the
`minimize_autogenerated_gui` handling; Zynthian's custom widgets per plugin URL (`plugins_custom_gui`); user banks and
saving, renaming, deleting presets (`create_user_bank` .. `rename_preset`, `zynthian_engine_jalv.py:973-1170`); the
per-plugin preset cache file; `graph_path` (port index) addressing learned from jalv's `#CTR>` feedback (this engine
names ports by symbol); the per-plugin channel workarounds (Triceratops, SO-*, DSP56300,
`zynthian_engine_jalv.py:937-947`); path (file) parameters; the zynapi web-configuration class methods. Not tested
here: crash and respawn of a worker under Zynthian (the daemon's own suite covers it), the chain manager and GUI
around the engine, a real autoconnect.

plugin-qualify in Zynthian: the hook points
-------------------------------------------

All at zynthian-ui `f46b0189b616`. No verdict or qualification concept exists there today (no match for "verdict" or
"qualif").

- The plugin table: `zyngine/zynthian_lv2.py` keeps it in `engine_config.json` (`:195`, default copy `:194`), one row per
  plugin with `ID, NAME, TITLE, TYPE, CAT, ENABLED, INDEX, URL, UI, DESCR, QUALITY, COMPLEX, EDIT` (`add_engine`
  `:453-465`, `generate_engines_config_file` `:534-547`, `:610-622`). A verdict per host class is one more key there,
  filled from the data set (offer.md, precomputed qualification).
- (a) Shown in the chooser: `zyngui/zynthian_gui_engine.py` `fill_list()` `:299-329` (the row, `:314-318`) and
  `update_info()` `:224-230` / `show_details()` `:232-256`, which already render `QUALITY`/`COMPLEX` stars and `DESCR`.
- (b) Refuse or warn: `zyngui/zynthian_gui_engine.py` `select_action()` `:336-364`, before
  `modify_chain_status["engine"] = engine` (`:348`) or around `self.zyngui.modify_chain()` (`:359`).
- (c) First use: `zyngine/zynthian_chain_manager.py` `add_processor()` `:1054-1110`, after the processor is made
  (`:1089`) and before `start_engine()` (`:1100`); or `start_engine()` `:1407-1443`, the branch that instantiates an
  engine class for the first time (`:1420-1434`).
- An engine is registered in `engine2class` (`zynthian_chain_manager.py:66-88` with the patch) and, for a standalone
  one, `standalone_engine_info` (`zynthian_lv2.py:163-178`); `PD` (PureData) is the precedent.

OWED, not done here
-------------------

To be run by the operator or the desk in one sitting, on a Raspberry Pi 4 and a Raspberry Pi 5, each with the V5 kit's
card (V5 ADAC) or a HifiBerry DAC+ ADC Pro (the V4 kit's), from the image above:

1. Flash `2026-10-15-zynthianos-vangelis-2610-stable.img.xz` (sha256 `83c4078b...19b6`), boot, pick the kit in webconf,
   record `cat /zynthian/build_info.txt`, `uname -a`, `cpufreq-info -p`, `grep JACKD_OPTIONS
   /zynthian/config/zynthian_envars.sh`, `vcgencmd measure_temp; vcgencmd get_throttled`.
2. Install from the FreeMixer channel (README, Debian trixie arm64): `apt install plugin-hostd omx-clap-host
   omx-plugins-clap plugin-qualify`; record the versions (`dpkg -l | grep -E 'plugin-hostd|omx-clap|plugin-qualify'`).
3. Path A on the device: stop `mod-host.service`, start `plugin-hostd -n -p 5555` with `lv2_worker mod-host`, run
   `tools/zynthian/path-a.sh` with `MOD_HOST_SO=/usr/local/lib/jack/mod-host.so` (or where the image keeps it),
   `MOD_HOST_BIN=/usr/local/bin/mod-host`, `MODUI_DIR=/zynthian/zynthian-sw/mod-ui`,
   `MODUI_PYTHON=/zynthian/zynthian-sw/mod-ui/modui-env/bin/python`, against the real ALSA card instead of the dummy
   driver (edit `jackd` in `modui-session.sh` to Zynthian's `JACKD_OPTIONS`). Expect the same 5 differences.
4. Path B on the device: `tools/zynthian/path-b.sh /zynthian/zynthian-ui <out>` with the image's Python 3.13 and lilv;
   then the engine inside the real UI (`ZYNTHIAN_PLUGIND=1`, restart zynthian), add an LV2 and a CLAP processor
   from the chooser, play the kit's MIDI in.
5. Timing, which nothing above measured: for each board and card at Zynthian's JACK settings (48000 Hz, period 256 on
   Pi 4, 128 on Pi 5, 2 periods), `jack_iodelay` round trip on a loopback cable; `plugin-qualify --host-profile
   mod-host --rates 48000 --quanta 128,256 <the 20 plugins most used in Zynthian's default engine_config.json>` and
   the same with `--host-profile omx-clap-host` for the omx CLAP set; xruns over 10 minutes with 4 chains loaded
   (`jack_cpu_load`, `journalctl -u jack2 | grep -c xrun`) under mod-host and under plugin-hostd; the board's
   temperature and throttle flags before and after. These figures feed the precomputed qualification (offer.md).
6. A worker crash on the device: `kill -9` an LV2 worker mid-note and record the gap in audio and that the instance
   comes back (`worker_list`, `instance_info`).

salvage: none (no `origin/lane/*` branch exists in FreeMixer/plugin-hostd; `git branch -r` lists only main).
