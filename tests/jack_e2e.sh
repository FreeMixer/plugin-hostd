#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# plugin-hostd with real workers over jack, in a PipeWire of its own: the script re-runs itself in a private
# user, net, pid and mount namespace with its own /proc, starts pipewire on a private runtime dir (no session
# manager: nodes, ports, links and the dummy driver are the daemon's own), then tests/jack_e2e.py drives the
# daemon and reads the graph back. Nothing here touches the PipeWire of the session that runs it.
#
# PLUGIN_HOSTD   the daemon (default ./plugin-hostd)
# OMX_CLAP_HOST  omx-clap-host, the CLAP worker (required)
# STRESS_CLAP    tests/stress.clap
# MOD_HOST       mod-host, the LV2 worker; with LV2_DIR, LV2_URI, LV2_BUNDLE and LV2_PARAM (a stereo effect of the path, its bundle, a control) it adds the LV2 steps
# JACK_LEVELS    tests/jack_levels
# FAKE_COMPRESSOR_CLAP, JACK_METER_SOURCE  omx-clap-host's tests/fake_compressor.clap and tests/jack_meter_source: with
#                both, the meters test runs, output_set through the daemon's feedback port

set -u

here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
export PLUGIN_HOSTD=${PLUGIN_HOSTD:-$root/plugin-hostd}
export STRESS_CLAP=${STRESS_CLAP:-$here/stress.clap}
export JACK_LEVELS=${JACK_LEVELS:-$here/jack_levels}

if [ -z "${JACK_E2E_INSIDE:-}" ]; then
    for f in "${OMX_CLAP_HOST:-}" "$PLUGIN_HOSTD" "$STRESS_CLAP" "$JACK_LEVELS"; do
        [ -e "$f" ] || { echo "missing '$f'" >&2; exit 2; }
    done
    export OMX_CLAP_HOST=$(readlink -f "$OMX_CLAP_HOST")
    exec env JACK_E2E_INSIDE=1 unshare --user --map-root-user --net --pid --fork --mount-proc "$0" "$@"
fi

runtime=$(mktemp -d /tmp/plugin-hostd-e2e.XXXXXX)
export XDG_RUNTIME_DIR=$runtime PIPEWIRE_RUNTIME_DIR=$runtime PULSE_RUNTIME_PATH=$runtime/pulse
unset DBUS_SESSION_BUS_ADDRESS
# pid 1 of the namespace: every process in it dies with this script, the trap only makes it orderly
cleanup() {
    kill -TERM -- -1 2>/dev/null
    wait 2>/dev/null
    rm -rf "${runtime:?}"
}
trap cleanup EXIT
[ "$$" = 1 ] || { echo "not pid 1 of a private pid namespace" >&2; exit 2; }
echo "ok   pid 1 of a private pid namespace"

ip link set lo up
pipewire >"$runtime/pw.log" 2>&1 &
for _ in $(seq 50); do [ -S "$runtime/pipewire-0" ] && break; sleep 0.1; done
[ -S "$runtime/pipewire-0" ] || { echo "pipewire did not come up" >&2; cat "$runtime/pw.log" >&2; exit 2; }
pw-metadata -n settings 0 clock.force-rate 48000 >/dev/null
echo "ok   private pipewire on $runtime"

python3 "$here/jack_e2e.py"
