The format tables: how a scan becomes a descriptor
===================================================

plugin-hostd turns what a CLAP or LV2 plugin states about itself into a `scanned` descriptor (omx-contract
`docs/descriptors.md`). Three layers do it, and each is one thing:

| Layer | What | Where |
|---|---|---|
| L1 description | one mapping table per format, data: every field a scan reads, mapped to a descriptor word, carried in the extension bag, or dropped by a named decision | `data/formats/clap.json` (`PLUGIN_HOSTD_CLAP_MAP`), `data/formats/lv2.json` (`PLUGIN_HOSTD_LV2_MAP`), item kind `formatMap` |
| L2 transforms | a closed list of named functions, each with its inverse, which a table names and never defines | `src/transforms.h` (`TRANSFORMS(X)`), `src/transforms.c` |
| L3 runtime | the field dump of one plugin, read as a host reads it | omx-clap-core's `omx-clap-scan --fields` |

`plugin-hostd-probe describe` joins them: it runs the dump in an isolated child, applies the table and its transforms,
and writes the descriptor. The same tables, read backwards, are what omx-plugins' generators write a CLAP face and an
LV2 `.ttl` from: one vocabulary, two directions, and the round trip (author, generate both faces, scan back, compare)
is the proof.

## The tables

`make install-contract` installs both tables, with omx-contract-devel's `install-contract-dir.sh`, as the package
`plugin-hostd` of the contract directory: `<contractdir>/3/plugin-hostd/formats/{clap,lv2}.json`, with its
`MANIFEST.json`, beside the daemon's verbs (`verbs.json`). The noarch package plugin-hostd-contract
(`plugin-hostd-contract` on Debian too) ships them, and a program that reads them at run time requires it.
It requires omx-contract 3.2.0 or later (`Requires`, Debian `Depends`): the tables live in omx-contract's contract
directory and are read against its schema, and 3.2.0 is the first whose source field takes an index
(`omx_clap_panel_display.meter_ids[0]`), so an older omx-contract never sits beside a table it refuses.

`make check-contract-dir` installs the package into a staging directory and runs `omx-contract validate` over it
together with the installed contract directory (omx-contract's own tables, omx-clap-core's): red on any table the
installed schema refuses, and red, never a skip, when the `omx-contract` command is absent. The coverage test below
walks the schema for the words only, never for the row keys; this gate reads every key as a reader of the installed
directory does.

A table's `rows` are keyed by the source field, and each row has exactly one class:

| Class | Carries | Meaning |
|---|---|---|
| `word` | `{ word, transform, values? \| factor? }` | the descriptor word it becomes (`controls[].travel.unit`), the transform that converts it (a name of `TRANSFORMS(X)`) and that transform's data: `values` for `lookup`, `factor` for `scale-by`. Never code |
| `extension` | `true` | carried verbatim into the descriptor's `extensions.<format>.<field>` (a record of a control's or a port's scope under `<scope>/<field>`) |
| `dropped` | `{ ruling }` | left out, by the decision it names: a spec path and section, or the TERM's own `out-of-scope` mark |

Each row names what it covers, one of two: `term`, a TERM of omx-contract's format files (`LV2_UNITS_TERMS#unit`), or
`from`, the header or specification link of a field no TERM file lists (the CLAP struct fields and `clap_entry`,
`rdf:type`, `rdfs:comment`, `rdfs:seeAlso`, `doap:name`, `doap:license`).

### Field names

The key of a row is the field as the dump names it:

- a CLAP TERM: its `id` (`CLAP_PARAM_IS_STEPPED`, `CLAP_EXT_LATENCY`, `CLAP_PLUGIN_FEATURE_DELAY`);
- a CLAP struct field: `<struct>.<member>` as the headers spell them (`clap_param_info.min_value`), or
  `<struct>.<function>` for what a call returns (`clap_plugin.get_extension`, `clap_plugin_params.value_to_text`);
- an LV2 TERM: `<prefix>:<term>`, the term's own name under the prefix of its specification (`units:db`,
  `lv2:toggled`, `pg:group`, `units:units.lv2` for the specification itself);
- any other LV2 predicate: its usual CURIE (`rdf:type`, `rdfs:comment`, `doap:name`).

The LV2 prefixes: `lv2` lv2core, `atom`, `bufsz` buf-size, `da` data-access, `dman` dynmanifest, `ev` event,
`ia` instance-access, `log`, `midi`, `morph`, `opts` options, `param` parameters, `patch`, `pg` port-groups,
`pprops` port-props, `pset` presets, `rsz` resize-port, `state`, `time`, `ui`, `units`, `urimap` uri-map, `urid`,
`work` worker; and `rdf`, `rdfs`, `doap`, `foaf` for the W3C and DOAP vocabularies.

