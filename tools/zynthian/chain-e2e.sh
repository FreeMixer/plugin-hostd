#!/bin/bash
# The plugind chain end to end: the spike engine (spike-engine.sh) applied to zynthian-ui at its pinned commit, and
# tools/zynthian/test-chain.py's scenarios (no sabotage: chain.sh holds those) run against plugin-hostd with
# omx-clap-host as its worker, an LV2 member on the adapter row and CLAP members, in a PipeWire of its own. With
# --round-trip it runs tools/zynthian/test-chain-round-trip.py instead, its sabotages included: a chain of omx-plugins
# members, the values each leaves on the audio.
#
#   tools/zynthian/chain-e2e.sh [--round-trip] <zynthian-ui clone> <out-dir>
#
# Environment: PLUGIN_HOSTD (a daemon with chain_get, plugin-hostd#162), CLAP_HOST (an omx-clap-host that runs the chain
# line, omx-clap-core#104), FAULT_CLAP_URI and CHAIN_FAULT_PARAM (a CLAP plugin that aborts on a write, and that write
# with %d for its instance: omx-clap-core's tests/fault-14.clap and "param_set %d 0 0.95"), PYTHON. test-chain.py
# also takes CHAIN_LV2_URI (a stereo LV2 effect, default x42's fil4 stereo) and CHAIN_LV2_PATH (its LV2 path, default the plugin-hostd
# default list, tools/search-paths.py lv2), CHAIN_CLAP_URI (a stereo CLAP effect). --round-trip takes JACK_IDENTITY (omx-clap-core's
# tests/jack_identity), OMX_CLAP_DIR (omx-plugins' CLAP directory, default /usr/lib/clap) and CHAIN_LV2_PATH.
set -u
if [ -z "${CHAIN_E2E_INSIDE:-}" ]; then
    export CHAIN_E2E_INSIDE=1
    # the namespace below has no network: the spike engine's patch is read before it
    . "$(cd "$(dirname "$0")" && pwd)/spike-engine.sh"
    spike_dir=$(mktemp -d /tmp/zyn-spike-engine.XXXXXX)
    spike_engine_fetch "$spike_dir" || exit 2
    if unshare --user --map-root-user --net --pid --fork --mount-proc true 2>/dev/null; then
        exec unshare --user --map-root-user --net --pid --fork --mount-proc "$0" "$@"
    fi
    exec unshare --user --map-root-user --net setsid -w "$0" "$@"
fi
test=test-chain.py
args=--no-sabotage
if [ "${1:-}" = --round-trip ]; then
    test=test-chain-round-trip.py
    args=
    shift
fi
zui_src=${1:?zynthian-ui clone}
out=$(mkdir -p "${2:?out dir}" && cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
. "$here/spike-engine.sh"
PYTHON=${PYTHON:-python3}
# the round trip's measure checks itself first, with no graph: a member's run that left no peak is played again
if [ "$test" = test-chain-round-trip.py ]; then
    "$PYTHON" "$here/$test" --self-test || exit 1
fi
export CHAIN_E2E=1 CHAIN_LV2_URI=${CHAIN_LV2_URI:-lv2:http://gareus.org/oss/lv2/fil4#stereo}
: "${PLUGIN_HOSTD:?}" "${CLAP_HOST:?}" "${FAULT_CLAP_URI:?}" "${CHAIN_FAULT_PARAM:?}"
if [ "$test" = test-chain.py ]; then
    : "${CHAIN_CLAP_URI:?}"
else
    : "${JACK_IDENTITY:?}"
fi

runtime=$(mktemp -d /tmp/zyn-chain-e2e.XXXXXX)
export XDG_RUNTIME_DIR=$runtime PIPEWIRE_RUNTIME_DIR=$runtime PULSE_RUNTIME_PATH=$runtime/pulse
unset DBUS_SESSION_BUS_ADDRESS
ip link set lo up
pipewire >"$runtime/pw.log" 2>&1 &
pw=$!
trap 'kill $pw 2>/dev/null; wait 2>/dev/null; rm -rf "$runtime"' EXIT
for _ in $(seq 50); do [ -S "$runtime/pipewire-0" ] && break; sleep 0.1; done
[ -S "$runtime/pipewire-0" ] || { echo "pipewire did not come up" >&2; exit 2; }

rm -rf "$out/zynthian-ui"
git -C "$zui_src" worktree add -f -q "$out/zynthian-ui" "$ZUI_SHA" || exit 1
spike_engine_apply "$out/zynthian-ui" "$out" || exit 2
echo "plugin-hostd: $("$PLUGIN_HOSTD" --version)"
echo "omx-clap-host: $CLAP_HOST"
if [ "$test" = test-chain.py ]; then
    echo "members: $CHAIN_LV2_URI (LV2, adapter row), $CHAIN_CLAP_URI (CLAP), $FAULT_CLAP_URI (CLAP, the culprit)"
else
    echo "members: omx-strip, omx-limiter (CLAP, ${OMX_CLAP_DIR:-/usr/lib/clap}), omx-delay (LV2, adapter row);" \
        "$FAULT_CLAP_URI (CLAP, the culprit)"
fi
timeout 1800 "$PYTHON" "$here/$test" --zui "$out/zynthian-ui" $args >"$out/test.log" 2>&1
rc=$?
git -C "$zui_src" worktree remove --force "$out/zynthian-ui"
grep -E '^(ok|FAIL|CHAIN|ROUND TRIP|     )' "$out/test.log"
exit $rc
