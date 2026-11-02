#!/bin/bash
# profile of the grouped 24-plugin chain (cvp24, plugin-hostd chain-add) and of mod-host on the same chain, 48000/256:
# perf record on the host's processes for 30 s while the row runs, then perf report --no-children (top 30) and the
# call graph of the top 5. libomx-clap-core is the 0.26.4 tag built here with its dbgsym, loaded through
# LD_LIBRARY_PATH, because the channel's build ships stripped with no dbgsym.
set -u
shopt -s nullglob
export HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LV2_PATH=/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/zynthian/zynthian-plugins/lv2
export CLAP_PATH=/usr/lib/clap
D=/root/omx-final-20261102; Y=$D/symbols; O=$D/s7-profile
mkdir -p $O
echo "=== perf $(date -u +%FT%TZ)"
if ! command -v perf >/dev/null; then
    dpkg-query -W -f='${Package}\n' | sort > $O/packages-before-perf.txt
    apt-get install -y --no-install-recommends linux-perf
    dpkg-query -W -f='${Package}\n' | sort > $O/packages-after-perf.txt
    comm -13 $O/packages-before-perf.txt $O/packages-after-perf.txt > $O/packages-added-by-perf.txt
    echo "added: $(tr '\n' ' ' < $O/packages-added-by-perf.txt)"
fi
perf --version
LIB=$Y/xs-0.26.4/usr/lib/aarch64-linux-gnu
for f in $(find $Y/x-0.26.4 -name '*.debug'); do perf buildid-cache --add $f -v; done
echo "rebuilt library: $(readelf -n $LIB/libomx-clap-core.so.0.26.4 | awk '/Build ID/{print $3}')"
echo "channel library: $(readelf -n /usr/lib/aarch64-linux-gnu/libomx-clap-core.so.0.26.4 | awk '/Build ID/{print $3}')"
echo "=== rows $(date -u +%FT%TZ)"
cd $D/plugin-hostd
LD_LIBRARY_PATH=$LIB python3 $D/profile-chain.py --bench $D/plugin-hostd/bench --out $O --seconds 30 --rate 48000 --frames 256 \
    --rows cvp24:H2:chain-add:fp,cvp24:H3::fp,cvp24:H2:chain-add:dwarf,cvp24:H3::dwarf,cvp24-lv2:H2:chain-add:fp
echo "=== reports $(date -u +%FT%TZ)"
for F in $O/*.data; do
    B=${F%.data}
    perf report -i $F --no-children --stdio --sort comm,dso -g none --percent-limit 0.5 > $B.dso.txt 2>/dev/null
    perf report -i $F --no-children --stdio --sort dso,sym -g none --percent-limit 0 2>/dev/null > $B.all.txt
    grep -vE '^#|^$' $B.all.txt | head -30 > $B.top30.txt
    P5=$(grep -vE '^#|^$' $B.all.txt | sed -n 5p | awk '{print $1}' | tr -d '%')
    perf report -i $F --no-children --stdio --sort dso,sym -g graph,0.5,callee --percent-limit ${P5:-5} > $B.top5-callgraph.txt 2>/dev/null
    echo "--- $(basename $B): top 5 from ${P5}%"; head -8 $B.top30.txt
done
echo "=== done $(date -u +%FT%TZ)"
