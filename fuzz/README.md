Fuzzing plugin-hostd
====================

The daemon reads two streams it does not control: the commands of any local client, and what each worker writes on its
feedback socket. Each has a libFuzzer harness here, built with clang under AddressSanitizer and
UndefinedBehaviorSanitizer and run in CI on every push and pull request (`.github/workflows/fuzz.yml`).

Each harness is one C file defining `LLVMFuzzerTestOneInput`. It reads its input as a small program, a sequence of
messages or operations, until the input ends; every input means something. No harness opens a socket, starts a
process or a thread, reads a clock, the environment or a file, or calls `dlopen`. Properties are checked with
`if (!cond) abort();`, never `assert()`; every outcome an input can choose returns 0, nothing calls `exit()`, and an
input of 64 MiB or more is refused. The header comment of each harness gives its input format and its properties.

The harnesses
-------------

| Harness | Code it drives | Input |
| --- | --- | --- |
| `fuzz_command` | `verbs_receive` and the dispatcher of `src/verbs.c` with the pin line grammar of `src/pin_words.c`, with everything below it replaced by the recorder of `fuzz/recorder.c` | up to 32 messages, each a flags byte (accept, or refuse with a declared code) and the message's bytes |
| `fuzz_reply` | the feedback reader of `src/relay.c`: `drain`, the gesture table, `relay_remove`, `relay_instance_gone`, `relay_event` | up to 512 operations: a worker writes, is read, closes, is removed; an instance goes; the controller takes short sends or goes away |

The recorder stands in for the supervisor, the pins, the descriptors and the socket's send. It answers every call with
the reply its verb declares in `include/plugin-hostd/protocol.h`, or with the refusal the input chose, and folds what an
accepted call changes into a digest of the daemon's state. `fuzz_reply` includes `src/relay.c` and answers its `recv`
and `send` itself, and builds it with a line limit of 6000 bytes so that small inputs reach the drop of a long line.

What each harness proves, beyond no sanitizer report:

- **command / reply**: every message gets one reply, a NUL-terminated string of a declared shape. When a call
  answered, the reply is that answer unchanged: the supervisor's text, or `resp <code>` of the code the pins returned.
  When none did, it is a reply the daemon makes itself, a refusal or `resp 0` for `quit`; the recorder's `sup_resp`
  is that reply, and no answer.
- **command / arity**: a verb the daemon parses itself is acted on, by its own call or by a broadcast to every worker,
  only with an argument count its declared syntax allows. `pin_layout`, `pin_expect`, and `connect` or `disconnect` of
  another count go to every worker for the worker to refuse.
- **command / words**: each call the daemon makes is handed the message's words at the places its verb declares them,
  as the harness reads them: a word as written, a number as `atoi` reads it, a line as its words joined by one space.
  The words a verb may leave out the harness works out from the message: the placement and the client of `add`, the
  members of `chain` and their count, the verdict of `pin_set`.
- **command / round-trip**: a command's words joined by one space, as the declaration writes them, make the same calls,
  the same reply and the same state. It compares the daemon with itself, so a word put in the wrong place on both sends
  keeps it true; the words property is what holds the place of each word.
- **command / refusal**: a refused command leaves the daemon's state as it was.
- **reply / bounded**: an unfinished line held for a worker never passes the line limit, and its buffer stays bounded.
- **reply / no-loss**: the controller reads every complete line a worker wrote once, in order, however the stream was
  cut and wherever its NULs fell, as a reference splitter over the same bytes reads them. The reference takes what
  `recv` hands over, so after each read, removal of a worker and removal of an instance, `recv` has handed over all the
  worker wrote to each source the relay read.
- **reply / shape**: every line the relay writes of its own is an event as written or the end of a gesture still held,
  once each.
- **reply / the controller's socket**: the relay writes to the controller's socket and to no other.

The harnesses found what is fixed with them: `worker_list`, `supervisor_reset` and `quit` took words their grammar
does not, a tab at the end of a command was not trimmed as a space is, and the end of a held gesture longer than 1024
bytes went out cut short.

The seed corpus
---------------

`fuzz/corpus/<harness>/` is written by `fuzz/gen_corpus.py` (`make fuzz-corpus`) and committed. The command seeds are
every verb of `protocol/plugin-hostd.json` and `protocol/mod-host.json` with sample arguments, each with its optional
words, with one word too many, refused by the supervisor and split by tabs, the placements of `add`, and the `send`
lines of `README.md` and `docs/own-host.md`. The reply seeds cut worker feedback at every byte and before every NUL,
hold, end and abandon gestures, put lines at and past the line limit, and write a line and then remove its worker or
an instance with no read between the two. Nothing is fetched; `make fuzz-corpus-check`
fails when the committed corpus is not what the generator writes.

The coverage witness
--------------------

`make fuzz-coverage` builds each harness for `llvm-cov`, runs it once over its corpus and prints the line coverage of
the functions it drives, then every line no seed reaches. `fuzz/coverage-floor.txt` holds the covered lines of each
harness, and the target is red below it, or when a property check of a harness file or of a helper it is built with
(`fuzz/recorder.c`, `fuzz/fuzz.h`) is executed by no seed (`fuzz/checks.awk`). A stop marked `not a property` needs no
seed.

