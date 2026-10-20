The offer to Zynthian: plugin-hostd and plugin-qualify, integrated
=================================================================

A plan, written 2026-10-20 from the spike FreeMixer/plugin-hostd#124 ([spike-report.md](spike-report.md)). It is a
draft for the operator: nothing in it has been proposed to or discussed with Zynthian's maintainers yet. Every figure
names its source; what was not measured says so.

What we would propose, small first
----------------------------------

| # | Step | What Zynthian gets | Their cost | Our cost |
|---|---|---|---|---|
| 1 | Packages only | `apt install plugin-hostd omx-clap-host omx-plugins-clap plugin-qualify` from the FreeMixer channel on their OS (trixie arm64 is published: plugin-hostd 0.6.0, omx-clap-host 0.12.0, omx-plugins-clap 0.12.0, plugin-qualify 0.12.0, `https://freemixer.github.io/deb/debian/trixie/Packages`) | none; a user can try it | keep the trixie arm64 builds green (CI already installs on Debian 12 and 13, both architectures: `docs/own-host.md`) |
| 2 | MOD-UI with plugin-hostd as its daemon (Path A) | a crashing LV2 plugin takes down only its own worker, not mod-host and the whole pedalboard | a switch in `etc/systemd/mod-host.service` (line 17 runs `jack_load -i 5555 mod-host`): start `plugin-hostd -p 5555` instead | the plugin-hostd fixes of `verbs.tsv`: own `mod-monitor`, replay `bundle_add` and `feature_enable` to new workers, relay host-wide feedback once, connect ports no instance owns; then the same session diff with 0 differences |
| 3 | The plugind engine (Path B) | LV2 and CLAP plugins in chains, each in a worker that is respawned; CLAP plugins (omx set) on Zynthian | review and merge of one engine file (247 lines) and 9 lines of registry (`zynthian_engine_plugind.patch`), opt-in by `ZYNTHIAN_PLUGIND=1` | keep the patch current with `vangelis`; the jalv features it lacks (spike-report, Path B) one by one, if they want them |
| 4 | A verdict in the chooser | per plugin, for their board and card: suitable / conditional / unsuitable, with the conditions it was measured under | a `VERDICT` key per plugin row (`zynthian_lv2.py` engine_config.json) and its display in `zynthian_gui_engine.py` (`fill_list` `:299-329`, `show_details` `:232-256`) | the data set (below), signed, per image release |
| 5 | Warn or refuse an unsuitable plugin; qualify a plugin the data set does not know at first use | a plugin that will xrun on this board says so before it is in a chain | the hooks in `select_action` (`zynthian_gui_engine.py:336-364`) and `add_processor` (`zynthian_chain_manager.py:1054-1110`) | `plugin-qualify` as the first-use step, its run time on a Pi measured (OWED) |
| 6 | CLAP behind MOD-UI | omx CLAP plugins in pedalboards | none beyond step 2, if mod-ui learns CLAP from an LV2 description we generate | an LV2 description per CLAP plugin (or mod-ui support), and the omx-clap-host verbs of `verbs.tsv` (param symbols, presets, state) |

