The Zynthian chain as a strip profile
=====================================

The strip model, as OpenMixer's strip declaration states it: a strip is a sorted chain of elements operating on
sound, its source is `live`, `synth` or `sum`, control-domain input belongs to the source and sits outside the chain,
and a profile states what one kind of strip carries. This page writes one Zynthian chain in those terms. Every fact is read from zynthian-ui `f46b0189b616`
(the commit `zynthian_engine_plugind.patch` applies to); `chain.py` is `zyngine/zynthian_chain.py`, `manager.py` is
`zyngine/zynthian_chain_manager.py`, `processor.py` is `zyngine/zynthian_processor.py`, `autoconnect.py` is
`zynautoconnect/zynthian_autoconnect.py`.

What a chain holds
------------------

- Three lists of slots: `midi_slots`, `synth_slots` ("should be single slot") and `audio_slots`; each slot is a list of
  PARALLEL processors (`chain.py:57-61`).
- "Processors receive audio/MIDI input from the previous slot. Processors in first slot use the chain's audio/MIDI
  input. An empty chain with audio input configured is pass-through" (`chain.py:43-49`); the switches are `midi_thru`
  and `audio_thru` (`chain.py:67-68`).
- A processor goes to a list by its engine's `TYPE` (`processor.py:63`): `MIDI Tool` to `midi_slots`, `Audio Effect`
  to `audio_slots`, any other type (`MIDI Synth`, `Audio Generator`, `Special`) to `synth_slots`
  (`get_slots_by_type`, `chain.py:120-132`).
- The mixer channel strip is a processor of the audio list: `MI` (and `MR` for a mixbus) is an `Audio Effect`
  (`manager.py:143-172`), added after the chain's first processor (`zyngui/zynthian_gui.py:1070-1076`); a new effect is
  inserted just before it, pre-fader (`zyngui/zynthian_gui_chain_options.py:192-199`). Effects after it are post-fader.

The profile
-----------

| Field | Zynthian chain | Read from |
|---|---|---|
| source | `synth` when `synth_slots` holds a processor: its JACK client feeds the first audio slot. `live` when it does not and `audio_thru` is set: the chain's capture pairs feed it. `sum` for a mixbus chain (`MR`): the mixer's send `zynmixer_chan:send_<nn>` feeds it | `chain.py:322-333` |
| source, one generator | adding a `MIDI Synth` to a chain that has one removes the old one ("Cannot have multiple synth engines") | `manager.py:1095-1098` |
| control domain | `midi_slots`, outside the audio chain: slot `i` takes the MIDI of slot `i-1`, slot 0 the chain's input (autoconnect); the last MIDI slot feeds the synth's MIDI input; with no MIDI slot and `midi_thru`, the chain's MIDI input does | `chain.py:386-418` |
| control domain, to effects | the same MIDI feeds every audio processor that is not `MI`/`MR` | `chain.py:419-424` |
| chain | `audio_slots` in order: each slot's processors take the previous slot's outputs | `chain.py:335-347` |
| tail boundary | the last slot's outputs go to the chain's outputs (`audio_out`, default `[0]`, the main mixbus; chain 0 the first two playback ports) | `chain.py:356-360`, `chain.py:91-106` |
| fixed element | the mixer strip `MI`/`MR` (fader, balance, mute, solo, sends) sits in `audio_slots`, so the pre/post-fader split is a position in the list, not a boundary of it | `manager.py:143-172`, `zyngui/zynthian_gui_chain_options.py:192-199` |
| pass-through | an empty audio list with `audio_thru` routes the input pairs straight to the outputs (`prev_slot_sources` stays the first sources) | `chain.py:331-333`, `chain.py:359-360` |
| placement | where a processor runs is its engine's: jalv one process per LV2 plugin (`zynthian_engine_jalv.py:84-98`), mod-ui one `Special` processor (`zynthian_engine_modui.py:67`, client `mod-host`, `:92-93`) holding a whole pedalboard, plugind one instance in plugin-hostd (`effect_<n>`) | as cited |
| realisation | the chain builds `audio_routes` (destination to sources, `chain.py:320-360`); `zynautoconnect` turns them into JACK links, pairing ports two at a time with mono spread (`autoconnect.py:1094-1098`), and disconnects only links it made itself (`zyn_routed_audio`, `autoconnect.py:1163-1186`) | as cited |

