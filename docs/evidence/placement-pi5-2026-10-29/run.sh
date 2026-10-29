#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# The placement runs on a Pi 5, against the JACK server that runs there: two then three instruments in separate workers,
# placement none then spread, 60 s each. DAEMON is the plugin-hostd built from this branch; OUT the directory the raw
# numbers go to (one directory per run).
#   DAEMON=./plugin-hostd OUT=out sh run.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
: "${DAEMON:?the plugin-hostd of this branch}" "${OUT:=out}"
# the instruments: Obxd and Monique, LV2 synths installed on the device, alternating; PYTHON has the JACK-Client
# module for the xrun count (Zynthian's venv does)
PYTHON=${PYTHON:-python3}
A=${A:-lv2:https://obxd.wordpress.com}
B=${B:-lv2:https://surge-synthesizer.github.io/lv2/MoniqueMonosynth}
LV2=${LV2:-/usr/lib/lv2:/usr/local/lib/lv2}
for n in 2 3; do
    for p in none spread; do
        "$PYTHON" "$here/measure.py" --daemon "$DAEMON" --placement "$p" --count "$n" --uri "$A" --uri "$B" \
            --lv2-path "$LV2" --window 60 --out "$OUT/$n-$p"
    done
done
