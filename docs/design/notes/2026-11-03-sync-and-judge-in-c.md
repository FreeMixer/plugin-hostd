# The device sync and the judge in C: plugin-hostd-sync

Status: proposed, for the plugin-qualify#207 row "the device sync and the judge in C, inside plugin-hostd" (was
plugin-qualify#190), ruled 2026-11-02: a device needs no Node to qualify plugins; the TypeScript judge stays the
reference and the C one is held equal to it by shared test vectors. No code in this note's pull request.

## What moves, measured

The brief counted ~2100 lines of JS. Read from plugin-qualify main (957d9bb), the sync reaches 38 TypeScript modules,
11 469 lines, about 8 000 of them code: `qualify-sync.ts` (1 275 code lines), `hosting-suitability.ts` (847),
`measurement/format.ts` (940), `probe-output.ts` (430), `clap-qualify.ts` (406), `clap-loader.ts` (368),
`qualify-rejudge.ts` (362), `qualification-record.ts` (353), `probe-runner.ts` (285), `probe-judge.ts` (249), and 28
smaller ones (pins file, rating, host profiles, grid, memory bound and budget, cost fields, host admission, distributed
records, isolated step, adapter pass, LV2 manifest reader, whole-file writer). The sync also starts two Node scripts of
its own: `tools/isolated-step.mjs` (a plugin-hostd of its own, one plugin, a sine through it) and
`tools/mod-host-admit.mjs` (one `add`/`remove` on a fresh mod-host or omx-clap-host). Both move too, or the device
still needs Node.

What does not move: the measurement (already C: `plugin-hostd-probe`, the interposer, `lv2_measure`, `clap-qualify`,
`isolated_signal`, `jack_peak`), the Python tools the sync runs (`lv2_resolve.py`, `descriptors.py`, `scan.py`: the
device keeps python3 and python3-lilv), the `plugin-qualify` CLI, the records-package tool and the declarations
generators, which stay in TypeScript as developer tools.

## A program of its own, not a subcommand

`plugin-hostd-sync`, a third program beside `plugin-hostd` and `plugin-hostd-probe`, built from the same tree.

- **Not a subcommand of `plugin-hostd`.** The daemon links mod-host's protocol library, runs for days and supervises the
  audio workers. The sync is a oneshot that runs under its own unit limits (Nice 19, CPUQuota 200%, MemoryMax 1000M,
  TasksMax 64, idle I/O). One executable is one SELinux domain transition and one set of limits; keeping them apart keeps
  the daemon from carrying 8 000 lines it never runs, and a core dump or a journal line names which one failed by
  its executable.
- **Not a subcommand of `plugin-hostd-probe`.** The probe runner is the program a measured plugin runs under, one
  plugin per run, under rlimits and a cgroup; the sync starts many of those and holds the state lock between them. Its
  `describe` subcommand stays where it is.
- **The same flags as today.** `plugin-hostd-sync` takes every flag and settings key `plugin-qualify-sync` takes
  (`SYNC_SETTINGS`, `--system`, `--force`, `--no-wait`, `--refresh-pins`, `--rejudge`, `--memory-only`,
  `--adapter-only`, `--isolated-only`, `--grid-hosts`), reads `/etc/omx/qualify.conf`, prints the same summary lines and
  exits 0, 1 or 2 on the same conditions. plugin-qualify's package keeps `/usr/bin/plugin-qualify-sync` as a link to
  it, so the package triggers, the man page and anyone's habit keep working.
- **The two step scripts become steps of the same program**: `plugin-hostd-sync step isolated <uri> <window-ms>` and
  `plugin-hostd-sync step admit <uri> [host]`, run as children exactly as the scripts are now (one process per plugin,
  killed at the budget), printing the same JSON line. They are protocol clients, and the protocol's client code is
  already in this tree.

## The C API and where it lives

`src/sync/`, one header per part, built into `plugin-hostd-sync` only. Each part is the twin of named TypeScript
modules and carries their names in its first comment, so a change to one side finds the other.