Verbs on the chain
------------------

| Verb | Where | What it does to the slots |
|---|---|---|
| add at a position | `manager.add_processor(chain_id, eng_code, slot)` (`manager.py:1054-1129`) → `chain.insert_processor` (`chain.py:639-680`) | always a NEW slot: `None` appends, `< 0` inserts first, past the end appends, else inserts at `slot`; the parallel branch is commented out (`chain.py:669-670`); the engine is started after the insert (`manager.py:1100`), then the graph is rebuilt (`manager.py:1118-1121`) |
| remove | `manager.remove_processor` (`manager.py:1210-1264`) → `chain.remove_processor` (`chain.py:705-746`) | the processor leaves its slot, an emptied slot is dropped (`chain.py:722-725`), the graph is rebuilt (`chain.py:731`); unused engines stop after (`manager.py:1250-1251`) |
| move up/down | `manager.nudge_processor` (`manager.py:1149-1174`) → `chain.nudge_processor` (`chain.py:758-804`) | moving a single processor past its neighbour MERGES it into the neighbour's slot (`chain.py:782`, `chain.py:799`); moving a parallel one out makes it a slot of its own (`chain.py:771-777`, `:793-795`); the mixer strip moves slot by slot (`chain.py:767-770`); the main output is muted while the audio graph changes (`manager.py:1165-1171`) |
| move to another chain | `manager.nudge_processor` left/right (`manager.py:1175-1207`) | remove from one chain, append to the other's list |
| swap | `chain.swap_processors` (`chain.py:806-836`) | its guard `processor1.type != processor2.type or processor1.type` refuses every typed processor, so it is unreachable for effects at this commit |
| restore | `manager.set_chain_state` (`manager.py:1573-1589`) | the saved slots are read processor by processor and each is added as a new slot (the code's own TODO, `:1590-1591`): a saved parallel slot comes back in series |

Limits
------

- One synth: `manager.py:1095-1098`.
- No limit on the number of audio or MIDI slots is enforced in these files.
- Movable: a synth or generator never (`manager.py:1131-1147`).
- Through plugind: instances are numbered by the engine, lowest free first (`zynthian_engine_plugind.py`, `__init__`);
  the daemon's own limits (`add` beyond `MAX_INSTANCE` answers `-1`, `tests/daemon_test.py` placement test) apply.

One Zynthian chain, one chain line
---------------------------------

The 2026-10-21 ruling on plugin-hostd#101: one Zynthian chain is one plugin-hostd `chain` line. The engine
(`zyngine/zynthian_plugind_chain.py`, in `zynthian_engine_plugind.patch`) says a chain's audio slots to the daemon
through the chain verb only. No `connect` or `disconnect` between plugind instances is sent.

| What | How |
|---|---|
| members | the plugind processors of the chain's audio slots, in slot order: one `chain <chain_id> <instance> ...` line, `<chain_id>` the Zynthian chain's own number |
| one worker | the daemon puts the members in one worker of place `chain:<chain_id>`; omx-clap-host runs them in the head member's JACK client (omx-clap-core#104) |
| add at a position | the chain inserts the slot (`chain.py:639-680`), the rebuild declares the new order; the daemon keeps the running worker and replays the new member into it (plugin-hostd#162) |
| move | a nudge of a plugind processor past a single plugind neighbour swaps the two slots (see below), and the rebuild declares the new order: the worker is sent the line and nothing else |
| remove | the rebuild declares the order without it (the member goes to a worker of its own), then the engine's `stop` sends `remove`; a chain left with no plugind processor is `chain_clear`ed and read back like any other edit |
| read-back | after every line the engine reads `chain_get <chain_id>` and requires the declared order to be the one it sent, or it refuses with `PLUGIND_READBACK_MISMATCH`; the running order it reads is what it routes |
| bypass, parameters | every instance verb names one member by its own number, as before: `bypass <n> 0/1` for the host's `:bypass`, `param_set <n> <symbol> <value>` |
| quarantine | the chain verb's own: a member that crashes the worker runs alone, the others go on in order and the daemon writes `chain_formed`; the engine reads the chain back on that event and routes the running order, so a quarantined member is out of the audio path until `quarantine_clear` |
| routes | the chain's client is the running head's, `effect_<head>`: it takes the first plugind slot's sources, the inner routes between members are dropped (the members run in order inside one client), and whatever the run fed is fed by the head's client. On a worker that runs no chain in one client (mod-host, row `lv2` of `worker_list`) the members keep their clients and Zynthian's routes stay as they are |
| a lost daemon | the hook runs while `rebuild_audio_graph` holds autoconnect's lock, which waits for ever (`autoconnect.py:1602`), so it never raises: a command that fails on the connection (a restart, a reset, no answer in `PLUGIND_TIMEOUT` seconds, 30 by default) logs `PLUGIND_DAEMON_LOST` once, the routes stay as Zynthian built them, the lock is released, the next command opens a new connection (one attempt per command, no loop), and the next realisation declares the line again; a clean close before any reply counts as a loss |
| version floor | `chain_get` (plugin-hostd#162, the first release after 0.10.0). A daemon that answers it with anything but `resp 0` or `NO_SUCH_CHAIN` (-522) has no read-back: the engine declares no chain, refuses with `PLUGIND_CHAIN_GET_ABSENT`, and the processors run one worker each, routed by autoconnect, as Path B did |

The refusals are codes, constants of the module, logged with the slot they name; none is a protocol code.

| code | when |
|---|---|
| `PARALLEL_SLOT_REFUSED` | a parallel slot holds a plugind processor. Refused until omx-plugins#229 gives a plugind chain a mixer element; the nudge that would form it answers False and leaves the chain as it was |
| `PLUGIND_RUN_SPLIT` | a processor plugin-hostd does not run (the mixer strip `MI`, a jalv processor) sits between two plugind ones. The first run of plugind slots is the chain line; the ones after the foreign processor run one worker each, routed by autoconnect |
| `PLUGIND_CHAIN_REFUSED` | the daemon refused the line (its code in the log line), as for members of two programs (`CHAIN_MIXED_FORMAT`) |
| `PLUGIND_READBACK_MISMATCH` | `chain_get` does not answer the declared order the line sent |
| `PLUGIND_CHAIN_GET_ABSENT` | the daemon predates the floor |
| `PLUGIND_DAEMON_LOST` | the connection to the daemon failed mid-command; the routes are Zynthian's own until the next realisation |

A move without a parallel step. Zynthian's nudge of a single processor merges it into its neighbour's slot
(`chain.py:782`, `:799`), and only a second nudge takes it out on the other side. With parallel slots refused, a
plugind processor could never pass another. So the patch makes the nudge of a plugind processor whose neighbour slot
holds one plugind processor a swap of the two slots: one nudge, one move, one chain line. A nudge into the mixer
strip's slot or into a foreign processor's is Zynthian's own, and a parallel slot it would form is refused.

Parallel slots: refused by name
-------------------------------

What Zynthian does today: every processor of a slot gets the previous slot's sources (`chain.py:342-346`, the same
`prev_slot_sources` for each member: a fan-out), and the NEXT slot, or the chain's outputs, gets the list of all
members as its sources (`chain.py:347`, `:359-360`). autoconnect then connects every member's output ports to the same
input ports of the next destination (`autoconnect.py:1089-1097`), and JACK sums them at that input. The mix is
implicit: unity gain per branch, no level, no bypass, nothing to read back.

A chain line is a series. A parallel slot of plugind processors would be a fan-out into an explicit mix element (unity
gain per branch, the slowest branch's latency), and no plugin that is an N-input mixer exists in omx-plugins yet
(omx-plugins#229). Until it does, a parallel slot holding a plugind processor is refused `PARALLEL_SLOT_REFUSED`
before it forms. The earlier link-by-hand layer (`zynthian_plugind_strip.py`, PR 129, `PLUGIND_MIX`) is gone with
mod-host's `connect` between workers.

Open points
-----------

- **Effects after the mixer strip.** `MI`/`MR` is a processor in the audio list (`manager.py:143-172`), and a new
  effect goes before it (`zyngui/zynthian_gui_chain_options.py:192-199`). A chain with plugind effects on both sides
  of it is two runs, and one chain line can hold only one: the run after the strip is refused `PLUGIND_RUN_SPLIT` and
  runs one worker per processor. Whether the strip's fader belongs in plugin-hostd's chain is not decided here.
- **A crashed head takes the chain's connections.** plugin-hostd records a connection against the client its port
  names (omx-clap-core PR 348, open question 1). The engine routes the running head on `chain_formed`, so Zynthian's
  autoconnect wires the new head; a connection made through the daemon is not moved.
- **An LV2 member joining a running chain** forms the chain's worker again: its bundle is not in the world the running
  worker was started with (plugin-hostd#162). A CLAP member joins in place.
- **A move is two library steps** in omx-clap-host (a removal and an insertion, omx-clap-core PR 348 open question 4),
  so the cycles between them run without the moved member.
- **MIDI to effects.** Every audio processor gets the chain's MIDI (`chain.py:419-424`). Not mapped.

Tests
-----

`tools/zynthian/chain.sh <zynthian-ui clone> <out>` applies the patch at the pinned commit and runs
`tools/zynthian/test-chain.py`: the real `zynthian_chain`, `zynthian_processor` and `zynthian_plugind_chain` against
plugin-hostd and `tests/fake-host` (no JACK, no plugin), autoconnect's lock a real one that counts a wait past two
seconds. Nine scenarios read the chain back with `chain_get` and the workers with `worker_list`; one kills the daemon
with a rebuild's command in flight and requires the lock free after every later rebuild. Each sabotage names the check
it must trip, and a sabotage that turns its scenario red on another check, or on an error no check names, is itself a
failure. Given a daemon without `chain_get` the floor scenario holds the engine to its refusal, its two members of one
row so that the old daemon would take the line the floor keeps from it. `tools/zynthian/chain-e2e.sh` runs the same
nine against omx-clap-host, an LV2 member on the adapter row and CLAP members, in a PipeWire of its own: one node per
chain (`pw-dump`), the crashed member's own node, and a tenth that measures the audio. After an add at a position and after a move, the
chain's output is the order `chain_get` reads back: equal to the same plugins one client each in series, within the
difference two such references show of each other, and at least 40 dB away from the other order.
`tools/zynthian/chain-e2e.sh --round-trip` runs `tools/zynthian/test-chain-round-trip.py` the same way with omx-plugins
members as installed: omx-strip (CLAP, Trim +12 dB), omx-limiter (CLAP, Ceiling -6 dBFS) and omx-delay (LV2 on the
adapter row, 10 ms, mix 0.5), declared in that order, the LV2 member joining the running CLAP chain last. Each member's
signature is measured alone first (the taps the noise leaves in its output: lag and gain), and must be what its
parameters say. The chain's output is then read for the members' values in the declared order: the limiter's lag and
the delay's tap after it, no louder than the ceiling, equal to the three one client each in series and at least 40 dB
away from the two other ways the three can sound. Removing the limiter forms the chain again and its output is the
strip's gain times the delay's taps with no lookahead; a fault plugin crashing between strip and limiter is quarantined
and the three play as before. Its sabotages (the line reversed, the line without its last member, the chain not formed
again after a removal) each turn a check of the audio red. CI runs it (`zynthian-chain` in `.github/workflows/ci.yml`)
with everything from the FreeMixer channel, by what it must do: plugin-hostd with `chain_get`, omx-clap-host 0.21.0 or
later, and omx-clap-host-tests with `fault-14.clap` and `jack_identity` (omx-clap-core#351). A channel that lacks one
fails the job by name. Beside them it installs Fedora's `pipewire-jack-audio-connection-kit`, so the libjack the host
loads is PipeWire's and not JACK2's, and `lilv-libs`, which the host opens itself at its first LV2 add; without either
the reference host is never ready or refuses the LV2 member, and the job fails by name.
`evidence/chain/` holds the runs with their commands. A claim about Zynthian
here is trixie arm64 container only until the Vangelis hardware run is dated, and these runs are less than that:
Fedora 44 containers on x86_64, the zynthian-ui Python modules imported with zyncoder and autoconnect stubbed. No
Zynthian image ran, and no Zynthian screen, UI or encoder was seen.
