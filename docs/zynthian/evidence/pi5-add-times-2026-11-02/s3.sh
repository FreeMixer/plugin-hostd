#!/bin/bash
# step 3: add and chain times on the Pi 5, private dummy JACK servers at 48000 Hz, 256 frames
export HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LV2_PATH=/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/zynthian/zynthian-plugins/lv2
export CLAP_PATH=/usr/lib/clap
D=/root/omx-final-20261102; O=$D/s3-add; cd $D/plugin-hostd
echo "=== step 3 begins $(date -u +%FT%TZ)"
python3 -I tools/zynthian/add-times.py --out $O/add-times-lv2.json --builds lv2 --sizes 2,4,7 --repeats 3
python3 -I tools/zynthian/add-times.py --out $O/add-times-clap.json --builds clap --sizes 2,4,7 --repeats 3
python3 -I $D/cold-to-snapshot-own.py $O/cold-to-snapshot-own.json
echo "=== step 3 ends $(date -u +%FT%TZ)"
