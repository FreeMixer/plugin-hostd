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

# --- the rules the unit tests guard: a copy of bench/ with one line changed must turn the named test red
break_unit() {  # break_unit <label> <file under bench/> <old> <new> <test name>
    local copy="$work/unit-$1"
    cp -r "$here" "$copy"
    python3 -I - "$copy/$2" "$3" "$4" <<'PY'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
assert s.count(old) == 1, "the sabotage did not land: " + old
open(p, "w").write(s.replace(old, new))
PY
    red "unit: $1" "(FAIL|ERROR): ${5##*.}" python3 -I "$copy/tests/test_bench.py" "$5"
}
break_unit spread-median lib/validate.py 'elif isinstance(s[field], (int, float)) and not span[0] <= s[field] <= span[1]:' \
    'elif False:' Schema.test_a_spread_that_does_not_hold_the_median_is_red
break_unit stress-key lib/validate.py 's.get("rate"), s.get("frames"), s.get("stress", "none"))' \
    's.get("rate"), s.get("frames"))' Schema.test_the_same_row_with_and_without_stress_are_two_rows
break_unit stress-xruns lib/validate.py 'and s.get("status") == "ok" and "xruns" not in s:' 'and False:' \
    Schema.test_a_stressed_row_without_xruns_is_red
break_unit spread-repeats lib/validate.py 'if s.get("repeats", 1) < 2:' 'if False:' Schema.test_a_spread_of_one_run_is_red
break_unit probe-count lib/bench.py 'self.total += 1' 'self.total += 0' Xruns.test_the_probe_counts_what_jack_reports
break_unit probe-server lib/bench.py 'self.NO_START | self.SERVER_NAME' 'self.SERVER_NAME' Xruns.test_the_probe_joins_the_private_server_only
break_unit probe-deaf lib/bench.py 'if counted == 0 and logged > 0:' 'if False:' Xruns.test_a_deaf_probe_is_failed_not_zero
break_unit probe-latency lib/bench.py 'return int(rng.max)' 'return int(rng.min)' Xruns.test_the_latency_is_the_longest_of_the_range
break_unit log-offset lib/bench.py 'f.seek(offset)' 'f.seek(0)' Xruns.test_the_servers_log_counts_new_xrun_lines_only
break_unit stress-pin lib/bench.py 'os.sched_setaffinity(0, {int(sys.argv[1])})' 'pass' Stress.test_a_busy_loop_runs_on_its_core_only
break_unit stress-mem lib/bench.py 'bytearray(int(sys.argv[1]) << 20)' 'bytearray(int(sys.argv[1]) << 10)' Stress.test_the_memory_touch_holds_its_size
break_unit stress-cores lib/bench.py 'return "busy%d+mem%d" % (len(cores), STRESS_MEM_MB)' 'return "busy1+mem%d" % STRESS_MEM_MB' Stress.test_the_profile_names_the_cores_and_the_memory
break_unit stress-both lib/bench.py '"both": [False, True]' '"both": [True]' Stress.test_stress_rows_are_the_same_scenario_with_and_without
break_unit rep-high lib/bench.py 'statistics.median_high(vals)' 'statistics.median_low(vals)' Repeats.test_a_count_stays_a_count_and_is_never_understated
break_unit rep-mean lib/bench.py 'round(statistics.median(vals), 2)' 'round(statistics.mean(vals), 2)' Repeats.test_the_median_is_the_middle_run_not_the_mean
break_unit rep-spread lib/bench.py 'spread[key] = [min(vals), max(vals)]' 'spread[key] = [min(vals), min(vals)]' Repeats.test_the_median_and_the_spread_of_three_runs
break_unit rep-failed lib/bench.py 'if row["status"] == "failed" and (wanted or len(runs)) > 1:' 'if False:' Repeats.test_a_failed_repeat_fails_the_row_and_names_it
break_unit rep-stop lib/bench.py 'if runs[-1]["status"] != "ok":' 'if False:' Repeats.test_the_runner_stops_repeating_at_the_first_row_that_is_not_ok
break_unit rep-count lib/bench.py 'for _ in range(self.args.repeats):' 'for _ in range(1):' Repeats.test_the_runner_runs_the_row_as_many_times_as_asked
break_unit plan-one lib/bench.py 'if len(segments) < 2:' 'if False:' Grouping.test_a_plan_of_one_segment_fails_the_row
break_unit plan-reply lib/bench.py 'words[:2] != ["resp", "0"]' 'False' Grouping.test_a_refused_plan_is_failed_with_the_daemons_words
break_unit pool-alone lib/bench.py 'and seg[0] not in alone]' 'and True]' Grouping.test_the_pool_takes_the_shareable_members_the_plan_left_alone
break_unit pool-holder lib/bench.py 'if len(holder) != 1 or sorted(holder[0][5]) != sorted(pooled):' 'if False:' Grouping.test_a_pool_under_another_name_is_failed
break_unit pool-min lib/bench.py 'if len(pooled) < 2:' 'if False:' Grouping.test_a_pool_of_one_is_not_a_pool
break_unit pins-replace lib/bench.py '[w for w in words if not w.startswith("verdict=")]' 'list(words)' Pins.test_each_uri_gets_its_verdict_and_the_rest_is_kept
break_unit pins-missing lib/bench.py 'if missing:' 'if False:' Pins.test_a_uri_the_daemon_never_learned_is_failed
break_unit conf-grouping lib/bench.py '"pins_dir", "grouping on")' '"pins_dir")' Pins.test_the_conf_of_a_plan_row_turns_pins_and_grouping_on_and_package_pins_off
break_unit conf-verdict lib/bench.py '"isolated" if u in alone else "in-process"' '"in-process" if u in alone else "isolated"' Pins.test_the_conf_of_a_plan_row_turns_pins_and_grouping_on_and_package_pins_off
break_unit scenario-strip scenarios.json '"count": 8, "unshared": ["drive"]' '"count": 8, "unshared": ["comp", "delay", "drive"]' Scenarios.test_the_grouping_scenarios_have_all_four_modes_and_a_strip_the_pins_cut
break_unit table-ratio lib/table.py 'ind[key] / grp[key]' 'grp[key] / ind[key]' Table.test_the_ratios_of_individual_over_chain
break_unit table-stress lib/table.py 'key = (label(r), r.get("stress", "none") != "none")' 'key = (label(r), False)' Table.test_xruns_are_summed_per_mode_with_and_without_stress
break_unit table-spread lib/table.py 'if lo != hi:' 'if False:' Table.test_a_spread_shows_beside_its_median
break_unit table-failed lib/table.py 'if r["status"] != "ok":' 'if False:' Table.test_a_failed_row_is_shown_with_its_reason
break_unit table-family lib/table.py '(cvp|grp)[0-9]+$' '.*$' Table.test_a_scenario_that_is_not_a_family_is_left_out
green "unit tests as they are" python3 -I "$here/tests/test_bench.py"

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
