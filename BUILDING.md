Building plugin-hostd
=====================

    make [MOD_HOST_DIR=<mod-host checkout>]

The protocol is mod-host's `libmod-host-protocol.so`, from `pkg-config
mod-host-protocol` when it is installed (mod-host's `make install-lib`),
otherwise from `MOD_HOST_DIR`, a mod-host tree where the library is built if
missing. The daemon needs libc and that library and nothing else.

The probe runner and the protocol generator also read omx-contract's C headers,
`<omxcontract/omx_contract_limits.h>` and `<omxcontract/omx_vocabulary.h>`, from
`pkg-config omx-contract` (`omx-contract-devel`, `libomx-contract-dev`, 3.4.0 or
later; `CONTRACT_CFLAGS=-I<dir>` for one that is not installed). The runner's
default rates are the contract's `ORACLE_FLOOR_RATES`, and the generator refuses
to build or run when the protocol's parameter scales are not the contract's
`PARAM_SCALES`. The probe output schema takes the words it shares with the
contract (`MEASUREMENT_LATENCY_METHODS`, `MEASUREMENT_VOICE_BASES`,
`MACHINE_CORE_BANDS`, `MACHINE_CLOCK_BANDS`, `RESOURCE_THREAD_SCHEDULING`) from
the vocabulary header: `protocol/probe-output.schema.in` names each as an
`@OMX_<ITEM>@` token and holds no list of its own. `make test-vocabulary` holds
each of those enums of the generated schema to the installed contract's
`omx-vocabulary.schema.json`, word for word and in order. `make
test-contract` checks both, against the installed contract and against a copy
of its header with the values changed. Nothing is linked: the header holds
values only.

Building without omx-clap-core
------------------------------

Nothing of omx-clap-core is needed to build the packages, only to run their checks: `omx-clap-host-tests` is a
`BuildRequires` inside `%if %{with check}` in the spec and a `Build-Depends` marked `<!nocheck>` in `debian/control`.

    rpmbuild -ba --without check packaging/plugin-hostd.spec
    dpkg-buildpackage -us -uc -b -Pnocheck

(`dnf builddep --without check` and `apt-get build-dep --build-profiles=nocheck` install the matching set.) `make
check-no-pins` fails if a build dependency on omx-clap-core appears outside the check stage.

Regenerating the protocol tables
--------------------------------

The tables in README.md marked `BEGIN GENERATED protocol:...`, the key list of the man page and
`protocol/plugin-hostd.json` are generated from `include/plugin-hostd/protocol.h`: `make gen` rewrites them and
`make check-generated` fails on any drift. `protocol/mod-host.json` is generated the same way from the mod-host
headers the build compiles against (`pkg-config --cflags mod-host-protocol`, or `MOD_HOST_DIR/src`), by
`tools/mod-host-json.py`; `make test-mod-host-json` checks that it follows them.

The daemon's verbs
------------------

The verbs the daemon adds to mod-host's protocol, and the codes they answer, are declared in `data/verbs.json`, a
`verbs` item of omx-contract's contract directory (schema 3.4.0 or later). `omx-contract render` writes them into
`include/plugin-hostd/plugin_hostd_host_verbs.h` and `plugin_hostd_vocabulary.h`, which are committed and which
`protocol.h` includes: `make render-verbs` rewrites them and `make check-rendered` fails on any drift. Both run the
`omx-contract` command (package `omx-contract`); the build itself does not. A refusal number omx-clap-host answers
too (mod-host's `-3` and `-902`, and the pin, parameter and note numbers) is named once, by omx-clap-core's
`reply.host.*` codes: `data/verbs.json` requires `omx-clap-core >= 0.22.0`, so both commands and
`make test-verbs-declared` read omx-clap-core's package of the contract directory (`omx-clap-core-contract`), or
the first directory of `OMX_CONTRACT_PATH` that holds one.

`make install-contract` installs `data/` as the package `plugin-hostd` of the contract directory. The noarch package
`plugin-hostd-contract` carries those files, and `plugin-hostd` and `plugin-hostd-devel` (`plugin-hostd-dev`) require
it at the same version.

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
`data/verbs.json` through the rendered header. `tests/verbs_contract.py` fails on a C string
that starts with one, and `tests/perturbation.py` renames a verb in a scratch
copy of `data/verbs.json` and of `mod-host.h` and requires the rebuilt daemon to answer the new name and
not the old.

    make test-jack OMX_CLAP_HOST=<omx-clap-host> [MOD_HOST=<mod-host> LV2_DIR=<lv2 path> LV2_URI=<a stereo effect> LV2_BUNDLE=<its bundle dir> LV2_PARAM=<a control taking 0.25>]

runs `tests/jack_e2e.sh`: the real workers behind the daemon, over jack inside
a PipeWire of its own (private user, net and pid namespace, torn down on
exit), with `tests/stress.clap` (a passthrough that crashes on a parameter
write, spins, keeps state). It kills workers and reads the graph and the audio
level of a neighbouring chain across the kill. Given omx-clap-host's meter fixtures
(`FAKE_COMPRESSOR_CLAP=/usr/libexec/omx-clap-host/tests/fake_compressor.clap JACK_METER_SOURCE=/usr/libexec/omx-clap-host/tests/jack_meter_source`,
installed by the omx-clap-host-tests package, which the spec and `debian/control` name as a build dependency of the check stage only, with a floor), it
also reads the meters of a CLAP compressor as `output_set` on the daemon's feedback port, before and after its
worker is killed.

Given `MOD_HOST` and a bundle, it also runs mod-host's scenario corpus against the daemon with an LV2 worker, and kills
an LV2 worker to read the graph and a parameter back. The CI job does this with the mod-host package of the FreeMixer
channel and this repository's fixture bundle: build `tests/plugin-hostd-fixture.lv2/plugin-hostd-fixture.so` and give
`MOD_HOST=/usr/bin/mod-host LV2_DIR=$PWD/tests LV2_URI=urn:plugin-hostd:test:stereo LV2_BUNDLE=plugin-hostd-fixture.lv2
LV2_PARAM=gain`. The world is the whole `tests/` directory on purpose: lilv warns about every entry that is no bundle
before mod-host says ready, and a worker must start behind that (#105).

    make test-jack2 OMX_CLAP_HOST=<omx-clap-host> [...]

is `test-jack` against JACK2's `jackd` (`-d dummy`) instead of pipewire's own jack implementation: the server
Zynthian runs. `JACK_SERVER=jackd` makes `tests/jack_e2e.sh` start a private `jackd` inside the same namespace,
wait for it with `jack_lsp`, and export `JACK_DEFAULT_SERVER` to it, before running the same `tests/jack_e2e.py`.
`JACK_SERVER=pipewire`, the default, is `test-jack` unchanged.

    make test-lv2-adapter OMX_CLAP_HOST_SRC=<omx-clap-core checkout> [MOD_HOST=<mod-host>]

runs `tests/lv2_adapter_e2e.py` in the same private namespace: the daemon in front of a real omx-clap-host and a real
mod-host (the one on `PATH` unless `MOD_HOST` names another). It builds `omx-clap-host` and its LV2 fixture bundle in
the checkout against this tree's headers, and `tests/lv2_fixture.c` into `tests/plugin-hostd-fixture.lv2`. It checks
that `lv2_worker omx-clap-host` runs an LV2 plugin through the adapter; that a plugin the adapter refuses answers
`-512`, with the event naming the `hosting.*` code from the reply to that add, also in a pool worker whose log several
plugins share; that `auto` runs a refused plugin on mod-host; and that a plugin no bundle holds for the adapter, which
it answers `-101`, is not found under `omx-clap-host` and is looked for by mod-host under `auto`, with no event in
either case. It also checks that a tempo set before a kill is handed to the respawned omx-clap-host, and that the note
verbs reach it and come back as it answered them, and are answered `-514` by the daemon for a plugin on mod-host. Where
omx-clap-host does not take them yet (a tempo, FreeMixer/omx-clap-core#88; the notes, FreeMixer/omx-clap-core#122) the
case prints `PENDING` with the issue and checks what the worker answers today. Without `OMX_CLAP_HOST_SRC` the target
prints `skip test-lv2-adapter` and does nothing else.

`make test-probe` runs the probe runner over `tests/probe-child` and `tests/lv2-probe-child`, stand-ins that print the
lines of plugin-qualify's prober and `lv2_measure`. With `PLUGIN_QUALIFY_BUILD=<plugin-qualify checkout>/native/build`
(`make -C native all` there) it also runs the real ones over plugin-qualify's instrument fixtures: a CLAP synth timed
holding `--probe-notes` at every rate of omx-contract's `ORACLE_FLOOR_RATES`, and an LV2 synth that allocates on a note
beside its clean twin. Without it those tests print `skip`.

`make sabotage` (`tests/sabotage.py`) breaks the daemon on purpose, one guard at a time, and
requires the named test to go red. The arms run side by side, `SABOTAGE_JOBS` at a time (default: the cores
the process may use, at most 8), each in a directory of its own with its own range of test ports, and print in the
order of the table; `SABOTAGE_JOBS=1` runs them one after the other. `SABOTAGE_KIND=<kind>` and `SABOTAGE_ONLY=<words>`
run some of them.

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

The tempo, the metre and the transport (`set_bpm`, `set_bpb`, `transport`, `transport_sync`) are the daemon's, not an
instance's: the latest line of each is kept, and every worker is handed them before anything else, when it is first
started and when it is respawned. Notes (`note_on` and the rest) are never kept.

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