| Harness | Lines | Covered | Lines no seed reaches |
| --- | ---: | ---: | --- |
| command | 178 | 92.13% | the paths taken when the message's copies or an answer get no memory (`tests/verbs_alloc_test.c` drives them) |
| reply | 210 | 90.00% | the paths taken when `realloc` fails (`tests/relay_test.c` and `tests/gesture_alloc_test.c` drive them), the relay thread's join and the listening socket in `relay_finish`, and the `fd < 0` guards of `relay_add` and `relay_remove` |

The records
-----------

Every `abort()` of a harness, of `fuzz/recorder.c` and of `fuzz/fuzz.h` is a check, and its comment says what breaks
it: one or more pairs of lines

```
mutant: src/relay.c:267 `> LINE_LIMIT` -> `>= LINE_LIMIT`
input: line-at-the-limit
```

a one-line change of `src/` or `include/` (the text between the first backticks, once on that line, becomes the text
between the second) and the seed of the harness's corpus on which that check aborts; or one line `not a property:
<reason>` for a stop that is no property, the harness's own allocation failing. This is the form the OSS Verify
enrolment reads. `make fuzz-records` applies each record alone, builds the plain harness (clang and libFuzzer, no
sanitizer), runs the record's seed, and is red unless the harness aborts (exit status 134) at that check's own
`abort()`, and exits 0 on the same seed without the change; the changed file is restored from a copy. To tell which
`abort()` fired, the records build includes a header that makes `abort()` name its file and line on standard error.
`fuzz/checks.awk` is the ratchet: `make fuzz-coverage` and `make fuzz-records` are red on a check whose comment has no
record and no `not a property:` line.

There are 34 records for the 30 property checks, at least one each, and 10 stops not a property.

The mutants
-----------

`fuzz/sabotage/<harness>-<property>.patch` is a one-line bug for each property, the first breakage each one had, and
`fuzz/sabotage/<harness>-<property>-<part>.patch` one for a part of a property; each is also a record. Its first two
lines name the check it breaks and the seed that catches it, as the enrolment's `mutants` directory wants them, and
`git apply` skips them. `make fuzz-sabotage` applies each, rebuilds the harness, runs it over every seed one at a
time, restores the source with `git checkout --`, and is red unless at least one seed makes the harness abort and
every seed that does aborts in `check_<property>` (for a part, its own `check_` function or the property's): a mutant
that also breaks another property does not pass.

| Mutant | The bug | Found by |
| --- | --- | --- |
| `command-reply` | the reply is sent without its NUL | `add-default` |
| `command-reply-answer` | a `pin_set` the pins refused is replied `resp 0` | `plugin-hostd-pin_set-refused` |
| `command-arity` | `pool_config` takes three words or more | `plugin-hostd-pool_config-extra` |
| `command-arity-broadcast` | `remove` of another count goes to every worker | `mod-host-remove-extra` |
| `command-words-add` | the placement and the client of `add` are swapped | `add-pool-p-fuzz_client` |
| `command-words-chain` | a `chain` loses its last member | `plugin-hostd-chain` |
| `command-words-pin-set` | the verdict of `pin_set` keeps its `verdict=` key | `plugin-hostd-pin_set-full` |
| `command-round-trip` | the first word is split at spaces only | `mod-host-add-tabs` |
| `command-refusal` | a refused `add` still starts a descriptor scan | `add-instance-past-the-table` |
| `reply-bounded` | the overflow check compares with the capacity, not the line limit | `line-past-the-limit-in-parts` |
| `reply-no-loss` | a line of exactly the line limit is dropped | `line-at-the-limit` |
| `reply-no-loss-read` | a removed worker is not read to its end | `written-then-removed` |
| `reply-shape` | a held gesture is ended with `begin` | `controller-takes-a-few-bytes-a-send` |

Running
-------

```
make fuzz                    # build both harnesses into build/fuzz/
make fuzz-run FUZZ_TIME=60   # fuzz each for 60 s; red on any crash
make fuzz-sabotage           # every mutant found by its own property
make fuzz-records            # every check's record makes that check abort on its seed
make fuzz-coverage           # the coverage witness
make fuzz-corpus             # write fuzz/corpus/ again
```

They need clang with libFuzzer (`compiler-rt` on Fedora) and, for `fuzz-coverage`, `llvm-cov` and `llvm-profdata`, and
mod-host's protocol headers, found as for the ordinary build. One harness by hand:

```
mkdir -p /tmp/new && build/fuzz/fuzz_reply -max_total_time=60 /tmp/new fuzz/corpus/reply
```

`make fuzz-run` writes an input that crashed a harness to `fuzz/findings/<harness>-crash-<sha1>`, with the log beside
it; CI uploads the directory as the `fuzz-findings` artifact. `build/fuzz/fuzz_<harness> <that file>` replays it. Once
the bug is fixed, copy the input into `fuzz/corpus/<harness>/` under a name that says what it is, and add it to
`fuzz/gen_corpus.py`, so every later run replays it first.
