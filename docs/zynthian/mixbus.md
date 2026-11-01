Mixbus chains and effects sends
===============================

Zynthian's `vangelis` branch has effects send and return: a Mixbus chain for each effect, which can hold as many serial
and parallel audio effects as you wish and feeds main by default, and in every other chain's mixer processor a send
level and a pre or post fader mode for each Mixbus. Mixbus chains are pinned to the right of the mixer. This page says
how a plugin-hostd (PH) plugin behaves in one. The short answer: as any plugin does. Zynthian's mixer does the send, and
the engine has to leave Zynthian's slots as they are.

What a user does
----------------

Nothing changes. Add a chain, choose Mixbus, add the effects, as with jalv: `Add Audio-FX processor`, and the menu lists
the PH plugins with the others. Move an effect with the chain's move action; moved into the slot next to it, it runs in
parallel with what is there, and moved again it comes out. In a chain that feeds it, the mixer processor has the send's
controller page, level and mode.

How a plugin behaves in a Mixbus
--------------------------------

A slot of Zynthian's holds one processor or several, and several are parallel: each takes the previous slot's output, and
the next slot sums theirs. The engine runs a worker per group, and a worker runs its plugins in series inside one JACK
client, so a group can only be plugins in series with nothing between them.

| Slots of the chain | What runs | JACK clients |
|---|---|---|
| A, B | A and B grouped in one worker | one, `effect_A`, carrying the chain's ports |
| A, [B, C] | a worker for each: B and C are parallel | three; A feeds both, both feed what comes next |
| A, B, [C, D], E, F | A with B, a worker each for C and D, E with F | four |
| A, the mixer strip, B | a worker each: the strip is in the signal's way | two |
| A, a jalv plugin, B | a worker each | two, and the jalv plugin's |

The same holds in any chain, and a synth at its head starts its first group. A Mixbus chain differs only at its input,
which is Zynthian's own: with no synth in the chain, its first slot takes `zynmixer_chan:send_<nn>`, and the last effect
feeds the Mixbus's strip. That route is built by `zynthian_chain.py` whatever the engine is.

The table is with the setting `grouping` on; with it off, the default, every plugin has a worker of its own. With it on, the daemon's planner decides inside each group: it may split one further, by a plugin's
pin and cost, and never joins anything across a slot. A plugin qualified as isolated has a worker of its own, in a Mixbus
as elsewhere. A worker that does not run some members as one (a member with a side chain, omx keyed-gate for one) keeps a
client per member; the engine sees that in the graph and connects those members one by one.

What sends and pre and post fader need from us
----------------------------------------------

