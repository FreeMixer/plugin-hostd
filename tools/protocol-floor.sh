#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# The plugin-hostd-protocol floor of this tree. The number is the one on the spec's BuildRequires of the devel package;
# CI reads it here, and tests/protocol_floor.py holds the spec's other lines and debian/control, which reads no
# variable, to it and it to the protocol's first release that declares what the sources use.
#
# Usage: protocol-floor.sh [spec]
spec=${1:-$(dirname "$0")/../packaging/plugin-hostd.spec}
floor=$(sed -n 's/^BuildRequires:[[:space:]]*(\{0,1\}plugin-hostd-protocol-devel[[:space:]]*>=[[:space:]]*\([^[:space:]]*\).*/\1/p' "$spec")
case $floor in
'' | *[!0-9.]*)
    echo "protocol-floor.sh: no one 'BuildRequires: (plugin-hostd-protocol-devel >= x.y.z with ... < x.y)' in $spec" >&2
    exit 1
    ;;
esac
printf '%s\n' "$floor"