### Field rows and value rows

Some TERMs are fields (`lv2:minimum`, `units:unit`); others are values a field takes (`units:db` is a value of
`units:unit`, `lv2:toggled` of `lv2:portProperty`, `CLAP_PARAM_IS_STEPPED` of `clap_param_info.flags`). Every TERM has
its row either way. A record of the dump is resolved in this order:

1. when its value is the key of a row (a value row): a `word` row converts it, a `dropped` row drops it, an `extension`
   row says the value has no word of its own and defers to the field's row;
2. otherwise the field's row: a `word` row converts the value (a `lookup` that has no entry for it carries the value
   in the bag instead), an `extension` row carries it in the bag, a `dropped` row drops it;
3. a field with no row at all is refused: `describe` names it and writes no descriptor.

A value row's `lookup` holds its own pair (`units:db` -> `dB`): the unit rows are the same correspondence as
omx-plugins' `LV2_UNITS` (`tools/gen.mjs`), and where the TERM file names the unit's word the row maps to that word,
which the coverage test holds.

### What a table drops

A row is `dropped` only by a decision it names. The TERMs omx-contract marks `out-of-scope` are dropped by that mark,
which the row quotes. A field this section rules out is dropped by `docs/formats.md#what-a-table-drops`:

- a runtime handle that is no fact of the plugin (`clap_param_info.cookie`, a pointer the host passes back);
- every field of the panel description (`omx_clap_plugin_panel_description.*` and the `omx_clap_panel_*` structures of
  omx-clap-core's `omx_clap_ext.h`): the panel travels whole, as the scan's `panel` object, by `panel_get`
  ([panel.md](panel.md)), and the descriptor carries none of it. A panel field's row is a drop and nothing else;
  `describe` refuses a table that makes one a word or the bag.

A TERM omx-contract marks `used` is never dropped: its row is a word or the bag.

### Outbound-read rows

A generator reads a value row of a table to write a face: the TERM is a value (not a `property`) and omx-contract
lists omx-plugins among its users (`by`). Such a row's transform is `identity` or `lookup`, the two a generator applies
by reading the table alone; what is structure (scale points, groups, module paths) stays in the generator's code.

## The transforms

`src/transforms.h` declares the closed list as one X-macro, `TRANSFORMS(X)`: the name a table writes, the inbound
function (format to descriptor) and its inverse (descriptor to format), all prefixed `transforms_`. A value crosses as
text: a JSON literal on the descriptor side (`-60`, `"dB"`, `true`, `["Filter","Envelope"]`), the dump's text on the
format side.

| Name | Inbound | Inverse | Data |
|---|---|---|---|
| `identity` | the value as it is, a number as a number | the same | none |
| `lookup` | the value's entry in `values` | the key whose entry it is | `values`, one to one: a table whose values repeat is refused |
| `scale-by` | the number times `factor` | the number divided by `factor` | `factor`, not zero |
| `flag` | present -> `true` | `true` -> the row's key, `false` -> nothing | none |
| `scale-points` | `<number> <label>` -> one point of the control's `values` and `labels` | the point back as `<number> <label>` | none |
| `group-path` | a CLAP module path `a/b` -> the group `["a","b"]` | the group joined by `/` | none |
| `port-group` | an LV2 group's label -> the group `["label"]`; a `pg:subGroupOf` label -> a level put before the group read so far | the path's last level, the group a port names | none |

A new transform is added when a row needs it, never before; `make test-transforms` runs every function and its inverse
over its vectors (in, out, back in, equal).

## The coverage test

`make test-format-coverage` runs `tests/format_coverage.py` once per format. The field list is every term of the
installed TERM files (`<contractdir>/3/omx-contract/formats/<format>/**`) plus every row with a `from`; each field has
exactly one row. It prints, per field, `mapped <word> <transform>`, `extension <format>` or `dropped <decision>`, then the
count per class. It is red for:

- a field with no row, and a row that covers no field (its `term` is no installed term);
- a `word` the descriptor schema lacks (walked in the installed `omx-contract.schema.json`), or a `lookup` entry that
  is no value the word takes;
- a `transform` that is not in `TRANSFORMS(X)`, or a `lookup` that is not one to one;
- a `used` TERM that is `dropped`, and a `dropped` row that names no decision;
- an outbound-read row whose transform is neither `identity` nor `lookup`;
- a unit row that does not map to the word its TERM names.

`tests/format_coverage.py --self-test` breaks a copy of each table three ways (one row removed, one `word` misspelt,
one transform renamed) and each arm must go red naming the field.

## The field dump

`omx-clap-scan --fields clap:<path>#<id> | lv2:<uri>` writes one record per line, TAB-separated:

```
<scope>	<field>	<value>
```

- `scope`: `plugin`; `param:<index>` (CLAP, in `clap_plugin_params.get_info` order); `audio_in:<index>`,
  `audio_out:<index>`, `note_in:<index>`, `note_out:<index>` (CLAP ports); `port:<index>` (an LV2 port, by
  `lv2:index`). A scope is a source field's first segment, so a bag key `<scope>/<field>` is one too. A CLAP plugin
  that serves a panel description adds `panel`, `section:<index>`, `control:<index>`, `role:<index>`,
  `display:<index>` and `placement_default:<index>` (omx-clap-scan 0.20.0); these scopes are no entry of the
  descriptor, and each of their fields is dropped (above).
- `field`: a row key, as named above.
- `value`: the field's value as text. A number in `%.17g`; a CLAP constant (a flag bit, a port type, a note dialect,
  an extension id, a feature the headers define) by its macro name, one record per flag set or per item; an LV2 URI as
  a CURIE under the prefixes above, a URI no prefix covers in full; a scale point or a CLAP value text as
  `<number> <label>`. A TAB or a newline in a text becomes a space.
