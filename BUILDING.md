Building plugin-hostd
=====================

    make [MOD_HOST_DIR=<mod-host checkout>]

The protocol is mod-host's `libmod-host-protocol.so`, from `pkg-config
mod-host-protocol` when it is installed (mod-host's `make install-lib`),
otherwise from `MOD_HOST_DIR`, a mod-host tree where the library is built if
missing. The daemon needs libc and that library and nothing else.

Regenerating the protocol tables
--------------------------------

The tables in README.md marked `BEGIN GENERATED protocol:...`, the key list of the man page and
`protocol/plugin-hostd.json` are generated from `include/plugin-hostd/protocol.h`: `make gen` rewrites them and
`make check-generated` fails on any drift. `protocol/mod-host.json` is generated the same way from the mod-host
headers the build compiles against (`pkg-config --cflags mod-host-protocol`, or `MOD_HOST_DIR/src`), by
`tools/mod-host-json.py`; `make test-mod-host-json` checks that it follows them.

Tests
-----

    make test

runs the daemon against `tests/fake-host`, a worker that speaks the same
protocol and dies, hangs or refuses on cue: placement, forwarding, the
ledger, replay to the byte, attribution, quarantine, the storm bound,
`worker_env`, pins, and the verb table against mod-host's README; `tests/pin_test.c` holds
`include/plugin-hostd/pin.h` to the FIPS 180-2 examples and to layout bytes hashed elsewhere. No jack, no plugin.

The verbs are read from their declarations, never spelled: mod-host's from the
command formats of `mod-host.h`, the daemon's own from
`include/plugin-hostd/protocol.h`. `tests/verbs_contract.py` fails on a C string
that starts with one, and `tests/perturbation.py` renames a verb in a scratch
copy of each header and requires the rebuilt daemon to answer the new name and
not the old.

    make test-jack OMX_CLAP_HOST=<omx-clap-host> [MOD_HOST=<mod-host> LV2_DIR=<lv2 path> LV2_URI=<a stereo effect> LV2_BUNDLE=<its bundle dir> LV2_PARAM=<a control taking 0.25>]

runs `tests/jack_e2e.sh`: the real workers behind the daemon, over jack inside
a PipeWire of its own (private user, net and pid namespace, torn down on
exit), with `tests/stress.clap` (a passthrough that crashes on a parameter
write, spins, keeps state). It kills workers and reads the graph and the audio
level of a neighbouring chain across the kill. Given omx-clap-host's meter fixtures
(`FAKE_COMPRESSOR_CLAP=<tree>/tests/fake_compressor.clap JACK_METER_SOURCE=<tree>/tests/jack_meter_source`), it
also reads the meters of a CLAP compressor as `output_set` on the daemon's feedback port, before and after its
worker is killed.

    make test-jack2 OMX_CLAP_HOST=<omx-clap-host> [...]

is `test-jack` against JACK2's `jackd` (`-d dummy`) instead of pipewire's own jack implementation: the server
Zynthian runs. `JACK_SERVER=jackd` makes `tests/jack_e2e.sh` start a private `jackd` inside the same namespace,
wait for it with `jack_lsp`, and export `JACK_DEFAULT_SERVER` to it, before running the same `tests/jack_e2e.py`.
`JACK_SERVER=pipewire`, the default, is `test-jack` unchanged.

`make sabotage` (`tests/sabotage.py`) breaks the daemon on purpose, one guard at a time, and
requires the named test to go red.

How the daemon keeps and replays state
======================================

Per instance, in memory: the `add` line, then the state-changing verbs as
sent, as text (`param_set`, `patch_set`, `preset_load`, `bypass`,
`param_monitor`, `monitor_output`, the `midi_`, `cc_` and `cv_` maps), a repeat of the same
setting replacing the earlier one, a `preset_load` dropping the parameter
writes before it; and the `connect`s that name the instance's jack client.
After a `preset_load` or `patch_set`, and after a quiet interval, it asks the
worker for `state_save <dir>` into one checkpoint directory of its own and,
for an instance whose state file is there, drops the verbs the state now
holds.

A worker that dies is respawned after a backoff, and each instance is put
back: `add`, one `state_load` of the checkpoint directory, the verb tail,
the connections (a connect the new client cannot make yet, because the peer's port has not reached it, is asked again by
the idle tick for `connect_retry_ms`). What a plugin held in RAM and exposed through no verb (a
reverb tail) is lost.

Who is blamed: a death with a command on the wire names that command's
instance. A death in a callback of a pool cannot be named from outside, so
the pool is split, each member into a worker of its own, and the one that
dies again is named (`instance_quarantined`) and stays own. In a worker of
one instance the death is that instance's. `storm_deaths` deaths inside `storm_window_ms` end
respawning for that placement only (`supervisor_gave_up`); its neighbours are
not touched.

The last verb is a suspect
--------------------------

A plugin that aborts in a callback dies after it answered `resp 0`, so the verb that killed it is in the ledger and
the respawn would play it again until the storm bound ends it. For `suspect_window_ms` after a reply (a setting, above: the
test plugins die 30 ms after it, and the daemon sees the death 40 to 100 ms later) the last verb the ledger kept, of
the instances of a worker, is a suspect. A worker that dies inside the window, of a crash or an exit and not of a
SIGKILL or SIGTERM from outside, has that verb taken out of the ledger: the value it replaced comes back, or the
parameter goes to the plugin's own, and the event `instance_verb_dropped <instance> suspect:<ms> <command>` names it,
`<ms>` being the age of the reply when the death was seen. The instance that sent it is blamed like the one whose
command was in flight: its crash is counted, and in a pool it is quarantined and leaves the pool alone. A death
outside the window replays everything, as before.
