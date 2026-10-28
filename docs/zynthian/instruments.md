Instruments through the engine: Surge XT on the Pi 5
=====================================================

Zynthian is an instrument, and Surge XT is the instrument it is judged on: ZynthianOS Vangelis builds Surge XT from
upstream `main` (`scripts/recipes/install_surge_xt.sh` in zynthian-sys) and plays it with jalv. This page records what
plugin-hostd and omx-clap-host do with Surge XT on a Zynthian Pi 5 today: what was proven, with the numbers and the
captures, what the host still lacks, and the exact commands. Everything below was measured on 2026-10-28 between 23:15
and 23:47 UTC; the raw records are under [evidence/instruments-2026-10-29/](evidence/instruments-2026-10-29/).

Instruments: voices across the cores
------------------------------------

**Why it matters.** A Zynthian is played. When a pad patch holds 16 notes, each with its own oscillators, filters and
envelopes, every voice is computed in every audio block, and the block has a deadline: 5.3 ms at 48 kHz and 256 frames.
A Pi 5 has four cores. If one instrument computes all its voices on one core, that core sets the polyphony the Pi can
play before the first xrun, however idle the other three are.

**What a CLAP host can do about it.** The CLAP thread-pool extension (`clap.thread-pool`) lets a plugin split its
block into tasks (one per voice, or per group of voices) and ask the host to run them (`request_exec`). The host
decides where those tasks run. Today omx-clap-host runs them one after the other on the audio thread that asked
(omx-clap-core `docs/clap-compatibility.md`, row `clap.thread-pool`): correct, and on one core.
omx-clap-core#395 (in progress, branch `feat/395-thread-pool`) spreads them: N-1 real-time helper threads per
worker, N being the cores the worker may use, each pinned to its own core and parked between cycles; on
`request_exec` the tasks are handed out by one atomic counter, the audio thread takes its share, and the call returns
when the last task is done, with no allocation, lock or system call on that path.

**The gate.** The pool is not a global switch. It is given per plugin by its qualification: a plugin whose
qualification is real-time safe and that asks for the pool gets helper threads; a plugin with real-time violations is
`isolated` (plugin-qualify#196: isolated is a hosting mode, never a refusal) and keeps the serial path, in a worker of
its own. A task that allocates or locks on a helper thread would stall the other cores' deadline too, so the
measurement that admits a plugin to a shared worker is the same one that admits it to the pool.

**What Surge XT does with it: nothing.** Surge XT 1.4.0 does not take part in the thread pool. Its CLAP offers
`clap.audio-ports`, `gui`, `latency`, `note-name`, `note-ports`, `params`, `posix-fd-support`, `preset-load`,
`remote-controls`, `render`, `state`, `tail`, `timer-support`, `track-info` and `voice-info`
([scan-extensions.txt](evidence/instruments-2026-10-29/scan-extensions.txt)), and no
`clap.thread-pool`: a plugin that wants the host's pool must offer `clap_plugin_thread_pool`, and Surge's source
calls no `request_exec` (the `clap.thread-pool` string in the binary comes from the CLAP headers it bundles). None of
the 489 descriptors on the device names the thread pool either. So #395 will not spread Surge XT's voices: on the Pi
they run on one core, whatever the host does. Measured (below): one omx-clap-host thread from 3% of a core at 1 voice
to 39% at 64 voices, 48 kHz, 256 frames.

**What does use the Pi's cores for instruments.** Separate workers. plugin-hostd runs each instrument (or each
chain) in a worker process of its own, and JACK runs independent clients in parallel. Measured: four Surge XT instances
in four workers, each holding 16 notes, ran on cpu0, cpu1, cpu2 and cpu3 at 14-15% each, 64 voices in all, at a
JACK DSP load of 17.6%; one instance playing 64 voices loaded JACK at 39.7%. The single-core figure (3% at 1 voice,
10% at 16, 39% at 64) is the baseline that placement multiplies by the number of instruments. Today the kernel
places the workers; plugin-hostd#226 (chain placement policy: spread workers across the audio cores and keep the
daemon off them, not yet built) makes it the host's decision. The thread pool remains the path for the plugins that do
split their voices into tasks.

