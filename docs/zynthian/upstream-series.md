The upstream series: plugin-hostd in Zynthian, step by step
==========================================================

This page is the order in which the Zynthian work is offered to zynthian/zynthian-sys and zynthian/zynthian-ui, branch
`vangelis`. The forks FreeMixer/zynthian-sys and FreeMixer/zynthian-ui carry the same work in the order it was built;
here it is cut into steps a maintainer can take one at a time. Each step has a branch on the fork, a base (the
upstream tip plus the steps before it), a few commits whose messages say what, why and how it was proven, its
qualification, and its revert. A step changes nothing a user sees unless the step says so, and each can be reverted
alone (later steps build on it, so a revert takes them with it).

The plan of 2026-10-20 ([offer.md](offer.md)) and the spike ([spike-report.md](spike-report.md)) are the reasons; this
page is the patches. Benchmarks and trade-offs of the Raspberry Pi 5 run of 2026-10-28 are in
[benchmarks.md](benchmarks.md) and [tradeoffs.md](tradeoffs.md), and the instruments proof is in
[instruments.md](instruments.md) (each written in a lane of its own and linked here before it lands); this page cites
them and repeats none of their figures beyond the totals.

Bases: zynthian/zynthian-sys `vangelis` at `50e151022f24`, zynthian/zynthian-ui `vangelis` at `f43b7da59eb4`
(2026-10-28). Every commit is signed. No step has been offered upstream except step 1.

