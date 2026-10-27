#!/bin/bash
# send.sh <port> <line> [<line> ...]: send each line to a mod-host protocol port on 127.0.0.1, NUL-terminated,
# and print its one reply on a line of its own. The runner holds one connection per host, as a controller does;
# this is the same framing for a person or a script.
set -euo pipefail

if [ $# -lt 2 ]; then
    echo "usage: send.sh <port> <line> [<line> ...]" >&2
    exit 2
fi
port=$1
shift
for line in "$@"; do
    reply=$(printf '%s\0' "$line" | nc -w 5 127.0.0.1 "$port" | tr -d '\0')
    if [ -z "$reply" ]; then
        echo "send.sh: no reply from port $port to: $line" >&2
        exit 1
    fi
    printf '%s\n' "$reply"
done
