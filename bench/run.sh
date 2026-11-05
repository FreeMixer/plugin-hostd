#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
# The benchmark runner: bench/README.md has the options and what each scenario measures.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
command -v python3 >/dev/null || { echo "run.sh: python3 is needed" >&2; exit 2; }
exec python3 -I "$here/lib/bench.py" "$@"
