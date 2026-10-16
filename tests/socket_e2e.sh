#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The daemon's command socket against omx-clap-core's socket_conformance.py: a command of exactly the receive buffer
# size, many commands in one write, one command over many writes, clients that leave mid-command, the size limit, a
# random chunking fuzz. The daemon relays controller commands whose length it does not choose, so every one of these
# must reach it whole. worker_list is the command: the daemon answers it itself, with no worker.
#
# PLUGIN_HOSTD:            the daemon (default ./plugin-hostd)
# SOCKET_CONFORMANCE:      the script (omx-clap-host-tests installs it in /usr/libexec/omx-clap-host/tests)
# SOCKET_E2E_PORT:         the command port (default 5571)
# SOCKET_CONFORMANCE_ARGS: extra arguments for the script (--seed N to repeat a fuzz run)

set -u

here=$(cd "$(dirname "$0")" && pwd)
daemon=${PLUGIN_HOSTD:-$here/../plugin-hostd}
script=${SOCKET_CONFORMANCE:-/usr/libexec/omx-clap-host/tests/socket_conformance.py}
port=${SOCKET_E2E_PORT:-5571}

for f in "$daemon" "$script"; do
    [ -e "$f" ] || { echo "missing $f" >&2; exit 2; }
done

log=$(mktemp)
"$daemon" -n -p "$port" >"$log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; rm -f "$log"' EXIT
for _ in $(seq 50); do grep -q "ready" "$log" && break; sleep 0.1; done
grep -q "ready" "$log" || { echo "plugin-hostd did not come up" >&2; cat "$log" >&2; exit 2; }
echo "plugin-hostd on port $port, protocol library: $(grep -o '/[^ ]*libmod-host-protocol[^ ]*' /proc/$pid/maps | sort -u)"

# shellcheck disable=SC2086
python3 -I "$script" --port "$port" --pid "$pid" --command worker_list --answer '^resp 0' ${SOCKET_CONFORMANCE_ARGS:-}
status=$?
kill -0 "$pid" 2>/dev/null || { echo "plugin-hostd is gone:"; tail -5 "$log"; status=1; }
exit $status
