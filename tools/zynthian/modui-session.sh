#!/bin/bash
# One mod-ui session against one daemon, every message between them logged.
#
#   tools/zynthian/modui-session.sh <mod-host|plugin-hostd> <out-dir>
#
# Starts a JACK server with the dummy driver (no sound card), the daemon on ports 6555/6556 (as Zynthian does, mod-host
# is loaded into jackd as an internal client, zynthian-sys etc/systemd/mod-host.service: `jack_load -i 5555 mod-host`;
# plugin-hostd is a process of its own, its LV2 worker the same mod-host built as a program), verb-proxy.py in front of
# it on 5555/5556, Zynthian's mod-ui on MODUI_PORT with the environment of zynthian-sys sbin/mod-ui.sh, and
# modui-drive.py against mod-ui. Leaves in <out-dir>: verbs.jsonl (every message), drive.jsonl (what mod-ui answered),
# and the logs of each program.
#
# Environment (defaults are the spike pod's):
#   MOD_HOST_SO     mod-host.so built from moddevices/mod-host (the internal client)
#   MOD_HOST_BIN    the mod-host program from the same build (plugin-hostd's LV2 worker; with MOD_HOST_PROCESS=1 the
#                   reference daemon itself)
#   PLUGIN_HOSTD    plugin-hostd
#   MODUI_DIR       a checkout of zynthian/mod-ui, utils/libmod_utils.so built
#   MODUI_PYTHON    a Python with mod-ui's requirements (tornado 4.3)
#   JACK_RATE, JACK_PERIOD  the dummy driver's rate and period
set -u
mode=${1:?mode: mod-host or plugin-hostd}
out=$(mkdir -p "${2:?out dir}" && cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
MOD_HOST_SO=${MOD_HOST_SO:-/tmp/spike/src/mod-host-upstream/mod-host.so}
MOD_HOST_BIN=${MOD_HOST_BIN:-/tmp/spike/src/mod-host-upstream/mod-host}
PLUGIN_HOSTD=${PLUGIN_HOSTD:-plugin-hostd}
MODUI_DIR=${MODUI_DIR:-/tmp/spike/src/mod-ui}
MODUI_PYTHON=${MODUI_PYTHON:-/tmp/spike/venv/bin/python}
MODUI_PORT=${MODUI_PORT:-8888}
JACK_RATE=${JACK_RATE:-48000}
JACK_PERIOD=${JACK_PERIOD:-256}
export JACK_DEFAULT_SERVER=${JACK_DEFAULT_SERVER:-spike}
pids=()
cleanup() {
    for ((i=${#pids[@]}-1; i>=0; i--)); do kill "${pids[i]}" 2>/dev/null; done
    sleep 1
    for p in "${pids[@]}"; do kill -9 "$p" 2>/dev/null; done
}
trap cleanup EXIT
# a session starts from nothing: mod-ui lists the presets and pedalboards an earlier one left in HOME first
rm -rf "$out"/*.jsonl "$out"/state "$out"/.lv2 "$out"/pedalboards "$out"/modui-data "$out"/user-files "$out"/bin "$out"/internal

# JACK2 finds an internal client by name in JACK_INTERNAL_DIR, not by path
mkdir -p "$out/internal" && ln -sf "$MOD_HOST_SO" "$out/internal/mod-host.so"
JACK_INTERNAL_DIR="$out/internal" jackd -n "$JACK_DEFAULT_SERVER" -r -d dummy -r "$JACK_RATE" -p "$JACK_PERIOD" >"$out/jackd.log" 2>&1 & pids+=($!)
for _ in $(seq 50); do jack_lsp >/dev/null 2>&1 && break; sleep 0.2; done

# the ports must be free: a jackd that crashed on the last session's teardown holds them while it dumps core
for _ in $(seq 120); do ss -Htan "( sport = :6555 or sport = :6556 )" 2>/dev/null | grep -q . || break; sleep 1; done
case $mode in
mod-host)
    if [ "${MOD_HOST_PROCESS:-0}" = 1 ]; then
        "$MOD_HOST_BIN" -n -p 6555 -f 6556 >"$out/daemon.log" 2>&1 & pids+=($!)
    else
        jack_load -i 6555 mod-host >"$out/daemon.log" 2>&1
    fi ;;
plugin-hostd)
    # its LV2 worker is the mod-host program of the same build: put it first on PATH
    mkdir -p "$out/bin" && ln -sf "$MOD_HOST_BIN" "$out/bin/mod-host"
    printf 'require_pins 0\n' >"$out/plugin-hostd.conf"
    PATH="$out/bin:$PATH" XDG_STATE_HOME="$out/state" "$PLUGIN_HOSTD" -n -p 6555 -f 6556 -c "$out/plugin-hostd.conf" \
        >"$out/daemon.log" 2>&1 & pids+=($!) ;;
*) echo "mode: mod-host or plugin-hostd" >&2; exit 2 ;;
esac
sleep 2

python3 "$here/verb-proxy.py" --log "$out/verbs.jsonl" >"$out/proxy.log" 2>&1 & pids+=($!)
sleep 1

data="$out/modui-data"; mkdir -p "$data" "$out/pedalboards" "$out/user-files"
(cd "$MODUI_DIR" && MOD_LOG=1 MOD_APP=0 MOD_DEV_ENVIRONMENT=0 MOD_DEV_HOST=0 MOD_DEV_HMI=1 MOD_SYSTEM_OUTPUT=0 \
    MOD_DATA_DIR="$data" MOD_USER_FILES_DIR="$out/user-files" MOD_USER_PEDALBOARDS_DIR="$out/pedalboards" \
    MOD_HTML_DIR="$MODUI_DIR/html" MOD_DEVICE_WEBSERVER_PORT="$MODUI_PORT" HOME="$out" \
    exec "$MODUI_PYTHON" ./server.py) >"$out/modui.log" 2>&1 & pids+=($!)

python3 "$here/modui-drive.py" --url "http://127.0.0.1:$MODUI_PORT" --log "$out/drive.jsonl"
rc=$?
jack_lsp -c >"$out/jack-graph-end.txt" 2>&1
[ "$mode" = mod-host ] && [ "${MOD_HOST_PROCESS:-0}" != 1 ] && jack_unload mod-host >/dev/null 2>&1
echo "session $mode: driver exit $rc, $(wc -l <"$out/verbs.jsonl") messages in $out/verbs.jsonl"
exit $rc
