#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# make fuzz-records: EVERY CHECK NAMES WHAT BREAKS IT. Each abort() of a harness, of its recorder and of fuzz/fuzz.h has
# in its comment a `mutant:` and `input:` record, a one-line change of the daemon and the seed on which that check
# aborts, or a `not a property:` line (fuzz/checks.awk, which refuses a check with neither). This applies each record
# alone, builds the plain harness (clang and libFuzzer, no sanitizer), runs it on the record's seed, and requires the
# abort of that check: exit status 134, and the abort() on the record's line. Built without the change, the same
# harness must exit 0 on every seed a record names. The changed file is restored from a copy on every exit path.
#
# To tell which abort() fired, the harness is built with a header that makes abort() name its file and line on
# standard error before it aborts; nothing else of the harness changes.
#
# Usage: FUZZ_BUILD=build/fuzz FUZZ_CC=clang PROTOCOL_CFLAGS=... records.sh
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
B=${FUZZ_BUILD:-build/fuzz}/records
CC=${FUZZ_CC:-clang}
mkdir -p "$B"
# every mutant aborts: no core file for any of them
ulimit -c 0

# the harness each file's checks belong to; fuzz/fuzz.h serves both
harness_of() {
    case $1 in
    fuzz/fuzz_command.c | fuzz/recorder.c) echo command ;;
    fuzz/fuzz_reply.c) echo reply ;;
    *) echo "" ;;
    esac
}
CHECKED="fuzz/fuzz_command.c fuzz/recorder.c fuzz/fuzz_reply.c fuzz/fuzz.h"

cat >"$B/abort-at.h" <<'EOF'
/* make fuzz-records: abort() names where it was called, then aborts */
#include <stdio.h>
#include <stdlib.h>
static inline void records_abort_at(const char *file, int line)
{
    fprintf(stderr, "records: abort at %s:%d\n", file, line);
    fflush(stderr);
    abort();
}
#define abort() records_abort_at(__FILE__, __LINE__)
EOF

build() {   # build <harness> <output>
    case $1 in
    command) extra="src/verbs.c fuzz/recorder.c" ;;
    *) extra= ;;
    esac
    # shellcheck disable=SC2086
    "$CC" -O0 -g -std=c11 -D_GNU_SOURCE -fsanitize=fuzzer -include "$B/abort-at.h" -Iinclude -Isrc -Ifuzz \
        ${PROTOCOL_CFLAGS:-} "fuzz/fuzz_$1.c" $extra -pthread -o "$2"
}

# runs <binary> <seed>: the exit status, and the abort() it reports in $B/last.log
runs() {
    # the subshell waits for the harness itself, so the abort is its exit status and the shell reports no signal
    ("$1" -runs=1 -handle_abrt=0 "$2" >"$B/last.log" 2>&1 </dev/null; exit $?) 2>/dev/null
}

# every record, and the ratchet over every checked file; the stops that are not a property, counted
: >"$B/records.list"
nap=0
for f in $CHECKED; do
    awk '{ printf "%d|1|%s\n", NR, $0 }' "$f" | awk -v file="$f" -v records=1 -f fuzz/checks.awk >>"$B/records.list" ||
        { echo "make fuzz-records: RED -- $f has a check with no record (above)"; exit 1; }
    k=$(awk '{ printf "%d|1|%s\n", NR, $0 }' "$f" | awk -v file="$f" -f fuzz/checks.awk | awk -F: '$4 == "-"' | wc -l)
    nap=$((nap + k))
done
[ -s "$B/records.list" ] || { echo "make fuzz-records: RED -- no record"; exit 1; }

# the plain harnesses as the tree is: every seed a record names passes
for h in command reply; do
    build "$h" "$B/fuzz_$h" >"$B/$h.build.log" 2>&1 </dev/null || { cat "$B/$h.build.log"; exit 1; }
done
red=
us=$(printf '\037')
while IFS="$us" read -r file at path line old new input; do
    h=$(harness_of "$file")
    seed=fuzz/corpus/$h/$input
    if [ -z "$h" ] || [ ! -f "$seed" ]; then
        echo "$file:$at: no seed $input of a harness"
        red="$red $file:$at"
        continue
    fi
    runs "$B/fuzz_$h" "$seed"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "$file:$at: the harness as it is exits $rc on $input, not 0"
        red="$red $file:$at"
    fi
done <"$B/records.list"

saved=
restore() {
    [ -n "$saved" ] && cp "$B/saved" "$saved"
    saved=
}
trap 'restore' EXIT
trap 'restore; exit 130' INT TERM

n=0
met=0
while IFS="$us" read -r file at path line old new input; do
    n=$((n + 1))
    h=$(harness_of "$file")
    seed=fuzz/corpus/$h/$input
    [ -n "$h" ] && [ -f "$seed" ] || continue
    if [ ! -f "$path" ]; then
        echo "$file:$at: $path is not a file of the tree"
        red="$red $file:$at"
        continue
    fi
    cp "$path" "$B/saved"
    saved=$path
    # the one change: <old> once on line <line>, replaced by <new>
    if ! OLD=$old NEW=$new awk -v l="$line" '
        BEGIN { old = ENVIRON["OLD"]; new = ENVIRON["NEW"]; bad = 1 }
        NR == l {
            n = 0; t = $0
            while ((i = index(t, old)) > 0) { n++; t = substr(t, i + length(old)) }
            if (n == 1) { i = index($0, old); $0 = substr($0, 1, i - 1) new substr($0, i + length(old)); bad = 0 }
        }
        { print }
        END { exit bad }' "$B/saved" >"$path"; then
        restore
        echo "$file:$at: \`$old\` is not once on $path:$line"
        red="$red $file:$at"
        continue
    fi
    if ! build "$h" "$B/mutant" >"$B/mutant.build.log" 2>&1 </dev/null; then
        restore
        cat "$B/mutant.build.log"
        echo "$file:$at: $path:$line \`$old\` -> \`$new\` does not build"
        red="$red $file:$at"
        continue
    fi
    restore
    runs "$B/mutant" "$seed"
    rc=$?
    fired=$(sed -n 's/^records: abort at //p' "$B/last.log" | tail -n 1)
    if [ "$rc" -eq 134 ] && [ "$fired" = "$file:$at" ]; then
        met=$((met + 1))
    else
        echo "$file:$at: $path:$line \`$old\` -> \`$new\` on $input: exit $rc, abort at ${fired:-none}, not 134 at $file:$at"
        red="$red $file:$at"
    fi
done <"$B/records.list"

if [ -n "$red" ]; then
    echo "make fuzz-records: RED -- $met of $n records met;$red"
    exit 1
fi
echo "make fuzz-records: all $n records met, each by its own check on its own seed; $nap stops not a property"
