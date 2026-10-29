Zynthian and plugin-hostd
=========================

What this directory holds: the spike that put plugin-hostd under Zynthian ([spike-report.md](spike-report.md)), the
plan built on it ([offer.md](offer.md)), mod-ui's verbs on mod-host and on plugin-hostd ([verbs.tsv](verbs.tsv)), one
Zynthian chain written as a strip profile ([chain-profile.md](chain-profile.md)), what the jalv and mod-ui engines
give a chain ([engine-gaps.md](engine-gaps.md)), the order the work is offered upstream in, step by step
([upstream-series.md](upstream-series.md)), the Pi 5 stress run of grouped, alone and jalv hosting
([stress.md](stress.md)), the screens of the menus and MOD GUIs on the Pi 5 ([captures.md](captures.md)), and the raw
logs of every run ([evidence/](evidence/)). The tools
and tests are under [tools/zynthian/](../../tools/zynthian/).

Benchmarks, trade-offs and the acceptance report
------------------------------------------------

For a review of the zynthian-ui and zynthian-sys changes:

- [benchmarks.md](benchmarks.md): every measurement on the Pi 5 and in the containers, a table and a figure per topic,
  each row with the file it comes from; what is not measured yet, with the command that would measure it.
- [tradeoffs.md](tradeoffs.md): the pros and cons of one worker per chain, CLAP hosting, qualification and pins, the
  mod-host protocol, the packaging, and what is not done, each tied to a measurement or a public fact.
- [acceptance-report.md](acceptance-report.md): the report `bench/report/make_report.py` writes from the measurement
  files, with every section it has no data for marked "not measured yet".

The engine lives in the FreeMixer/zynthian-ui fork
--------------------------------------------------

The Zynthian engine is not kept here. It is the plugin-hostd engine of the fork
[FreeMixer/zynthian-ui](https://github.com/FreeMixer/zynthian-ui), branch `vangelis` (its default branch), on top of
zynthian/zynthian-ui `vangelis`. It provides:

- the engine `PH` (`zyngine/zynthian_engine_plugin_hostd.py`): LV2 and CLAP plugins, each processor one instance of a
  shared plugin-hostd daemon spoken to over the mod-host protocol, the daemon started with zynthian-sys's
  `plugin-hostd-start.sh`;
- LV2 plugins offered through plugin-hostd by default; a plugin plugin-hostd refuses stays on jalv, listed in its
  menu;
- the plugin menus ordered and tagged from the per-plugin qualification records, CLAP entries keyed by pin URI
  (`zyngine/zynthian_plugin_qualification.py`, `zyngine/zynthian_plugin_tiers.py`);
- chains synced through the daemon's planner (`plan`, `plan_get`, `plan_clear`): what runs together is the daemon's
  answer, and a Grouping entry in the processor options tells why a plugin runs alone
  (`zyngine/zynthian_plugin_hostd_grouping.py`); a grouped member, and a chain on the lv2-clap row, is one JACK client;
- CLAP parameters addressed by their number;
- the protocol read from the daemon's installed files, a missing file or name one clear refusal
  (`zyngine/zynthian_plugin_hostd_protocol.py`);
- a one-time converter of jalv snapshots to plugin-hostd (`tools/convert_snapshots_to_ph.py`);
- its tests against a fake plugin-hostd (`tests/` of the fork).

The spike's engine and the round trip
-------------------------------------

The spike wrote its engine, `zynthian_engine_plugind` with the chain module `zynthian_plugind_chain`, as a patch
against zynthian-ui `f46b0189b616`. The fork superseded it and the patch is no longer kept in this tree; it stays at
commit `b0190da1278f` of this repository (branch `devel/zynthian`), and every record under [evidence/](evidence/)
names it as it ran. The tools still drive plugin-hostd's chain verb through that engine:
[tools/zynthian/spike-engine.sh](../../tools/zynthian/spike-engine.sh) reads the patch from that commit (or from the
file `SPIKE_ENGINE_PATCH` names) and applies it to a worktree of zynthian-ui at the pinned commit.

The round trip, as the `zynthian-chain` CI job runs it, needs plugin-hostd with `chain_get`, omx-clap-host 0.21.0 or
later with omx-clap-host-tests, and omx-plugins (CLAP and LV2), from the FreeMixer channel, and a PipeWire with its
libjack:

    git clone https://github.com/zynthian/zynthian-ui /tmp/zynthian-ui
    export PLUGIN_HOSTD=/usr/bin/plugin-hostd CLAP_HOST=/usr/bin/omx-clap-host
    export JACK_IDENTITY=/usr/libexec/omx-clap-host/tests/jack_identity
    export FAULT_CLAP_URI='clap:/usr/libexec/omx-clap-host/tests/fault-14.clap#org.openmixer.fault.14'
    export CHAIN_FAULT_PARAM='param_set %d 0 0.95'
    tools/zynthian/chain-e2e.sh --round-trip /tmp/zynthian-ui /tmp/round-trip

It passes when the last line is `ROUND TRIP PASS: 0 failed`. `tools/zynthian/chain.sh` runs the chain's scenarios and
their sabotages offline against plugin-hostd and `tests/fake-host` (`make plugin-hostd tests/fake-host` first).
