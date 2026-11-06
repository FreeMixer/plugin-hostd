#!/bin/bash
# gate.sh <file>...: the soundness gate over the documents of a run taken together. Names each cell that disagrees with
# its twins, its stress pair, its smaller-frames neighbour or its own repeats, and the run.sh arguments that measure it
# alone. Exit 1 when there is one.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
command -v python3 >/dev/null || { echo "gate.sh: python3 is needed" >&2; exit 2; }
exec python3 -I "$here/lib/gate.py" "$@"