| Step | Title | Repo | Branch on the fork | Base | Commits | Qualification | Upstream |
|---|---|---|---|---|---|---|---|
| 1 | mod-ui recipe on Python 3.13 | sys | `modui-python313-upstream` | `0774a585a` (older vangelis) | 1 | bash -n | open, zynthian/zynthian-sys#228 |
| 2 | OpenMixer repository, plugin-hostd installed, not enabled | sys | `upstream/02-openmixer-repo` | `50e1510` + 1 | 1 (+1 merge) | bash -n, shellcheck: pass; install on a device owed | not yet |
| 3 | plugin-hostd as MOD-UI's mod-host, switchable, off | sys | `upstream/03-modhost-backend` | 2 | 2 | ready check 0 failed; MOD-UI session diff: 135 calls, 5 replies differ (spike run); backend check on the device owed | not yet |
| 4 | The plugin-hostd engine (PH), not the default | ui | `upstream/04-plugin-hostd-engine` | `f43b7da5` (needs sys 3 on the device) | 2 | pytest 82 passed, 1 skipped; chain round trip (spike engine) | not yet |
| 5 | Qualification records and pins; unsuitable plugins stay on jalv | sys + ui | `upstream/05-qualification` (both) | sys 3; ui 4 | 1 + 1 | sys container check 80/80; pytest 124 passed; sync on the device owed | not yet |
| 5a | Plugin menus sort and show the qualification figures (latency, RT safety, cost) | ui | left to its lane (FreeMixer/zynthian-ui#16) | 5 | - | in progress | not yet |
| 6 | The engine is the default for LV2 instruments and effects | ui + sys | `upstream/06-engine-default` (both) | ui 5; sys 5 | 1 + 1 | pytest 133 passed; sys container check 91/91; device walk owed | not yet |
| 7 | CLAP plugins through the engine | ui + sys | `upstream/07-clap` (both) | ui 6; sys 6 | 1 + 1 | pytest 136 passed; sys container check 96/96 | not yet |
| 7a | Instruments through the engine: MIDI in, polyphony, MPE, Surge XT | ui | left to its lane (plugin-hostd `lane/zynthian-instruments`) | 7 | - | in progress ([instruments.md](instruments.md)) | not yet |
| 8 | MOD GUIs and LV2 complements from omx-panel | sys | `upstream/08-modgui` | sys 7 | 1 | sys container check 110/110 with omx-panel 0.6.0; GUIs on the device owed | not yet |
| 9 | Chain cost estimate before an insert | ui | none: plan only (FreeMixer/zynthian-ui#13) | 6 | - | - | not yet |

"sys" is zynthian-sys, "ui" zynthian-ui. A ui step needs the sys steps before it on the device: the engine of step 4
starts its daemon with step 3's `sbin/plugin-hostd-start.sh`, and step 5's menus read the records step 5's sync
writes.

Three words recur from step 5 on. Qualification puts each plugin in one class, measured on the device:
**suitable** (runs in-process and may share a worker with others), **isolated** (runs, but is not real-time safe: it
gets a worker of its own and is never grouped with real-time safe plugins) and **unsuitable** (it crashed, hung or
failed to load; its pin is refused and it is not loaded by plugin-hostd). No plugin is unsuitable for real-time
safety alone. The class names are plugin-qualify's (FreeMixer/plugin-qualify#196); the planner rule that keeps an
isolated plugin apart is plugin-hostd's (FreeMixer/plugin-hostd#231).

How the branches were made
--------------------------

Each step was rebuilt on the current upstream tip from the fork's commits, mapped below, and squashed into commits a
reviewer reads once: fix-ups of earlier fork commits are folded into the commit they fix, and each commit message ends
with the fork commits it carries (`cherry picked from commit ...`). Where a fork commit did two steps' work, the step
takes only its part; the differences from the fork are stated in the step. Two fork changes are not in the series:

- `3339416` made plugin-hostd MOD-UI's default mod-host. In the series MOD-UI stays on `jack_load` unless the user
  switches (step 3); proposing that default is a decision for after step 3 has been used.
- `a8b3e05` pointed the setup scripts at the forks' repositories. Upstream takes its own.

The fork's commit `2a47105` (step 1 in the fork) has the same content as step 1's branch, which is kept as it is
because it is an open pull request. Step 2's branch merges the upstream tip into it, so the series applies in order;
the merge drops out once #228 is merged.

Fork commits by step. zynthian-sys: `2a47105` 1; `446762e` 2; `15d6db6`, `a132abc`, `637112b`, `b8754a3` 3; `67fc69a`,
`0c5f757`, `a8b3e05` (the qualification part), `da66f46`, `8f06f7d`, `fc60d02`, `4a0aed9` 5; `3339416` (the UI engine
variable), `a43c758`, `a8b3e05` (the envars part) 6; `3f12b4b`, `1ce2158`, `edd83ca`, `e7499ec`, `17aa757`, `62eaa9f`
8. zynthian-ui: `4478038c`, `7193e482`, `14524708`, `6fe50a36`, `daef29b0`, `89849333`, `c516a835`, `e6dfb61c`,
`e23798c5`, `70f69bce`, `76ee70c0`, `23705a83`, `b8f1fa05`, `ea042550`, `10532849`, `da3ce7a1`, `af1fb0be` (the
switch) 4; `b3e6e6f8`, `d2e5b090`, `e8d880d0` 5; `af1fb0be` (the default), `951f8e3e`, `95eaeaeb` 6; `4478038c` (the
CLAP scan) 7.

Device proofs and captures
--------------------------

Each step lists what it proves without the device (run for this page, results below) and what only the device can
prove. The device is a Raspberry Pi 5 with ZynthianOS Vangelis-2610.1 ([evidence/image/inspect.txt](evidence/image/inspect.txt)).
Screen captures go to `evidence/series/<step>/` under the names given in each step; they are owed: they need a root
login on the device, which this run did not have. Each is taken the same way:

    # the touchscreen UI, on the device (zynthian.service draws on X display :0)
    DISPLAY=:0 xwd -root -silent | convert xwd:- png:- > /tmp/<name>.png
    # a MOD-UI page, from a machine on the same network
    chromium --headless --window-size=1280,800 --screenshot=<name>.png http://zynthian.local:8888/

A capture is taken with the UI's own menus, adding and removing a test chain, and leaves the device's chains as they
were. Figures come from [tools/zynthian/series-figures.py](../../tools/zynthian/series-figures.py), which draws them
from the measurement files (`--check` fails when a committed figure no longer matches its data).

Step 1: mod-ui recipe on Python 3.13
------------------------------------

Repo zynthian-sys, branch `modui-python313-upstream`, base `0774a585a`. Commit: `5f02fee` install_mod-ui.sh: works
on Python 3.13 (trixie).

**Why.** On a Vangelis-2610.1 image (trixie, Python 3.13) MOD-UI does not start: its private environment points at
`/usr/bin/python3.11`, which trixie does not have, and `pip install -r requirements.txt` stops on pycrypto, which does
not build on 3.13. A user who picks the MOD-UI engine gets nothing.

**What changes for a user.** Running `install_mod-ui.sh` on a trixie image builds MOD-UI's environment on the
interpreter the image has (pycryptodome for pycrypto, the ssl backport), and MOD-UI starts. Nothing else changes.

**Qualification.** `bash -n` passes. The pull request reports the recipe run on a Pi with trixie and MOD-UI coming
up.

**How to use it in Zynthian.** As root: `$ZYNTHIAN_RECIPE_DIR/install_mod-ui.sh`, then pick MOD-UI in the UI's engine
list; MOD-UI's page opens at `http://zynthian.local:8888/`. Capture owed: `01-modui-recipe/modui-page.png` (MOD-UI's
pedalboard page, served by the rebuilt environment).

**What can go wrong; revert.** A pip mirror without one of the pinned wheels stops the recipe; it changes nothing
installed before it. Revert the commit and the recipe builds as before.

**Upstream.** Open: zynthian/zynthian-sys#228.

Step 2: the OpenMixer repository and plugin-hostd, installed, not enabled
-------------------------------------------------------------------------

Repo zynthian-sys, branch `upstream/02-openmixer-repo`, base `50e1510` + step 1 (merge `1f2a866`). Commit: `24f8791`
Add the OpenMixer repository and install plugin-hostd, not enabled.

**Why.** The steps after this one run plugins in plugin-hostd, which keeps each plugin in a worker process of its own
so a crashing plugin does not take mod-host and every other plugin with it. They need the package on the image first,
from a signed repository, without changing what runs.

**What changes for a user.** Nothing visible. The setup scripts install `openmixer-release` (the signing key and the
apt source of the running Debian release) and run the new recipe `scripts/recipes/install_openmixer.sh`, which
installs `plugin-hostd` and `omx-clap-host` (the program its workers run CLAP plugins and its LV2 adapter in);
`update_system_image.sh` keeps them current. No service is enabled; mod-host, MOD-UI, jalv and the menus are as
before. The fork's commit installed omx-plugins and omx-panel here too; they move to steps 7 and 8, where they are
used, so this step changes no menu (omx-plugins brings LV2 plugins that jalv would list).

**Qualification.** `bash -n` on every changed script and shellcheck on the new recipe: pass, no finding. Owed on the
device: the recipe run twice, the second a no-op, and `systemctl list-units` unchanged.

**How to use it in Zynthian.** On a running Zynthian, as root: `$ZYNTHIAN_RECIPE_DIR/install_openmixer.sh`. After the
next boot nothing is different; `plugin-hostd --version` answers. No capture: no screen changes.

**What can go wrong; revert.** No network at setup time: the recipe says so and the next run tries again. An
architecture other than arm64 or amd64 is skipped with a message. Revert the commit; the packages stay installed and
unused, or `apt remove plugin-hostd omx-clap-host`.

**Upstream.** Not yet.

Step 3: plugin-hostd as the mod-host of the MOD-UI engine, switchable, off by default
-------------------------------------------------------------------------------------

Repo zynthian-sys, branch `upstream/03-modhost-backend`, base step 2 (`24f8791`). Commits: `61190a3` plugin-hostd as
the mod-host of the MOD-UI engine, switchable, off by default; `01f2a62` plugin-hostd-start.sh: one script starts a
plugin-hostd and waits until it is ready.

**Why.** With `jack_load`, every MOD-UI plugin runs inside JACK's process: one plugin that crashes takes mod-host and
the whole pedalboard with it. plugin-hostd answers the mod-host protocol on the same port and runs each plugin in a
worker of its own, so a crash costs that plugin only. The user should be able to try that with one setting and go
back with the same setting.

**What changes for a user.** Nothing until they switch. `ZYNTHIAN_MODHOST_BACKEND` (default `jack_load`) picks what
answers MOD-UI on port 5555; `mod-host.service` keeps its name and runs `sbin/mod-host-backend.sh`, which starts one
backend and removes the other. `sbin/set_modhost_backend.sh plugin-hostd` switches and restarts MOD-UI if it ran.
`sbin/plugin-hostd-start.sh` is the one place a plugin-hostd is started, and it waits for the ready line the daemon
declares in its own protocol file rather than for the port.

**Qualification.**

- `tests/plugin-hostd-ready-check.sh` (no device, a stand-in daemon that opens no port): 0 failed. It also fails a
  wrong line, a silent daemon and a missing protocol file.
- MOD-UI's verbs on both backends, from the spike's recorded session ([evidence/path-a/diff.txt](evidence/path-a/diff.txt),
  [verbs.tsv](verbs.tsv)): 135 calls over 16 verbs, 5 replies differ: two `connect` to `mod-monitor` (plugin-hostd
  had no mod-monitor client), one `feature_enable aggregated-midi` (mod-host -202, plugin-hostd 0) and two
  `preset_load` of a preset file (-105). Figure:
  [evidence/series/03-modhost-backend/verb-replies.svg](evidence/series/03-modhost-backend/verb-replies.svg), one
  bar per verb, the differing replies dark. That session ran plugin-hostd of the spike; the same session on the
  current release (`tools/zynthian/path-a.sh`) is owed, and [benchmarks.md](benchmarks.md) carries the verb diff of
  the 2026-10-28 run.
- Owed on the device: `tests/modhost-backend-check.sh` (root, JACK running, mod-ui and mod-host stopped): add,
  `param_set`, `param_get` and remove of one CLAP and one LV2 plugin over port 5555, no process or JACK client left.

**How to use it in Zynthian.** As root: `/zynthian/zynthian-sys/sbin/set_modhost_backend.sh plugin-hostd`, then open
MOD-UI and load a pedalboard; it plays as before, and `jack_lsp` lists one `effect_<n>` client per plugin. Going back:
the same command with `jack_load`. Captures owed: `03-modhost-backend/modui-jack_load.png` and
`03-modhost-backend/modui-plugin-hostd.png`, the same pedalboard in MOD-UI on each backend (the reader should see the
same page).

**What can go wrong; revert.** The five differing replies above: a pedalboard that routes through mod-monitor, or
loads a preset file, behaves differently on plugin-hostd until those are fixed in plugin-hostd. A daemon that never
prints its ready line fails the unit after `TimeoutStartSec=20`. Revert: set
`jack_load`, or revert the two commits.

**Upstream.** Not yet.

Step 4: the plugin-hostd engine (PH), not the default
-----------------------------------------------------

Repo zynthian-ui, branch `upstream/04-plugin-hostd-engine`, base `f43b7da5`; on the device it needs zynthian-sys
step 3. Commits: `d7c5352c` Add the plugin-hostd engine (PH), not the default; `3135deb0` processor options: a
Grouping entry tells why a PH plugin runs alone.

**Why.** jalv runs one process and one JACK client per plugin, so a chain of n plugins is n clients, and nothing
keeps a crashing plugin's process from taking its chain's sound with it. plugin-hostd can run a chain's plugins in one
worker and one client and restarts a lost worker. A user should be able to try it per device without anyone's menus
changing.

**What changes for a user.** Nothing until they set `ZYNTHIAN_PLUGIN_ENGINE=plugin-hostd`. Then each LV2 instrument
and effect is offered through plugin-hostd ("Name (PH)") instead of jalv; MIDI tools stay with jalv. The engine
starts one daemon per Zynthian on port 5570 with step 3's script, reads the daemon's reply codes from the files it
ships (a missing file is one clear refusal), declares each chain to the daemon's planner, which says what runs
together, brings a lost daemon back with every instance's preset and values, and builds its controller pages from
omx-panel's layout of the plugin descriptor when omx-panel is installed (step 8 installs it; `apt install omx-panel`
before that). A processor that runs alone has a "Grouping" entry in its options saying why. Snapshots holding PH
processors load whatever the setting. Differences from the fork: the fork made plugin-hostd the default and listed
CLAP plugins here; in the series those are steps 6 and 7. The engine's CLAP code paths (parameters by number, chain
clients on the clap rows) are in this step because its chain tests use CLAP members.

