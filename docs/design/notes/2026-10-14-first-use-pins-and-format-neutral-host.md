# First-use pins, one pins format, a format-neutral host

Status: built, released in v0.3.0 (2026-10-16). Covers plugin-hostd#25 and #26 (PRs #30 and #31) and plugin-qualify#55.
One question is open: openmixer ruled on 2026-10-17 that an external plugin carries no pins and that its
qualification record is evidence only (openmixer `docs/design/specs/2026-10-17-contract-definitions-installed-by-owners.md`,
the "Pins for external plugins" ruling). Whether first-use pins stay for third-party plugins, and with them #42
(pins.d) and #71 (`verdict=refused`), waits on the operator reconciling that ruling with this note.

## Why

An unpinned plugin is refused (-508) while `require_pins` is on, so a standalone user's first `add` fails unless a
controller sent `pin_set` first. Only openmixer does that. Everyone else would turn `require_pins` off, and then no pin
is checked at all. The pin should be taken on first use and kept, and a change after that should be loud.

## Settings

| key | default | meaning |
|---|---|---|
| `pin_mode` | `first-use` | `strict` or `first-use`, read only while `require_pins` is 1 |
| `pin_store` | empty | the file the learned pins are kept in; empty means `$XDG_STATE_HOME/plugin-hostd/pins`, else `$HOME/.local/state/plugin-hostd/pins` |
| `pin_file` | empty | a pins file loaded at startup, written by `plugin-qualify --all --pins` |

`require_pins 0` still means no pin is checked. `strict` is today's behaviour, byte for byte: a plugin with no pin is
refused with -508. A host that pins by itself (openmixer) sets `pin_mode strict` in the drop-in it generates.

## One line format

The pin store, the pins file and the `pin_set` verb carry the same line:

    pin_set <uri> <path>=<sha256>[,<path>=<sha256>...] <scheme>:<sha256> [verdict=<word>]

- In a file the leading `pin_set` is optional, `#` starts a comment, blank lines are skipped.
- The layout word is `-` when the layout has not been learned yet (see below). `pin_set` as a verb refuses `-`.
- `verdict=` is the qualification verdict of the pinned bytes: `in-process`, `isolated` or `refused`. Absent means
  not qualified. The verb takes it too, so one parser reads all three.

The store holds only the pins the daemon learned or accepted. A pin that arrived by `pin_set` or `pin_file` is the
controller's, is not written to the store, and replaces a stored one of the same uri while the daemon runs. The store
is written to a temporary file in the same directory and renamed, mode 0600.

## First use

`add` with `pin_mode first-use`, and no pin for the uri:

1. The daemon collects the files the format loads for it (below), hashes them over open descriptors and records a pin
   with layout `-` and no verdict. Nothing is accepted from a failed collection: the add is refused with -509 and no
   pin is recorded.
2. The instance is placed `own`, whatever the placement said. In-process or pooled placement needs a verdict of
   `in-process` on the pin, and a learned pin has none.
3. After the worker accepted the add, the daemon asks it for the layout (`pin_layout <instance>`, reply
   `resp 0 <scheme>:<sha256>`), records it in the pin and writes the store. A worker that does not know the verb leaves
   the layout at `-`; the files are still checked on every later add.

Later `add`s check the stored pin as `strict` does: files hashed before any worker sees the add, the layout handed to the
worker with `pin_expect`. A layout of `-` sends no `pin_expect`, and the add learns it as in step 3.

A replayed add (a respawned worker) never learns: it checks the pin it has, and a pin that is gone or changed refuses
the replay as it does today.

## A change

- Files differ: add answers -509. Layout differs: the worker refuses and add answers -510. In either case, and in
  both modes, the daemon emits `pin_changed <uri> files` or `pin_changed <uri> layout` on the feedback port, once per
  refused add and per refused replay.
- The pin stays as it was. Nothing loads the changed plugin until the controller decides.
- `pin_accept <uri>` takes the new pin: the daemon collects and hashes the files again, records them with layout `-` and
  drops the verdict, so the next add learns the new layout and places the instance `own`. It answers `resp 0`, or -509
  when the files cannot be collected, or -508 when there was no pin to accept. In `strict` mode it is refused too:
  a host that pins itself changes a pin with `pin_set`.

Accepting never makes a plugin in-process: that stays a decision of qualification (`verdict=in-process`).

## The pins file of plugin-qualify

`plugin-qualify --all --pins <file>` writes the same line for every plugin it qualified, with `verdict=`. The daemon loads
the file at start with `pin_file`; a line it cannot parse stops the start with the line number named. A file loaded
this way is the controller's. One command scans, qualifies and pins what is installed; a corrupted hash in the file makes
the add answer -509.

## Format-neutral host (#26)

The daemon keeps one table of formats, `PHD_FORMATS`. Today the table is two names, and the rest of the format is spread
as `if (fmt == FMT_CLAP)` in the supervisor and pins. After this change a format is one row of `src/formats.c`:

| capability | meaning | lv2 | clap |
|---|---|---|---|
| `name` | the word `policy_set`, `worker_env` and `worker_list` use | lv2 | clap |
| `prefix`, `strip_prefix` | how a uri says it is this format, and whether the worker gets it without | `lv2:` stripped, also the default for a bare uri | `clap:` kept |
| `worker` | the program, from the settings | `mod_host` | `clap_host` |
| `pin_collect` | the root and the relative files the host loads for a uri | the bundle's manifest, binary and seeAlso files | the `.clap` file |
| `layout_check` | the worker takes `pin_expect` and `pin_layout` | no | yes |
| `world_scope` | what the worker's world is made of | one bundle (narrowed) | none |
| `pin_pool` | whether a pin lets the plugin share a worker | no: placed `own` | yes |
| `native_instance_verbs` | whether the worker answers the verbs of `PHD_INSTANCE_VERBS` | no: the daemon does | yes |
| `answer` | the daemon's answer when the worker does not | `track_info` kept, `remote_pages` 0, `param_info` -103/-511 | none |

The protocol text names no format where a capability is meant: -501 says "a format whose pin holds only in one
bundle's world", `policy_set` and `worker_env` take the names of the table. `formats_register` adds a row at run time, for
the one test that registers a third format (`tests/format_test.c`): it goes through add, param_set, pin_set, pin_check and
remove with the protocol untouched, and a row with a capability missing is refused by `formats_register` with a named
reason, so the test goes red instead of the daemon compiling it silently.

## Owed to the workers

- `omx-clap-host`: the `pin_layout <instance>` verb (the layout it already computes for `pin_expect`). Until it lands, a
  learned CLAP pin keeps layout `-` and only its files are checked. The fake worker in `tests/` answers it.
- openmixer: write `pin_mode strict` in the drop-in it generates.

## Not decided here

In-process placement of a standalone host's plugins. The verdict travels in the pin; what the host does with it is the
host's.
