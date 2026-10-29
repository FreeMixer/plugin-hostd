#!/bin/bash
# Read a ZynthianOS SD image without mounting it (no root): its Debian release, packages, the commits of zynthian-ui,
# zynthian-sys and mod-ui it carries, its audio defaults and what runs plugins.
#
#   tools/zynthian/image-inspect.sh <zynthianos.img> <out-dir>
#
# Needs debugfs (e2fsprogs). The root file system is the image's second partition, read through debugfs's offset option.
set -u
img=${1:?image}; out=$(mkdir -p "${2:?out dir}" && cd "$2" && pwd)
off=$(python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(512); print(struct.unpack('<I', d[446+16+8:446+16+12])[0]*512)" "$img")
D() { debugfs -R "$1" "$img?offset=$off" 2>/dev/null; }
{
echo "root partition offset $off"
echo "== /etc/os-release"; D "cat /etc/os-release" | grep -E '^(PRETTY_NAME|VERSION_CODENAME)='
echo "== /etc/debian_version"; D "cat /etc/debian_version"
echo "== /zynthian/build_info.txt"; D "cat /zynthian/build_info.txt"
D "dump /var/lib/dpkg/status $out/dpkg-status"
echo "== packages: $(grep -c '^Package:' "$out/dpkg-status")"
for p in jackd2 libjack-jackd2-0 python3 liblilv-0-0 linux-image-rpi-v8 linux-image-rpi-2712 raspi-firmware a2jmidid \
    openmixer-release plugin-hostd omx-clap-host omx-plugins omx-panel plugin-qualify; do
    printf '%s %s\n' "$p" "$(awk -v p="$p" '$1=="Package:"{x=($2==p)} x&&$1=="Version:"{print $2; exit}' "$out/dpkg-status")"
done
for r in zynthian-ui zynthian-sys zynthian-webconf zyncoder; do
    head=$(D "cat /zynthian/$r/.git/HEAD"); ref=${head#ref: }
    printf '== %s %s %s %s\n' "$r" "$ref" "$(D "cat /zynthian/$r/.git/$ref" 2>/dev/null)" \
        "$(D "cat /zynthian/$r/.git/config" | sed -n 's/^[[:space:]]*url = //p' | head -1)"
done
echo "== /zynthian/zynthian-sw"; D "ls /zynthian/zynthian-sw" | tr -s ' \t\n' '\n' | grep -v '^\.*$' | sort | tr '\n' ' '; echo
echo "== mod-host / jalv / mod-ui"; for f in /usr/local/bin/mod-host /usr/local/lib/jack/mod-host.so /usr/lib/jack/mod-host.so /usr/local/bin/jalv /zynthian/zynthian-sw/mod-ui/server.py; do D "stat $f" | head -1 | sed "s#^#$f: #"; done
echo "== LV2 bundles"; for d in /usr/lib/lv2 /usr/local/lib/lv2 /zynthian/zynthian-plugins/lv2; do printf '%s %s\n' "$d" "$(D "ls $d" | tr -s ' \t\n' '\n' | grep -c '\.lv2$')"; done
echo "== /zynthian/config/zynthian_envars.sh (audio, JACK, board)"; D "cat /zynthian/config/zynthian_envars.sh" | grep -n -E 'SOUNDCARD|JACKD_OPTIONS|ALSA|RBPI|DISPLAY_NAME|WIRING|KIT'
echo "== /boot/firmware/config.txt (dtoverlay, governor-relevant)"; D "cat /boot/firmware/config.txt" | grep -n -E '^(dtoverlay|arm_freq|force_turbo|over_voltage|\[)' | head -20
} >"$out/inspect.txt"
cat "$out/inspect.txt"
