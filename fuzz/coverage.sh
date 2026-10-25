#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# THE COVERAGE WITNESS (make fuzz-coverage). Each harness, built for llvm-cov without sanitizers, has run once over its
# seed corpus; this prints the line coverage of the functions the harness exists to drive, and every line of them the
# corpus never reached. The relay's thread, its listening socket and its wake-up pipe are not the reader and are not
# counted.
#
# THE FLOOR. fuzz/coverage-floor.txt holds, per harness, the number of covered lines the committed corpus reaches. A
# harness below its floor turns this red: a seed lost, a harness that stopped driving a function, or code that grew
# lines its corpus never reaches. Raise a floor when coverage rises; lower one only with the change that removed the
# lines.
#
# THE HARNESS FLOOR. Every property check of the harness, each abort() in fuzz/fuzz_<harness>.c and in the helpers of
# fuzz/ it is built with, and the statement that guards it (fuzz/checks.awk), must be executed by at least one seed: a
# check no seed reaches is a property nobody tests. This names the file and line of every such check and turns red. A
# stop marked `not a property` needs no seed. A check whose comment has no `mutant:` and `input:` record and no
# `not a property:` line turns this red as well (fuzz/records.sh proves the records).
#
# Usage: coverage.sh <cov build dir> <harness>...   (LLVM_COV names llvm-cov)
set -eu
B=$1
shift
LLVM_COV=${LLVM_COV:-llvm-cov}
FLOOR=fuzz/coverage-floor.txt
[ -f "$FLOOR" ] || { echo "coverage.sh: no $FLOOR" >&2; exit 2; }
low=
dead=

# the functions each harness covers; static functions are matched by their bare name
funcs() {
    case $1 in
    command) echo src/verbs.c :: is_instance_verb is_placement pin_set_words number chain_words reply handle \
        verbs_receive ;;
    reply) echo src/relay.c :: send_line gesture_seen gesture_end gestures_end gestures_end_instance drain \
        relay_finish relay_event relay_add relay_instance_gone relay_remove ;;
    *) echo "coverage.sh: no function list for harness '$1'" >&2; exit 2 ;;
    esac
}

# the files whose checks belong to each harness: its own, and the helpers of fuzz/ it is built with
checked() {
    case $1 in
    command) echo fuzz/fuzz_command.c fuzz/recorder.c fuzz/fuzz.h ;;
    reply) echo fuzz/fuzz_reply.c ;;
    esac
}
unrecorded=

for h in "$@"; do
    set -- $(funcs "$h")
    files=
    while [ "$1" != "::" ]; do files="$files $1"; shift; done
    shift
    bin=$B/fuzz_$h prof=$B/$h.profdata
    echo "== fuzz_$h: $(ls fuzz/corpus/$h | wc -l) seed inputs"
    # Name Regions Miss Cover Lines Miss Cover ...: keep the listed functions
    tot=$B/$h.covered
    "$LLVM_COV" report -show-functions "$bin" -instr-profile="$prof" $files |
    awk -v want="$*" -v tot="$tot" '
        BEGIN { n = split(want, w, " "); for (i = 1; i <= n; i++) keep[w[i]] = 1 }
        { name = $1; sub(/^.*:/, "", name) }
        (name in keep) && NF >= 10 {
            printf "  %-26s lines %4d  missed %3d  %s\n", name, $5, $6, $7
            lines += $5; missed += $6; seen[name] = 1
        }
        END {
            for (k in keep) if (!(k in seen)) printf "  %-26s NOT FOUND in the report\n", k
            printf "  %-26s lines %4d  missed %3d  %.2f%%\n", "TOTAL", lines, missed,
                   lines ? 100 * (lines - missed) / lines : 0
            print lines - missed > tot
        }'
    for f in "$@"; do
        "$LLVM_COV" show "$bin" -instr-profile="$prof" -name-regex="^(.*:)?$f\$" $files 2>/dev/null |
        awk -v f="$f" -F'|' '$2 ~ /^ *0$/ { sub(/^ */, "", $1); printf "    unreached %s:%s %s\n", f, $1, $3 }'
    done
    : >"$B/$h.checks"
    for src in $(checked "$h"); do
        "$LLVM_COV" show "$bin" -instr-profile="$prof" "$src" >"$B/$h.show"
        awk -v file="$src" -f fuzz/checks.awk "$B/$h.show" >>"$B/$h.checks" || unrecorded="$unrecorded $src"
    done
    nchk=$(awk -F: '$4 != "-"' "$B/$h.checks" | wc -l)
    nnap=$(awk -F: '$4 == "-"' "$B/$h.checks" | wc -l)
    if [ "$nchk" -eq 0 ]; then
        echo "  CHECKS: no property check found in $(checked "$h")"
        dead="$dead $h"
    elif awk -F: '$4 == "0" { n++ } END { exit !n }' "$B/$h.checks"; then
        awk -F: '$4 == "0" { t = $0; sub(/^([^:]*:){4}/, "", t)
            printf "  CHECK: %s:%d no seed reaches (abort at line %d): %s\n", $1, $2, $3, t }' "$B/$h.checks"
        dead="$dead $h"
    else
        echo "  checks: all $nchk property checks of $(checked "$h" | tr ' ' ',') reached; $nnap stops not a property"
    fi
    covered=$(cat "$tot")
    floor=$(awk -v h="$h" '$1 == h { print $2 }' "$FLOOR")
    if [ -z "$floor" ]; then
        echo "  FLOOR: fuzz_$h has no line in $FLOOR"
        low="$low $h"
    elif [ "$covered" -lt "$floor" ]; then
        echo "  FLOOR: fuzz_$h covers $covered lines, below its floor of $floor"
        low="$low $h"
    else
        echo "  floor $floor: held ($covered covered)"
    fi
done

[ -z "$low" ] || echo "make fuzz-coverage: RED -- below the coverage floor:$low"
[ -z "$dead" ] || echo "make fuzz-coverage: RED -- harness checks no seed reaches:$dead"
[ -z "$unrecorded" ] || echo "make fuzz-coverage: RED -- checks with no record and no not-a-property line:$unrecorded"
[ -z "$low$dead$unrecorded" ] || exit 1
echo "make fuzz-coverage: every harness at or above its coverage floor, every check reached"
