#!/bin/bash
# second pass of the profile: the plugin-hostd rows again, the worker being omx-clap-host relinked from the same 0.26.4
# objects without -s (the release Makefile links with -s, so the channel's binary has no symbols and no dbgsym), and
# libomx-clap-core the 0.26.4 tag built here; per-object symbol reports and the callers of memcpy.
set -u
shopt -s nullglob
export HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LV2_PATH=/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/zynthian/zynthian-plugins/lv2
export CLAP_PATH=/usr/lib/clap
D=/root/omx-final-20261102; Y=$D/symbols; O=$D/s7b-profile
mkdir -p $O
LIB=$Y/xs-0.26.4/usr/lib/aarch64-linux-gnu
HOST=$Y/unstripped/omx-clap-host
echo "worker binary: $HOST $(readelf -n $HOST | awk '/Build ID/{print $3}') ($(file -b $HOST | grep -o 'with debug_info, not stripped'))"
echo "library: $LIB/libomx-clap-core.so.0.26.4 $(readelf -n $LIB/libomx-clap-core.so.0.26.4 | awk '/Build ID/{print $3}')"
echo "=== rows $(date -u +%FT%TZ)"
cd $D/plugin-hostd
LD_LIBRARY_PATH=$LIB python3 $D/profile-chain.py --bench $D/plugin-hostd/bench --out $O --seconds 30 --rate 48000 --frames 256 \
    --conf "clap_host $HOST" \
    --rows cvp24:H2:chain-add:fp,cvp24:H2:chain-add:dwarf,cvp24-lv2:H2:chain-add:fp,cvp24-lv2:H2:chain-add:dwarf
echo "=== reports $(date -u +%FT%TZ)"
for F in $O/*.data; do
    B=${F%.data}
    perf report -i $F --no-children --stdio --sort comm,dso -g none --percent-limit 0.5 > $B.dso.txt 2>/dev/null
    perf report -i $F --no-children --stdio --sort dso,sym -g none --percent-limit 0 2>/dev/null > $B.all.txt
    grep -vE '^#|^$' $B.all.txt | head -30 > $B.top30.txt
    P5=$(grep -vE '^#|^$' $B.all.txt | sed -n 5p | awk '{print $1}' | tr -d '%')
    perf report -i $F --no-children --stdio --sort dso,sym -g graph,0.5,callee --percent-limit ${P5:-5} > $B.top5-callgraph.txt 2>/dev/null
    # the host's own code: omx-clap-host (the LV2 adapter is linked into it) and libomx-clap-core, every symbol
    perf report -i $F --no-children --stdio --sort dso,sym -g none --percent-limit 0 \
        --dsos omx-clap-host,libomx-clap-core.so.0.26.4,libc.so.6 > $B.host.txt 2>/dev/null
    perf report -i $F --no-children --stdio --sort sym -g caller,0.5,callee,function,percent --percent-limit 0 \
        --symbols __memcpy_generic,__memset_zva64 > $B.memcpy-callers.txt 2>/dev/null
    echo "--- $(basename $B): top 5 from ${P5}%"; head -8 $B.top30.txt
    echo "    host code:"; grep -vE '^#|^$' $B.host.txt | head -15
done
echo "=== done $(date -u +%FT%TZ)"
