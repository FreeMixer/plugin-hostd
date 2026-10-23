# Presets in the host

The ruling "PRESETS IN THE HOST" of 2026-10-22 on plugin-hostd#131, as this tree builds it. The schema is
[protocol/preset.schema.json](../protocol/preset.schema.json); `tests/preset_format.py` holds it to the examples below.

## Who owns what

- The **worker** (omx-clap-host for CLAP, its LV2 adapter for LV2) holds the instance, so it owns the primitives: list
  the plugin's own presets, load one, write the instance to a file, load a file.
- The **daemon** relays the verbs to the worker that holds the instance and passes its answer back; it answers -902
  only while the worker does. Before a file reaches a worker it reads it and refuses one that is not a preset file of
  a version it knows (`PRESET_INVALID`) or that names another plugin (`PRESET_PLUGIN_CHANGED`), so no worker guesses at
  a format. After a `preset_save` the worker answered it reads the file back, and refuses one that breaks the format.
- The **consumer** (the console, the Zynthian engine) owns the library: where files live, the user's presets, rename,
  delete, banks. The host never decides a path or a name: both arrive as arguments.

MIDI learn is policy of the surfaces: the host answers `midi_learn`, `midi_map`, `midi_unmap`, `cv_map` and `cv_unmap`
only as the mechanism, and the host verb table keeps them optional for every profile.

## Verbs

| verb | arguments | reply |
| --- | --- | --- |
| `preset_list` | `<instance>` | `resp <count>`, then `preset_get <instance> <index>` one row each |
| `preset_load` | `<instance> <stable name \| file path>` | `resp 0` |
| `preset_save` | `<instance> <file path> <name>` | `resp 0`: the worker wrote the file |
| `preset_show` | `<instance> <stable name \| file path>` | `resp 0 <carries> <name>` |

A file path is absolute (it starts with `/`); any other word is a stable name of the plugin's own presets, the
`load_key` of `preset_get`. The name of `preset_save` is the rest of the line, quoted when it holds a space. A
`preset_show` whose first argument is no instance number is mod-host's form and goes to every worker as before.
`bundle_add` and `bundle_remove` stay as declared.

### Refusals

| code | name | who | when |
| --- | --- | --- | --- |
| -523 | `PRESET_NOT_OFFERED` | worker | a stable name the plugin does not offer, or a plugin with no preset system and no state |
| -524 | `PRESET_INVALID` | daemon, worker | a path that is not absolute, a `preset_save` with no name, a file that cannot be read, is empty or over 64 MiB (`PHD_PRESET_FILE_MAX`), is no JSON, is of an unknown format version, or breaks the schema; the file a worker wrote for `preset_save` that breaks it |
| -525 | `PRESET_NEEDS_STATE` | worker | a file that carries state for a worker that cannot take state yet; it disappears when every worker takes state |
| -526 | `PRESET_PLUGIN_CHANGED` | daemon, worker | the file's plugin id is not the instance's (the daemon), or its version or fingerprint (the worker) |
| -527 | `LOAD_REFUSED` | worker | the plugin refused the state or the preset (its load callback failed) |

## The file: org.openmixer.preset

The console's format, extended additively. `/1` stays valid and is params-only: our own plugins and their factory
presets never change. A file with a state body is `/2`.

