The panel a plugin publishes, served to a host
==============================================

A plugin of omx-plugins states how its panel is laid out through the CLAP extension
`org.openmixer.panel-description/1` (omx-clap-core's `src/omx_clap_ext.h`, omx-plugins' `include/omx_panel_description.h`):
its family, a fingerprint, and five tables, the sections, the controls (each with its parameter, section, widget and
visibility rule), the roles, the displays and the placement defaults. A host that draws the panel itself, such as
Zynthian's engine, reads it from the daemon with `panel_get`.

## The verb

```
panel_get <uri>          resp 0 "<path>"
```

`<uri>` is the one `add` takes (`clap:<path>#<id>`, `lv2:<uri>`). The reply is the path of the plugin's panel file,
one quoted word as `descriptor_get` answers its descriptor. The codes are `descriptor_get`'s:

| Code | When |
|---|---|
| `-529` | no descriptor, or a descriptor with no panel beside it, for the plugin's binary as it is now: no add since it changed, a binary that cannot be found, a descriptor filed by a daemon that predates `panel_get` |
| `-530` | the scan of its add has not filed the panel yet: ask again |
| `-531` | the last scan filed no panel: the descriptor failed, or the panel stage did (the scanner states no panel, see below); the next add scans again |
| `-528` | descriptor_dir could not be written |
| `-902` | no `<uri>`, or more than one word |

## Where the panel comes from

The answered `add` of a plugin whose files have no descriptor runs the scan, in a child of its own, as it does for
`descriptor_get`. The scan has two stages:

1. `plugin-hostd-probe describe <target>`, whose stdout is the descriptor, filed as
   `<descriptor_dir>/<id>@<version>-<hash>.json`;
2. once that file is in place, `plugin-hostd-probe panel <target>`, whose stdout is the panel, filed under the same
   name in `<descriptor_dir>/panels/`. Both are written once, atomically.

`panel` runs `omx-clap-scan --json` on the plugin's file (omx-clap-core 0.20.0 or later) and copies the `panel` object
the scan prints for the plugin's id, byte for byte. The daemon never reads the plugin's `decl.json` and never calls the
extension: what the scan printed is what a host gets. An add of a plugin whose descriptor is in place and whose panel
is not (a descriptor of an older daemon, a panel stage that failed) runs the panel stage alone.

## The file

```json
{"plugin": {"format": "clap", "id": "org.openmixer.delay"}, "panel": {"family": "...", "fingerprint": "...",
 "sections": [...], "controls": [...], "roles": [...], "displays": [...], "placementDefaults": [...]}}
```

- `panel` is the scan's object as omx-clap-scan(1) states it: each entry with the members of its structure, a code by
  omx-plugins' word for it, an id that is none as `null`, a visibility mask as a hex string.
- `panel` is `null` for a plugin that serves no description.
- a table the scan refused for its count (past 4096 entries) stays refused: `{"refused": "too-many", "count": <n>,
  "max": 4096}` in place of its array, the other tables as they are.
- an LV2 plugin's `panel` is `null`: the description is a CLAP extension, and nothing is run for it.
- a scan that states no `panel` for the plugin (a scanner before omx-clap-scan 0.20.0, a plugin that fails to
  initialise) is refused, and `panel_get` answers `-531`: a missing panel is never read as a null one.

The field dump (`omx-clap-scan --fields`) prints the same description under its own scopes; the format table drops
each of those fields (docs/formats.md#what-a-table-drops), so the descriptor carries none of it.

## Why a verb of its own

The panel could have been a word more of `descriptor_get`'s reply, or a member of the descriptor. The protocol's own
conventions decide against both:

- Reply size. A message is at most `line_max`, 4096 bytes, the socket's buffer, and one panel table may hold 4096
  entries. A panel never fits a reply, so it is a file the reply names, as the descriptor is.
- No optional reply words. Every reply of the protocol is one fixed grammar, word by word (`protocol.json`'s
  `reply`); what is optional is a verb, answered or refused with `-902`, never a field a client must guess the
  presence of. A second path in `descriptor_get`'s reply would change a `required` verb's grammar for every client
  that parses it. A new verb leaves `descriptor_get` as it is, and a daemon that predates `panel_get` answers it
  `-902`, which no client misreads.
- The descriptor is omx-contract's document. A `scanned` descriptor follows `omx-contract.schema.json`, which has no
  panel; the descriptor file stays what plugin-qualify and omx-contract's reader read.

So `panel_get` is a daemon verb, required for every profile like `descriptor_get`, with its file beside the
descriptor's and the same codes.

## Drawing a panel: the three verbs together

A native renderer combines what the daemon serves; none of the three replaces another.

| What | Verb | Keyed by |
|---|---|---|
| the structure: sections, which control is in which, its widget, when it is shown, roles, displays | `panel_get <uri>` | the plugin's files |
| what a value means: unit, scale, range, default, step, the stable symbol | `param_info <instance> <symbol>` | the running instance |
| the pages of 8 a hardware surface steps through | `remote_pages <instance>`, `remote_page_get <instance> <page>` | the running instance |

1. After `add <uri> <instance>`, ask `panel_get <uri>` until it is no `-530`. Only a `null` panel, and an LV2 plugin
   until its bundle is read for a panel (FreeMixer/plugin-hostd#149), mean the plugin states no layout: draw the
   controls in parameter order, as a host did before. Every other code is a failure to show, not a plugin without a
   layout: `-531` is a panel stage that failed and `-528` a descriptor directory that could not be written, and the
   plugin may well have a layout. Name the failure to the user, and draw in parameter order only as the fallback.
2. For each control of `panel.controls` (in table order), its `paramId` is the CLAP parameter id, the number
   `omx-clap-scan` lists a parameter by and the `<symbol>` the instance verbs take for a CLAP instance. The daemon does not parse that word:
   `sup_instance_verb` (src/supervisor.c) passes the line of a format with native instance verbs, CLAP among them, to the
   worker untouched, and omx-clap-host(1) states that it addresses a CLAP parameter by its decimal CLAP id.
   `param_info <instance> <paramId>` gives its unit and scale,
   so a knob shows `dB` and moves on its own scale; `-511` means the worker holds no checked contract, and the range
   and default come from `omx-clap-scan`'s parameter list.
3. A control whose `visibleParamId` is not `null` is shown while bit `v` of `visibleMask` is set, `v` the value of that
   parameter (`param_get`).
4. `remote_page_get` gives the plugin's own grouping in eights, each slot a symbol: a surface with eight encoders
   pages through those, the panel's sections and widgets dressing each slot.
5. A refused table is drawn as the plugin having none of it, and named to the user: its count is in the refusal.

What the panel cannot give yet: an enum's labels and the remote pages in the scan itself (FreeMixer/omx-clap-core#318);
until then a choice's labels come from the worker (`param_info` and the plugin's value texts) and the pages from
`remote_page_get`, both on a running instance.
