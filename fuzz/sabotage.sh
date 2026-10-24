#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# make fuzz-sabotage: A PROPERTY NO MUTANT CAN BREAK CHECKS NOTHING. fuzz/mutants/<harness>-<property>.patch is a
# one-line bug in the code the harness drives, one for each property the harness checks. This applies each, rebuilds
# the harness, and runs it over its seed corpus one seed at a time; the mutant is found when a seed makes the harness
# abort in check_<property> (or a check_<property>_<part>), the function that holds that property's checks. A crash anywhere else does not count. The
# source is restored with `git checkout --` on every exit path, and the sanitizer build is rebuilt as the tree is at
# the end.
#
# Usage: FUZZ_BUILD=build/fuzz MAKE=make sabotage.sh
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
B=${FUZZ_BUILD:-build/fuzz}
MAKE=${MAKE:-make}
OUT=$B/sabotage
mkdir -p "$OUT"

patched=
restore() {
    [ -n "$patched" ] && git checkout -- $patched
    patched=
}
trap 'restore' EXIT
trap 'restore; exit 130' INT TERM

if ! git diff --quiet -- src; then
    echo "fuzz-sabotage: src/ has uncommitted changes; refusing to patch over them" >&2
    exit 2
fi

missed=
n=0
for p in fuzz/mutants/*.patch; do
    m=$(basename "$p" .patch)
    h=${m%%-*}
    prop=${m#*-}
    fn=check_$(echo "$prop" | tr - _)
    n=$((n + 1))
    files=$(git apply --numstat "$p" | awk '{ print $3 }')
    if ! git apply "$p"; then
        echo "$m: $p no longer applies"
        missed="$missed $m"
        continue
    fi
    patched=$files
    echo "== $m: fuzz_$h against $(grep '^+[^+]' "$p" | sed 's/^+[[:space:]]*//')"
    if ! $MAKE --no-print-directory "$B/fuzz_$h" >"$OUT/$m.build.log" 2>&1; then
        cat "$OUT/$m.build.log"
        echo "$m: the mutant does not build"
        missed="$missed $m"
        restore
        continue
    fi
    found=
    other=
    for seed in fuzz/corpus/$h/*; do
        "$B/fuzz_$h" -runs=1 -artifact_prefix="$OUT/$m-" "$seed" >"$OUT/$m.log" 2>&1 && continue
        if grep -qE "in $fn(_[a-z]+)*[ (]" "$OUT/$m.log"; then
            found=$seed
            break
        fi
        other="$other $(basename "$seed")"
    done
    restore
    if [ -n "$found" ]; then
        echo "$m: found by $found, in $fn: $(grep -m1 -E '^SUMMARY: ' "$OUT/$m.log")"
    else
        [ -n "$other" ] && echo "$m: seeds that crashed elsewhere:$other"
        echo "$m: MUTANT NOT FOUND -- no seed breaks $fn"
        missed="$missed $m"
    fi
done

# leave the sanitizer build as the tree is, not as the last mutant was
$MAKE --no-print-directory fuzz >"$OUT/rebuild.log" 2>&1 || { cat "$OUT/rebuild.log"; exit 1; }

if [ "$n" -eq 0 ]; then
    echo "make fuzz-sabotage: RED -- no mutant in fuzz/mutants/"
    exit 1
fi
if [ -n "$missed" ]; then
    echo "make fuzz-sabotage: RED --$missed"
    exit 1
fi
echo "make fuzz-sabotage: all $n mutants found, each by its own property"
