#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# The plugin-hostd-protocol ceiling of this tree: the next minor after the floor (below 1.0 a minor may break), as the
# spec's `plugin-hostd-protocol-devel < x.y` has it. CI reads it here; tests/protocol_floor.py holds every other
# declaration of it to this number.
#
# Usage: protocol-ceiling.sh [spec]
spec=${1:-$(dirname "$0")/../packaging/plugin-hostd.spec}
ceiling=$(sed -n 's/^BuildRequires:[[:space:]]*(plugin-hostd-protocol-devel[[:space:]]*>=[[:space:]]*[^[:space:]]*[[:space:]]*with[[:space:]]*plugin-hostd-protocol-devel[[:space:]]*<[[:space:]]*\([^[:space:])]*\)).*/\1/p' "$spec")
case $ceiling in
'' | *[!0-9.]*)
    echo "protocol-ceiling.sh: no one 'BuildRequires: (plugin-hostd-protocol-devel >= x.y.z with plugin-hostd-protocol-devel < x.y)' in $spec" >&2
    exit 1
    ;;
esac
printf '%s\n' "$ceiling"