| part | twin of | what it does |
|---|---|---|
| `jsout.c` | `JSON.stringify` | writes a value byte-for-byte as `JSON.stringify(v, null, n)` does: key order as built, string escapes, numbers as ECMAScript `Number::toString` (shortest round trip, `1e+21`, `-0` as `0`) |
| `state.c` | `qualify-sync.ts` (state, digests) | `sync_state_read`, `sync_state_write`, `digest_files`, `recorded_as_is`, `same_binary_elsewhere`, `refresh_pins` |
| `pins.c` | `pins-file.ts` | `pins_text`, `changed_pin_lines`, `removed_pin_uris`; a line is read back by the daemon's own `src/pins.c` parser, so the TS `parsePinLine` vectors run against the daemon |
| `discover.c` | `qualify-sync.ts`, `lv2-loader.ts`, `clap-loader.ts` | the items on the search paths, the LV2 manifest reader, lilv's choice through `lv2_resolve.py` |
| `judge.c` | `rating.ts`, `hosting-suitability.ts`, `probe-judge.ts`, `clap-qualify.ts` (rtSafetyDocument), `host-admission.ts` (rating), `memory-budget.ts`, `cost-fields.ts` | `judge_probe_output(output, profiles, facts) -> judgment`: reasons, worst-wins fold, deciding reason, hosting, cost beside the verdict |
| `record.c` | `qualification-record.ts`, `probe-output.ts` (reader) | the record built and written, the unmeasured record, `prune_stale`, `record_stem`, `plugin_counts` |
| `run.c` | `probe-runner.ts`, `measurement-grid.ts`, `memory-bound.ts`, `qualify-isolated.ts`, `qualify-adapter-pass.ts`, `qualify-rejudge.ts`, `distributed-records.ts` | one item qualified; the passes |
| `main.c` | `bin/plugin-qualify-sync.mjs`, `qualify-sync.ts` (settings, lock, quiet wait, send) | arguments, settings, `flock(2)` on `<state>.lock`, the `.again` and `qualify-pending` markers, `pin_set`/`pin_clear` to a running daemon |

JSON is read with the tree's `json.c` (`jparse`), extended where `JSON.parse` differs: `\u` escapes and surrogate pairs
to UTF-8, a repeated key keeps its first place and its last value. SHA-256 is `pin.h`'s, the digest the daemon pins
with.

## Byte for byte: existing devices keep their state

A device upgraded from the TypeScript sync reads its `/var/lib/omx/qualify-sync.json`, its records and its pin file as
they are, and its next run measures nothing that the last one recorded. Held by:

- **The state file** is written as `JSON.stringify(state, null, 1)` plus a newline, through `<path>.new`, fsync, rename
  and a directory fsync (`whole-file.ts`). Fields in the order each TypeScript site builds them (an entry: `format`, `root`,
  `files`, `plugins`, `qualifiedAt`, `seconds`, `distributed`; a digest: `path`, `sha256`, `size`, `mtimeMs`, `ino`).
  A state read and written again without change is the same bytes, unknown fields included: the C keeps the parsed
  tree and edits it, as the spreads in the TypeScript do.
- **Numbers as Node makes them.** `mtimeMs` is Node's `sec * 1e3 + nsec / 1e6` in binary64; `ino` is the inode as a
  binary64 (the same rounding above 2^53); `seconds` is milliseconds over 1000; `qualifiedAt` is `toISOString()`, UTC
  with milliseconds. The skip test compares `size`, `mtimeMs` and `ino` as the doubles the file holds.
- **Order as JavaScript sorts.** File lists and pin lines are sorted by UTF-16 code unit, which differs from byte order
  only between a character above U+FFFF and one in U+E000..U+FFFF; `jsout.c` carries that comparison.
- **Names that are not UTF-8.** Node reads them with U+FFFD in place, cannot stat the result and skips the plugin; the C
  skips such a name too and says so, so the state never holds a name one side can write and the other cannot.
- **Records** are `JSON.stringify(record, null, 2)` plus a newline, with the probe output copied beside them as the
  bytes the runner printed. Unmeasured records, the `.owed` file and the pin file the same way.
- **The lock** is `flock(2)` on the same `<state file>.lock` the TypeScript takes through `flock(1)`, so a run of either
  excludes a run of the other during an upgrade.

## Every number from the contract

No value a declaration owns is typed in C (the 2026-11-03 no-exceptions ruling). Two owners:

- **omx-contract**: `ORACLE_FLOOR_RATES`, `RT_HARD_TARGET`. Read from `omx_contract_limits.h` at build, as
  `plugin-hostd-probe` already reads the floor rates.