| field | | meaning |
| --- | --- | --- |
| `format` | required | `org.openmixer.preset/1` or `org.openmixer.preset/2`; any other is refused, never guessed |
| `plugin.id` | required | the plugin's id: the CLAP id, or the LV2 uri; a /1 may give `plugin` as the id alone, a string, as the factory presets of omx-plugins do |
| `plugin.version` | required in /2 | the plugin's version as its descriptor says |
| `plugin.fingerprint` | required in /2 | the descriptor fingerprint: the plugin's layout pin, `omx-layout/1:<sha256>`; a fingerprint of a scheme this version does not know is refused |
| `id` | required | stable, minted by the consumer; a worker writing a file names it after the file (its name without `.json`) |
| `name` | required | display, free text, editable on user presets only |
| `alias` | optional | a short label, at most 12 characters, for small displays (a scribble strip); absent means derive from `name` |
| `bank`, `tags`, `description` | optional | the consumer's |
| `createdAt`, `modifiedAt` | optional | ISO 8601 UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `carries` | required in /2 | `params`, `params+state` or `state` |
| `params` | | `[{symbol, unit, value}]`: plain values, written as the plugin gave them, never a float widened |
| `state` | | `{encoding: "base64", context, bytes, files?}`; `context` is `preset` or `project` for CLAP (the clap.state context), `lv2` for LV2; `files` `[{name, encoding, bytes}]` are LV2 state paths, a file name each |

The writer picks `carries`: `params` when the plugin has only declared parameters, otherwise `state` (`params+state`
when both are read). `carries` and the body agree: `params` has `params` and no `state`, `params+state` both, `state`
a `state`. Unknown fields are kept on rewrite.

A params-only file of /2:

```json
{"format": "org.openmixer.preset/2",
 "plugin": {"id": "org.freemixer.comp", "version": "1.2.0",
            "fingerprint": "omx-layout/1:0000000000000000000000000000000000000000000000000000000000000000"},
 "id": "warm", "name": "Warm Pad", "createdAt": "2026-10-22T21:00:00Z", "modifiedAt": "2026-10-22T21:00:00Z",
 "carries": "params", "params": [{"symbol": "gain", "unit": "dB", "value": -3.25}]}
```

A state file adds `"carries": "params+state"` and
`"state": {"encoding": "base64", "context": "preset", "bytes": "AAEC"}`.

## Loading a file

1. The daemon reads the file and checks it against the format above (`PRESET_INVALID` when it does not hold), then
   its plugin id against the instance's, the add's uri with no `clap:` or `lv2:` prefix (`PRESET_PLUGIN_CHANGED`); no
   worker is asked.
2. The worker compares the plugin's version and fingerprint with the instance's: another answers
   `PRESET_PLUGIN_CHANGED` and nothing is applied.
3. The worker applies the state body when the file carries one, then the parameter values, each clamped to its
   declared range, an unknown symbol ignored, as clap.state's load does.

Parameter feedback (the `param_set` event a worker writes for a value the plugin moved by itself, a preset load
included) is the declared event of protocol/plugin-hostd.json; a controller's own writes produce none.

## What this tree builds

The daemon's side, in `src/presets.c` (the check of a file) and `sup_preset_verb` in `src/supervisor.c` (the relay):

- `preset_load`, `preset_save` and `preset_show` of an instance: the checks above, then the line as it came to the worker
  that holds the instance, and its answer back. `preset_show <uri>` with no instance goes to every worker, as before.
- `preset_list` and `preset_get`: relayed to a worker that answers the instance verbs; an instance of mod-host is
  answered `NO_PRESET_LIST` (-515) by the daemon.
- The checks are held to the schema: `tests/preset_conformance.py` runs the daemon's check (`tests/preset-check`) over
  the files of `tests/fixtures/presets`, every broken copy `tests/preset_format.py` refuses, and the factory presets of
  omx-plugins (from `OMX_PLUGINS_DIR`, a checkout beside this one, or fetched; skipped with its reason when none can be
  read). `tests/daemon_test.py` saves a preset, loads it back and reads the values, and refuses a file of a changed
  plugin, an oversize file and a broken one with no worker asked, through `tests/fake-host`.

The worker's side (writing and reading the file in omx-clap-host and its LV2 adapter, the clap.preset-load and
clap.state calls, the version and fingerprint check, `PRESET_NOT_OFFERED`, `PRESET_NEEDS_STATE`, `LOAD_REFUSED`) is not
in this tree: `tests/fake-host` stands in for it here.
