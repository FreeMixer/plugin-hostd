# The host verb table, the daemon's half of it, and the declared limits

Status: built on cluster/plugin-hostd-131-cluster (#131). Ruled by the operator 2026-10-21 as part of the strip
declaration. The starting values come from docs/zynthian/verbs.tsv on devel/zynthian: mod-ui's 35 host verbs as an
LV2 worker and a CLAP worker answered them.

## The table

`PHD_HOST_VERBS` in include/plugin-hostd/protocol.h, written to protocol/plugin-hostd.json as `host_verbs`. The key
`verbs` already holds the daemon's own verbs, so the mod-ui verbs get a table of their own. Each row is one verb mod-ui
sends and one word for each profile:

| word | the answer the daemon serves |
|---|---|
| `required` | not a refusal: a `resp` code of 0 or more |
| `optional` | any answer; a refusal is allowed |
| `absent` | a refusal, on purpose: the verb has no meaning here |

The profiles:

- `lv2`: the instance's worker is the lv2 row (mod-host).
- `clap`: the instance's worker is the clap row (omx-clap-host).
- `console`: openmixer's console, which runs both rows at once. A verb that names no instance is sent to every
  worker, and the daemon answers the worst reply, so the console's answer is the lv2 and clap answers together.

The three columns start out equal. The operator's list:

- required: add, remove, bypass, connect, param_set, state_load, state_save, state_tmpdir, feature_enable,
  bundle_add, bundle_remove, preset_load, preset_save, preset_show, transport, transport_sync, cpu_load
- optional: midi_learn, midi_map, midi_unmap, cv_map, cv_unmap, monitor_midi_program, monitor_output,
  output_data_ready, patch_get, patch_set
- absent on purpose: cc_map, cc_value_set, cc_unmap (no Control Chain), hmi_map, hmi_unmap (no MOD HMI),
  show_external_ui, set_midi_program_change_pedalboard_bank_channel and
  set_midi_program_change_pedalboard_snapshot_channel (commented out in Zynthian's mod-ui and never sent)

## Who answers what

A required verb is served when two things hold: the worker does its part, and the daemon does its part. The
contract test (tests/host_verbs_contract.py) checks the daemon's part. Its workers are tests/fake-host. Under
`FAKE_WORKER=omx-clap-host` the fake refuses the verbs omx-clap-host refuses that are the daemon's to cover. For the
other verbs it answers as a worker that meets the table. Whether the real omx-clap-host meets its part is owed by
omx-clap-core (listed below). Its own contract test should read this same table.

These are the daemon's part, from the tsv's last column:

- `bundle_add` and `bundle_remove` are kept, as the set of bundles added and not removed. Each worker of a row that
  loads LV2 bundles (lv2) is given them when it starts. Today a worker started after a `bundle_add` never hears it,
  and a user preset of that bundle then fails with -105.
- `state_tmpdir` is kept, the latest line, and handed to each such worker when it starts.
- These three go only to the workers of a row that loads LV2 bundles. An LV2 bundle or an LV2 state directory does
  not concern a CLAP worker, so the daemon answers for it. With no such worker up, the answer is 0 and the line is
  kept for the next worker.
- `feature_enable` is kept, the latest line per feature, and handed to every worker when it starts. Today a worker
  started later never hears it. It still goes to every worker. If a CLAP worker refuses `processing`, that refusal
  is the answer: the daemon does not answer 0 for audio it cannot stop.

These are owed by omx-clap-host, one omx-clap-core issue each. This lane could not file them because the pod has
no GitHub token. Each item below is the body of its issue, and the tsv rows hold the evidence:

- `connect`: mod-ui writes LV2 port symbols, and the CLAP worker names its ports otherwise (-205 for 22 of 24).
  The CLAP plugin needs an LV2 description first: omx-clap-host, or a generator over `omx-clap-scan --json`.
- `param_set` by symbol: one symbol per CLAP parameter, the symbols an LV2 description of the plugin would carry
  (-103 for all 40 in the replay).
- `state_load`: load the instance's CLAP state from the pedalboard directory (-105).
- `preset_load`, `preset_save`, `preset_show`: CLAP preset-load, and writing the state as a preset file (-902).
- `feature_enable processing`: answer it (-902).
- `state_tmpdir`: optional for omx-clap-host now, because the daemon answers for it.

Not built here. A pedalboard's `connect` through mod-monitor needs plugin-hostd to open the JACK client named
mod-host itself and load mod-monitor.so. That is a JACK client in the daemon, which this change does not add.

## Limits, declared once

These are rows of `PHD_CONSTANTS`, written to the JSON's `constants` and to README's constants table:

- `line_words_max` 64: the words of one command line the daemon reads. verbs.c reads its token array size from it.
- `chain_members_min` 1: a chain of one is valid, so an isolated plugin's trip is a chain of one. The floor of 1
  overrides #101's draft of 2. #101's chain lives on wave/contract-one-pass (its refusal of "fewer than two
  instances" and its codes -518 to -522), not on main. When it lands it reads this constant.
- Pool members: `pool_max`, default 8 (`PHD_DEFAULT_POOL_MAX`), is already a declared default. It applies to each
  pool, and a pool belongs to one format.

The chain codes are not declared again here. They are #101's, on wave/contract-one-pass, and a second
declaration on main would fork them.