Nothing. The send level and mode are controllers on the mixer processor, and they go to `zynmixer`. Choosing pre or post
fader changes where the mixer takes the send from, before the Mixbus's input. Pinning and moving a Mixbus are the chain
manager's order of chains. Tests with Zynthian's real chain manager show that none of these sends a line to the daemon
(`test_chain_manager` in zynthian-ui's `tests/test_plugin_hostd_signal_path.py`). The one thing a send reads from a
plugin is a name, for a Mixbus with no title: it takes the first effect's, which a PH plugin gives.

What was measured
-----------------

At JACK ports: a tone in, the chain's own routes connected in order, the level out, against the input. The plugin is omx
eq8, flat, so unity gain, on plugin-hostd 0.15.4, omx-clap-host 0.25.3 and zynthian-ui's own engine and chain, on a dummy
JACK server at 48000 Hz and 256 frames in a container. Script clients stand in for the mixer strip, at -20 dB, for
`zynmixer_bus`, and for a jalv plugin, at -6 dB. The script is `tools/ph_signal_path_proof.py` in zynthian-ui.

| Chain | Level | The right answer |
|---|---|---|
| two in series | +0.00 dB | +0.00 dB |
| two in a parallel slot | +6.02 dB | +6.02 dB |
| one, then a parallel slot of two | +6.02 dB | +6.02 dB |
| pre-fader, strip at -20 dB, post-fader | -20.00 dB | -20.00 dB |
| a client at -6 dB between two | -6.02 dB | -6.02 dB |
| Mixbus, two in series, from its send's place | +0.00 dB | +0.00 dB |
| Mixbus, a parallel slot of two, from its send's place | +6.02 dB | +6.02 dB |

Before this, the engine handed a chain's plugins to the daemon as one list. With only that put back, the second, third,
fourth, fifth and last rows above read +0.00 dB: parallel plugins ran in series, and the signal went past the strip or
the other plugin. It did not show on current daemons, because the engine could not read the reply of `plan` or a record
of `worker_list` as they have been since plugin-hostd 0.14, and so it grouped nothing at all. Both are fixed together
([zynthian-ui#53](https://github.com/FreeMixer/zynthian-ui/pull/53)), which also means chains are grouped on current
daemons from that change on.

On the Pi, plugin-hostd 0.15.7, omx-clap-host 0.25.4, the same script passes 10 of 10; those ten hold no Mixbus row
([log](evidence/pi5-claims-2026-10-31/engine-proof/proof.log)). Not measured yet: a Mixbus with Zynthian's own mixer in the path
rather than script clients. The steps are below.

Example: one reverb and delay on a bus
--------------------------------------

What a user does, with the plugin-hostd engine on:

1. Add a chain and choose Mixbus. In its options, `Add Audio-FX processor`: omx reverb, then omx delay, each "(PH)".
2. In each chain that should feed it, open the mixer processor's controller page and raise the send level for that Mixbus,
   pre or post fader as you like.

What you get: one reverb and one delay in place of one per chain. Measured on a Pi 5 as a JACK graph on a private dummy server,
without Zynthian's routing, read digitally at JACK ports: mda EPiano instruments holding notes, feeding one reverb and delay or a
pair each, into the main output, 48000 Hz and 256 frames. Grouped makes each reverb and delay one chain.

Our own omx reverb and delay, LV2 builds on every host, plugin-hostd 0.15.5, omx-clap-host 0.25.3, 4 instruments, five repeats,
medians ([rows](evidence/pi5-claims-2026-10-31/mixbus/mixbus.tsv)):

| | shared: JACK DSP | shared: PSS | a pair each: JACK DSP | a pair each: PSS |
|---|---|---|---|---|
| mod-host | 1.98 % | 82.1 MB | 2.16 % | 105.8 MB |
| plugin-hostd, grouped | 2.66 % | 84.7 MB | 3.09 % | 122.2 MB |
| plugin-hostd, one worker each | 2.85 % | 89.9 MB | 3.43 % | 133.3 MB |
| jalv | 2.23 % | 298.2 MB | 3.28 % | 551.1 MB |

Sharing saves memory on every host. mod-host uses less CPU and memory than plugin-hostd here; the gain of plugin-hostd is over
jalv, in memory and xruns: plugin-hostd grouped read 0 in every repeat, jalv up to 7 shared and 11 with a pair each.

Dragonfly Room and PitchedDelay, both stereo, plugin-hostd 0.15.7, 4 instruments, three repeats, 0 xruns, level -1.7 dBFS in every
row ([rows](evidence/pi5-claims-2026-10-31/mixbus/mixbus-stereo-pair.tsv)):

| | shared: JACK clients | shared: JACK DSP | shared: PSS | a pair each: JACK clients | a pair each: PSS |
|---|---|---|---|---|---|
| plugin-hostd, grouped | 5 | 5.85 % | 88.6 MB | 8 | 134.5 MB |
| plugin-hostd, one worker each | 6 | 6.13 % | 93.7 MB | 12 | 145.5 MB |

A group runs one audio width: a stereo reverb and a mono delay do not group. The worker refuses the chain, plugin-hostd 0.15.7
reports the refusal, the engine ends a run at a change of width
([zynthian-ui#57](https://github.com/FreeMixer/zynthian-ui/pull/57)), and the plugins run one by one at the same level.

These rows are not through Zynthian's own routing; a Mixbus built from its menu has not been measured on the Pi.

What stays to integrate
-----------------------

For the [upstream series](upstream-series.md), small and opt-in as the rest of it:

- **In Zynthian's files: nothing new.** The engine's existing call from `rebuild_audio_graph` and its one line for a
  client shared by several members stay as they are. No line of `zynmixer`, the send pages, pinning or `set_state`
  changes, and with the engine off nothing runs.
- **In the engine:** the change above folds into step 4 when the steps are cut again, with its tests, and the chain view's
  figures into step 9: latency adds along the steps, and a parallel slot counts its longest branch.
- **To discuss, not to patch:** a parallel slot saved in a snapshot comes back in series, for every engine, since
  `set_state` adds each saved processor as a new slot and says so in a TODO. The workers follow the chain that comes back,
  so PH plugins stay correct either way. If Zynthian restores parallel slots one day, the engine needs no change.
- **Not planned:** a parallel slot inside one worker. A worker's chain is a series; a parallel slot in one client would need a
  mix element, and JACK's summing does the job.
  A Mixbus with parallel effects costs a worker per branch.

Steps for the Pi
----------------

After the benchmark run has finished, never beside it. All at a private dummy server, and nothing downloaded:

    cd /zynthian/zynthian-ui && git pull
    jackd -n phproof -d dummy -r 48000 -p 256 &
    JACK_DEFAULT_SERVER=phproof python3 tools/ph_signal_path_proof.py \
        --uri 'clap:/usr/lib/clap/omx-eq8.clap#org.openmixer.eq8'
    JACK_DEFAULT_SERVER=phproof python3 tools/ph_signal_path_proof.py --conf 'grouping on' \
        --uri 'clap:/usr/lib/clap/omx-eq8.clap#org.openmixer.eq8'
    kill %1

Each line says `ok` or `FAIL`, with the level, the clients and the workers; the exit status is 0 when every line is `ok`.
Then, in the UI with Zynthian's own mixer: add a Mixbus with omx eq8 and omx comp, and read `jack_lsp -c`:
`zynmixer_chan:send_<nn>` connects to `effect_<head>`, and `effect_<head>` to the Mixbus's strip. Move the second effect
into the first's slot and read it again: the send connects to both clients and both to the strip. Add an audio chain with
a send to the Mixbus, then raise the send level and switch pre and post fader, and read the level at the strip's input
for each. Save a snapshot, load it, and read `jack_lsp -c` a third time.

