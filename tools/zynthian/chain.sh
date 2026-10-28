#!/bin/bash
# The plugind chain of the Zynthian engine, offline: the spike engine (spike-engine.sh) applied to zynthian-ui at its
# pinned commit, and tools/zynthian/test-chain.py run against plugin-hostd and tests/fake-host (no JACK, no plugin).
#
#   tools/zynthian/chain.sh <zynthian-ui clone> <out-dir>
#
# Environment: PLUGIN_HOSTD (./plugin-hostd, with chain_get: plugin-hostd#162), FAKE_HOST (tests/fake-host),
# PLUGIN_HOSTD_OLD (a daemon without chain_get, for the floor scenario), PYTHON; CHAIN_E2E and the variables
# test-chain.py names for the run against omx-clap-host. Build the daemon first: make plugin-hostd tests/fake-host.
set -u
zui_src=${1:?zynthian-ui clone}
out=$(mkdir -p "${2:?out dir}" && cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
. "$here/spike-engine.sh"
PYTHON=${PYTHON:-python3}
rm -rf "$out/zynthian-ui"
git -C "$zui_src" worktree add -f -q "$out/zynthian-ui" "$ZUI_SHA" || exit 1
spike_engine_apply "$out/zynthian-ui" "$out" || exit 2
timeout 900 "$PYTHON" "$here/test-chain.py" --zui "$out/zynthian-ui" >"$out/test.log" 2>&1
rc=$?
git -C "$zui_src" worktree remove --force "$out/zynthian-ui"
grep -E '^(ok|FAIL|CHAIN)' "$out/test.log"
exit $rc