Licences: plugin-hostd, omx-clap-host, omx-plugins-clap and plugin-qualify are GPL-3.0-or-later (`COPYING`, the SPDX
lines of the sources); zynthian-ui is GPL-3.0 or later ("either version 3 of the License, or any later version", in
each file's header, e.g. `zyngine/zynthian_engine.py`); the patch carries the same header. Both sides are
GPL-3.0-or-later.

Packaging for their OS: the image is Raspberry Pi OS trixie aarch64 (ZynthianOS Vangelis-2610.1, Debian 13.7, Python
3.13.5: `evidence/image/inspect.txt`), not bookworm; the previous stable series (oram) was bookworm. We publish both
(`deb/debian/bookworm` and `deb/debian/trixie`, amd64 and arm64). mod-host is not in our channel: Zynthian builds it
from moddevices/mod-host at HEAD (`zynthian-sys scripts/recipes/install_mod-host.sh:13`) into `/usr/local/bin`, which
is what plugin-hostd's LV2 workers use. Their image would add our channel's key and list (README, Install) in
`zynthian-sys` setup scripts, or carry the packages in their own `packages/` area on os.zynthian.org.

What we need from their maintainers: which of steps 1-6 they want at all; who reviews an engine patch; whether a
systemd switch for mod-host (step 2) is acceptable or they prefer our package to ship a drop-in; their list of the
plugins enabled by default per kit (the data set's scope); a Pi 4 and a Pi 5 with the V5 kit to measure on, or runs
on theirs with our commands (OWED in the spike report).

Open questions for them:

1. Is the MOD-UI engine still in use enough to be worth step 2, or is Path B (chains) the only one that matters?
2. Do they want CLAP plugins in the chooser, and from which source (our omx set, others)?
3. Should a verdict hide an unsuitable plugin, mark it, or only warn when chosen?
4. Would they ship a signed data set in the image, and whose key do they trust for it?
5. Is a first-use qualification run of tens of seconds acceptable when a user picks an unknown plugin?
6. Do they pin mod-host to a commit for a release (the sha line in `install_mod-host.sh:9` is commented out)? A verdict
   is measured against one worker build.

Precomputed qualification
-------------------------

Zynthian runs on few machines: a Raspberry Pi, a kit card, Zynthian's JACK settings. So the verdicts can be measured
once per class and shipped; the device measures only what the data set does not know.

### (a) The matrix

zynthian-sys is cited at `f5e41b3b270a` and zynthian-webconf at `7c229b35f96f`, the commits the image carries
(`evidence/image/inspect.txt`).

| Axis | Values | Source |
|---|---|---|
| Board | Raspberry Pi 5, Pi 4 (and 400, CM4, which zynthian-sys still knows) | `zynthian-sys scripts/zynthian_envars_extended.sh:95-116`, `boot/config.txt:24` (`[cm4]`); V5 kit is Pi 5 based |
| Card | V5 ADAC (V5/V5.1 kit), HifiBerry DAC+ ADC PRO (V4 kit), Z2 ADAC; others only on demand | `zynthian-webconf lib/audio_config_handler.py:46-252` (41 presets); `zynthian-sys config/zynthian_envars_V5.sh:40`, `_V4.sh:36`, `_Z2.sh:36` |
| JACK | V5 on Pi 5: `-r 48000 -p 128 -n 2`; V5 on Pi 4, V4, Z2: `-r 48000 -p 256 -n 2`; all with `-P 70 -s -S -d alsa -d hw:sndrpihifiberry -X raw` | `config/zynthian_envars_V5_pi5.sh:43`, `_V5.sh:43`, `_V4.sh:39`, `_Z2.sh:39`; the Pi-5 variant chosen in `sbin/zynthian_autoconfig.py:177-180`; webconf's default `-p 128` on Pi 5, `-p 256` otherwise (`audio_config_handler.py:38-42`) |
| Kernel | linux-image-rpi-2712 / -v8 6.18.50-1+rpt1, not PREEMPT_RT | image `dpkg-status`; no RT kernel in `setup_system_raspioslite_64bit_trixie.sh` |
| Governor | performance, set before JACK starts | `sbin/cpu-performance.sh:3`, `etc/systemd/cpu-performance.service` |
| Clock | V5 kit overclocked ("Maximum") by default | `config/zynthian_envars_V5.sh:34`; `scripts/update_zynthian_sys.sh:195-296` |
| RT limits | rtprio 95 for audio | `etc/security/limits.d/audio.conf` |
| Memory | Pi 4 and Pi 5 at 2, 4 and 8 GB: an axis only for the plugins whose resident size the probe reports above a threshold (samplers, convolution, NAM models) | to be set from the first measured run |

Four classes cover the official kits: (Pi 5, V5 ADAC, 48000/128), (Pi 4, V5 ADAC, 48000/256), (Pi 4, HifiBerry DAC+
ADC PRO, 48000/256), (Pi 4, Z2 ADAC, 48000/256). Each verdict carries, as its test conditions: kernel version and
preempt model, governor, clock (arm_freq, over_voltage_delta), temperature and throttle flags before and after, JACK
rate, period and periods, the card, the worker (mod-host commit or omx-clap-host version).

### (b) The data file

Not a new format: plugin-qualify's qualification record, schema `plugin-qualify.qualification-record/1` (plugin-qualify
`src/qualification-record.ts:22-69`: plugin format and id, `testedVersion`, `binary`, `verdicts[]` with `host`,
`rating`, `hosting`, `reasons`, `cost[]` per rate and quantum, `measurements`, `tool`, `measuredAt`, and `probe` with
the protocol name and version, `machineClass`, `meetsProtocol`), one record per plugin and class; the data set is an
index over those records, not a format of its own. Looked up by (binary hash, board, card, rate, period): the record's
`binary` (path, `sha256` and the hash of every file of the bundle, plugin-qualify `src/probe-output.ts:135-141`)
identifies the build, so a user-built copy of the same plugin is not mistaken for the measured one.

What the record does not have yet, and the spike found Zynthian needs: board model and card are not machine-class fields
in the planned design for shared measurements (the shared class is kept to architecture, family, core band, clock band
and RT flags, so a shared figure does not identify a device); rate and period are per run. For Zynthian the lookup key
adds board and card as declared fields of the data set's index, not of the shared machine class, so nothing identifying
leaves a user's device. This is a schema question for plugin-qualify and openmixer before any file ships.

Signing: the planned opt-in sharing of measurements signs figures with a per-machine key and exports them by hand, over
no network. For an image-shipped set the signer would be whoever measures the reference classes (us, or Zynthian), the
key in the image, the set a file next to `engine_config.json`; a record that fails its signature is ignored and the
plugin is treated as unknown.

### (c) Measuring it

On real hardware only, one machine per class (the four above), at the reference measurement protocol (the one a record's
`probe.protocol` names: every declared rate and quantum, 64 warm-up and 512 measured blocks, a 1 kHz -6 dBFS stimulus,
median and p95 per sample, the optimised profile, `meetsProtocol` false disqualifies a run). The protocol's profile is
the console's; on a Pi it is Zynthian's own (performance governor, their clock), which the record carries. Emulation
gives function, not timing: qemu or an x86 run can prove the engine and the verbs, never a verdict. The hardware list is
OWED in the spike report.

Rerunning: a job that watches (1) Zynthian's default `engine_config.json` per release (the enabled plugins), (2) the
kernel package version in their image, (3) a new plugin binary hash in their plugin packages, and requeues the
affected (plugin, class) cells on the class's machine; the set is regenerated and signed per image release. The
cluster has no Pi today; the job needs one Pi per class reachable from it.

### (d) The margin policy

A verdict is plugin-qualify's rating, never a pass or fail alone: `suitable` (every dimension measured and inside its
budget), `conditional` (nothing disqualifies it, something needs attention: the issue's "risky"), `unknown` (a
dimension could not be decided: not shown as a pass), `unsuitable` (a dimension failed on measured evidence)
(plugin-qualify `src/rating.ts:13-36`). Each is shown with its conditions (class, rate, period, kernel, governor,
worker). The margin itself, the share of a period a plugin may take on a class before it is conditional, is a number
to be set from the first measured runs, not guessed here.
