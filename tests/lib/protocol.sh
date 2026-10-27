# SPDX-License-Identifier: GPL-3.0-or-later
# The mod-host line protocol from a shell, the one client every test of plugin-hostd, omx-clap-host and the
# controllers sources: a command is one line ended by a NUL, a reply is one NUL-ended line. Installed by
# plugin-hostd-tests as /usr/libexec/plugin-hostd/tests/lib/protocol.sh, and in this tree as tests/lib/protocol.sh.
#
#   protocol_send FD SECONDS LINE           the reply to LINE on the open descriptor FD, on stdout
#   protocol_expect FD SECONDS LINE WANTED  0 when the reply is WANTED, 1 and a line on stderr when it is not
#   protocol_wait_ready LOG [TRIES]         0 when LOG holds the readiness marker within TRIES tenths of a second (50)
#   send LINE                               protocol_send on PROTOCOL_FD (3) for PROTOCOL_TIMEOUT (5) seconds
#
# A script that talks to one socket opens it on a descriptor (exec 3<>/dev/tcp/127.0.0.1/$port), sets PROTOCOL_FD and
# PROTOCOL_TIMEOUT if it differs from the defaults, and calls send; one that talks to several calls protocol_send.

# a worker prints a line ending with this once its socket accepts (protocol.h PHD_WORKER_READY_MARKER)
PROTOCOL_READY_MARKER=${PROTOCOL_READY_MARKER:-ready!}

protocol_send() {
    local reply=
    printf '%s\0' "$3" >&"$1"
    IFS= read -r -d '' -t "$2" reply <&"$1"
    printf '%s\n' "$reply"
}

protocol_expect() {
    local reply
    reply=$(protocol_send "$1" "$2" "$3")
    [ "$reply" = "$4" ] && return 0
    printf 'protocol_expect: %s -> %s, wanted %s\n' "$3" "$reply" "$4" >&2
    return 1
}

protocol_wait_ready() {
    local i
    for ((i = 0; i < ${2:-50}; i++)); do
        grep -q -F "$PROTOCOL_READY_MARKER" "$1" 2>/dev/null && return 0
        sleep 0.1
    done
    grep -q -F "$PROTOCOL_READY_MARKER" "$1" 2>/dev/null
}

send() {
    protocol_send "${PROTOCOL_FD:-3}" "${PROTOCOL_TIMEOUT:-5}" "$1"
}
