# Presets in the host

The ruling "PRESETS IN THE HOST" of 2026-10-22 on plugin-hostd#131, as this tree builds it. The schema is
[protocol/preset.schema.json](../protocol/preset.schema.json); `tests/preset_format.py` holds it to the examples below.

## Who owns what

- The **worker** (omx-clap-host for CLAP, its LV2 adapter for LV2) holds the instance, so it owns the primitives: list
  the plugin's own presets, load one, write the instance to a file, load a file.
- The **daemon** relays the verbs to the worker that holds the instance and passes its answer back; it answers -902
  only while the worker does. Before a file reaches a worker it reads it and refuses one that is not a preset file of
  a version it knows (`PRESET_INVALID`), so no worker guesses at a format.
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
| `preset_show` | `<instance> <stable name \| file path>` | `resp 0 <json>`: what a load would apply, on one line of JSON (below) |

The reply of `preset_show` is `resp 0 <json>`, one shape on every worker and through the daemon, which passes the worker's
line on unchanged: the rest of the line after `resp 0 ` is one JSON object on one line. For a file it is the document with
each state body's `bytes` replaced by its decoded `size`; for a listed preset (a stable name) it holds `name`, `loadKey`
and `location`. It is not `resp 0 <carries> <name>`: `carries` and `name` are fields of that object.

A file path is absolute (it starts with `/`); any other word is a stable name of the plugin's own presets, the
`load_key` of `preset_get`. The name of `preset_save` is the rest of the line, quoted when it holds a space. A
`preset_show` whose first argument is no instance number is mod-host's form and goes to every worker as before.
`bundle_add` and `bundle_remove` stay as declared.

### Refusals

| code | name | who | when |
| --- | --- | --- | --- |
| -523 | `PRESET_NOT_OFFERED` | worker | a stable name the plugin does not offer, or a plugin with no preset system and no state |
| -524 | `PRESET_INVALID` | daemon, worker | a path that is not absolute, a `preset_save` with no name, a file that cannot be read, is no JSON, is of an unknown format version, or breaks the schema |
| -525 | `PRESET_NEEDS_STATE` | worker | a file that carries state for a worker that cannot take state yet; it disappears when every worker takes state |
| -526 | `PRESET_PLUGIN_CHANGED` | worker | the file's plugin id, version or fingerprint is not the instance's |
| -527 | `LOAD_REFUSED` | worker | the plugin refused the state or the preset (its load callback failed) |

## The file: org.openmixer.preset

The console's format, extended additively. `/1` stays valid and is params-only: our own plugins and their factory
presets never change. A file with a state body is `/2`.

| field | | meaning |
| --- | --- | --- |
| `format` | required | `org.openmixer.preset/1` or `org.openmixer.preset/2`; any other is refused, never guessed |
| `plugin.id` | required | the plugin's id: the CLAP id, or the LV2 uri |
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

1. The daemon reads the file and checks it against the format above (`PRESET_INVALID` when it does not hold); no
   worker is asked.
2. The worker compares `plugin` with the instance: another id, version or fingerprint answers `PRESET_PLUGIN_CHANGED`
   and nothing is applied.
3. The worker applies the state body when the file carries one, then the parameter values, each clamped to its
   declared range, an unknown symbol ignored, as clap.state's load does.

Parameter feedback (the `param_set` event a worker writes for a value the plugin moved by itself, a preset load
included) is the declared event of protocol/plugin-hostd.json; a controller's own writes produce none.
