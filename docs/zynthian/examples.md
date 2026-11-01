Usage examples
==============

Three things to do with plugin-hostd under Zynthian, each with the steps, what you get and its limits. The figures are from the
[benchmarks](benchmarks.md), and what is proven on the device is on the [status page](status.md). Through Zynthian's own engine,
grouping has passed its proof on the Pi on omx-clap-host 0.25.4 and zynthian-ui's fork at
[76b5e106](https://github.com/FreeMixer/zynthian-ui/commit/76b5e106); chains built from the menu with it are still to be measured.

A group: plugins in series in one worker
----------------------------------------

A run of plugins in series shares one worker process and one JACK client, instead of one process each.

To see it on the daemon, install the packages as in [Use plugin-hostd in your own host](../own-host.md), then:

    send() { printf '%s\0' "$1" | nc -w3 127.0.0.1 5555 | tr '\0' '\n'; }
    echo 'require_pins 0' > plugin-hostd.conf     # for this try: no plugin here has a pin
    jackd -r -d dummy -r 48000 -p 256 >/dev/null 2>&1 & sleep 2
    plugin-hostd -n -p 5555 -c plugin-hostd.conf >plugin-hostd.log 2>&1 & sleep 2
    send "add clap:/usr/lib/clap/omx-eq8.clap#org.openmixer.eq8 0"          # resp 0
    send "add clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp 1"        # resp 1
    send "add clap:/usr/lib/clap/omx-limiter.clap#org.openmixer.limiter 2"  # resp 2
    send "worker_list"                                                      # three workers, place own
    send "chain 1 0 1 2"                                                    # resp 0
    send "chain_get 1"                                                      # resp 0 w4 0,1,2 0,1,2
    send "worker_list"                                                      # one worker, place chain
    jack_lsp | cut -d: -f1 | sort -u                                        # effect_0 and system
    send "chain_clear 1"                                                    # back to a worker each

These lines were run as written in a clean debian:trixie container, with plugin-hostd 0.15.6 and omx-clap-host 0.25.3; on that release a value set before `chain` was lost, as 0.25.4 fixes, so have 0.25.4. With
pins on, the default, `chain` answers -501 for a plugin whose pin does not say it may share a worker.

What you get, 24 LV2 plugins in series (omx comp, delay and drive in turn) on a Pi 5 at 48000 Hz and 256 frames, on a private
dummy JACK server, three repeats, medians ([all rows](benchmarks.md#current-versions-chains-up-to-24-plugins)):

| | processes | JACK clients | JACK DSP | PSS |
|---|---|---|---|---|
| grouped | 2 | 1 | 13.51 % | 61.1 MB |
| mod-host | 1 | 26 | 15.51 % | 112.1 MB |
| jalv | 24 | 24 | 19.23 % | 993.6 MB |

Time to add the 24, with the add into the chain: 435 ms, against mod-host's 749 ms ([rows](benchmarks.md#time-to-add-and-the-same-chain-with-the-add-into-the-chain)).

Ten third-party plugins in a group share one worker and keep ten JACK clients. That saves memory (45.0 MB against
89.3 MB under mod-host and 463.6 MB under jalv) ([rows](benchmarks.md#current-versions-chains-up-to-24-plugins)).

Under Zynthian, the setting is `grouping on` in `/zynthian/config/plugin-hostd.conf`, and the UI restarted. It is off unless
you set it. A group is then what your chain has in series with nothing between: a parallel slot, the mixer strip or a jalv
plugin ends it ([the table](mixbus.md#how-a-plugin-behaves-in-a-mixbus)). A processor that runs alone has a Grouping entry in
its options saying why.

A limit:

- On plugin-hostd 0.15.4 the group did not form within 20 s in one of four cells at 18 plugins and on one repeat at 32 and at
  48. On 0.15.5 it formed in all six cells at 18 and in every repeat up to 24; there is no newer row at 32 or 48.

A channel strip as plugins
--------------------------

EQ and dynamics per chain are ordinary effects in that chain. `zynmixer` does not change: it keeps its level, pan and sends,
and the plugins are processors like any other. There are two equal ways. In both, with the plugin-hostd engine on
(`ZYNTHIAN_PLUGIN_ENGINE=plugin-hostd` in `/zynthian/config/zynthian_envars.sh`, then restart the UI), select the chain, open its
options and use `Add Audio-FX processor`; a plugin's entry ends in "(PH)". Its controller pages follow its own sections.

**Separate plugins: omx keyed-gate, omx eq8, omx comp.** You pick each one and its order, and eq8 has eight bands. Each is one
more load and, unless they are grouped, one more worker per chain.

**One plugin: omx strip.** One load and one worker per chain, on any host, CLAP or LV2. It holds input trim, filters, a gate, four
EQ bands and a compressor, in stereo. The design is fixed: those five stages, each with its own switch, though its Order
parameter puts them in any order.

What it costs, from qualification at 48000 Hz and 512 frames, CLAP, median per block
([table](benchmarks.md#cost-and-the-grid-gap)): omx strip 5.89 us; omx eq8 4.39 us and omx comp 6.96 us, 11.35 us together with
eight EQ bands against four. omx keyed-gate is 17.85 us more. These are plugins alone, not a chain measured as a chain.

What you get: on the Pi, omx eq8 from the menu, its pages, its Factory and User banks and a saved user preset are
[captured](captures.md#omx-eq8-retaken-on-omx-plugins-0-16-0) and [read back](digital-proofs.md#presets-factory-and-user-banks).

Limits:

- Neither way has a mixing-strip test yet, across a set of chains, and omx strip has not been tried from the menu.
- A preset on a running CLAP omx eq8 loads on the daemon on omx-clap-host 0.25.4 and has not been retried from the menu.

Shared effects on a Mixbus
--------------------------

One effect on a bus instead of one per chain, sent to from each chain with Zynthian's own sends. The steps, the figures and the limits
are on the Mixbus page: [one reverb and delay on a bus](mixbus.md#example-one-reverb-and-delay-on-a-bus).