- the provenance: a CLAP dump writes `plugin	clap_entry	<file name of the .clap>`, an LV2 dump
  `plugin	rdfs:seeAlso	<bundle directory>/<data file>`, the `.ttl` that describes the plugin.

The first line is `# omx-clap-scan --fields 1`, the format's version; a dump with another version is refused.

## The descriptor `describe` writes

`plugin-hostd-probe describe [--table <file>] [--fields-from <dump.tsv>] clap:<path>#<id> | lv2:<uri>` writes the
`scanned` descriptor on stdout, exit 0; 2 when nothing is written (usage, a table it cannot read, a refused dump), 3 when
the dump cannot be made. Without `--fields-from` it runs `omx-clap-scan --fields` under the probe runner's limits, in a
child of its own (`run`'s isolation); with it, it reads a recorded dump, which is what its own tests do.

What the tables leave to `describe`:

- each scope is one entry: a CLAP `param:` scope a control, a CLAP port scope a port, an LV2 `port:` scope a control
  when a row makes it one (`lv2:ControlPort`) and a port when a row gives it a port kind; `id` and `name` follow the
  entry;
- an LV2 control's kind is `travel` (its `lv2:ControlPort` row) unless another record of the port gives a more
  specific one (`toggle`, `choice`, `trigger`), whatever order the dump lists the port's records in;
- an LV2 output control is `readonly`; an LV2 port that reports latency (`lv2:latency`) is no control;
- consecutive LV2 audio ports of one direction, role and group are one port, its `channels` their count, its layout
  `mono` or `stereo` by that count;
- a CLAP port that is not main is `aux`; a control's `unit` is `unknown` when no row sets it, its `scale` `unknown`
  on CLAP and `linear` on LV2 (where a scale not stated is linear); its `meaning` is `unknown` when no row sets it; a
  control with points is a `choice`, its `ids` taken from its labels and its default the id of the default's point, a
  `toggle` defaults to its default being non-zero;
- an LV2 port's group path is its `pg:group` label with one `pg:subGroupOf` record per group above it, nearest first
  (the scanner follows the chain, `lv2:name` else `rdfs:label` of each group); the path is read outermost first, and a
  `pg:subGroupOf` with no `pg:group` before it is refused;
- the bag holds a field's one value as it is, two or more as a list;
- a plugin no feature of which maps is an `audio-effect`; an LV2 plugin's `id` and `uri` are the URI asked for;
- the links a scanned descriptor needs (`source.from`): a CLAP descriptor's own, `<file>#clap_entry`; each LV2
  control's, `<data file>#<symbol>`, from the row of `clap_entry` and of `rdfs:seeAlso`; a character a link cannot hold
  becomes `_`; `instrument` is written when the features hold it, `polyphonic` when it states more than one voice; `latency`
  is always written, `reports` false when no row sets it.
- a word of a table that `describe` does not write is refused with the table: a new word is code here first.
