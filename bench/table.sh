#!/bin/bash
# table.sh <file>...: the chains-vs-processes and grouping-vs-processes rows of omx-bench/1 documents as markdown:
# the figures with their spread, the ratios of one process per plugin to one chain, the xruns summed per mode.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
command -v python3 >/dev/null || { echo "table.sh: python3 is needed" >&2; exit 2; }
exec python3 -I "$here/lib/table.py" "$@"
