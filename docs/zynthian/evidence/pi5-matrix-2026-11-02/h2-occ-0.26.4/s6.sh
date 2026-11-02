#!/bin/bash
# the rows deferred to omx-clap-core 0.26.4: step 1's plugin-hostd rows of cvp24, cvp24-lv2 and tp10, and step 3's grouped
# cold rows of the 24-plugin and ten third-party sets
export HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LV2_PATH=/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/zynthian/zynthian-plugins/lv2
export CLAP_PATH=/usr/lib/clap
D=/root/omx-final-20261102; cd $D/plugin-hostd
echo "=== guard check $(date -u +%FT%TZ)"
for u in http://calf.sourceforge.net/plugins/Compressor urn:zamaudio:ZamComp; do python3 $D/calf-clobber.py --uri $u; done
echo "=== step 1 H2 rows $(date -u +%FT%TZ)"
bash bench/run.sh --class rpi5 --out $D/s6-matrix-h2 --rates 48000 --frames 256 --scenarios cvp24,cvp24-lv2,tp10 --hosts H2 \
    --stress none --repeats 3 --logs $D/s6-matrix-h2/logs
echo "=== step 3 grouped cold rows $(date -u +%FT%TZ)"
python3 -I $D/cold-to-snapshot-grouped.py $D/s6-add-grouped/cold-to-snapshot-grouped.json
echo "=== done $(date -u +%FT%TZ)"