**What it costs and what it buys.** For Surge XT: placement costs one process per instrument (an omx-clap-host
worker) and buys the other three cores for three more instruments. For the pool: the helper threads cost a wake-up per
block and pinned real-time threads on every core, which is why the pool is gated by qualification and measured before
it is enabled. Off versus on, with a plugin that asks for the pool, is **not measured yet**; the #395 lane measures it
with the bench of plugin-hostd#179 (`bench/lib/bench.py`, branch `feat/zynthian-benchmarks`), once with the pool off
and once on (`OMX_CLAP_THREAD_POOL`, which #395 introduces):

    OMX_CLAP_THREAD_POOL=off   bench/lib/bench.py --class rpi5 --out pool-off --rates 48000,96000 --frames 128,256 --stress none
    OMX_CLAP_THREAD_POOL=cores bench/lib/bench.py --class rpi5 --out pool-on  --rates 48000,96000 --frames 128,256 --stress none

**How a musician sees it.** As more voices before the first xrun at a given block size, and as more instruments on
one Pi. With Surge XT at 48 kHz and 256 frames, one instance held 64 voices at 39% of one core with no xrun; four
instances held 16 voices each, one per core, with no xrun. The first xrun was not reached in these runs.

What was proven
---------------

Surge XT `main` (1.4.0, commit `dab78c6`) as CLAP, built for trixie arm64 and installed as
`/usr/local/lib/clap/Surge XT.clap`; played by plugin-hostd 0.13.1 with omx-clap-host 0.23.2 workers, and by jalv as
Zynthian's stock path plays the LV2 (installed by the image, built 2024-04-19). Pi 5, 4 GB, kernel 6.18.50+rpt,
JACK 48 kHz, 256 frames, 2 periods (dummy driver), governor `powersave` at 1.5 GHz (as found, not changed).
`jack-instrument-probe` sends a scripted MIDI scenario into the instrument's note input and measures its two outputs
window by window: peak and RMS level, pitch (rising zero crossings per second, meaningful for one note), brightness
(RMS of the first difference over RMS), JACK xruns; `instrument-proof.py` adds the CPU of every core and of every thread
of the host processes. No window of any run had an xrun.

| Proof | plugin-hostd, Surge XT CLAP | jalv, Surge XT LV2 | Result |
|---|---|---|---|
| It plays | C4 at 261.4 Hz, -13.5 dBFS peak | the same | PASS |
| Velocity | with A Velocity > VCA Gain at 0.0 (its default 1.0 means no velocity response): velocity 20, 64, 127 give -53.9, -37.3, -13.5 dBFS | not set (jalv cannot set an LV2 `patch:` parameter at start); default flat as in the CLAP | PASS |
| Polyphony | 1, 8, 16, 32, 48, 64 notes held, all sounding (limit raised to 64) | 1, 8, 16, 32 at the default limit | PASS |
| Voice stealing | default limit 16: 32 notes cost what 16 do (10% / 10%, DSP 11.3 / 11.3) | 9% / 9%, DSP 10.4 / 10.5 | PASS |
| Pitch bend | A4 440.0 Hz, full up 494.0 Hz, full down 392.0 Hz, back 440.0 Hz (two semitones each way) | 440.0, 494.0, 392.0, 441.0 Hz | PASS |
| Sustain (CC 64) | note released: silent; released under the pedal: -13.5 dBFS; pedal up: silent | the same | PASS |
| All notes off | 8 notes, CC 123: silent 1.5 s later; the `all_notes_off` verb: silent | CC 123: silent | PASS |
| Mod wheel (CC 1) | patch "Oldest Trick In The Book MW" (routes the wheel to filter 1 cutoff): brightness 0.029 at 0, 0.300 at 127, 0.025 back at 0 | the same patch as an LV2 preset: 0.033, 0.300, 0.025 | PASS (CLAP: only from a path without spaces, omx-clap-core#401) |
| MPE | zone set by the MPE configuration message (RPN 6, 15 member channels); a note on member channel 2: 440 Hz; a full bend on member channel 3 leaves it at 440 Hz; a quarter-range bend on its own channel: 880 Hz (12 semitones: the 48-semitone MPE range) | 440, 440, 880 Hz | PASS |
| Through the UI's own path | Add Chain > Instrument > Surge XT (PH) > channel 1: chain `effect_1000` into `zynmixer_chan:input_00a`, a note at -13.5 dBFS | | PASS, for a CLAP file without a space in its name |
| Native window | `show_external_ui` maps Surge XT's own window on the Pi's X display in 664 ms, `hide_external_ui` closes it | | PASS in the host; the engine never asks for it (zynthian-ui#21) |

How Vangelis' own MPE zone option reaches the plugin was not traced; the probe sends the configuration message itself.

The numbers
-----------

CPU of the omx-clap-host thread that runs Surge XT (percent of one core over a 4 s window, the kernel's 10 ms
accounting: ±1-2%), JACK's DSP load, notes held, 48 kHz, 256 frames:

| Notes | plugin-hostd, limit 16 (default) | plugin-hostd, limit 64 | jalv, limit 16 (default) |
|---|---|---|---|
| 1 | 3% · DSP 3.7 | 2% · DSP 3.5 | 3% · DSP 3.6 |
| 8 | 6% · DSP 7.0 | 6% · DSP 7.0 | 6% · DSP 6.7 |
| 16 | 10% · DSP 11.3 | 10% · DSP 11.3 | 9% · DSP 10.4 |
| 32 | 10% · DSP 11.3 | 19% · DSP 20.2 | 9% · DSP 10.5 |
| 48 | | 29% · DSP 29.7 | |
| 64 | | 39% · DSP 39.7 | |
| 4 instances x 16 | 14-15% on each of cpu0..cpu3 · DSP 17.6 | | |

Start-up, from the request to the instrument's ports in JACK: plugin-hostd answered `add` in 580-585 ms over five
runs (ports present 0.83 s after the daemon itself started); jalv's ports appeared 1.85 s and 1.98 s after it was
started. The Zynthian UI added the chain, including its own MIDI channel screen and the 775 controllers it reads, in
about 3.7 s.

The same instrument costs the same in both hosts (within a point at every note count); what plugin-hostd adds is the
start-up time, the remote pages, the protocol's note verbs, the native window on request and the qualification
behind the worker.

Qualification
-------------

    CLAP_PATH=/usr/local/lib/clap plugin-qualify --isolate --out <dir> --host-profile omx-clap-host,openmixer-console '/usr/local/lib/clap/Surge XT.clap'

plugin-qualify 0.16.1, 112 s, on the quiet device. Verdict for both host profiles: rating `unsuitable`, hosting
**`isolated`**, deciding `hosting.rt-safety.violations-in-run` (410 966 allocations and 115 032 locks over the
sweep, no system calls, no thread violations; under notes 18 884 allocations and 98 304 locks). By plugin-qualify#196
that is **isolated**: Surge XT runs, in a worker of its own, and is never grouped with real-time safe plugins; it does
not dismiss it. Cost at 512 frames: median 2.07-2.14 µs per sample at 44.1, 48, 96 and 192 kHz (about 10% of a core
at 48 kHz), 95th percentile 27-37 µs per sample (the note-on blocks); latency declared 0, measured 0-25 frames. The
record says "voices held 128" (Surge's declared capacity), but the default patch sounds 16 of them: the cost is a
16-voice cost (plugin-qualify#203). The record also marks the binary `unpinnable`: its file name holds a space
(plugin-hostd#240). The probe ran under the `powersave` governor, unpinned (`meetsProtocol: false`).
Records: [qualify/](evidence/instruments-2026-10-29/qualify/).

Extensions Surge asks for (omx-clap-core#327)
---------------------------------------------

| Extension | Status here | Evidence |
|---|---|---|
| `clap.note-ports`, MPE | PASS: Surge offers CLAP, MIDI and MIDI MPE (prefers CLAP); MPE zone, per-channel bend and its 48-semitone range behave | MPE row above |
| `clap.voice-info` | read: count 128, capacity 128, overlapping notes; the count does not follow the patch's polyphony limit | scan fields; plugin-qualify#203 |
| `clap.remote-controls/2` | PASS in the host: 5 pages (Macros; Scene A Mixer, Filters; Scene B Mixer, Filters); the engine does not use them | `remote_pages`, `remote_page_get`; zynthian-ui#19 |
| `clap.preset-load/2` | PASS for a file path without spaces (the mod wheel patch loads); FAIL for a `%20` path, answered `resp 0` and not loaded | omx-clap-core#401 |
| preset listing | FAIL: omx-clap-host 0.23.2 answers `preset_list` with `not found`, the UI's preset screen is empty | omx-clap-core#383 |
| `clap.state-context/2` | untested | |
| parameter modulation events | untested | |
| `clap.tuning/2` | untested: the host offers none (omx-clap-core#186) | |
| `clap.param-indication/4` | untested: the host offers none (omx-clap-core#187) | |
| `clap.thread-pool` | Surge does not offer it | the section above |
| `clap.gui` | PASS: own window over X11 on the Pi display | `ui/native-window-x11.png` |
| wildcard note-off | PASS: CC 123 and `all_notes_off` silence 8 held notes | All notes off row |
| Surge's own unison crash seen in 1.3.4 | not exercised: no unison patch was played | |

Captures
--------

- [menu-instruments.png](evidence/instruments-2026-10-29/ui/menu-instruments.png): Add Chain > Instrument, the PH
  entries with their qualification tags;
- [menu-three-surge-entries.png](evidence/instruments-2026-10-29/ui/menu-three-surge-entries.png): the same title three
  times (zynthian-ui#20);
- [controller-pages.png](evidence/instruments-2026-10-29/ui/controller-pages.png): Surge XT's controller pages in the
  engine, omx-panel's layout of 775 parameters (zynthian-ui#19);
- [preset-list-empty.png](evidence/instruments-2026-10-29/ui/preset-list-empty.png): the preset screen, no presets
  (omx-clap-core#383);
- [mixer-with-surge-chain.png](evidence/instruments-2026-10-29/ui/mixer-with-surge-chain.png) and
  [chain-options.png](evidence/instruments-2026-10-29/ui/chain-options.png): the chain in the mixer;
- [lv2-add-refused-stays-on-channel.png](evidence/instruments-2026-10-29/ui/lv2-add-refused-stays-on-channel.png): the
  LV2 entry refused, the UI silent (zynthian-ui#18, plugin-hostd#239);
- [native-window-x11.png](evidence/instruments-2026-10-29/ui/native-window-x11.png): Surge XT's own window on the Pi
  display through `show_external_ui`.

What the host still lacks for Surge XT
--------------------------------------

- **Surge's own file names.** The CLAP is `Surge XT.clap`: plugin-hostd cannot add it or pin it (`resp -101`,
  plugin-hostd#240); the LV2 binary is `libSurge%20XT.so`: plugin-hostd refuses it (`-509`, the daemon does not decode
  it, plugin-hostd#239). As installed by the image, Surge XT does not run through the engine in either format. Every
  proof above used a symlink without the space.
- **Presets.** No listing (`preset_list` not registered in omx-clap-host, omx-clap-core#383), and a file preset whose
  path holds a space answers success without loading (omx-clap-core#401). The LV2 path lists Surge's factory banks
  through Zynthian's TTL (`factory_presets.ttl`); the CLAP path lists none.
- **The controller pages a player needs.** The engine pages through all 775 parameters; Surge's five remote pages
  are read by the host and not shown (zynthian-ui#19).
- **The native window over VNC.** The host shows it (capture above); the engine has no entry to ask for it
  (zynthian-ui#21). It is wider than a 1024x768 screen.
- **Modulation-path assignment.** No CLAP extension carries Surge's modulation matrix. The native window carries it
  (shown, not exercised). Surge's own OSC server (`/mod/...`) was not measured: it has to be enabled in Surge's
  settings, from the window.
- **Voices across the cores** for Surge: none from the pool (Surge does not ask for it); placement of instances
  across cores is the route (plugin-hostd#226).
- **The UI on a refusal.** A refused add leaves no message and a half-made chain that blocks the next start
  (zynthian-ui#18).

Not proven here
---------------

- The first xrun: no run reached it (64 voices, one instance: 39% of a core).
- The thread pool's effect: not measurable with Surge XT, and #395 is not built yet.
- Whether 1.4.0 still has the unison crash seen in 1.3.4; parameter modulation events; `clap.state-context`; tuning; Surge's OSC
  modulation route; Vangelis' MPE zone option itself.
- Velocity through jalv with velocity sensitivity on (jalv cannot set the parameter at start).
- Anything at another rate or block size than 48 kHz / 256 frames, or under the `performance` governor.

The exact commands
------------------

Build (on any x86_64 host with podman; details in
[build/README.md](evidence/instruments-2026-10-29/build/README.md)):

    git clone --recursive https://github.com/surge-synthesizer/surge.git
    podman run --rm --arch amd64 -v $PWD:/src -v $PWD/out:/out docker.io/amd64/debian:trixie /src/luajit.sh
    podman run --rm --arch amd64 -v $PWD:/src -v $PWD/out:/out docker.io/amd64/debian:trixie /src/build.sh
    aarch64-linux-gnu-strip -o 'Surge XT.clap' 'out/b/surge_xt_products/Surge XT.clap'
    scp 'Surge XT.clap' root@zynthian.local:'/usr/local/lib/clap/Surge XT.clap'

On the Pi (the tools from `tools/zynthian/`; a symlink without the space until plugin-hostd#240):

    gcc -O2 -o jack-instrument-probe jack-instrument-probe.c -ljack -lm
    ln -s '/usr/local/lib/clap/Surge XT.clap' /root/surge/SurgeXT.clap
    U=clap:/root/surge/SurgeXT.clap#org.surge-synth-team.surge-xt
    L=https://surge-synthesizer.github.io/lv2/surge-xt
    P='/zynthian/venv/bin/python3 -I instrument-proof.py'
    $P --out hostd-default --host hostd --uri $U --only start,velocity,poly,bend,sustain,anoff,mpe
    $P --out hostd-velsense --host hostd --uri $U --only velocity --param '1285869018 0.0'
    $P --out hostd-poly64 --host hostd --uri $U --only poly --poly 1,8,16,32,48,64 --param '240235375 1.0'
    $P --out hostd-cc --host hostd --uri $U --only cc --cc-preset /root/surge/OldestTrickMW.fxp
    $P --out hostd-x4 --host hostd --uri $U --instances 4 --only poly --poly 16
    $P --out jalv-default --host jalv --uri $L --only start,velocity,poly,bend,sustain,anoff,mpe
    $P --out jalv-cc --host jalv --uri $L --only cc --cc-preset $L:preset188

`OldestTrickMW.fxp` is a copy of `patches_factory/Leads/Oldest Trick In The Book MW.fxp`. `240235375` is Surge's
Polyphony Limit (normalised, 1.0 = 64 voices) and `1285869018` its A Velocity > VCA Gain (0.0 = full velocity
response), both as `omx-clap-scan --fields` lists them. The script starts its own plugin-hostd on port 5591 with no
pins, removes everything it started, and leaves `windows.tsv`, `protocol.log` and the scenarios in each `--out`.

The UI was driven over its OSC CUIA port (UDP 1370: `ADD_CHAIN`, `SELECT <i>`, `SELECT_ACTION S|B`, `BANK_PRESET`,
`ARROW_DOWN`, `BACK`) and captured with `scrot` on display :0. The run held the device by writing under
`/root/omx-stress-instruments/`, which the benchmark matrix (`tools/zynthian/matrix.py --wait-idle`) waits on.
