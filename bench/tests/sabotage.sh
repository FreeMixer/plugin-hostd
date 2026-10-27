#!/bin/bash
# Break each guard of the harness on purpose and watch it go red, then run it whole and watch it stay green:
#   validator: a shipped example passes; a document with one field broken fails, naming file, scenario and rule
#   teardown:  a copy of the runner whose host stop leaves the host, and one whose last stop leaves the JACK server,
#              both end non-zero naming the process left; the runner as it is ends with nothing left
# The teardown part needs jackd2, jack-example-tools and omx-clap-host: run it with --teardown.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0

red() {  # red <label> <expected text> <command...>: the command must fail and print the expected text
    local label=$1 want=$2
    shift 2
    if "$@" >"$work/out" 2>&1; then
        echo "FAIL $label: exit 0, expected red"; fail=1; return
    fi
    if ! grep -qE -- "$want" "$work/out"; then
        echo "FAIL $label: red, but its message lacks /$want/:"; sed 's/^/  /' "$work/out"; fail=1; return
    fi
    echo "ok   $label: red, $(grep -E -m1 -- "$want" "$work/out")"
}

green() {
    local label=$1
    shift
    if "$@" >"$work/out" 2>&1; then
        echo "ok   $label: green"
    else
        echo "FAIL $label:"; sed 's/^/  /' "$work/out"; fail=1
    fi
}

# --- the validator
for ex in "$here"/examples/*.json; do
    green "validate $(basename "$ex")" "$here/validate.sh" "$ex"
done
examples=("$here"/examples/*.json)
ex=${examples[0]}
break_doc() {  # break_doc <name> <python statement on d>
    python3 -I - "$ex" "$work/$1.json" "$2" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
exec(sys.argv[3])
json.dump(d, open(sys.argv[2], "w"))
EOF
}
first_ok='[s for s in d["scenarios"] if s["status"] == "ok"][0]'
break_doc status "${first_ok}[\"status\"] = \"fine\""
red "validator: a status no one declared" "status.json: scenario [a-z0-9-]+ H[1-4] [0-9]+/[0-9]+.*: scenarios/[0-9]+/status:enum" \
    "$here/validate.sh" "$work/status.json"
break_doc dsp "${first_ok}[\"dsp_load_avg\"] = None"
red "validator: an ok row with no DSP load" "dsp.json: scenario .*: scenarios/[0-9]+/dsp_load_avg:type" \
    "$here/validate.sh" "$work/dsp.json"
break_doc unsupported 's = [s for s in d["scenarios"] if s["status"] != "ok"][0]; s["note"] = ""'
red "validator: a row that did not run, with no reason" "unsupported.json: scenario .*: scenarios/[0-9]+/note:minLength" \
    "$here/validate.sh" "$work/unsupported.json"
break_doc maxavg "${first_ok}[\"dsp_load_max\"] = ${first_ok}[\"dsp_load_avg\"] - 0.5"
red "validator: a max below its average" "maxavg.json: scenario .*: rule:max-not-below-avg" \
    "$here/validate.sh" "$work/maxavg.json"
break_doc extra "${first_ok}[\"dsp\"] = 1"
red "validator: a field the schema does not declare" "extra.json: scenario .*: scenarios/[0-9]+:additionalProperties" \
    "$here/validate.sh" "$work/extra.json"

# --- the teardown
if [ "${1:-}" = "--teardown" ]; then
    sabotage() {  # sabotage <name> <old> <new>: a copy of bench/ with one line of the runner changed
        cp -r "$here" "$work/$1"
        python3 -I - "$work/$1/lib/bench.py" "$2" "$3" <<'EOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
assert s.count(old) == 1, "the sabotage did not land: " + old
open(p, "w").write(s.replace(old, new))
EOF
    }
    args=(--class ci --rates 48000 --frames 256 --window 1 --scenarios clap1 --hosts H1 --keep-governor)
    sabotage host-left "            self.procs.stop(self.proc)" "            pass"
    red "teardown: a host left after its row" "teardown after clap1 H1 48000/256 left [0-9]+ omx-clap-host" \
        "$work/host-left/run.sh" --out "$work/res" "${args[@]}"
    sabotage jack-left "        if p not in self.live:" "        if p not in self.live or p.name.startswith('jackd'):"
    red "teardown: the JACK server left at the end" "teardown left 1 process\(es\) of this run: [0-9]+ jackd" \
        "$work/jack-left/run.sh" --out "$work/res" "${args[@]}"
    green "teardown: the runner as it is" "$here/run.sh" --out "$work/res" "${args[@]}"
    # a zombie is no running process: a container whose pid 1 reaps nothing keeps one for each orphan that exited
    left=$(pgrep -a -r RSDT -x 'jackd|omx-clap-host|plugin-hostd|jalv|jack_simple_cli' || true)
    if [ -n "$left" ]; then
        echo "FAIL a process is left after the teardown checks:"; echo "$left"
        fail=1
    fi
fi
exit $fail
