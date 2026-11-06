#!/bin/bash
# Break each guard of the harness on purpose and watch it go red, then run it whole and watch it stay green:
#   validator: a shipped example passes; a document with one field broken fails, naming file, scenario and rule
#   teardown:  a copy of the runner whose host stop leaves the host, and one whose last stop leaves the JACK server,
#              both end non-zero naming the process left; the runner as it is ends with nothing left
# The teardown part needs jackd2, jack-example-tools and omx-clap-host: run it with --teardown.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d)
# the copies of bench/ below sit outside the checkout: the one list of search folders is still the checkout's
export SEARCH_PATHS_TOOL="$here/../tools/search-paths.py"
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
break_unit probe-deaf lib/bench.py 'return max(counted, logged), note' 'return counted, note' Xruns.test_a_deaf_probe_is_not_zero_and_not_a_failure
break_unit xrun-note lib/bench.py 'if not xrun_sources_agree(counted, logged):' 'if False:' Xruns.test_a_windows_xruns_are_the_larger_of_the_probe_and_the_log
break_unit xrun-tolerance lib/bench.py 'max(XRUN_TOLERANCE, max(counted, logged) // 10)' 'max(XRUN_TOLERANCE, max(counted, logged) // 5)' Xruns.test_a_windows_xruns_are_the_larger_of_the_probe_and_the_log
break_unit log-burst lib/bench.py 'if named and not in_burst:' 'if named:' Xruns.test_the_servers_log_counts_new_xrun_events_only
break_unit dsp-warmup lib/bench.py '        return vals[1:]' '        return vals[:seconds]' Xruns.test_the_dsp_load_is_read_from_the_server_by_the_probe_and_the_first_reading_is_dropped
break_unit dsp-client lib/bench.py '        if not self.client:
            raise Failed("the probe has no JACK client to read the DSP load from")' '        pass' Xruns.test_a_probe_without_a_client_cannot_read_the_dsp_load
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
break_unit rep-stop lib/bench.py 'if runs[i] and runs[i][-1]["status"] != "ok":' 'if False:' Repeats.test_the_runner_stops_repeating_at_the_first_row_that_is_not_ok
break_unit rep-count lib/bench.py 'for _ in range(self.args.repeats):' 'for _ in range(1):' Repeats.test_the_runner_runs_the_row_as_many_times_as_asked
break_unit jack-hang lib/bench.py '    except subprocess.TimeoutExpired:
        raise JackUnanswered' '    except OSError:
        raise JackUnanswered' JackUnanswered.test_a_jack_tool_that_hangs_is_a_failed_row_naming_it
break_unit jack-restart lib/bench.py '        if isinstance(e, JackUnanswered):
            self.jack_dirty = True' '        pass' JackUnanswered.test_the_run_goes_on_and_jack_starts_again_after_a_row_it_did_not_answer
break_unit jack-nostart lib/bench.py '                    except JackUnanswered as e:
                        self.jack_stop()' '                    except ZeroDivisionError as e:
                        self.jack_stop()' JackUnanswered.test_a_jack_that_does_not_start_again_fails_each_row_and_the_run_still_ends
break_unit probe-timeout lib/bench.py '                self._lost("timed out after %g s" % PROBE_TIMEOUT_S)' '                return None' ProbeHardTimeout.test_a_call_that_hangs_fails_the_row_within_the_timeout_and_the_process_is_gone
break_unit probe-close lib/bench.py '            self.procs.stop(proc)' '            pass' ProbeHardTimeout.test_close_returns_from_a_wedged_server_and_kills_the_process
break_unit probe-stray lib/bench.py '            jack.add(self.probe.proc.pid)' '            pass' ProbeHardTimeout.test_the_probe_is_not_a_process_left_behind_by_a_row
break_unit probe-gone lib/bench.py '            raise Failed("the JACK server went away")' '            pass' ProbeHardTimeout.test_a_server_that_went_away_is_an_error_not_an_old_reading
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
break_unit table-family lib/table.py '(cvp|cvc|cvl|grp)[0-9]+$' '.*$' Table.test_a_scenario_that_is_not_a_family_is_left_out
# --- the soundness gate: each check, broken on purpose, turns the test that feeds it a disturbed sample red
break_unit gate-spread lib/soundness.py 'if span and avg > 0 and span[1] - span[0] > max(SPREAD_REL * avg, FLOOR):' \
    'if False:' Soundness.test_a_wide_spread_is_flagged_and_a_narrow_one_is_not
break_unit gate-spread-floor lib/soundness.py 'span[1] - span[0] > max(SPREAD_REL * avg, FLOOR)' \
    'span[1] - span[0] > SPREAD_REL * avg' Soundness.test_a_spread_inside_the_noise_floor_is_not_flagged
break_unit gate-twin lib/soundness.py 'if over(b["dsp_load_avg"], a["dsp_load_avg"], CELL_REL):' \
    'if False:' Soundness.test_twins_at_two_period_counts_that_disagree_flag_the_higher
break_unit gate-twin-median lib/soundness.py 'if abs(v - med) > max(CELL_REL * med, FLOOR):' \
    'if False:' Soundness.test_three_twins_flag_the_one_away_from_the_median
break_unit gate-stress lib/soundness.py 'if over(r["dsp_load_avg"], low, CELL_REL):' \
    'if False:' Soundness.test_a_cell_above_its_stressed_twin_is_flagged
