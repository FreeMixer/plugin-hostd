#!/bin/bash
# validate.sh <file>...: check omx-bench/1 documents against bench/schema/omx-bench.v1.schema.json and the rules the
# schema cannot say. Exit 1 names the file, the scenario row and the rule of the first problem of each file.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ $# -lt 1 ]; then
    echo "usage: validate.sh <file>..." >&2
    exit 2
fi
exec python3 -I "$here/lib/validate.py" "$here/schema/omx-bench.v1.schema.json" "$@"
