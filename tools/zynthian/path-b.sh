#!/bin/bash
# Path B of the Zynthian spike (FreeMixer/plugin-hostd#124): zynthian_engine_plugind.patch applied to zynthian-ui at the
# pinned commit and tested against Zynthian's engine classes, with JACK (dummy driver) and plugin-hostd running.
#
#   tools/zynthian/path-b.sh <zynthian-ui clone> <out-dir>
#
# Environment: MOD_HOST_BIN (plugin-hostd's LV2 worker), PLUGIN_HOSTD, PYTHON (a Python with lilv, rdflib, psutil,
# pexpect), CLAP_URI. jack-note-meter is built from jack-note-meter.c into <out-dir>.
set -u
zui_src=${1:?zynthian-ui clone}
out=$(mkdir -p "${2:?out dir}" && cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
ZUI_SHA=f46b0189b6163472db39aa607369f397ed23b65a
MOD_HOST_BIN=${MOD_HOST_BIN:-mod-host}
PLUGIN_HOSTD=${PLUGIN_HOSTD:-plugin-hostd}
PYTHON=${PYTHON:-python3}
export JACK_DEFAULT_SERVER=${JACK_DEFAULT_SERVER:-spike}
rm -rf "$out/zynthian-ui"
git -C "$zui_src" worktree add -f -q "$out/zynthian-ui" "$ZUI_SHA" || exit 1
git -C "$out/zynthian-ui" apply "$here/../../docs/zynthian/zynthian_engine_plugind.patch" || exit 1
mkdir -p "$out/bin"
gcc -O2 -o "$out/bin/jack-note-meter" "$here/jack-note-meter.c" -ljack -lm || exit 1
ln -sf "$(command -v "$MOD_HOST_BIN")" "$out/bin/mod-host"
for _ in $(seq 60); do ss -Htan "( sport = :5555 or sport = :5556 )" | grep -q . || break; sleep 1; done
jackd -n "$JACK_DEFAULT_SERVER" -r -d dummy -r 48000 -p 256 >"$out/jackd.log" 2>&1 & J=$!
sleep 2
printf 'require_pins 0\n' >"$out/plugin-hostd.conf"
PATH="$out/bin:$PATH" XDG_STATE_HOME="$out/state" "$PLUGIN_HOSTD" -n -p 5555 -f 5556 -c "$out/plugin-hostd.conf" \
    >"$out/daemon.log" 2>&1 & D=$!
sleep 2
PATH="$out/bin:$PATH" timeout 120 "$PYTHON" "$here/test-path-b.py" --zui "$out/zynthian-ui" >"$out/test.log" 2>&1
rc=$?
kill $D; sleep 1; kill $J; wait 2>/dev/null
git -C "$zui_src" worktree remove --force "$out/zynthian-ui"
grep -E '^(ok|FAIL|PATH-B)' "$out/test.log"
exit $rc
