Durable writes: the command loop never waits on the disk
========================================================

plugin-hostd writes its own files (the running history, the pin store and its list of accepted plugins, the
descriptors and panels a scan files) on one writer thread, first in first out, and the command loop never waits on
the disk for any verb: an fsync that takes seconds on a slow SD card or a busy disk would otherwise leave every
controller unanswered for as long. The loop hands the writer a copy of the bytes, so the two share no state that
changes. A periodic history save that still waits is replaced by the next one of the same file, the latest wins. A verb
whose reply says its change is on disk (`history_clear`, `pin_clear`, `pin_accept`; `pin_set` writes no file) answers
once its write has landed, and answers `resp -902` when the write failed; the loop serves every other duty meanwhile, and the
controller's later commands are answered after it, in the order they were sent. A write any other verb hands over, such
as the pin an `add` learns, is best effort: it is said on stderr when it fails and the reply does not wait for it. A
verb that reads one of these files back (`pin_reload`, `pin_changed`, `descriptor_get`, `panel_get`), and the poll of
the pin files, waits until nothing is queued, so it never reads a file older than one already handed over. `quit`
drains the queue before the daemon exits. The queue is bounded, at 64 writes and 64 MiB: a write past that is refused,
and a verb that needed it answers `resp -901`. A deferred reply is one reply, as every reply is: the protocol does not
change. `src/writer.c` is the writer, and the tests that hold each rule are in `tests/daemon_test.py`, under the slow
disk of `tests/slow_fsync.c`, with a sabotage arm for each in `tests/sabotage.py`.
