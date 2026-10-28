#!/bin/bash
set -o pipefail
export LV2_PATH=/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/zynthian/zynthian-plugins/lv2:/zynthian/zynthian-sw/pianoteq/arm-64bit:/zynthian/zynthian-my-data/plugins/lv2
export CLAP_PATH=/usr/lib/clap
export JACK_DEFAULT_SERVER=omxpq
export JACK_NO_START_SERVER=1
export PATH=/root/omx-deep-20261028/bin:$PATH
echo "== deep qualify start $(date -u +%FT%TZ) $(dpkg-query -W -f \"plugin-qualify \${Version}\" plugin-qualify) host=$(hostname) $(nproc) cores"
plugin-qualify --all --isolate --rates 44100,48000,96000,192000 --quanta 128,256,512,1024 --host-profile openmixer-console,jalv,mod-host,omx-clap-host --format json --out /root/omx-deep-20261028/records --pins /root/omx-deep-20261028/qualified.pins > /root/omx-deep-20261028/qualify.json 2> /root/omx-deep-20261028/qualify.err; rc=$?
echo "== plugin-qualify rc=$rc $(date -u +%FT%TZ) records=$(ls /root/omx-deep-20261028/records | wc -l) pins=$(grep -vc "^#" /root/omx-deep-20261028/qualified.pins 2>/dev/null)"
echo "== device sync --force start $(date -u +%FT%TZ)"
plugin-qualify-sync --system --force > /root/omx-deep-20261028/sync.log 2>&1; src=$?
echo "== sync rc=$src $(date -u +%FT%TZ) records=$(ls /var/lib/omx/qualification | wc -l) pins=$(grep -vc "^#" /var/lib/omx/qualified.pins)"