break_unit gate-scaling lib/soundness.py 'if fb > fa and over(b["dsp_load_avg"], a["dsp_load_avg"], CELL_REL):' \
    'if False:' Soundness.test_more_frames_costing_more_is_flagged_and_fewer_is_not
break_unit gate-throttle lib/soundness.py 'if bits & THROTTLE_NOW:' \
    'if False:' Soundness.test_a_throttled_repeat_is_flagged
break_unit gate-throttle-history lib/soundness.py 'THROTTLE_NOW = 0x7 ' \
    'THROTTLE_NOW = 0xf0007 ' Soundness.test_a_history_only_throttle_bit_is_not_a_disturbance_now
break_unit gate-freq lib/soundness.py 'if freqs and min(freqs) < (1 - FREQ_REL) * max(freqs):' \
    'if False:' Soundness.test_a_frequency_that_moved_between_repeats_is_flagged
break_unit gate-silent lib/soundness.py 'if not isinstance(db, (int, float)) or db < SILENT_DB:' \
    'if False:' Soundness.test_a_silent_output_is_flagged
break_unit gate-output lib/soundness.py 'and abs(db - want) > OUTPUT_DB:' \
    'and False:' Soundness.test_an_output_unlike_the_same_set_one_process_per_plugin_is_flagged
break_unit gate-output-hosts lib/soundness.py 'OUTPUT_HOSTS = ("H1", "H2")' \
    'OUTPUT_HOSTS = ("H1", "H2", "H3", "H4")' Soundness.test_the_other_builds_of_h3_and_h4_are_not_held_to_the_h2_level
break_unit gate-annotate lib/soundness.py 'gate = {"verdict": "unstable", "reasons": bad[(0, i)]}' \
    'gate = {"verdict": "pass", "reasons": []}' Soundness.test_annotate_marks_every_row_and_names_the_reasons
break_unit gate-validate lib/validate.py 'if gate.get("verdict") != "unstable":' \
    'if False:' GateCommands.test_validate_refuses_the_disturbed_pi_cell_and_names_it
break_unit gate-validate-pass lib/validate.py 'if gate.get("verdict") != "unstable":' \
    'if not gate:' GateCommands.test_validate_refuses_a_pass_mark_on_a_disturbed_cell
break_unit gate-validate-why lib/validate.py 'and not gate.get("reasons"):' \
    'and False:' GateCommands.test_validate_wants_a_reason_with_an_unstable_mark
break_unit gate-exit lib/gate.py 'sys.exit(1 if bad else 0)' \
    'sys.exit(0)' GateCommands.test_gate_sh_exits_1_on_the_pi_cells_and_prints_the_rerun
break_unit gate-rerun lib/bench.py 'if not plan or (r.get("gate") or {}).get("rerun"):' \
    'if True:' SettleGate.test_a_cell_that_breaks_a_check_is_rerun_and_marked_pass_when_the_rerun_agrees
break_unit gate-rerun-once lib/bench.py 'if not plan or (r.get("gate") or {}).get("rerun"):' \
    'if not plan:' SettleGate.test_a_cell_already_rerun_alone_is_not_rerun_again
break_unit gate-mark lib/bench.py 'unstable = soundness.annotate(doc)' \
    'unstable = 0' SettleGate.test_a_cell_that_still_breaks_after_the_rerun_is_published_as_unstable
break_unit interleave lib/bench.py '        for _ in range(self.args.repeats):
            for i, (s, h, mode, stress) in enumerate(group):' \
    '        for i, (s, h, mode, stress) in enumerate(group):
            for _ in range(self.args.repeats):' Interleave.test_the_hosts_take_turns_across_the_repeats
break_unit state-kept lib/bench.py 'row["repeat_state"] = states' \
    'pass' MachineState.test_the_repeats_keep_their_states_and_cycles
break_unit state-irq lib/bench.py 'counts.index(max(counts))' \
    '0' MachineState.test_the_state_reads_frequency_temperature_cores_and_the_usb_interrupt
break_unit state-cores lib/bench.py 'cores.add(int(f.read().rsplit(")", 1)[1].split()[36]))' \
    'cores.add(0)' MachineState.test_the_state_reads_frequency_temperature_cores_and_the_usb_interrupt
break_unit output-level lib/bench.py 'math.sqrt(sum(x * x for x in data) / len(data)) / 32768.0' \
    'math.sqrt(sum(x * x for x in data) / len(data))' MachineState.test_a_wav_is_read_as_its_level
break_unit table-unstable lib/table.py 'and id(r) not in bad}' \
    '}' TableSoundness.test_an_unstable_cell_is_shown_as_such_and_makes_no_ratio
break_unit table-cycles lib/table.py 'cycles = WINDOW_S * row["rate"] / row["frames"]' \
    'cycles = 1' TableSoundness.test_the_table_carries_the_switches_of_a_cycle
break_unit table-format lib/table.py 'l["dsp_load_avg"] / c["dsp_load_avg"] if c["dsp_load_avg"] else 0' \
    'c["dsp_load_avg"] / l["dsp_load_avg"]' TableSoundness.test_the_format_pairs_put_clap_beside_lv2_on_one_host
break_unit table-rate lib/table.py 'and id(r) not in bad and r.get("dsp_load_avg")' \
    'and r.get("dsp_load_avg")' TableSoundness.test_the_rate_ratio_is_made_from_cells_that_passed
break_unit scenario-cvl scenarios.json '"id": "cvl32", ' \
    '"id": "cvx32", ' FormatScenarios.test_every_clap_chain_scenario_has_its_lv2_twin_on_h1_and_h2
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