**Qualification.** `python3 -m pytest tests` at the branch tip: 82 passed, 1 skipped (the first commit alone: 79
passed, 1 skipped). They drive the engine against a fake daemon speaking the protocol from the shipped files: start,
reuse, restart and replay, parameters, presets, state, the chain and plan verbs, JACK client names, pages, the
protocol-file refusals, and the menu switch; with the default changed to plugin-hostd, three of them fail. The chain
round trip through plugin-hostd's chain verb, with a fault plugin killed mid-chain, passes in CI with the spike's
engine ([evidence/chain/round-trip-channel.txt](evidence/chain/round-trip-channel.txt), [chain-profile.md](chain-profile.md));
the Pi 5 chain round trip of 2026-10-28 is in [benchmarks.md](benchmarks.md). Owed on the device: the walk below
with this engine.

**How to use it in Zynthian.** Set `ZYNTHIAN_PLUGIN_ENGINE=plugin-hostd` in `/zynthian/config/zynthian_envars.sh`
and restart the UI. Add an audio effect to a chain: the effect list now shows "(PH)"
entries. Select one and turn a knob: the plugin follows. Captures owed: `04-plugin-hostd-engine/effect-list-jalv.png`
and `04-plugin-hostd-engine/effect-list-ph.png` (the same category before and after the setting),
`04-plugin-hostd-engine/pages-ph.png` (a plugin's controller pages in the engine) beside
`08-modgui/modgui.png` (the same plugin's MOD GUI): both come from omx-panel's one layout of the plugin's descriptor.
The device carries only the OpenMixer packages plugin-hostd, omx-clap-host, omx-panel, omx-plugins and plugin-qualify,
no OpenMixer console; the listing that shows it (`dpkg -l | grep -E 'omx|openmixer|plugin-'`) is owed with the
captures.

**What can go wrong; revert.** A daemon the start script cannot start: the engine logs the reason and adds nothing;
jalv entries are untouched. An LV2 feature jalv has and the engine lacks ([engine-gaps.md](engine-gaps.md)) shows on
that plugin only. Revert: unset the variable, or revert the two commits.

**Upstream.** Not yet.

Step 5: qualification records and pins; unsuitable plugins stay on jalv
-----------------------------------------------------------------------

Repos zynthian-sys and zynthian-ui, branch `upstream/05-qualification` in each. sys base step 3 (`01f2a62`); ui base
step 4 (`3135deb0`). Commits: sys `70f730e` Plugin qualification: plugin-qualify, its sync, and plugin-hostd's pins;
ui `c92903ff` Plugin menus from qualification records; unsuitable plugins stay on jalv.

**Why.** A Zynthian holds hundreds of LV2 plugins and nothing in the menu says which are safe to play live on this
board. plugin-hostd can group plugins into one worker only if it knows, for this device, which class each is in:
suitable, isolated or unsuitable. A plugin that crashes on load should not be offered through a host that cannot run
it, and should not vanish either.

**What changes for a user.** sys: `install_openmixer.sh` installs plugin-qualify and, once, enables
`plugin-qualify-sync.timer` (two minutes after boot, lowest CPU and disk priority) and `.path` (a plugin directory
changed) over Zynthian's plugin directories (`/etc/omx/qualify.conf`), and sets `require_pins 1` with
`pin_mode first-use` in `/zynthian/config/plugin-hostd.conf`: a plugin the sync has not reached yet still loads, in a
worker of its own. `$ZYNTHIAN_MY_DATA_DIR/plugins/lv2` joins `LV2_PATH`. Each step is done once and recorded, so a
setting changed by hand stays and a package removed by hand is not installed again; `update_zynthian_sys.sh` runs the
recipe, so an existing device gets the same. `scripts/omx_prequalify_image.sh` lets an image builder ship an image
already qualified (arm64 hardware only). ui: with plugin-hostd as the plugin engine, the menus put suitable plugins
first, tagged with what was measured ("live · 1.2 ms · RT"), then the others; an isolated plugin is listed, tagged
"not RT"; an unsuitable one is offered once, through jalv, tagged, and its PH entry stays out; one that crashed or
hung is hidden (shown greyed with `ZYNTHIAN_PLUGIN_SHOW_HIDDEN=1`). With jalv as the plugin engine, the default
until step 6, the menus are untouched. Difference from the fork: the fork's recipe installed each package only on its
first run; the series records each package, so a package a later step adds is installed on the next update, and a
removed package no longer reports a version.

**Qualification.** sys: `tests/default-install-check.sh` in a trixie container with the packages (`podman run ...`,
the command is in the script's header): 80/80. An existing Zynthian (require_pins 0, sync off) and a new image end in
the same state, a second update changes nothing, a choice made by hand stays, a removed package stays removed, the
image hook refuses amd64 and on stubbed arm64 qualifies one CLAP. ui: `python3 -m pytest tests`: 124 passed, 1
skipped (the tier table row by row, real Pi 5 records as fixtures, the engine screen's own code over fixture records,
jalv leaving the menu untouched, unsuitable plugins on jalv). The 2026-10-28 run on the Pi 5 wrote 1823 plugin
records; [benchmarks.md](benchmarks.md) counts them by class and [tradeoffs.md](tradeoffs.md) says what each class
costs. Owed on the device: the first-boot sync's duration and `systemctl status plugin-qualify-sync`.

**How to use it in Zynthian.** After `update_zynthian_sys.sh` (or the recipe), reboot and wait for the first sync
(it runs at low priority; `journalctl -u plugin-qualify-sync` says when it is done). With plugin-hostd as the plugin
engine, open a chain's "add audio effect" list: entries carry their tag and the live ones come first. Captures owed:
`05-qualification/effect-list-tagged.png` (the tags and the order) and `05-qualification/effect-list-unsuitable-on-jalv.png`
(an unsuitable plugin listed once, without "(PH)", tagged).

**What can go wrong; revert.** The first sync on a fresh image takes a long time (every plugin is loaded and
measured); until then plugins load first-use, in a worker of their own. A plugin whose files change is refused by
plugin-hostd until the next sync qualifies it again. Revert: `systemctl disable --now plugin-qualify-sync.timer
plugin-qualify-sync.path` and `require_pins 0` (README), or revert the two commits.

**Upstream.** Not yet.

Step 5a: plugin menus sort and show the qualification figures (latency, RT safety, cost)
---------------------------------------------------------------------------------------

Repo zynthian-ui. In progress in its own lane: issue FreeMixer/zynthian-ui#15, pull request FreeMixer/zynthian-ui#16.
Base: step 5. Its branch is that lane's; it joins the series once rebased on `upstream/05-qualification`.

**Why.** The tags of step 5 say the class and one latency; a musician choosing between two reverbs wants the figures
side by side and the list sorted by the one that matters to them.

**Qualification, how to use it, revert.** Written by that lane in its pull request; this page takes them when it
lands.

Step 6: the engine is the default for LV2 instruments and effects
-----------------------------------------------------------------

Repos zynthian-ui and zynthian-sys, branch `upstream/06-engine-default` in each. ui base step 5 (`c92903ff`); sys
base step 5 (`70f730e`). Commits: ui `f0893e7b` plugin-hostd is the default engine for LV2 instruments and effects;
sys `b5de40b` zynthian_envars.sh: plugin-hostd as the UI's plugin engine by default.

**Why.** Steps 4 and 5 let a user opt in, and make the opt-in safe: what the host cannot run stays on jalv, and what
it can only run alone is kept apart. Once that has been used, a new user should get it without editing a file.

**What changes for a user.** With `ZYNTHIAN_PLUGIN_ENGINE` unset, the menus offer each LV2 instrument and effect
through plugin-hostd. A suitable plugin may share a worker; an isolated one runs in plugin-hostd in a worker of its
own, never grouped with real-time safe ones; only an unsuitable one stays on jalv. MIDI tools stay with jalv.
`zynthian_envars.sh` declares `ZYNTHIAN_PLUGIN_ENGINE="plugin-hostd"` and `ZYNTHIAN_PLUGIN_HOSTD_PORT="5570"`; an
existing config gets the variable once and a config that names an engine is left as it is. MOD-UI's backend stays
`jack_load`. Saved chains with jalv processors load as saved; `tools/convert_snapshots_to_ph.py`, run once by hand,
writes a plugin-hostd copy of a snapshot beside it (`foo.ph.zss`), leaving unsuitable plugins on jalv.

**Qualification.** ui: `python3 -m pytest tests`: 133 passed, 1 skipped: the default, the switch back, an unknown
value, plugin-hostd not installed, the converter over fixture snapshots, an isolated plugin offered through
plugin-hostd (`test_plugin_engine_default`) and run there as a segment, worker and JACK client of its own
(`test_engine_plugin_hostd`, `test_plan`). sys: `tests/default-install-check.sh`: 91/91; with the line that sets the
variable removed, two checks fail. Owed on the device: an isolated plugin added from the menu and `worker_list`
showing it in a worker of its own; the chain round trip and the jalv comparison of the 2026-10-28 run are in
[benchmarks.md](benchmarks.md).

**How to use it in Zynthian.** After the update, restart the UI (the recipe's report says so). Add an instrument
chain: the instrument list shows the "(PH)" entries in place of jalv's; play it. To go back:
`ZYNTHIAN_PLUGIN_ENGINE="jalv"` and restart. Captures owed: `06-engine-default/synth-list.png` (the instrument list
by default), `06-engine-default/processor-options-grouping.png` (an isolated plugin's "Grouping" entry: "Not grouped:
it was qualified to run isolated").

**What can go wrong; revert.** A plugin that behaves differently in plugin-hostd than in jalv ([engine-gaps.md](engine-gaps.md));
the user converts per snapshot, so a show file stays on jalv until they choose. Revert: `ZYNTHIAN_PLUGIN_ENGINE=jalv`,
or revert the two commits.

**Upstream.** Not yet.

Step 7: CLAP plugins through the engine
---------------------------------------

Repos zynthian-ui and zynthian-sys, branch `upstream/07-clap` in each. ui base step 6 (`f0893e7b`); sys base step 6
(`b5de40b`). Commits: ui `245d0db0` plugin-hostd engine: offer the CLAP plugins omx-clap-scan finds; sys `898d637`
install_openmixer.sh: install omx-plugins, the CLAP and LV2 effects.

**Why.** Zynthian runs no CLAP plugin today. The 2026-10-28 run on the Pi 5 counted 494 CLAP plugin records; the
engine already runs them.

**What changes for a user.** The menus list the CLAP instruments and effects on the device ("Name (PH)"), from
omx-clap-scan over `CLAP_PATH`, `~/.clap`, `/usr/lib/clap` and `/usr/local/lib/clap`, kept in
`/zynthian/config/plugin-hostd-clap.json` until a directory changes (the scan loads every plugin). An entry is keyed
by its pin URI `clap:<file>#<id>`, since DPF-built files share one CLAP id; a parameter is addressed by its CLAP
number. The recipe installs omx-plugins (OpenMixer's effects, CLAP and LV2). With jalv as the plugin engine the menus
stay as they were.

**Qualification.** ui: `python3 -m pytest tests`: 136 passed, 1 skipped: the default catalogue offers what a stand-in
omx-clap-scan prints, the scan is cached until a directory changes, no scanner means no CLAP entries; with the scan
turned off one fails. sys: `tests/default-install-check.sh`: 96/96, including omx-plugins installed on its first run
over an existing install. Owed on the device: a CLAP effect in a chain with a knob moving it; the spike's path-b run
moved a CLAP control through the engine of its time ([evidence/path-b/test.log](evidence/path-b/test.log)).

**How to use it in Zynthian.** Add an audio effect: CLAP plugins appear in their category with "(PH)", the category
taken from the plugin's CLAP features. Capture owed: `07-clap/effect-list-clap.png`.

**What can go wrong; revert.** The first scan after install loads every CLAP file, which takes time at the first UI
start; a plugin that crashes the scan is left out and logged. Revert the two commits; `apt remove omx-plugins`.

**Upstream.** Not yet.

Step 7a: instruments through the engine: MIDI in, polyphony, MPE, Surge XT
--------------------------------------------------------------------------

Repo zynthian-ui. In progress in its own lane (plugin-hostd branch `lane/zynthian-instruments`); its branch on the
fork is that lane's. Base: step 7.

**Why.** Zynthian is used for instruments first. An engine that runs effects well and instruments badly is not one a
Zynthian user can take.

**Qualification.** The device proof that lane is producing, [instruments.md](instruments.md): Surge XT (CLAP) on the
Pi 5, notes, polyphony and CPU per core, velocity, CC, pitch bend, sustain, all-notes-off, a capture of the engine's
pages, and the same patch on jalv for comparison. Known gaps: CLAP voices run on one core today (the CLAP thread
pool, FreeMixer/omx-clap-core#395, in progress); Surge's own GUI only over VNC; modulation-path assignment
(FreeMixer/omx-clap-core#327).

Step 8: MOD GUIs and LV2 complements from omx-panel
---------------------------------------------------

Repo zynthian-sys, branch `upstream/08-modgui`, base step 7 (`898d637`). Commit: `ee69a22` MOD GUIs and LV2
complements from omx-panel for plugins that ship none.

**Why.** MOD-UI draws a plugin with the MOD GUI the plugin ships; many LV2 plugins on a Zynthian ship none and get
MOD-UI's generic rendering. The descriptor that gives the touchscreen its controller pages (step 4) can give MOD-UI a
panel too, so both show one layout.

**What changes for a user.** The recipe installs omx-panel; `update_zynthian_sys.sh` enables its two units, which the
package installs and never enables: `omx-modgui-sync` (a MOD GUI per LV2 plugin that ships none, each a bundle of its
own in `/usr/local/lib/lv2` whose manifest declares no plugin, so the plugin's bundle is never touched) and
`omx-complement-sync` (LV2 port-group complements for plugins that declare none). Both run at boot and after every
qualification sync, at the lowest priority, with Zynthian's `LV2_PATH` from a drop-in. MOD-UI shows new GUIs at its
next start. Difference from the fork: the fork added its own drop-in queuing the GUI sync after the qualification
sync; omx-panel 0.6.0 ships that drop-in itself, so the series has none. The complement sync, unreleased when the
fork's commits were written, is in omx-panel 0.6.0 and is enabled here.

**Qualification.** `tests/default-install-check.sh` in a trixie container with omx-panel 0.6.0: 110/110 (both units
enabled with Zynthian's `LV2_PATH`, queued by the package's drop-ins, a second update changing nothing). The GUIs
themselves are tested in omx-panel against a real lilv world. Owed on the device: `omx-modgui-sync --check` and a
generated GUI in MOD-UI.

**How to use it in Zynthian.** After the update and a reboot, open MOD-UI and add a plugin that ships no MOD GUI: it
shows omx-panel's panel. Captures owed: `08-modgui/modgui-before.png` and `08-modgui/modgui.png` (the same plugin
without and with the generated GUI), and `08-modgui/modgui.png` beside `04-plugin-hostd-engine/pages-ph.png`: one
layout, two screens.

**What can go wrong; revert.** An omx-panel older than 0.6.0 lacks the units: the update says so and names the
command that upgrades it. A plugin that cannot get a GUI is named in the sync's summary and keeps MOD-UI's rendering.
Revert: `systemctl disable omx-modgui-sync omx-complement-sync`, or revert the commit.

**Upstream.** Not yet.

Step 9: chain cost estimate before an insert (plan only)
--------------------------------------------------------

Repo zynthian-ui. No branch: the work is FreeMixer/zynthian-ui#13. Base: step 6.

**Why.** On a Pi, the plugin that breaks a chain is the one added last. The chain editor can ask plugin-hostd what a
chain with the new plugin would cost (latency, CPU, RAM) from the qualification records before the insert, and
recommend, warn or refuse.

**Plan.** The question goes to the daemon's planner, which already answers `plan` and `plan_get` (step 4); a cost
query is new protocol and lands in plugin-hostd first. The menu shows the answer at the insert; a refusal names the
figure that refused it. No patch until the daemon's verb exists and is released.

Not done in this run
--------------------

- Every capture above, and every proof marked owed on the device: they need a root login on the Pi 5.
- shellcheck reports three info or style notes in the fork's own test scripts (`default-install-check.sh`,
  `plugin-hostd-ready-check.sh`), none of warning level; they are left as the fork has them.
