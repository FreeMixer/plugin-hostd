#!/bin/bash
# Path A of the Zynthian spike (FreeMixer/plugin-hostd#124): mod-ui with plugin-hostd as its daemon, against mod-host.
#
#   tools/zynthian/path-a.sh <out-dir>
#
# 1. modui-session.sh twice, mod-host (Zynthian's way: an internal client of jackd) then plugin-hostd, and verb-diff.py
#    over the two verb logs;
# 2. verb-replay.py: the plugin-hostd session's commands again, every LV2 add made a CLAP add;
# 3. verb-probe.py: each of mod-ui's 33 verbs once, against mod-host, plugin-hostd with an LV2 worker and plugin-hostd
#    with a CLAP worker;
# 4. who owns mod-monitor under plugin-hostd: two LV2 instances, the first removed.
# Environment as modui-session.sh; CLAP_URI names the CLAP plugin (default omx-comp of omx-plugins-clap).
set -u
out=$(mkdir -p "${1:?out dir}" && cd "$1" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
MOD_HOST_SO=${MOD_HOST_SO:-/tmp/spike/src/mod-host-upstream/mod-host.so}
MOD_HOST_BIN=${MOD_HOST_BIN:-/tmp/spike/src/mod-host-upstream/mod-host}
PLUGIN_HOSTD=${PLUGIN_HOSTD:-plugin-hostd}
CLAP_URI=${CLAP_URI:-clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp}
LV2_PROBE=(--uri http://calf.sourceforge.net/plugins/Compressor --sym threshold --osym compression)
CLAP_PROBE=(--uri "$CLAP_URI" --sym 1 --osym 0)
export JACK_DEFAULT_SERVER=${JACK_DEFAULT_SERVER:-spike} MOD_HOST_SO MOD_HOST_BIN PLUGIN_HOSTD

waitfree() { for _ in $(seq 120); do ss -Htan "( sport = :$1 or sport = :$(($1 + 1)) )" | grep -q . || break; sleep 1; done; }
jack_up() {
    mkdir -p "$out/internal" && ln -sf "$MOD_HOST_SO" "$out/internal/mod-host.so"
    JACK_INTERNAL_DIR="$out/internal" jackd -n "$JACK_DEFAULT_SERVER" -r -d dummy -r 48000 -p 256 >"$out/jackd-$1.log" 2>&1 &
    JACKD=$!
    for _ in $(seq 50); do jack_lsp >/dev/null 2>&1 && break; sleep 0.2; done
}
jack_down() { kill "$JACKD" 2>/dev/null; wait "$JACKD" 2>/dev/null; }
phd_up() {
    mkdir -p "$out/bin" && ln -sf "$MOD_HOST_BIN" "$out/bin/mod-host"
    printf 'require_pins 0\n' >"$out/plugin-hostd.conf"
    PATH="$out/bin:$PATH" XDG_STATE_HOME="$out/state-$1" "$PLUGIN_HOSTD" -n -p 5555 -f 5556 -c "$out/plugin-hostd.conf" \
        >"$out/daemon-$1.log" 2>&1 &
    PHD=$!
    sleep 2
}
phd_down() { kill "$PHD" 2>/dev/null; wait "$PHD" 2>/dev/null; }

# 1. the two sessions and their difference
for mode in mod-host plugin-hostd; do
    waitfree 6555
    "$here/modui-session.sh" "$mode" "$out/session-$mode"
done
python3 "$here/verb-diff.py" "$out/session-mod-host/verbs.jsonl" "$out/session-plugin-hostd/verbs.jsonl" \
    --json "$out/diff.json" >"$out/diff.txt"

# 2. the session with CLAP plugins; 4. mod-monitor's owner
waitfree 5555; jack_up clap-replay; phd_up clap-replay
MH_PORT=5555 python3 "$here/mhsend.py" "add http://moddevices.com/plugins/caps/AmpVTS 0" \
    "add http://moddevices.com/plugins/caps/AmpVTS 1" worker_list >"$out/monitor-owner.txt"
jack_lsp | grep -v system: >>"$out/monitor-owner.txt"
echo "--- remove 0" >>"$out/monitor-owner.txt"
MH_PORT=5555 python3 "$here/mhsend.py" "remove 0" "connect system:capture_1 mod-monitor:in_1" \
    "connect effect_1:out mod-monitor:in_1" >>"$out/monitor-owner.txt"
jack_lsp | grep -v system: >>"$out/monitor-owner.txt"
MH_PORT=5555 python3 "$here/mhsend.py" "remove -1" >/dev/null
MH_PORT=5555 python3 "$here/verb-replay.py" "$out/session-plugin-hostd/verbs.jsonl" "$CLAP_URI" >"$out/clap-replay.tsv"
phd_down; jack_down

# 3. every verb once on each daemon
waitfree 5555; jack_up probe-ref
jack_load -i 5555 mod-host >"$out/probe-ref-load.log" 2>&1; sleep 1
MH_PORT=5555 timeout 120 python3 "$here/verb-probe.py" "${LV2_PROBE[@]}" --dir "$out/probe-ref" >"$out/probe-ref.tsv"
jack_unload mod-host >/dev/null 2>&1; jack_down
for kind in lv2 clap; do
    waitfree 5555; jack_up "probe-$kind"; phd_up "probe-$kind"
    if [ "$kind" = lv2 ]; then args=("${LV2_PROBE[@]}"); else args=("${CLAP_PROBE[@]}"); fi
    MH_PORT=5555 timeout 120 python3 "$here/verb-probe.py" "${args[@]}" --dir "$out/probe-$kind" >"$out/probe-$kind.tsv"
    phd_down; jack_down
done
paste <(cut -f1,2,3 "$out/probe-ref.tsv") <(cut -f3 "$out/probe-lv2.tsv") <(cut -f3 "$out/probe-clap.tsv") \
    >"$out/probe.tsv"
echo "path A: $(grep -c '^DIFF' "$out/diff.txt") differing replies, $(grep -c '^ONLY' "$out/diff.txt") unmatched commands;" \
    "probe rows $(wc -l <"$out/probe.tsv"); out $out"