- **plugin-qualify's declarations** (`qualify-declarations.ts`, `host-profiles.ts`, `hosting-codes.generated.ts`):
  `HOST_BUDGETS`, `PI_CELLS`, `DEFAULT_HOSTING_POLICY`, `QUALIFY_QUANTA`, `MEMORY_LIMIT_RAM_FRACTION`,
  `MEMORY_PASS_PROBE_NOTES`, the profiles' feature and extension lists, the hosting codes, the tool names, environment
  names and timeouts. plugin-qualify publishes them as a contract package, `contract.d/3/plugin-qualify/`, written by a
  generator from the TypeScript declarations (the `gen-python-declarations.mjs` pattern, `check:generated` keeps it
  current), installed by omx-contract's `install-contract-dir.sh` and shipped as `plugin-qualify-contract`.
  `plugin-hostd-sync` reads that package at start and refuses to run, exit 2, naming the item, when one is missing or
  of the wrong kind. There is no built-in fallback.

Held by two tests: the C run against a contract directory with one budget changed gives the verdict that budget
gives (the value is read, not compiled in), and a source check fails on a numeric literal in `src/sync/judge.c` and
`src/sync/run.c` other than 0 and 1.

## The proof: one judge, two implementations, the same bytes

`tests/sync_diff.py` runs the TypeScript (a plugin-qualify checkout, `PLUGIN_QUALIFY_DIR`, built, as `MOD_HOST_DIR`
names mod-host) and the C on the same inputs and compares bytes: the state file, every record, the pin file, the
verdict rows, the summary line. Inputs: plugin-qualify's fixtures (`fixtures/probe-output`, `admission`, `clap-scan`,
`records-0.16.1`), the vectors of its tests that cover these modules, and one real sweep (a device's `/var/lib/omx`
after a full run: 1 018 entries, 2 646 records). The clock is fixed for both (a preload for Node, a test build of the
C), never masked. A red names the first differing byte and its JSON path. Sabotage: one verdict rule broken in C
turns it red; that run is part of the pull request that adds the rule.

The test needs Node and runs in CI and on a developer's machine; nothing a device installs needs it.

## The switch

- **Units.** `plugin-qualify-sync.service`: `ExecStart=/usr/bin/plugin-hostd-sync --system --no-wait --settle-s 60`.
  The comment about naming the interpreter first goes (a native executable in `/usr/bin` takes the ordinary daemon
  transition). The timer, the path unit, the generator, the tmpfiles and the limits stay as they are, in
  plugin-qualify, which still owns `qualify.conf` and the tools the sync starts.
- **Packages.** plugin-hostd ships `plugin-hostd-sync` and its man page. plugin-qualify (the device package) drops
  `nodejs` from Requires/Depends, requires the plugin-hostd that ships the sync and `plugin-qualify-contract`, and links
  `/usr/bin/plugin-qualify-sync` to `plugin-hostd-sync`. The Node CLI (`plugin-qualify`,
  `plugin-qualify-records-package`, `dist/`) moves to a new `plugin-qualify-cli` subpackage that requires `nodejs`;
  `packaging/check-installed.sh` stops using `node` for its checks.
- **The TypeScript sync** stays in the CLI package as the reference the differential test runs; no unit starts it.

## Order

Each phase is its own pull request with its own vectors; the switch comes last, after all of them are equal.

1. `jsout`, state, pins, records bookkeeping (`prune_stale`, `record_stem`, `plugin_counts`), settings parsing.
2. The judge and the record writer.
3. The run: discovery, digests, probe runs, the isolated and admission steps, the passes, the distributed layer,
   sending pins, the lock.
4. The contract package in plugin-qualify, then the switch (units, packages).

Lands after plugin-qualify #283, #286 and #287, which change `hosting-suitability.ts`, `host-admission.ts`,
`qualify-isolated.ts` and `qualify-sync.ts`: the C follows them, and the vectors are taken after they merge.

## Not decided here

- The idle gate the 2026-11-02 ruling on plugin-qualify#207 asks of the first run (no xruns, CPU below a stated
  threshold): it belongs to the sync and is written once, in C, after the switch.
- Whether `plugin-hostd --pin-files` is called in-process instead of as a child: a child at first, as today.
