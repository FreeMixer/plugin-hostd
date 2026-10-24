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

Parallel slots: fan-out and an explicit mix
-------------------------------------------

What Zynthian does today: every processor of a slot gets the previous slot's sources (`chain.py:342-346`, the same
`prev_slot_sources` for each member: a fan-out), and the NEXT slot, or the chain's outputs, gets the list of all
members as its sources (`chain.py:347`, `:359-360`). autoconnect then connects every member's output ports to the same
input ports of the next destination (`autoconnect.py:1089-1097`), and JACK sums them at that input. The mix is
implicit: unity gain per branch, no level, no bypass, nothing to read back.

In the strip profile a parallel slot is neither a pool (a SET of instances in one process, no order) nor a chain (a
series). It is a third thing: a FAN-OUT of the previous element's output to every member's input, then an explicit
MIX ELEMENT that sums the members' outputs, whose output feeds the next slot. No input port is ever fed by more than
one source.

| Mix element field | Value |
|---|---|
| role | `mix` |
| inputs | N branches, one per member, in slot order, each a stereo pair of the mixer's own input ports |
| gain per branch | declared; default 1.0 per branch, which is what Zynthian's implicit sum does today (unity per connected output, `autoconnect.py:1089-1097`); not 1/N, since that would change the level of every existing parallel slot |
| bypass | the mixer instance's own mod-host `bypass` |
| latency | the maximum of the branch latencies; the protocol has no latency verb on plugin-hostd's main, so the value is unknown (None) and no branch is delay-compensated |
| realisation | one plugin-hostd instance of an N-input mixer plugin, declared to the engine by `PLUGIND_MIX` (its URI, branch count, port and gain names) |

No N-input mixer is installed on the machine this was written on (`/usr/lib64/lv2` holds only the LV2 spec bundles, and
there is no CLAP directory), and the omx-plugins
catalogue (23 plugins, `plugins/` on its `main`, 2026-10-21) holds none: `omx-strip` is a channel strip, the
rest are effects and test plugins. omx-dsp has the summing kernel (`include/omxdsp/mix/omx_bus_sum.h`) but no plugin
around it. So the element and its link plan are defined and tested, and the realisation is refused with
`MIX_ELEMENT_ABSENT` when no mixer is declared; the refusal happens before the slot is formed (a nudge that would
merge two processors answers False and leaves the chain as it was).

Boundaries of the plugind strip
-------------------------------

The plugind strip (`zyngine/zynthian_plugind_strip.py`, in `zynthian_engine_plugind.patch`) owns the links between
two ADJACENT audio stages that are both plugin-hostd's: a stage is one processor, or a parallel slot with its mix
element. It makes them with mod-host's `connect` and takes them down with `disconnect` before an instance is removed.
Inside a parallel slot it owns every member-to-mix link. Every other link stays the chain's and autoconnect's: the
source into the first stage, a plugind stage next to the mixer strip or to another engine's processor, and the last
stage into the outputs; for those the strip only rewrites `audio_routes` so that a destination after a parallel slot
is fed by the mix element and never by the members. A parallel slot holding a processor that is not plugin-hostd's is
refused with `PARALLEL_SLOT_FOREIGN`, and one with more members than the declared mixer has branches with
`MIX_BRANCHES_EXCEEDED`.

Open points
-----------

- **Parallel slots in the strip model.** The strip model of the openmixer draft has no parallel element yet; this page
  proposes fan-out plus a `mix` element as the third arrangement beside pool and chain. Whether the draft takes it,
  and how a mix element's branch gains are presented, is not decided here. The only way a parallel slot forms at this
  commit is a nudge into a neighbour (`chain.py:782`, `:799`); a restore flattens it (`manager.py:1584-1585`), so a
  saved parallel slot does not survive a reload in Zynthian itself. A new mix element starts at the declared gains: a
  member added to or taken from a slot gives the slot a new mixer instance, and branch gains set by hand are not
  carried over.
- **A reorder passes through a parallel slot.** Zynthian has no move verb for effects but the nudge, and a nudge of a
  single processor merges it into its neighbour's slot (`chain.py:782`, `:799`); only a second nudge takes it out on
  the other side (`chain.py:771-777`, `:793-795`). So reordering two effects always forms a parallel slot for one
  step. With a mixer declared, the strip realises that step (a mixer instance is added, then removed on the second
  nudge, `tools/zynthian/test-strip.py` `move_relinks_through_the_parallel_step`); with none, the first nudge is
  refused `MIX_ELEMENT_ABSENT` and a plugind chain cannot be reordered by nudging at all. Whether Zynthian should get a
  plain move (a swap of adjacent slots) instead is not decided here.
- **Latency of a mix.** Branches of unequal latency are summed as they come; nothing compensates them.
- **Who owns a link.** autoconnect disconnects a link only if it once made it (`autoconnect.py:1176-1181`); a link
  between two plugind instances must never be made by autoconnect, or a later pass may take the strip's link down. The
  patch drops those destinations from `audio_routes` before autoconnect reads them; whether a link made by autoconnect
  before the patch took effect (an engine swapped live) can linger in `zyn_routed_audio` is not tested here.
- **The mixer strip as an element.** `MI`/`MR` is a processor in the list, not a fixed boundary; in the strip model it
  would be the `fader` element with a fixed position. Zynthian lets it move slot by slot (`chain.py:767-770`). Not
  mapped.
- **MIDI to effects.** Every audio processor gets the chain's MIDI (`chain.py:419-424`); in the strip model that is
  control-domain input reaching chain elements, which the draft spec places with the source. Not mapped.

Tests
-----

`tools/zynthian/strip.sh <zynthian-ui clone> <out>` applies the patch at the pinned commit and runs
`tools/zynthian/test-strip.py`: the real `zynthian_chain`, `zynthian_processor` and `zynthian_plugind_strip` against
plugin-hostd and `tests/fake-host`, no JACK and no plugin. Seven scenarios read the daemon's graph back
(`list_connections`) and its values (`param_get`), and nine sabotages each turn one red. `evidence/strip/test.log` is
one run. Not tested: the plugind engine itself under the strip (it needs lilv and JACK: `test-path-b.py`), real JACK
ports and their names, autoconnect's pass over the rewritten routes, Zynthian's GUI, any timing, and any hardware.
